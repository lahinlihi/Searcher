"""
범부처통합연구지원시스템(IRIS) 크롤러
접수예정 → 사전규격, 접수중 → 일반공고
"""

from .base_crawler import BaseCrawler
from datetime import datetime
import re
import unicodedata


class IrisCrawler(BaseCrawler):
    """IRIS 크롤러"""

    def __init__(self):
        super().__init__(
            site_name='IRIS',
            base_url='https://www.iris.go.kr',
            use_selenium=True
        )
        self.crawl_url = 'https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do'

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")

        try:
            # Selenium으로 페이지 로드 (wait_time=5초로 AJAX 대기)
            soup = self.fetch_page(self.crawl_url, wait_time=5)

            if not soup:
                raise Exception("페이지를 가져올 수 없습니다")

            # 공고 목록 파싱
            self._parse_tender_list(soup)

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            self.errors.append(f"크롤링 오류: {str(e)}")
            print(f"[{self.site_name}] 오류: {str(e)}")
        finally:
            # Selenium 드라이버 종료
            self._close_selenium_driver()

        return self.get_results()

    def _parse_tender_list(self, soup):
        """공고 목록 파싱"""
        # .dbody 컨테이너 찾기
        dbody = soup.select_one('.dbody')
        if not dbody:
            print(f"[{self.site_name}] 공고 목록을 찾을 수 없습니다")
            return

        # 공고 항목들 (li 요소)
        items = dbody.select('li')
        print(f"[{self.site_name}] {len(items)}개의 공고 발견")

        for idx, item in enumerate(items[:100]):  # 최대 100개
            try:
                tender = self._parse_tender_item(item, idx)
                if tender:
                    self.results.append(tender)
            except Exception as e:
                print(f"[{self.site_name}] 항목 {idx + 1} 파싱 오류: {str(e)}")
                continue

    def _parse_tender_item(self, item, idx):
        """개별 공고 항목 파싱"""
        # 1. 기관명
        agency_elem = item.select_one('.inst_title')
        agency = self._sanitize_text(
            agency_elem.get_text(
                strip=True)) if agency_elem else 'IRIS'

        # 2. 제목
        title_elem = item.select_one('.title a')
        if not title_elem:
            return None
        title = self._sanitize_text(title_elem.get_text(strip=True))

        # 3. 링크 및 공고 ID 추출
        onclick = title_elem.get('onclick', '')
        tender_id, status_code = self._extract_id_from_onclick(onclick)

        if not tender_id:
            print(f"[{self.site_name}] 공고 ID를 추출할 수 없습니다: {onclick}")
            return None

        # 링크 생성
        url = f"{
            self.base_url}/contents/retrieveBsnsAncmBtinSituDtlView.do?bsnsAncmSn={tender_id}"

        # 4. 메타정보 추출
        meta_elems = item.select('.etc_info span')
        tender_number = ''
        announced_date = None
        status_text = ''

        for meta in meta_elems:
            text = meta.get_text(strip=True)

            # 공고번호
            if '공고번호' in text or 'KN_' in text:
                tender_number = text.split(
                    ':', 1)[-1].strip() if ':' in text else text.strip()

            # 공고일자
            elif '공고일자' in text or meta.get('class') and 'ancmDe' in meta.get('class', []):
                date_text = text.split(
                    ':', 1)[-1].strip() if ':' in text else text.strip()
                announced_date = self._parse_date(date_text)

            # 공고상태
            elif '공고상태' in text or meta.get('class') and 'rcveSttSeNmLst' in meta.get('class', []):
                status_text = text.split(
                    ':', 1)[-1].strip() if ':' in text else text.strip()

        # 5. 상태 배지 (접수중/접수예정/마감)
        badge_elem = item.select_one('.d_day')
        badge_text = badge_elem.get_text(strip=True) if badge_elem else ''

        # 6. 상태 판단 (접수예정 → 사전규격, 접수중 → 일반)
        # status_text에 "예정"이 있거나 badge_text가 "접수예정"이면 사전규격
        if '예정' in status_text or '예정' in badge_text:
            status = '사전규격'
        else:
            status = '일반'

        # 7. 공고번호 생성 (없으면 ID 사용)
        if not tender_number:
            tender_number = f"IRIS_{tender_id}"

        # 8. 마감일 추정 (공고일 + 30일, 실제 마감일은 상세 페이지에서 확인 필요)
        deadline_date = None
        if announced_date:
            from datetime import timedelta
            deadline_date = announced_date + timedelta(days=30)

        return {
            'title': title,
            'agency': agency,
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': None,
            'estimated_price': None,
            'bid_method': '공모',
            'status': status,
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': url
        }

    def _extract_id_from_onclick(self, onclick):
        """
        onclick 속성에서 공고 ID와 상태 코드 추출
        예: f_bsnsAncmBtinSituListForm_view('017974','ancmIng')
        → ('017974', 'ancmIng')
        """
        # 정규식으로 추출
        pattern = r"f_bsnsAncmBtinSituListForm_view\('([^']+)','([^']+)'\)"
        match = re.search(pattern, onclick)

        if match:
            return match.group(1), match.group(2)
        return None, None

    def _parse_date(self, date_text):
        """날짜 파싱"""
        if not date_text:
            return None

        # 날짜만 추출 (YYYY-MM-DD 형식)
        date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_text)
        if date_match:
            try:
                return datetime(
                    int(date_match.group(1)),
                    int(date_match.group(2)),
                    int(date_match.group(3))
                )
            except BaseException:
                pass

        return None

    def _sanitize_text(self, text):
        """텍스트 정리: 특수문자, replacement character 등을 제거"""
        if not text:
            return text

        # Replacement character (�, U+FFFD) 제거
        text = text.replace('\ufffd', '')

        # 기타 제어 문자 제거 (탭, 개행 제외)
        text = ''.join(char for char in text if unicodedata.category(
            char)[0] != 'C' or char in '\t\n\r')

        # 연속된 공백을 하나로
        text = re.sub(r'\s+', ' ', text)

        # 앞뒤 공백 제거
        text = text.strip()

        return text
