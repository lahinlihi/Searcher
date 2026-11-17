"""
자동 크롤링 스케줄러
APScheduler를 사용하여 정해진 시간에 자동으로 크롤링을 실행합니다.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import json
import concurrent.futures

from crawlers.sungdonggu_crawler import SungDongGuCrawler
from crawlers.generic_crawler import GenericCrawler
from crawlers.g2b_api_crawler import G2BApiCrawler
from crawlers.g2b_pre_spec_crawler import G2BPreSpecCrawler
from crawlers.lh_api_crawler import LHApiCrawler
from crawlers.smb24_api_crawler import SMB24ApiCrawler
from crawlers.kosmes_crawler import KosmesCrawler
from crawlers.sbiz24_crawler import Sbiz24Crawler
from crawlers.rss_crawler import RSSCrawler
from crawlers.mois_predece_crawler import MOISPredeceCrawler
from crawlers.kist_bid_crawler import KISTBidCrawler
from crawlers.kist_notice_crawler import KISTNoticeCrawler
from crawlers.koica_api_crawler import KOICAApiCrawler
from deduplication import mark_duplicates_in_db, mark_nia_procurement_duplicates
from database import db, Tender, CrawlLog
from settings_manager import settings_manager



# crawler_type 값 → 전용 구현체가 있는 목록
SUPPORTED_CRAWLER_TYPES = {
    'api',          # G2BApiCrawler
    'pre_spec',     # G2BPreSpecCrawler
    'lh_api',       # LHApiCrawler
    'smb24_api',    # SMB24ApiCrawler
    'mois_predece', # MOISPredeceCrawler
    'kist_bid',     # KISTBidCrawler
    'kist_notice',  # KISTNoticeCrawler
    'koica_api',    # KOICAApiCrawler
    'kosmes',       # KosmesCrawler
    'sbiz24',       # Sbiz24Crawler
    'rss',          # RSSCrawler
    'generic',      # GenericCrawler (범용)
    'list',         # GenericCrawler (리스트형)
}

# 레거시 크롤러: 항상 구현됨 (site_id 기준)
LEGACY_CRAWLERS = {'sung-dong-gu'}


# ── 예약 작업 실행 기록 ────────────────────────────────────────────────────
#
# 예약 작업의 결과는 지금까지 print 뿐이었다. 그 출력은 서버를 재시작할 때마다
# 덮어써지는 로그 파일로 가므로, 어느 날 수집이 빠졌을 때 '실패했는지, 아예
# 안 돌았는지'를 나중에 알 방법이 없었다. 작업마다 한 줄씩 DB 에 남긴다.
# 이 기록은 '오늘 이미 돌았는가' 판정(기동 시 보충 실행)에도 쓴다.
# 기록 자체가 실패해도 작업은 계속돼야 하므로 예외는 전부 삼킨다.

_JOB_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job         TEXT NOT NULL,
    run_date    TEXT NOT NULL,      -- YYYY-MM-DD (서버 현지 시각)
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,      -- running / ok / empty / failed
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_runs ON job_runs(job, run_date);
"""


def _job_conn():
    import hr_news
    conn = hr_news.connect()
    conn.executescript(_JOB_RUNS_SCHEMA)
    return conn


def job_run_start(job):
    try:
        conn = _job_conn()
        try:
            now = datetime.now()
            cur = conn.execute(
                'INSERT INTO job_runs (job, run_date, started_at, status) '
                'VALUES (?,?,?,?)',
                (job, now.strftime('%Y-%m-%d'),
                 now.isoformat(timespec='seconds'), 'running'))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    except Exception as e:
        print(f"[실행기록] 시작 기록 실패 (무시): {type(e).__name__}: {e}")
        return None


def job_run_finish(run_id, status, detail=''):
    if run_id is None:
        return
    try:
        conn = _job_conn()
        try:
            conn.execute(
                'UPDATE job_runs SET finished_at=?, status=?, detail=? WHERE id=?',
                (datetime.now().isoformat(timespec='seconds'), status,
                 (detail or '')[:2000], run_id))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[실행기록] 종료 기록 실패 (무시): {type(e).__name__}: {e}")


def job_runs_on(job, run_date):
    """그날 이 작업의 상태 목록. 조회 실패 시 None."""
    try:
        conn = _job_conn()
        try:
            return [r['status'] for r in conn.execute(
                'SELECT status FROM job_runs WHERE job=? AND run_date=? ORDER BY id',
                (job, run_date))]
        finally:
            conn.close()
    except Exception as e:
        print(f"[실행기록] 조회 실패 (무시): {type(e).__name__}: {e}")
        return None


