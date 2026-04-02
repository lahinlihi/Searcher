"""
중소벤처기업진흥공단 (kosmes) 입찰공고 크롤러
내부 AJAX API (/sh/nts/notice03.json) 사용
"""

from .base_crawler import BaseCrawler
from datetime import datetime


class KosmesCrawler(BaseCrawler):
    """중소벤처기업진흥공단 입찰공고 크롤러"""

    def __init__(self, site_config):
        super().__init__(
            '중소벤처기업진흥공단',
            'https://www.kosmes.or.kr',
            verify_ssl=False
        )
        self.max_items = site_config.get('max_items', 20)
        self.api_url = 'https://www.kosmes.or.kr/sh/nts/notice03.json'
        self.detail_url = 'https://www.kosmes.or.kr/nsh/SH/NTS/SHNTS006M0.do'

    def crawl(self, **kwargs):
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")

        try:
            response = self.session.post(
                self.api_url,
                data={
                    'nowPage': '1',
                    'pageCount': str(self.max_items),
                    'rowCount': str(self.max_items),
                    'param': 'proc=List'
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'},
                timeout=30
            )

            if response.status_code != 200:
                self.errors.append(f"API 호출 실패: HTTP {response.status_code}")
                return self.get_results()

            data = response.json()
            items = data.get('ds_infoList', [])
            print(f"  전체 {len(items)}건")

            for item in items:
                try:
                    tender = self._parse_item(item)
                    if tender:
                        self.results.append(tender)
                except Exception as e:
                    print(f"  항목 파싱 오류: {e}")

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            self.errors.append(f"크롤링 오류: {str(e)}")
            print(f"[{self.site_name}] {e}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _parse_item(self, item):
        slno = item.get('BUBD_BID_PUAN_SLNO')
        title = item.get('TITL_NM', '').strip()
        if not slno or not title:
            return None

        announced_date = self._parse_dt(item.get("TO_CHAR(REG_DTM,'YYYYMMDD')", ''))
        deadline_date = self._parse_dt_str(item.get('BIDPRICE_TTIME', ''))
        opening_date = self._parse_dt_str(item.get('BIDPRICE_STIME', ''))

        return {
            'title': title[:200],
            'agency': '중소벤처기업진흥공단',
            'tender_number': f"KOSMES-{slno}",
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': opening_date,
            'estimated_price': None,
            'bid_method': '일반경쟁입찰',
            'status': '일반',
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': f"{self.detail_url}?BUBD_BID_PUAN_SLNO={slno}"
        }

    def _parse_dt(self, date_str):
        """YYYYMMDD 형식 파싱"""
        if not date_str or len(date_str) < 8:
            return None
        try:
            return datetime.strptime(date_str[:8], '%Y%m%d')
        except ValueError:
            return None

    def _parse_dt_str(self, date_str):
        """YYYY-MM-DD HH:MM 형식 파싱"""
        if not date_str or date_str == '--':
            return None
        try:
            return datetime.strptime(date_str.strip(), '%Y-%m-%d %H:%M')
        except ValueError:
            try:
                return datetime.strptime(date_str.strip()[:10], '%Y-%m-%d')
            except ValueError:
                return None
