"""
범부처통합연구지원시스템(IRIS) 크롤러
AJAX JSON API 직접 호출 방식 (Selenium 불필요)
- 접수중  → 일반공고 (나라장터 일반 상당)
- 접수예정 → 사전규격 (나라장터 사전규격 상당)
"""

from .base_crawler import BaseCrawler
from datetime import datetime
import re
import unicodedata


class IrisCrawler(BaseCrawler):
    """IRIS 크롤러 — AJAX JSON API 방식"""

    # HTML 목록 페이지 (Referer 헤더용)
    LIST_URL = 'https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do'
    # AJAX 데이터 엔드포인트
    AJAX_URL = 'https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituList.do'
    # 상세 페이지 URL 템플릿
    DETAIL_URL = 'https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituDtlView.do?bsnsAncmSn={ancm_id}'

    def __init__(self, site_config=None):
        super().__init__(
            site_name='IRIS',
            base_url='https://www.iris.go.kr',
            use_selenium=False   # AJAX 방식 — Selenium 불필요
        )
        self.site_config = site_config or {}
        # 접수예정 최대 수집 페이지 수 (기본 5 = 50건)
        self.max_pages_pre = self.site_config.get('max_pages_pre', 5)
        # Referer / AJAX 요청 헤더 추가
        self.session.headers.update({
            'Referer': self.LIST_URL,
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded',
        })

    def crawl(self, **kwargs):
        """접수중(일반) + 접수예정(사전규격) 수집

        접수중: 전체 페이지 수집 (보통 수십~백 건 수준)
        접수예정: max_pages_pre 페이지까지만 (기본 5페이지=50건, 과거 데이터 방대)
        """
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")

        # 접수예정 최대 페이지 수 (site_config 또는 kwarg, 기본 5)
        max_pages_pre = kwargs.get('max_pages_pre', self.max_pages_pre)

        tabs = [
            ('ancmIng', '일반',      None),           # 접수중 — 전체 수집
            ('ancmPre', '사전규격',  max_pages_pre),  # 접수예정 — 최근 n페이지만
        ]

        for ancm_prg, status, max_pages in tabs:
            label = '접수중' if ancm_prg == 'ancmIng' else f'접수예정(최대{max_pages}페이지)'
            print(f"[{self.site_name}] [{label}] 수집 시작...")
            try:
                count_before = len(self.results)
                self._crawl_tab(ancm_prg, status, max_pages=max_pages)
                added = len(self.results) - count_before
                print(f"[{self.site_name}] [{label}] {added}건 수집")
            except Exception as e:
                self.errors.append(f"[{label}] 크롤링 오류: {str(e)}")
                print(f"[{self.site_name}] [{label}] 오류: {str(e)}")

        print(f"[{self.site_name}] 완료: 총 {len(self.results)}건 수집")
        return self.get_results()

    # ------------------------------------------------------------------
    # 탭별 전체 페이지 수집
    # ------------------------------------------------------------------

    def _crawl_tab(self, ancm_prg, status, max_pages=None):
        """지정 탭을 순회하며 수집. max_pages=None이면 전체 페이지."""
        page = 1
        while True:
            data = self._fetch_page(ancm_prg, page)
            if not data:
                break

            items = data.get('listBsnsAncmBtinSitu', [])
            if not items:
                break

            for item in items:
                try:
                    tender = self._parse_item(item, status)
                    if tender:
                        self.results.append(tender)
                except Exception as e:
                    print(f"[{self.site_name}] 항목 파싱 오류: {str(e)}")
                    continue

            pagination = data.get('paginationInfo', {})
            total_pages = pagination.get('totalPageCount', 1)
            current_page = pagination.get('currentPageNo', page)
            print(f"[{self.site_name}]   페이지 {current_page}/{total_pages} 처리 완료")

            # 마지막 페이지 또는 최대 페이지 도달 시 종료
            if current_page >= total_pages:
                break
            if max_pages is not None and current_page >= max_pages:
                print(f"[{self.site_name}]   최대 페이지({max_pages}) 도달, 수집 종료")
                break
            page += 1

    # ------------------------------------------------------------------
    # AJAX POST 요청
    # ------------------------------------------------------------------

    def _fetch_page(self, ancm_prg, page):
        """AJAX 엔드포인트에 POST 요청 → JSON 반환"""
        payload = {
            'bizSearch': '',
            'bsnsTl': '',
            'ancmPrg': ancm_prg,
            'pageIndex': str(page),
            'ancmId': '',
            'ancmNo': '',
            'ancmTurn': '',
            'seq': '',
            'hirkSorgnBsnsCd': '',
            'bsnsAncmTap': '',
            'shSorgnYyBsnsCd': '',
            'sorgnIdArr': '',
            'ancmSttArr': '',
            'pbofrTpArr': '',
            'qualCndtArr': '',
            'blngGovdSeArr': '',
            'techFildArr': '',
            'shBsnsYy': '',
            'prgmId': '',
        }
        try:
            resp = self.session.post(
                self.AJAX_URL,
                data=payload,
                timeout=30,
                verify=True,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            self.errors.append(f"페이지 요청 실패 (ancmPrg={ancm_prg}, page={page}): {str(e)}")
            return None

    # ------------------------------------------------------------------
    # 항목 파싱
    # ------------------------------------------------------------------

    def _parse_item(self, item, status):
        """JSON 항목 → 공고 dict"""
        title = self._sanitize_text(item.get('ancmTl', ''))
        if not title:
            return None

        ancm_id = item.get('ancmId', '')
        if not ancm_id:
            return None

        # 기관: 소관기관(sorgnNm) 표시, 부처(blngGovdSeNm) 보조
        agency = self._sanitize_text(
            item.get('sorgnNm') or item.get('blngGovdSeNm') or 'IRIS'
        )

        # 공고번호
        tender_number = self._sanitize_text(item.get('ancmNo', '')) or f"IRIS_{ancm_id}"

        # 날짜
        announced_date = self._parse_date(item.get('ancmDe', ''))    # 공고일자 YYYY-MM-DD
        deadline_date  = self._parse_dotdate(item.get('rcveEndDe', ''))  # 접수마감 YYYY.MM.DD
        start_date     = self._parse_dotdate(item.get('rcveStrDe', ''))  # 접수시작 YYYY.MM.DD

        # 상세 URL
        url = self.DETAIL_URL.format(ancm_id=ancm_id)

        return {
            'title':           title[:200],
            'agency':          agency[:100],
            'tender_number':   tender_number,
            'announced_date':  announced_date,
            'deadline_date':   deadline_date,
            'opening_date':    None,
            'estimated_price': None,
            'bid_method':      '공모',
            'status':          status,
            'is_sme_only':     False,
            'source_site':     self.site_name,
            'url':             url,
        }

    # ------------------------------------------------------------------
    # 날짜 파싱 헬퍼
    # ------------------------------------------------------------------

    def _parse_date(self, date_text):
        """YYYY-MM-DD 형식 파싱"""
        if not date_text:
            return None
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', str(date_text).strip())
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                pass
        return None

    def _parse_dotdate(self, date_text):
        """YYYY.MM.DD 형식 파싱"""
        if not date_text:
            return None
        m = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', str(date_text).strip())
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except Exception:
                pass
        return None

    def _sanitize_text(self, text):
        """텍스트 정리"""
        if not text:
            return ''
        text = str(text).replace('\ufffd', '')
        text = ''.join(
            ch for ch in text
            if unicodedata.category(ch)[0] != 'C' or ch in '\t\n\r'
        )
        return re.sub(r'\s+', ' ', text).strip()
