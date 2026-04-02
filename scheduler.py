"""
자동 크롤링 스케줄러
APScheduler를 사용하여 정해진 시간에 자동으로 크롤링을 실행합니다.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import json

from crawlers.sungdonggu_crawler import SungDongGuCrawler
from crawlers.generic_crawler import GenericCrawler
from crawlers.g2b_api_crawler import G2BApiCrawler
from crawlers.g2b_pre_spec_crawler import G2BPreSpecCrawler
from crawlers.iris_crawler import IrisCrawler
from crawlers.lh_api_crawler import LHApiCrawler
from crawlers.smb24_api_crawler import SMB24ApiCrawler
from crawlers.kosmes_crawler import KosmesCrawler
from crawlers.rss_crawler import RSSCrawler
from crawlers.mois_predece_crawler import MOISPredeceCrawler
from crawlers.kist_bid_crawler import KISTBidCrawler
from crawlers.kist_notice_crawler import KISTNoticeCrawler
from crawlers.koica_api_crawler import KOICAApiCrawler
from deduplication import mark_duplicates_in_db
from database import db, Tender, CrawlLog
from settings_manager import settings_manager


class CrawlScheduler:
    """크롤링 스케줄러"""

    def __init__(self, app):
        self.app = app
        self.scheduler = BackgroundScheduler(timezone='Asia/Seoul')

        # 레거시 크롤러 (하드코딩)
        self.legacy_crawlers = {
            'sung-dong-gu': SungDongGuCrawler()
        }

        # 동적 크롤러는 설정에서 로드
        self.crawlers = {}
        self._load_crawlers()

    def start(self):
        """스케줄러 시작"""
        # 크롤링 작업 스케줄 추가 (예: 매일 09:00, 17:00)
        self.scheduler.add_job(
            func=self.run_crawl_job,
            trigger=CronTrigger(hour=9, minute=0),
            id='crawl_morning',
            name='오전 크롤링',
            replace_existing=True
        )

        self.scheduler.add_job(
            func=self.run_crawl_job,
            trigger=CronTrigger(hour=17, minute=0),
            id='crawl_evening',
            name='오후 크롤링',
            replace_existing=True
        )

        self.scheduler.start()
        print("[스케줄러] 자동 크롤링 스케줄러가 시작되었습니다.")
        print("[스케줄러] - 오전 09:00")
        print("[스케줄러] - 오후 17:00")

    def stop(self):
        """스케줄러 중지"""
        self.scheduler.shutdown()
        print("[스케줄러] 스케줄러가 중지되었습니다.")

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
                cwd=repo_dir, capture_output=True, text=True, timeout=15
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
            subprocess.run(['git', 'add', '-A'], cwd=repo_dir, timeout=15)

            commit_msg = (
                f"auto: Claude Code 수정 반영 "
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]"
            )
            commit_result = subprocess.run(
                ['git', 'commit', '-m', commit_msg],
                cwd=repo_dir, capture_output=True, text=True, timeout=15
            )
            if commit_result.returncode != 0:
                print(f"[스케줄러] git commit 실패: {commit_result.stderr.strip()}")
                return

            push_result = subprocess.run(
                ['git', 'push'],
                cwd=repo_dir, capture_output=True, text=True, timeout=60
            )
            if push_result.returncode == 0:
                print("[스케줄러] git push: GitHub 업로드 완료")
            else:
                print(f"[스케줄러] git push 실패 (무시하고 계속): {push_result.stderr.strip()}")

        except Exception as e:
            print(f"[스케줄러] git push 오류 (무시하고 계속): {e}")

    def run_crawl_job(self):
        """
        크롤링 작업 실행
        모든 사이트를 크롤링하고 결과를 DB에 저장
        """
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

                # 각 사이트 크롤링
                for site_name, crawler in self.crawlers.items():
                    # 설정에서 비활성화된 사이트는 건너뛰기
                    site_info = sites_config.get(site_name, {})
                    if not site_info.get('enabled', True):
                        print(f"[{site_name}] 설정에서 비활성화됨 - 건너뜀")
                        continue

                    try:
                        print(f"[{site_name}] 크롤링 시작...")
                        result = crawler.crawl()

                        site_results[site_name] = {
                            'success': result['success'],
                            'count': result['count']
                        }

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
                            'error': str(e)
                        }

                # 중복 제거
                unique_tenders, duplicate_count = mark_duplicates_in_db(
                    self.app, all_tenders)

                # DB에 저장
                new_count = 0
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
                        is_duplicate=tender_data.get('is_duplicate', False)
                    )
                    db.session.add(tender)
                    new_count += 1

                db.session.commit()

                # 크롤링 로그 업데이트
                crawl_log.completed_at = datetime.now()
                crawl_log.total_found = len(all_tenders)
                crawl_log.new_tenders = new_count
                crawl_log.site_results = json.dumps(
                    site_results, ensure_ascii=False)
                crawl_log.status = 'completed'
                db.session.commit()

                print("[스케줄러] 크롤링 완료")
                print(f"  - 총 수집: {len(all_tenders)}건")
                print(f"  - 새 공고: {new_count}건")
                print(f"  - 중복 제거: {duplicate_count}건")

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

                # 각 사이트 크롤링
                for site_name, crawler in crawlers_to_run.items():
                    try:
                        print(f"[{site_name}] 크롤링 시작...")
                        result = crawler.crawl()

                        site_results[site_name] = {
                            'success': result['success'],
                            'count': result['count']
                        }

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
                            'error': str(e)
                        }

                # 중복 제거
                unique_tenders, duplicate_count = mark_duplicates_in_db(
                    self.app, all_tenders)

                # DB에 저장
                new_count = 0
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
                        is_duplicate=tender_data.get('is_duplicate', False)
                    )
                    db.session.add(tender)
                    new_count += 1

                db.session.commit()

                # 크롤링 로그 업데이트
                crawl_log.completed_at = datetime.now()
                crawl_log.total_found = len(all_tenders)
                crawl_log.new_tenders = new_count
                crawl_log.site_results = json.dumps(
                    site_results, ensure_ascii=False)
                crawl_log.status = 'completed'
                db.session.commit()

                print("[수동 크롤링] 완료")
                print(f"  - 총 수집: {len(all_tenders)}건")
                print(f"  - 새 공고: {new_count}건")
                print(f"  - 중복 제거: {duplicate_count}건")

                return {
                    'success': True,
                    'total_found': len(all_tenders),
                    'new_tenders': new_count,
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
                    elif crawler_type == 'iris':
                        # IRIS 전용 크롤러
                        crawler = IrisCrawler()
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: IRIS 전용 크롤러 생성")
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
                    else:
                        # GenericCrawler 사용 (일반 웹 크롤링)
                        crawler = GenericCrawler(
                            site_info.get('name', site_id), site_info)
                        self.crawlers[site_id] = crawler
                        print(f"[스케줄러] {site_id}: 범용 크롤러 생성")
                except Exception as e:
                    print(f"[스케줄러] {site_id}: 크롤러 생성 실패 - {str(e)}")

        print(f"[스케줄러] 총 {len(self.crawlers)}개 크롤러 로드됨")

    def reload_crawlers(self):
        """크롤러 재로드 (설정 변경 시)"""
        print("[스케줄러] 크롤러 재로드 중...")
        self.crawlers = {}
        self._load_crawlers()
