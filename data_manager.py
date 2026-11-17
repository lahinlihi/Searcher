"""
데이터 관리 기능
오래된 공고 삭제, 데이터베이스 초기화 등의 데이터 관리 기능을 제공합니다.
"""

from datetime import datetime, timedelta
from database import db, Tender, Filter, CrawlLog, Bookmark


class DataManager:
    """데이터 관리 클래스"""

    def __init__(self, app):
        self.app = app

    def delete_old_tenders(self, days=30):
        """
        오래된 공고 삭제

        Args:
            days (int): 보관 기간 (일)

        Returns:
            int: 삭제된 공고 수
        """
        with self.app.app_context():
            try:
                cutoff_date = datetime.now() - timedelta(days=days)

                # 오래된 공고 조회
                old_tenders = Tender.query.filter(
                    Tender.created_at < cutoff_date
                ).all()

                count = len(old_tenders)

                # 삭제
                for tender in old_tenders:
                    db.session.delete(tender)

                db.session.commit()

                print(f"[데이터 관리] {days}일 이상 오래된 공고 {count}건 삭제 완료")
                return count

            except Exception as e:
                db.session.rollback()
                print(f"[데이터 관리] 오래된 공고 삭제 실패: {str(e)}")
                return 0



    def reset_database(self, keep_filters=True):
        """
        데이터베이스 초기화

        Args:
            keep_filters (bool): 필터 프리셋 유지 여부

        Returns:
            dict: 삭제된 레코드 수
        """
        with self.app.app_context():
            try:
                result = {
                    'tenders': 0,
                    'logs': 0,
                    'bookmarks': 0,
                    'filters': 0
                }

                # 공고 삭제
                tender_count = Tender.query.count()
                Tender.query.delete()
                result['tenders'] = tender_count

                # 크롤링 로그 삭제
                log_count = CrawlLog.query.count()
                CrawlLog.query.delete()
                result['logs'] = log_count

                # 즐겨찾기 삭제
                bookmark_count = Bookmark.query.count()
                Bookmark.query.delete()
                result['bookmarks'] = bookmark_count

                # 필터 삭제 (옵션)
                if not keep_filters:
                    filter_count = Filter.query.count()
                    Filter.query.delete()
                    result['filters'] = filter_count

                db.session.commit()

                print("[데이터 관리] 데이터베이스 초기화 완료")
                print(f"  - 공고: {result['tenders']}건")
                print(f"  - 로그: {result['logs']}건")
                print(f"  - 즐겨찾기: {result['bookmarks']}건")
                if not keep_filters:
                    print(f"  - 필터: {result['filters']}건")

                return result

            except Exception as e:
                db.session.rollback()
                print(f"[데이터 관리] 데이터베이스 초기화 실패: {str(e)}")
                return None

    def get_database_stats(self):
        """
        데이터베이스 통계 조회

        Returns:
            dict: 통계 정보
        """
        with self.app.app_context():
            try:
                stats = {
                    'total_tenders': Tender.query.count(),
                    'active_tenders': Tender.query.filter(
                        Tender.deadline_date >= datetime.now()).count(),
                    'expired_tenders': Tender.query.filter(
                        Tender.deadline_date < datetime.now()).count(),
                    'pre_announcement': Tender.query.filter_by(
                        status='사전규격').count(),
                    'total_filters': Filter.query.count(),
                    'total_logs': CrawlLog.query.count(),
                    'total_bookmarks': Bookmark.query.count(),
                    'latest_crawl': None}

                # 최근 크롤링 시간
                latest_log = CrawlLog.query.order_by(
                    CrawlLog.started_at.desc()).first()
                if latest_log:
                    stats['latest_crawl'] = latest_log.started_at.isoformat()

                return stats

            except Exception as e:
                print(f"[데이터 관리] 통계 조회 실패: {str(e)}")
                return None


    def cleanup_duplicates(self):
        """
        중복 공고 정리

        Returns:
            int: 삭제된 중복 공고 수
        """
        with self.app.app_context():
            try:
                # is_duplicate=True인 공고 삭제
                duplicate_tenders = Tender.query.filter_by(
                    is_duplicate=True).all()
                count = len(duplicate_tenders)

                for tender in duplicate_tenders:
                    db.session.delete(tender)

                db.session.commit()

                print(f"[데이터 관리] 중복 공고 {count}건 삭제 완료")
                return count

            except Exception as e:
                db.session.rollback()
                print(f"[데이터 관리] 중복 공고 삭제 실패: {str(e)}")
                return 0

