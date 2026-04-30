"""
소상공인24 (sbiz24.kr) 크롤러
소진공 공고조회 및 신청 목록 크롤링
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import json


class Sbiz24Crawler(BaseCrawler):
    """소상공인24 크롤러"""

    RCRT_TYPE_LABELS = {
        '101': '소상공인',
        '102': '전통시장',
        '113': '소상공인/예비창업자',
        '104': '예비창업자',
        '105': '청년창업자',
    }

    def __init__(self, site_config=None):
        super().__init__(
            site_name='소상공인24',
            base_url='https://www.sbiz24.kr'
        )
        site_config = site_config or {}
        self.days_range = site_config.get('days_range', 30)
        self.max_items = site_config.get('max_items', 100)

        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Origin-Method': 'GET',
            'Referer': 'https://www.sbiz24.kr/',
        })

    def _init_session(self):
        """익명 세션 초기화 (Bearer 없이 /api/auth 호출)"""
        self.session.get(f'{self.base_url}/', timeout=10)
        self.session.post(
            f'{self.base_url}/api/auth',
            json={},
            headers={'Authorization': ''},
            timeout=10
        )

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")

        try:
            self._init_session()
            self._fetch_all()
            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            error_msg = f"크롤링 오류: {str(e)}"
            self.errors.append(error_msg)
            print(f"[{self.site_name}] {error_msg}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _fetch_all(self):
        """페이지 반복 수집"""
        page_size = 50
        start_row = 0
        cutoff = datetime.now() - timedelta(days=self.days_range)

        while len(self.results) < self.max_items:
            payload = {
                'sortModel': [{'colId': 'rcptPd.from', 'sort': 'desc'}],
                'search': {
                    'searchValue': '',
                    'rcrtTypeCdNmList': [],
                    'regionNmList': [],
                    'tpbizCdList': [],
                    'bhis': {'from': None, 'to': None},
                    'wrkr': {'from': None, 'to': None},
                    'sls': {'from': None, 'to': None},
                    'aplySeYn': 'N',
                    'sbrPbancYn': 'N',
                    'itrstPbancYn': 'N',
                    'departNmList': None,
                    'ptPbancSortBy': 'INSERT',
                    'pbancNm': '',
                    'regionCdList': [],
                },
                'paging': True,
                'startRow': start_row,
                'endRow': start_row + page_size,
            }

            resp = self.session.post(
                f'{self.base_url}/api/pbanc/sbiz24PbancList',
                json=payload,
                timeout=20
            )

            if resp.status_code != 200:
                self.errors.append(f"API 오류: HTTP {resp.status_code}")
                break

            data = resp.json()
            if not data.get('result'):
                self.errors.append(f"API result=false: {data.get('message', '')}")
                break

            items = data.get('data', {}).get('default', {}).get('list', [])
            total = data.get('data', {}).get('default', {}).get('total', 0)

            if start_row == 0:
                print(f"  전체 {total}건, 최대 {self.max_items}건 수집 예정")

            if not items:
                break

            for item in items:
                try:
                    tender = self._parse_item(item)
                    if tender:
                        self.results.append(tender)
                except Exception as e:
                    print(f"  항목 파싱 오류: {e}")

            start_row += page_size
            if start_row >= total or start_row >= self.max_items:
                break

    def _parse_item(self, item):
        """개별 공고 항목 파싱"""
        pbanc_sn = item.get('pbancSn')
        if not pbanc_sn:
            return None

        title = (item.get('pbancNm') or '').strip()
        if not title:
            return None

        rcrt_type_cd = item.get('rcrtTypeCd', '')
        rcrt_label = self.RCRT_TYPE_LABELS.get(rcrt_type_cd, '소상공인')

        rcpt_pd = item.get('rcptPd') or {}
        biz_pd = item.get('bizPd') or {}

        announced_date = self._parse_datetime(rcpt_pd.get('from'))
        deadline_date = self._parse_datetime(rcpt_pd.get('to'))
        opening_date = self._parse_date(biz_pd.get('from'))

        aply_se = item.get('aplyPsbltySe', '')
        if aply_se == 'Y':
            status = '접수중'
        elif aply_se == 'EX':
            status = '마감'
        else:
            status = '일반'

        url = f'{self.base_url}/#/pbanc/{pbanc_sn}'

        return {
            'title': title[:200],
            'agency': '소상공인시장진흥공단',
            'tender_number': f'SBIZ24-{pbanc_sn}',
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': opening_date,
            'estimated_price': None,
            'bid_method': rcrt_label,
            'status': status,
            'is_sme_only': True,
            'source_site': self.site_name,
            'url': url,
        }

    def _parse_datetime(self, dt_str):
        """'YYYY-MM-DD HH:mm' 또는 'YYYY-MM-DD' 형식 파싱"""
        if not dt_str:
            return None
        dt_str = dt_str.strip()
        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None

    def _parse_date(self, date_str):
        """'YYYY-MM-DD' 형식 파싱"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str.strip(), '%Y-%m-%d')
        except ValueError:
            return None
