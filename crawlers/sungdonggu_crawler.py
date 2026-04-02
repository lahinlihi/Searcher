"""
성동구 크롤러
성동구청 입찰공고 크롤링
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import random


class SungDongGuCrawler(BaseCrawler):
    """성동구 크롤러 (샘플)"""

    def __init__(self):
        super().__init__('성동구', 'https://www.sd.go.kr')

    def crawl(self, **kwargs):
        """성동구 공고 크롤링"""
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")

        # 샘플 데이터 생성
        num_tenders = random.randint(2, 8)
        for i in range(num_tenders):
            tender_number = f'SD-{datetime.now().year}-{random.randint(10000, 99999)}'

            # 성동구 특화 공고 제목
            titles = [
                f'성동구 공공시설 {i + 1} 건설공사',
                f'성동구청 IT 시스템 구축 {i + 1}',
                f'성동구 도로 보수 공사 {i + 1}',
                f'성동구 복지시설 운영 용역 {i + 1}',
                f'성동구 환경 개선 사업 {i + 1}'
            ]

            tender = {
                'title': random.choice(titles),
                'agency': '성동구청',
                'tender_number': tender_number,
                'announced_date': datetime.now() - timedelta(days=random.randint(1, 10)),
                'deadline_date': datetime.now() + timedelta(days=random.randint(5, 25)),
                'opening_date': datetime.now() + timedelta(days=random.randint(6, 26)),
                'estimated_price': random.randint(30, 150) * 1000000,
                'bid_method': '일반경쟁입찰',
                'status': '일반',
                'is_sme_only': random.choice([True, False]),
                'source_site': self.site_name,
                'url': f"{self.base_url}/main/selectBbsNttView.do?key=1473&bbsNo=184&nttNo={tender_number}"
            }
            self.results.append(tender)

        print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")
        return self.get_results()
