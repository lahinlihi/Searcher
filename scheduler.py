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


class CrawlScheduler:
    """크롤링 스케줄러"""

    def __init__(self, app):
        self.app = app
        self.scheduler = BackgroundScheduler(timezone='Asia/Seoul')

        # 크롤링 중지 제어
        import threading
        self._stop_event = threading.Event()   # set() 하면 크롤러 루프 중단
        self._crawl_thread = None              # 현재 실행 중인 크롤 스레드

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

        # 크롤러 모드: 매일 09:00, 17:00
        # misfire_grace_time: APScheduler 기본값(1초)이 너무 짧아 스케줄러 스레드가
        # 트리거 시점에 잠깐만 지연돼도(다른 작업 충돌, GC 등) 그날 실행이 조용히 스킵되는
        # 문제가 반복됐음. 여유 있게 잡아 트리거 시점이 지나도 그날 안에는 늦게라도 실행되게 함.
        self.scheduler.add_job(
            func=self.run_crawl_job,
            trigger=CronTrigger(hour=9, minute=0),
            id='crawl_morning',
            name='오전 크롤링',
            replace_existing=True,
            misfire_grace_time=3600
        )

        self.scheduler.add_job(
            func=self.run_crawl_job,
            trigger=CronTrigger(hour=17, minute=0),
            id='crawl_evening',
            name='오후 크롤링',
            replace_existing=True,
            misfire_grace_time=3600
        )

        self.scheduler.start()
        print("[스케줄러] 자동 크롤링 스케줄러가 시작되었습니다.")
        print("[스케줄러] - 오전 09:00")
        print("[스케줄러] - 오후 17:00")

    def stop(self):
        """스케줄러 중지"""
        self.scheduler.shutdown()
        print("[스케줄러] 스케줄러가 중지되었습니다.")

    @property
    def is_crawling(self):
        """현재 크롤링이 진행 중인지 여부"""
        return self._crawl_thread is not None and self._crawl_thread.is_alive()

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
        """
        크롤링 작업 실행
        모든 사이트를 크롤링하고 결과를 DB에 저장
        """
        import threading as _threading
        self._stop_event.clear()
        self._crawl_thread = _threading.current_thread()

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
                crawl_log.completed_at = datetime.now()
                crawl_log.status = 'failed'
                crawl_log.error_message = str(e)
                db.session.commit()

                print(f"[스케줄러] 크롤링 실패: {str(e)}")

    def run_manual_crawl(self, sites=None):
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
                crawl_log.completed_at = datetime.now()
                crawl_log.status = 'failed'
                crawl_log.error_message = str(e)
                db.session.commit()

                print(f"[수동 크롤링] 실패: {str(e)}")

                return {
                    'success': False,
                    'error': str(e)
                }

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