class CrawlScheduler:
    """크롤링 스케줄러"""

    def __init__(self, app):
        self.app = app
        self.scheduler = BackgroundScheduler(timezone='Asia/Seoul')

        # 크롤링 중지 제어
        import threading
        self._stop_event = threading.Event()   # set() 하면 크롤러 루프 중단
        self._crawl_thread = None              # 현재 실행 중인 크롤 스레드 (참고용, 진행 여부 판단에는 미사용)
        self._is_crawling = False              # 명시적 진행 상태 플래그.
        # 예약 크롤과 수동 크롤이 겹치지 않게 하는 잠금. 겹치면 두 크롤이 같은
        # 크롤러 인스턴스·Selenium 드라이버·중지 신호·진행률 변수를 함께 쓴다.
        self._crawl_lock = threading.Lock()
        # 주의: is_crawling 판정에 스레드의 is_alive()를 쓰지 않는다.
        # APScheduler(BlockingScheduler)는 내부적으로 스레드 풀을 재사용해 잡을 실행하므로,
        # run_crawl_job()이 이미 끝나도 그 잡을 실행했던 풀 스레드 자체는 계속 살아있어
        # is_alive()가 계속 True를 반환하는 버그가 있었다(실제 확인됨: 크롤링은 9분 만에
        # 끝났는데 UI에는 55분 넘게 "진행 중"으로 표시됨). 그래서 시작/종료 시점에
        # 직접 True/False로 설정하는 플래그로 판단한다.

        # 진행 상황 추적 (진행률/현재 사이트/경과 시간 표시용)
        self._current_site = None
        self._current_site_started_at = None
        self._sites_done = 0
        self._sites_total = 0

        # 원격 sync 모드 여부 (팀원 인스턴스)
        self._remote_sync = None
        sync_cfg = settings_manager.get('sync', {})
        if sync_cfg.get('enabled') and sync_cfg.get('server_url') and sync_cfg.get('token'):
            from remote_sync import RemoteSync
            self._remote_sync = RemoteSync(
                server_url=sync_cfg['server_url'],
                token=sync_cfg['token']
            )
            print(f"[스케줄러] 원격 Sync 모드: {sync_cfg['server_url']}")
        else:
            # 레거시 크롤러 (하드코딩) — SungDongGuCrawler는 더미 샘플이므로 제거,
            # settings.json의 GenericCrawler 설정을 사용
            self.legacy_crawlers = {}
            # 동적 크롤러는 설정에서 로드
            self.crawlers = {}
            self._load_crawlers()

    def start(self):
        """스케줄러 시작"""
        if self._remote_sync:
            # 팀원 모드: 원격 서버에서 공고 동기화
            sync_cfg = settings_manager.get('sync', {})
            interval = int(sync_cfg.get('interval_minutes', 60))
            self.scheduler.add_job(
                func=self.run_remote_sync_job,
                trigger='interval',
                minutes=interval,
                id='remote_sync',
                name=f'원격 공고 동기화 (매 {interval}분)',
                replace_existing=True,
                next_run_time=datetime.now()  # 시작하자마자 1회 실행
            )
            self.scheduler.start()
            print(f"[스케줄러] 원격 Sync 스케줄러 시작 (매 {interval}분)")
            return

        # 크롤러 모드: settings.json의 crawl.times (기본 09:00, 17:00)에 맞춰 등록
        # misfire_grace_time: APScheduler 기본값(1초)이 너무 짧아 스케줄러 스레드가
        # 트리거 시점에 잠깐만 지연돼도(다른 작업 충돌, GC 등) 그날 실행이 조용히 스킵되는
        # 문제가 반복됐음. 여유 있게 잡아 트리거 시점이 지나도 그날 안에는 늦게라도 실행되게 함.
        # (단, 이 값은 서버가 켜져 있을 때만 통한다. 서버가 예정 시각 뒤에 켜진 날은
        #  아래 _schedule_catch_up 이 보충한다.)
        self._add_crawl_jobs()
        self._add_hr_news_job()

        self.scheduler.start()
        print("[스케줄러] 자동 크롤링 스케줄러가 시작되었습니다.")
        for t in self._get_crawl_times():
            print(f"[스케줄러] - {t}")

        self._schedule_catch_up()

    def _schedule_catch_up(self):
        """
        서버가 예정 시각보다 늦게 켜진 날, 놓친 작업을 한 번 보충한다.

        위의 misfire_grace_time 은 서버가 **켜져 있는 동안** 실행이 늦어진 경우만
        구제한다. 서버가 꺼져 있던 시각의 실행은 '놓친 실행'으로 잡히지도 않는다.
        스케줄러는 켜진 시점 이후의 첫 시각(= 내일)만 예약하기 때문이다.
        실제로 07:30 이후에 PC 가 켜진 날(11-06, 11-13, 11-16)은 HR뉴스가 0건이었다.

        이 서버는 재시작이 잦으므로 '오늘 이미 돌았는지'를 반드시 확인한다.
        확인 없이 보충하면 재시작할 때마다 네이버·LLM·나라장터 호출이 반복된다.
        """
        from datetime import timedelta
        now = datetime.now()
        hr_scheduled = False

        try:
            if settings_manager.get('hr_news.enabled', True):
                h, m = (int(x) for x in self._get_hr_news_time().split(':'))
                due = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if now > due and not self._hr_news_ran_today(now):
                    self.scheduler.add_job(
                        func=self.run_hr_news_job, trigger='date',
                        run_date=now + timedelta(seconds=120),
                        id='hr_news_catchup', name='HR뉴스 수집 (보충)',
                        replace_existing=True, misfire_grace_time=3600)
                    hr_scheduled = True
                    print(f"[스케줄러] 오늘 {h:02d}:{m:02d} HR뉴스 수집을 놓쳤습니다 "
                          "— 2분 뒤 보충 실행합니다.")
        except Exception as e:
            print(f"[스케줄러] HR뉴스 보충 판정 실패 (무시): {type(e).__name__}: {e}")

        try:
            dues = []
            for t in self._get_crawl_times():
                try:
                    h, m = (int(x) for x in t.split(':'))
                except (ValueError, AttributeError):
                    continue
                d = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if d < now:
                    dues.append(d)
            if dues:
                last_due = max(dues)        # 여러 번 놓쳐도 가장 최근 한 번만 보충
                with self.app.app_context():
                    ran = CrawlLog.query.filter(
                        CrawlLog.started_at >= last_due).first() is not None
                if not ran:
                    # HR뉴스 보충과 겹치지 않게 띄운다 (둘 다 같은 DB 에 쓴다)
                    delay = 600 if hr_scheduled else 120
                    self.scheduler.add_job(
                        func=self.run_crawl_job, trigger='date',
                        run_date=now + timedelta(seconds=delay),
                        id='crawl_catchup', name='크롤링 (보충)',
                        replace_existing=True, misfire_grace_time=3600)
                    print(f"[스케줄러] 오늘 {last_due:%H:%M} 크롤링을 놓쳤습니다 "
                          f"— {delay // 60}분 뒤 보충 실행합니다.")
        except Exception as e:
            print(f"[스케줄러] 크롤링 보충 판정 실패 (무시): {type(e).__name__}: {e}")

    def _hr_news_ran_today(self, now):
        """오늘 HR뉴스 작업이 이미 돌았는가 (보충 실행 여부 판정)."""
        today = now.strftime('%Y-%m-%d')
        runs = job_runs_on('hr_news', today)
        if runs is None:
            return True                 # 기록을 읽지 못하면 보충하지 않는다(안전한 쪽)
        if 'ok' in runs or 'running' in runs or len(runs) >= 2:
            return True                 # 성공했거나, 돌고 있거나, 이미 두 번 시도했다
        try:
            import hr_news
            conn = hr_news.connect()
            try:
                # 실행 기록이 생기기 전에 돈 날(또는 수동 수집)도 '돌았다'로 본다
                n = conn.execute(
                    'SELECT COUNT(*) FROM hr_news WHERE collected_at LIKE ?',
                    (today + '%',)).fetchone()[0]
            finally:
                conn.close()
            return n > 0
        except Exception as e:
            print(f"[스케줄러] HR뉴스 수집 여부 조회 실패: {type(e).__name__}: {e}")
            return True

    def _get_crawl_times(self):
        """settings.json의 crawl.times를 읽어 ['HH:MM', ...] 반환 (없으면 기본값)"""
        times = settings_manager.get('crawl.times', ['09:00', '17:00'])
        if not times:
            times = ['09:00', '17:00']
        return times

    def _add_crawl_jobs(self):
        """현재 설정된 crawl.times에 맞춰 크롤링 잡을 등록 (job id: crawl_0, crawl_1, ...)"""
        for idx, t in enumerate(self._get_crawl_times()):
            try:
                hour, minute = t.split(':')
                hour, minute = int(hour), int(minute)
            except (ValueError, AttributeError):
                print(f"[스케줄러] 잘못된 시간 형식 무시: {t}")
                continue
            self.scheduler.add_job(
                func=self.run_crawl_job,
                trigger=CronTrigger(hour=hour, minute=minute),
                id=f'crawl_{idx}',
                name=f'크롤링 {idx + 1} ({t})',
                replace_existing=True,
                misfire_grace_time=3600
            )

    # ── HR뉴스 수집 ────────────────────────────────────────────────────────
    #
    # hr_news 모듈은 tenders 크롤러와 무관한 독립 파이프라인이다(NAVER API HUB).
    # 임포트를 잡 실행 시점으로 늦추고 예외를 삼켜, 이 기능의 문제가
    # 서버 기동이나 기존 크롤링 스케줄을 깨뜨리지 않게 한다.

    def _get_hr_news_time(self):
        """settings.json의 hr_news.time (기본 07:30 — 당일 발행에 맞추려면 아침)"""
        return settings_manager.get('hr_news.time', '07:30') or '07:30'

    def run_hr_news_job(self):
        """HR뉴스 작업 실행 + 실행 기록. 본문은 _run_hr_news_job_inner."""
        run_id = job_run_start('hr_news')
        self._hr_notes = []
        self._hr_collected = None
        status, detail = 'ok', ''
        try:
            self._run_hr_news_job_inner()
            if self._hr_collected == 0:
                # 수집 0건은 조용한 날이 아니라 API 실패일 가능성이 높다
                # (hr_news.search 는 실패를 빈 목록으로 돌려준다)
                status = 'empty'
            detail = ' / '.join(self._hr_notes)
        except BaseException as e:
            # SystemExit 도 잡는다 — hr_news._keys() 는 키가 없으면 sys.exit 한다.
            status = 'failed'
            detail = ' / '.join(self._hr_notes + [f'{type(e).__name__}: {e}'])
            print(f"[HR뉴스] 작업 실패로 기록: {type(e).__name__}: {e}")
            if not isinstance(e, (Exception, SystemExit)):
                raise
        finally:
            job_run_finish(run_id, status, detail)

    def _run_hr_news_job_inner(self):
        """HR뉴스 수집 → 토픽 선정 → 상위 토픽 다각도 심화"""
        try:
            import hr_news
        except Exception as e:
            print(f"[HR뉴스] 모듈 임포트 실패 — 건너뜁니다: {type(e).__name__}: {e}")
            raise

        try:
            deep_n = int(settings_manager.get('hr_news.deep_topics', 3) or 3)
            days = int(settings_manager.get('hr_news.days', 3) or 3)

            merged, calls = hr_news.collect(days=days, quiet=True)
            conn = hr_news.connect()
            try:
                new, upd = hr_news.upsert(conn, list(merged.values()))
                print(f"[HR뉴스] 수집 {len(merged)}건 (신규 {new} 갱신 {upd}), API {calls}회")
                self._hr_collected = len(merged)
                self._hr_notes.append(f'수집 {len(merged)}건(신규 {new})')

                topics, _ = hr_news.rank_topics(conn, days=days, top_n=10)
                targets = [t for t in topics
                           if not t['metrics']['excluded']][:deep_n]
                for t in targets:
                    dm, dc, _ = hr_news.deepen(t['query'], days=days + 3, quiet=True)
                    n, u = hr_news.upsert(conn, list(dm.values()))
                    calls += dc
                    print(f"[HR뉴스] 심화 '{t['query']}' → {len(dm)}건 "
                          f"(신규 {n} 갱신 {u})")
                # 시사점 생성 — 수집·심화가 끝난 뒤 같은 커넥션으로 이어간다.
                # 실패해도 수집 결과는 이미 저장됐으므로 여기서만 예외를 삼킨다.
                try:
                    import insight
                    n_top = int(settings_manager.get('hr_news.insight_topics',
                                                     deep_n) or deep_n)
                    results, _ = insight.generate_daily(
                        conn, days=days, top_n=n_top, quiet=True)
                    saved, run_date = insight.save_daily(conn, results)
                    ok = sum(1 for r in results if r['ok'])
                    print(f"[HR뉴스] 시사점 {saved}건 저장 "
                          f"(검사 통과 {ok}, run_date={run_date}, 검수 대기)")
                    self._hr_notes.append(f'시사점 {saved}건(검사 통과 {ok})')
                    for r in results:
                        if not r['ok']:
                            labels = ', '.join(b['label']
                                               for b in r['lint']['blocking'][:3])
                            print(f"[HR뉴스]   ⚠ '{r['topic']}' 차단 — {labels}")
                except Exception as e:
                    import traceback
                    print(f"[HR뉴스] 시사점 생성 실패: {type(e).__name__}: {e}")
                    traceback.print_exc()
                    self._hr_notes.append(f'시사점 생성 실패: {type(e).__name__}: {e}')

                # 입찰동향 A/B/C 분류 — 메일에 '지원사업' 구분을 채우려면
                # 분류가 먼저 있어야 한다. 사전규격·중소벤처24 는 status 로
                # 구분이 끝나므로 '등록공고/일반/재공고/변경공고' 만 분류한다.
                # 실패해도 시사점은 이미 저장됐으므로 여기서만 예외를 삼킨다.
                try:
                    import tender_brief as tb
                    tb.ensure_schema(conn)
                    preset = tb.get_preset(conn)
                    rows = tb.candidates(conn, preset, days=days)
                    need = [r for r in rows
                            if (r['status'] or '').strip() in tb.STATUS_NORMAL]
                    if need:
                        saved_c, api_c = tb.classify(conn, need, quiet=True)
                        print(f"[HR뉴스] 입찰동향 분류 {saved_c}건 "
                              f"(후보 {len(rows)} 중 분류대상 {len(need)}, "
                              f"API {api_c}회)")
                    else:
                        print("[HR뉴스] 입찰동향 분류 대상 없음")
                except Exception as e:
                    print(f"[HR뉴스] 입찰동향 분류 실패: {type(e).__name__}: {e}")
                    self._hr_notes.append(f'입찰동향 분류 실패: {type(e).__name__}: {e}')
            finally:
                conn.close()
            print(f"[HR뉴스] 완료 — 총 API {calls}회")
        except Exception as e:
            import traceback
            print(f"[HR뉴스] 작업 실패: {type(e).__name__}: {e}")
            traceback.print_exc()
            raise       # 바깥 run_hr_news_job 이 실패로 기록한다

    def _add_hr_news_job(self):
        """HR뉴스 수집 잡 등록 (job id: hr_news)"""
        if not settings_manager.get('hr_news.enabled', True):
            print("[스케줄러] HR뉴스 수집 비활성 (hr_news.enabled=false)")
            return
        t = self._get_hr_news_time()
        try:
            hour, minute = (int(x) for x in t.split(':'))
        except (ValueError, AttributeError):
            print(f"[스케줄러] 잘못된 HR뉴스 시간 형식 무시: {t}")
            return
        self.scheduler.add_job(
            func=self.run_hr_news_job,
            trigger=CronTrigger(hour=hour, minute=minute),
            id='hr_news',
            name=f'HR뉴스 수집 ({t})',
            replace_existing=True,
            misfire_grace_time=3600
        )
        print(f"[스케줄러] HR뉴스 수집 등록 ({t})")

    def reload_schedule(self):
        """
        settings.json의 crawl.times가 바뀐 뒤 호출 — 기존 크롤링 잡을 전부 지우고
        새 시간으로 재등록한다. 서버 재시작 없이 스케줄 변경을 즉시 반영하기 위함.
        """
        if self._remote_sync:
            return  # 원격 sync 모드는 이 스케줄과 무관
        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith('crawl_'):
                self.scheduler.remove_job(job.id)
        self._add_crawl_jobs()
        print("[스케줄러] 크롤링 시간 재설정 완료:", ', '.join(self._get_crawl_times()))

    def stop(self):
        """스케줄러 중지"""
        self.scheduler.shutdown()
        print("[스케줄러] 스케줄러가 중지되었습니다.")

    @property
    def is_crawling(self):
        """현재 크롤링이 진행 중인지 여부"""
        return self._is_crawling

    @property
    def crawl_progress(self):
        """현재 크롤링 진행 상황 (진행 중이 아니면 None)"""
        if not self.is_crawling:
            return None
        elapsed = 0
        if self._current_site_started_at:
            elapsed = int((datetime.now() - self._current_site_started_at).total_seconds())
        percent = round(self._sites_done / self._sites_total * 100, 1) if self._sites_total else 0
        return {
            'current_site': self._current_site,
            'current_site_elapsed_sec': elapsed,
            'sites_done': self._sites_done,
            'sites_total': self._sites_total,
            'percent': percent,
        }

    def stop_crawl(self):
        """
        실행 중인 크롤링을 즉시 중지.
        현재 처리 중인 크롤러의 완료를 기다리지 않고 바로 반환한다.
        Selenium 크롤러는 driver.quit()으로 대기 중인 페이지 로드를 강제 종료하며,
        그 외 크롤러는 백그라운드 스레드가 자체 타임아웃(약 30초) 내에 조용히 소멸한다.
        """
        if not self.is_crawling:
            return False
        self._stop_event.set()
        print("[수동 크롤링] 강제 중지 요청됨 — 즉시 중단합니다.")
        return True

    def run_remote_sync_job(self):
        """
        팀원 인스턴스용 — 중앙 서버에서 공고 데이터를 동기화.
        크롤링 없이 원격 API를 호출하여 로컬 DB를 최신 상태로 유지.
        """
        print(f"\n[RemoteSync] 동기화 시작: {datetime.now()}")
        self._git_pull()  # 최신 코드도 반영

        with self.app.app_context():
            try:
                result = self._remote_sync.sync(days_back=30)
                if result['errors']:
                    print(f"[RemoteSync] 오류 {len(result['errors'])}건:")
                    for e in result['errors'][:5]:
                        print(f"  - {e}")
                print(
                    f"[RemoteSync] 완료 — "
                    f"신규: {result['new']}건, 업데이트: {result['updated']}건"
                )
            except Exception as e:
                print(f"[RemoteSync] 실패: {e}")

    def _git_pull(self):
        """
        Git pull 실행 — 최신 코드 반영
        실패해도 크롤링은 계속 진행
        """
        import subprocess, os  # noqa: E401
        try:
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            result = subprocess.run(
                ['git', 'pull', '--ff-only'],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30
            )
            if result.returncode == 0:
                msg = result.stdout.strip()
                if 'Already up to date' in msg:
                    print("[스케줄러] git pull: 이미 최신 버전")
                else:
                    print(f"[스케줄러] git pull: 업데이트됨\n{msg}")
            else:
                print(f"[스케줄러] git pull 실패 (무시하고 계속): {result.stderr.strip()}")
        except Exception as e:
            print(f"[스케줄러] git pull 오류 (무시하고 계속): {e}")

    def _git_push(self):
        """
        Claude Code 등으로 수정된 코드를 자동 commit + push
        - data/ 는 .gitignore 로 제외되므로 API 키·DB는 절대 올라가지 않음
        - 변경사항이 없으면 아무것도 하지 않음
        - 실패해도 크롤링 결과에 영향 없음
        """
        import subprocess, os  # noqa: E401
        try:
            repo_dir = os.path.dirname(os.path.abspath(__file__))

            # 변경된 추적 파일 확인 (data/ 제외는 .gitignore 가 보장)
            status = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=repo_dir, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=15
            )
            changed = status.stdout.strip()
            if not changed:
                print("[스케줄러] git push: 변경사항 없음 — 스킵")
                return

            # 변경 파일 목록 출력
            lines = changed.splitlines()
            print(f"[스케줄러] git push: 변경파일 {len(lines)}개 감지")
            for line in lines[:10]:
                print(f"  {line}")

            # add → commit → push
            subprocess.run(
                ['git', 'add', '-A'], cwd=repo_dir, timeout=15,
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )

            commit_msg = (
                f"auto: Claude Code 수정 반영 "
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]"
            )
            commit_result = subprocess.run(
                ['git', 'commit', '-m', commit_msg],
                cwd=repo_dir, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=15
            )
            if commit_result.returncode != 0:
                print(f"[스케줄러] git commit 실패: {commit_result.stderr.strip()}")
                return

            push_result = subprocess.run(
                ['git', 'push'],
                cwd=repo_dir, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=60
            )
            if push_result.returncode == 0:
                print("[스케줄러] git push: GitHub 업로드 완료")
            else:
                print(f"[스케줄러] git push 실패 (무시하고 계속): {push_result.stderr.strip()}")

        except Exception as e:
            print(f"[스케줄러] git push 오류 (무시하고 계속): {e}")

    def _run_crawler_with_timeout(self, site_name, crawler, timeout_sec=200):
        """
        크롤러를 타임아웃과 함께 실행.
        타임아웃은 '문제 감지 도구'이며, 발생 시 원인 힌트와 함께 로그를 남기고
        해당 크롤러를 건너뛴다. 정상 실행이 목표이며 타임아웃은 최후의 안전망.

        강제 중지(_stop_event)가 설정되면 현재 크롤러의 완료를 기다리지 않고
        즉시 제어를 반환한다. 백그라운드 스레드는 자체 타임아웃(페이지 로드 30초,
        HTTP 요청 30초) 내에 스스로 종료되며, 결과는 이미 버려지므로 무해하다.

        주의: 여기서 crawler._close_selenium_driver()를 크로스스레드로 호출하면 안 된다.
        아직 작업 스레드가 같은 driver 객체로 driver.get() 등을 실행 중일 수 있어,
        동시에 quit()이 끼어들면 chromedriver/chrome 프로세스가 정상 종료되지 못하고
        좀비로 남는 문제가 실제로 발생했다(수십~백여 개 누적 확인). 반드시 작업 스레드
        자신이 크롤러 종료 시점에 정리하도록 두고, 여기서는 손대지 않는다.

        Returns:
            (result_dict, status): status는 'ok' | 'timeout' | 'stopped'
        """
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        import time

        start_time = time.time()
        crawler_type = type(crawler).__name__
        poll_interval = 0.5

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(crawler.crawl)

        while True:
            if self._stop_event.is_set():
                elapsed = int(time.time() - start_time)
                print(f'[{site_name}] ■ 강제 중지 요청 수신 ({elapsed}초 진행 중) — 대기하지 않고 즉시 중단합니다.')

                # 스레드 종료를 기다리지 않고 반환 (wait=False) — 백그라운드에서 자체 타임아웃 시 조용히 소멸
                # (driver.quit()을 여기서 호출하지 않음 — 작업 스레드와의 경합으로 크롬 프로세스가
                #  좀비로 남는 문제가 있었음. 작업 스레드 자신이 나중에 정리하도록 둔다)
                executor.shutdown(wait=False, cancel_futures=False)

                return {
                    'success': False,
                    'count': 0,
                    'data': [],
                    'errors': ['사용자 강제 중지'],
                }, 'stopped'

            try:
                result = future.result(timeout=poll_interval)
                executor.shutdown(wait=False)
                return result, 'ok'
            except FuturesTimeout:
                elapsed = time.time() - start_time
                if elapsed < timeout_sec:
                    continue  # 짧은 폴링 간격으로 재시도, stop_event 재확인

                elapsed = int(elapsed)
                # 타임아웃 원인 힌트 추론
                use_selenium = getattr(crawler, 'use_selenium', False)
                if use_selenium:
                    hint = 'Selenium(Chrome) 드라이버가 응답하지 않음 — Chrome/ChromeDriver 버전 확인 또는 headless 환경 문제'
                else:
                    hint = '네트워크 응답 없음 — 대상 사이트 점검 또는 방화벽·IP 차단 여부 확인'

                msg = (
                    f'[{site_name}] ⚠ 크롤러 타임아웃 ({elapsed}초 경과 / 한도 {timeout_sec}초)\n'
                    f'  크롤러 유형: {crawler_type}\n'
                    f'  원인 힌트: {hint}\n'
                    f'  조치: 해당 크롤러를 건너뛰고 다음 크롤러 계속 실행. 유지보수 필요.'
                )
                print(msg)

                # driver.quit()을 여기서 호출하지 않음 — 위 stop 분기와 동일한 이유
                # (작업 스레드와의 경합으로 크롬 프로세스가 좀비로 남는 문제가 있었음)
                executor.shutdown(wait=False)

                return {
                    'success': False,
                    'count': 0,
                    'data': [],
                    'errors': [f'타임아웃 {elapsed}초 — {hint}'],
                }, 'timeout'

    def run_crawl_job(self):
        """예약 크롤 진입점. 이미 크롤이 돌고 있으면 이번 회차는 건너뛴다."""
        if not self._crawl_lock.acquire(blocking=False):
            print(f"[스케줄러] 다른 크롤링이 진행 중 — 이번 예약 실행은 건너뜁니다: {datetime.now()}")
            return
        try:
            self._run_crawl_job_locked()
        finally:
            self._crawl_lock.release()

    def run_manual_crawl(self, sites=None):
        """수동 크롤 진입점. 이미 크롤이 돌고 있으면 시작하지 않는다."""
        if not self._crawl_lock.acquire(blocking=False):
            print("[수동 크롤링] 다른 크롤링이 진행 중 — 시작하지 않습니다.")
            return {'success': False, 'error': '이미 크롤링이 진행 중입니다.'}
        try:
            return self._run_manual_crawl_locked(sites)
        finally:
            self._crawl_lock.release()

    def _mark_crawl_failed(self, crawl_log, e):
        """
        크롤 실패를 로그에 남긴다.

        저장 도중 DB 오류(잠금, 무결성)로 실패했다면 세션에 깨진 트랜잭션이
        남아 있다. 되돌리지 않고 commit 하면 그 commit 도 실패해, 로그가
        영원히 'running' 으로 남고 화면에는 크롤이 끝나지 않은 것처럼 보인다.
        """
        try:
            db.session.rollback()
            crawl_log.completed_at = datetime.now()
            crawl_log.status = 'failed'
            crawl_log.error_message = str(e)[:2000]
            db.session.commit()
        except Exception as e2:
            db.session.rollback()
            print(f"[스케줄러] 실패 로그 기록도 실패: {type(e2).__name__}: {e2}")

    def _close_finished_drivers(self, site_results):
        """
        이번 크롤에서 **끝까지 돈** 사이트의 Selenium 브라우저를 닫는다.

        닫지 않으면 헤드리스 크롬이 다음 크롤까지 몇 시간씩 떠 있고, 그 사이
        서버를 재시작하면 주인 없는 프로세스로 남는다(2026-11-17 확인: 09시
        크롤이 띄운 크롬·드라이버 18개, 약 1GB 가 서버 재시작 뒤에도 남아 있었다).

        타임아웃·강제 중지로 끝난 사이트는 건드리지 않는다. 작업 스레드가 아직
        같은 드라이버를 쓰고 있을 수 있고, 그때 quit() 이 끼어들면 크롬이 좀비로
        남는다(_run_crawler_with_timeout 의 주의 참고). 그런 드라이버는 지금까지
        처럼 다음 크롤 시작 때 정리된다.
        """
        for site_name, res in site_results.items():
            errs = ' '.join(str(x) for x in (res.get('errors') or []))
            if '타임아웃' in errs or '강제 중지' in errs:
                continue
            crawler = self.crawlers.get(site_name)
            if crawler is not None and getattr(crawler, 'driver', None):
                try:
                    crawler._close_selenium_driver()
                except Exception as e:
                    print(f"[{site_name}] 드라이버 종료 실패 (무시): {e}")

    def _run_crawl_job_locked(self):
        """
        크롤링 작업 실행
        모든 사이트를 크롤링하고 결과를 DB에 저장
        """
        import threading as _threading
        self._stop_event.clear()
        self._crawl_thread = _threading.current_thread()
        self._is_crawling = True

        print(f"\n[스케줄러] 자동 크롤링 시작: {datetime.now()}")

        # 크롤링 전 최신 코드 반영
        self._git_pull()

        with self.app.app_context():
            # 크롤링 로그 생성
            crawl_log = CrawlLog(
                started_at=datetime.now(),
                status='running'
            )
            db.session.add(crawl_log)
            db.session.commit()

            try:
                all_tenders = []
                site_results = {}

                # 설정에서 활성화된 사이트만 크롤링
                sites_config = settings_manager.get('crawl.sites_config', {})
                if not sites_config:
                    sites_config = settings_manager.get('crawl.sites', {})

                # Selenium 드라이버를 매 크롤 실행 전 초기화
                # — 이전 실행에서 열어둔 드라이버가 오래 유지되면(16시간 등) stale 상태가 되어
                #   driver.get()에서 무한대기가 발생함. 실행마다 새 드라이버를 사용해 방지.
                for crawler in self.crawlers.values():
                    if hasattr(crawler, '_close_selenium_driver'):
                        crawler._close_selenium_driver()

                # 진행률 초기화 (비활성화 사이트 제외한 실제 실행 대상 수 기준)
                self._sites_done = 0
                self._sites_total = sum(
                    1 for s in self.crawlers
                    if sites_config.get(s, {}).get('enabled', True)
                )

                # 각 사이트 크롤링 (사이트당 최대 120초 — 진단용 타임아웃)
                for site_name, crawler in self.crawlers.items():
                    # 강제 중지 신호 확인
                    if self._stop_event.is_set():
                        print("[스케줄러] 중지 신호 수신 — 나머지 크롤러를 건너뜁니다.")
                        break

                    # 설정에서 비활성화된 사이트는 건너뛰기
                    site_info = sites_config.get(site_name, {})
                    if not site_info.get('enabled', True):
                        print(f"[{site_name}] 설정에서 비활성화됨 - 건너뜀")
                        continue

                    self._current_site = site_name
                    self._current_site_started_at = datetime.now()

                    try:
                        print(f"[{site_name}] 크롤링 시작...")
                        result, status = self._run_crawler_with_timeout(site_name, crawler)
                        site_elapsed = int((datetime.now() - self._current_site_started_at).total_seconds())

                        site_results[site_name] = {
                            'success': result['success'],
                            'count': result['count'],
                            'errors': result.get('errors', [])[:3],
                            'elapsed_sec': site_elapsed,
                        }
                        self._sites_done += 1

                        if status == 'stopped':
                            break
                        if status == 'timeout':
                            continue

                        # 데이터가 있으면 오류가 있어도 저장 (부분 수집 허용)
                        if result['data']:
                            all_tenders.extend(result['data'])
                        if not result['success']:
                            print(f"[{site_name}] 경고 (부분 수집): {result['errors']}")

                    except Exception as e:
                        print(f"[{site_name}] 크롤링 실패: {str(e)}")
                        site_results[site_name] = {
                            'success': False,
                            'count': 0,
                            'errors': [str(e)],
                        }

                # 끝까지 돈 사이트의 브라우저를 닫는다 (다음 크롤까지 띄워 두지 않는다)
                self._close_finished_drivers(site_results)

                # 중복 제거
                unique_tenders, duplicate_count = mark_duplicates_in_db(
                    self.app, all_tenders)

                # DB에 저장 (신규 INSERT + 기존 UPDATE)
                new_count = 0
                update_count = 0
                all_by_number = {t['tender_number']: t for t in all_tenders if t.get('tender_number')}
                unique_numbers = {t['tender_number'] for t in unique_tenders if t.get('tender_number')}

                # 1) 신규 공고 INSERT
                for tender_data in unique_tenders:
                    tender = Tender(
                        title=tender_data['title'],
                        agency=tender_data['agency'],
                        demand_agency=tender_data.get('demand_agency'),
                        tender_number=tender_data['tender_number'],
                        announced_date=tender_data.get('announced_date'),
                        deadline_date=tender_data.get('deadline_date'),
                        opening_date=tender_data.get('opening_date'),
                        estimated_price=tender_data.get('estimated_price'),
                        bid_method=tender_data.get('bid_method'),
                        status=tender_data.get('status', '일반'),
                        is_sme_only=tender_data.get('is_sme_only', False),
                        source_site=tender_data['source_site'],
                        url=tender_data.get('url'),
                        is_duplicate=tender_data.get('is_duplicate', False),
                        extra_data=tender_data.get('extra_data'),
                        business_number=tender_data.get('business_number'),
                    )
                    db.session.add(tender)
                    new_count += 1

                # 2) 기존 공고 UPDATE — 주요 필드 갱신 (extra_data 유무와 무관하게 적용)
                update_numbers = [num for num, td in all_by_number.items()
                                   if num not in unique_numbers]
                if update_numbers:
                    existing_records = Tender.query.filter(
                        Tender.tender_number.in_(update_numbers)).all()
                    existing_map = {t.tender_number: t for t in existing_records}
                    for num in update_numbers:
                        td = all_by_number[num]
                        ex = existing_map.get(num)
                        if not ex:
                            continue
                        changed = False
                        if not ex.extra_data and td.get('extra_data'):
                            ex.extra_data = td['extra_data']
                            changed = True
                        if td.get('deadline_date') and ex.deadline_date != td['deadline_date']:
                            ex.deadline_date = td['deadline_date']
                            changed = True
                        if td.get('opening_date') and ex.opening_date != td['opening_date']:
                            ex.opening_date = td['opening_date']
                            changed = True
                        if td.get('status') and ex.status != td['status']:
                            ex.status = td['status']
                            changed = True
                        if td.get('url') and not ex.url:
                            ex.url = td['url']
                            changed = True
                        if td.get('business_number') and not ex.business_number:
                            ex.business_number = td['business_number']
                            changed = True
                        if td.get('agency') and ex.agency != td['agency']:
                            ex.agency = td['agency']
                            changed = True
                        if changed:
                            update_count += 1

                db.session.commit()

                # 크롤링 로그 업데이트
                crawl_log.completed_at = datetime.now()
                crawl_log.total_found = len(all_tenders)
                crawl_log.new_tenders = new_count
                crawl_log.site_results = json.dumps(
                    site_results, ensure_ascii=False)
                crawl_log.status = 'stopped' if self._stop_event.is_set() else 'completed'
                db.session.commit()

                if self._stop_event.is_set():
                    print("[스케줄러] 크롤링 강제 중지됨")
                else:
                    print("[스케줄러] 크롤링 완료")
                print(f"  - 총 수집: {len(all_tenders)}건")
                print(f"  - 새 공고: {new_count}건")
                print(f"  - 업데이트: {update_count}건")
                print(f"  - 중복 제거: {duplicate_count}건")

                # 크롤링 후 smb24 기관명 보정 (agency 없는 건 bizinfo 스크래핑)
                self._fix_smb24_agencies()

                # NIA [조달입찰공고] 중 나라장터 동명 공고가 있으면 중복 처리
                nia_dup_count = mark_nia_procurement_duplicates(self.app)
                if nia_dup_count:
                    print(f"  - NIA 조달입찰공고 중복처리: {nia_dup_count}건")

                # 크롤링 후 코드 변경사항 자동 push (data/는 .gitignore 제외)
                self._git_push()

            except Exception as e:
                # 크롤링 실패
                self._mark_crawl_failed(crawl_log, e)

                print(f"[스케줄러] 크롤링 실패: {str(e)}")

            finally:
                self._is_crawling = False
                self._current_site = None

    def _run_manual_crawl_locked(self, sites=None):
        """
        수동 크롤링 실행

        Args:
            sites (list): 크롤링할 사이트 리스트 (None이면 전체)

        Returns:
            dict: 크롤링 결과
        """
        import threading as _threading
        self._stop_event.clear()
        self._crawl_thread = _threading.current_thread()
        self._is_crawling = True

        print(f"[수동 크롤링] 시작: {datetime.now()}")

        with self.app.app_context():
            crawl_log = CrawlLog(
                started_at=datetime.now(),
                status='running'
            )
            db.session.add(crawl_log)
            db.session.commit()

            try:
                all_tenders = []
                site_results = {}

                # 설정에서 활성화된 사이트 가져오기
                sites_config = settings_manager.get('crawl.sites_config', {})
                if not sites_config:
                    sites_config = settings_manager.get('crawl.sites', {})

                # 예약 크롤과 같은 이유로, 시작 전에 묵은 Selenium 드라이버를 정리한다.
                # 이 처리가 예약 쪽에만 있어서, 수동 크롤은 몇 시간 전 드라이버를
                # 그대로 써 driver.get() 에서 멈출 수 있었다.
                for crawler in self.crawlers.values():
                    if hasattr(crawler, '_close_selenium_driver'):
                        crawler._close_selenium_driver()

                # 크롤링할 사이트 결정
                crawlers_to_run = {}
                if sites:
                    # 사용자가 특정 사이트를 지정한 경우
                    for site in sites:
                        if site in self.crawlers:
                            crawlers_to_run[site] = self.crawlers[site]
                else:
                    # 지정하지 않은 경우 설정에서 활성화된 사이트만 크롤링
                    for site_name, crawler in self.crawlers.items():
                        site_info = sites_config.get(site_name, {})
                        if site_info.get('enabled', True):
                            crawlers_to_run[site_name] = crawler

                # 진행률 초기화
                self._sites_done = 0
                self._sites_total = len(crawlers_to_run)

                # 각 사이트 크롤링 (사이트당 최대 120초 — 진단용 타임아웃)
                for site_name, crawler in crawlers_to_run.items():
                    # 강제 중지 신호 확인
                    if self._stop_event.is_set():
                        print("[수동 크롤링] 중지 신호 수신 — 나머지 크롤러를 건너뜁니다.")
                        break

                    self._current_site = site_name
                    self._current_site_started_at = datetime.now()

                    try:
                        print(f"[{site_name}] 크롤링 시작...")
                        result, status = self._run_crawler_with_timeout(site_name, crawler)
                        site_elapsed = int((datetime.now() - self._current_site_started_at).total_seconds())

                        site_results[site_name] = {
                            'success': result['success'],
                            'count': result['count'],
                            'errors': result.get('errors', [])[:3],
                            'elapsed_sec': site_elapsed,
                        }
                        self._sites_done += 1

                        if status == 'stopped':
                            break
                        if status == 'timeout':
                            continue

                        # 데이터가 있으면 오류가 있어도 저장 (부분 수집 허용)
                        if result['data']:
                            all_tenders.extend(result['data'])
                        if not result['success']:
                            print(f"[{site_name}] 경고 (부분 수집): {result['errors']}")

                    except Exception as e:
                        print(f"[{site_name}] 크롤링 실패: {str(e)}")
                        site_results[site_name] = {
                            'success': False,
                            'count': 0,
                            'errors': [str(e)],
                        }

                # 끝까지 돈 사이트의 브라우저를 닫는다 (다음 크롤까지 띄워 두지 않는다)
                self._close_finished_drivers(site_results)

                # 중복 제거
                unique_tenders, duplicate_count = mark_duplicates_in_db(
                    self.app, all_tenders)

                # DB에 저장 (신규 INSERT + 기존 UPDATE)
                new_count = 0
                update_count = 0
                all_by_number = {t['tender_number']: t for t in all_tenders if t.get('tender_number')}
                unique_numbers = {t['tender_number'] for t in unique_tenders if t.get('tender_number')}

                # 1) 신규 공고 INSERT
                for tender_data in unique_tenders:
                    tender = Tender(
                        title=tender_data['title'],
                        agency=tender_data['agency'],
                        demand_agency=tender_data.get('demand_agency'),
                        tender_number=tender_data['tender_number'],
                        announced_date=tender_data.get('announced_date'),
                        deadline_date=tender_data.get('deadline_date'),
                        opening_date=tender_data.get('opening_date'),
                        estimated_price=tender_data.get('estimated_price'),
                        bid_method=tender_data.get('bid_method'),
                        status=tender_data.get('status', '일반'),
                        is_sme_only=tender_data.get('is_sme_only', False),
                        source_site=tender_data['source_site'],
                        url=tender_data.get('url'),
                        is_duplicate=tender_data.get('is_duplicate', False),
                        extra_data=tender_data.get('extra_data'),
                        business_number=tender_data.get('business_number'),
                    )
                    db.session.add(tender)
                    new_count += 1

                # 2) 기존 공고 UPDATE — 주요 필드 갱신 (extra_data 유무와 무관하게 적용)
                update_numbers = [num for num, td in all_by_number.items()
                                   if num not in unique_numbers]
                if update_numbers:
                    existing_records = Tender.query.filter(
                        Tender.tender_number.in_(update_numbers)).all()
                    existing_map = {t.tender_number: t for t in existing_records}
                    for num in update_numbers:
                        td = all_by_number[num]
                        ex = existing_map.get(num)
                        if not ex:
                            continue
                        changed = False
                        if not ex.extra_data and td.get('extra_data'):
                            ex.extra_data = td['extra_data']
                            changed = True
                        if td.get('deadline_date') and ex.deadline_date != td['deadline_date']:
                            ex.deadline_date = td['deadline_date']
                            changed = True
                        if td.get('opening_date') and ex.opening_date != td['opening_date']:
                            ex.opening_date = td['opening_date']
                            changed = True
                        if td.get('status') and ex.status != td['status']:
                            ex.status = td['status']
                            changed = True
                        if td.get('url') and not ex.url:
                            ex.url = td['url']
                            changed = True
                        if td.get('business_number') and not ex.business_number:
                            ex.business_number = td['business_number']
                            changed = True
                        if td.get('agency') and ex.agency != td['agency']:
                            ex.agency = td['agency']
                            changed = True
                        if changed:
                            update_count += 1

                db.session.commit()

                # 크롤링 로그 업데이트
                crawl_log.completed_at = datetime.now()
                crawl_log.total_found = len(all_tenders)
                crawl_log.new_tenders = new_count
                crawl_log.site_results = json.dumps(
                    site_results, ensure_ascii=False)
                crawl_log.status = 'stopped' if self._stop_event.is_set() else 'completed'
                db.session.commit()

                if self._stop_event.is_set():
                    print("[수동 크롤링] 강제 중지됨")
                else:
                    print("[수동 크롤링] 완료")
                print(f"  - 총 수집: {len(all_tenders)}건")
                print(f"  - 새 공고: {new_count}건")
                print(f"  - 업데이트: {update_count}건")
                print(f"  - 중복 제거: {duplicate_count}건")

                # 크롤링 후 smb24 기관명 보정
                self._fix_smb24_agencies()

                # NIA [조달입찰공고] 중 나라장터 동명 공고가 있으면 중복 처리
                nia_dup_count = mark_nia_procurement_duplicates(self.app)
                if nia_dup_count:
                    print(f"  - NIA 조달입찰공고 중복처리: {nia_dup_count}건")

                return {
                    'success': True,
                    'total_found': len(all_tenders),
                    'new_tenders': new_count,
                    'updated_tenders': update_count,
                    'duplicate_count': duplicate_count,
                    'site_results': site_results
                }

            except Exception as e:
                self._mark_crawl_failed(crawl_log, e)

                print(f"[수동 크롤링] 실패: {str(e)}")

                return {
                    'success': False,
                    'error': str(e)
                }

            finally:
                self._is_crawling = False
                self._current_site = None

    def _load_crawlers(self):
        """설정에서 크롤러 동적 로드"""
        # sites_config 또는 sites 키 사용 (둘 다 확인)
        sites_config = settings_manager.get('crawl.sites_config', {})
        if not sites_config:
            sites_config = settings_manager.get('crawl.sites', {})

        print(f"[스케줄러] 설정에서 로드된 사이트 수: {len(sites_config)}")
        print(f"[스케줄러] 사이트 목록: {list(sites_config.keys())}")

        for site_id, site_info in sites_config.items():
            # 레거시 크롤러가 있으면 우선 사용
            if site_id in self.legacy_crawlers:
                self.crawlers[site_id] = self.legacy_crawlers[site_id]
                print(f"[스케줄러] {site_id}: 레거시 크롤러 사용")
            else:
                # crawler_type에 따라 적절한 크롤러 생성
                crawler_type = site_info.get('crawler_type', 'generic')

                try:
                    if crawler_type == 'api':
                        # API 크롤러 (나라장터 API 등)
                        crawler = G2BApiCrawler(
                            site_info.get('name', site_id), site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: API 크롤러 생성")
                    elif crawler_type == 'pre_spec':
                        # 사전규격 API 크롤러 (나라장터 사전규격)
                        crawler = G2BPreSpecCrawler(
                            site_info.get('name', site_id), site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: 사전규격 API 크롤러 생성")
                    elif crawler_type == 'lh_api':
                        # LH API 크롤러
                        crawler = LHApiCrawler(site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: LH API 크롤러 생성")
                    elif crawler_type == 'smb24_api':
                        # 중소벤처 24 API 크롤러
                        crawler = SMB24ApiCrawler(site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: 중소벤처 24 API 크롤러 생성")
                    elif crawler_type == 'rss':
                        # RSS 피드 크롤러
                        crawler = RSSCrawler(site_info.get('name', site_id), site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: RSS 크롤러 생성")
                    elif crawler_type == 'mois_predece':
                        # 행정안전부 대통령공고 크롤러
                        crawler = MOISPredeceCrawler(site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: 행정안전부 대통령공고 크롤러 생성")
                    elif crawler_type == 'kist_bid':
                        # KIST 입찰정보 API 크롤러 (내부망 전용)
                        crawler = KISTBidCrawler(site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: KIST 입찰정보 API 크롤러 생성")
                    elif crawler_type == 'kist_notice':
                        # KIST 일반공지 크롤러
                        crawler = KISTNoticeCrawler(site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: KIST 일반공지 크롤러 생성")
                    elif crawler_type == 'koica_api':
                        # KOICA 조달정보 API 크롤러
                        crawler = KOICAApiCrawler(site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: KOICA 조달정보 API 크롤러 생성")
                    elif crawler_type == 'kosmes':
                        # 중소벤처기업진흥공단 크롤러
                        crawler = KosmesCrawler(site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: 중소벤처기업진흥공단 크롤러 생성")
                    elif crawler_type == 'sbiz24':
                        # 소상공인24 크롤러
                        crawler = Sbiz24Crawler(site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: 소상공인24 크롤러 생성")
                    else:
                        # GenericCrawler 사용 (일반 웹 크롤링)
                        crawler = GenericCrawler(
                            site_info.get('name', site_id), site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: 범용 크롤러 생성")
                except Exception as e:
                    print(f"[스케줄러] {site_id}: 크롤러 생성 실패 - {str(e)}")

        print(f"[스케줄러] 총 {len(self.crawlers)}개 크롤러 로드됨")

    def _fix_smb24_agencies(self):
        """
        중소벤처 24 공고 중 기관명이 비어있는 건을 bizinfo 페이지 스크래핑으로 보정.
        크롤링 완료 후 자동 실행되며, 수동 크롤링 후에도 호출됨.
        - 대상: source_site='중소벤처 24', agency='', url에 'bizinfo' 포함
        - ThreadPoolExecutor(15 workers)로 병렬 처리
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        try:
            from crawlers.smb24_api_crawler import SMB24ApiCrawler

            with self.app.app_context():
                targets = Tender.query.filter(
                    Tender.source_site == '중소벤처 24',
                    Tender.agency == '',
                    Tender.url.like('%bizinfo%')
                ).all()

                if not targets:
                    print("[SMB24 기관명 보정] 보정 대상 없음")
                    return

                print(f"[SMB24 기관명 보정] 보정 대상: {len(targets)}건 — 병렬 스크래핑 시작")

                _crawler = SMB24ApiCrawler({'service_key': ''})
                # 15개 동시 요청에 맞게 커넥션 풀 확장 (기본값 10 → 15)
                from requests.adapters import HTTPAdapter
                _adapter = HTTPAdapter(pool_connections=1, pool_maxsize=15)
                _crawler.session.mount('http://', _adapter)
                _crawler.session.mount('https://', _adapter)

                def _scrape(tender_id, url):
                    try:
                        return tender_id, _crawler._scrape_agency(url)
                    except Exception:
                        return tender_id, ''

                # 병렬 스크래핑
                id_to_agency = {}
                done = 0
                with ThreadPoolExecutor(max_workers=15) as executor:
                    futures = {
                        executor.submit(_scrape, t.id, t.url): t.id
                        for t in targets
                    }
                    for future in as_completed(futures):
                        tender_id, agency = future.result()
                        id_to_agency[tender_id] = agency
                        done += 1
                        if done % 30 == 0:
                            print(f"  [{done}/{len(targets)}] 스크래핑 중...")

                # DB 일괄 업데이트
                fixed = 0
                for tender in targets:
                    agency = id_to_agency.get(tender.id, '')
                    if agency:
                        tender.agency = agency[:100]
                        fixed += 1

                db.session.commit()
                print(f"[SMB24 기관명 보정] 완료: {fixed}/{len(targets)}건 보정")

        except Exception as e:
            print(f"[SMB24 기관명 보정] 실패: {e}")
            import traceback
            traceback.print_exc()

    def reload_crawlers(self):
        """크롤러 재로드 (설정 변경 시)"""
        print("[스케줄러] 크롤러 재로드 중...")
        self.crawlers = {}
        self._load_crawlers()
