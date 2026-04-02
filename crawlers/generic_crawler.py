"""
범용 크롤러
설정 기반으로 다양한 사이트를 크롤링할 수 있는 범용 크롤러
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import random
import re
import unicodedata


class GenericCrawler(BaseCrawler):
    """
    설정 기반 범용 크롤러

    사이트 설정에 다음 정보가 포함되어야 함:
    - crawl_url: 크롤링할 페이지 URL
    - crawl_type: 'list' (공고 목록 페이지) 또는 'sample' (샘플 데이터 생성)
    - selectors: CSS 셀렉터 정보 (선택사항)
    """

    def __init__(self, site_name, site_config):
        """
        Args:
            site_name (str): 사이트 이름
            site_config (dict): 사이트 설정
                - url: 기본 URL
                - crawl_url: 크롤링 URL (선택)
                - crawl_type: 'list', 'sample' (기본값: 'sample')
                - selectors: CSS 셀렉터 설정 (선택)
                - verify_ssl: SSL 인증서 검증 여부 (선택, 기본값: True)
                - use_selenium: Selenium 사용 여부 (선택, 기본값: False)
                - encoding: 인코딩 (선택, 예: 'utf-8', 'euc-kr')
        """
        base_url = site_config.get('url', '')
        verify_ssl = site_config.get('verify_ssl', True)
        use_selenium = site_config.get('use_selenium', False)
        encoding = site_config.get('encoding', None)
        super().__init__(
            site_name,
            base_url,
            verify_ssl=verify_ssl,
            use_selenium=use_selenium,
            encoding=encoding)

        self.site_config = site_config
        self.crawl_url = site_config.get('crawl_url', base_url)
        self.crawl_type = site_config.get('crawl_type', 'sample')
        self.selectors = site_config.get('selectors', {})
        self.onclick_pattern = site_config.get('onclick_pattern', '')
        self.url_template = site_config.get('url_template', '')
        self.title_attr = site_config.get('title_attr', '')
        self.title_clean_regex = site_config.get('title_clean_regex', '')

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")
        print(f"  타입: {self.crawl_type}")

        try:
            if self.crawl_type == 'list':
                # 실제 웹페이지 크롤링
                self._crawl_list_page()
            elif self.crawl_type == 'sample':
                # 샘플 데이터 생성 (테스트 목적으로만 사용)
                print(f"[{self.site_name}] 샘플 모드는 비활성화되었습니다 - 크롤링 건너뜀")
            else:
                print(f"[{self.site_name}] 알 수 없는 크롤링 타입: {self.crawl_type}")

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            self.errors.append(f"크롤링 오류: {str(e)}")
            print(f"[{self.site_name}] 오류: {str(e)}")

        return self.get_results()

    def _crawl_list_page(self):
        """
        실제 웹페이지 크롤링

        selectors 설정 예시:
        {
            'item': '.notice-item',  # 공고 목록 아이템 셀렉터
            'title': '.title',       # 제목
            'agency': '.agency',     # 발주기관
            'date': '.date',         # 날짜
            'link': 'a'              # 링크
        }
        """
        soup = self.fetch_page(self.crawl_url)

        if not soup:
            raise Exception("페이지를 가져올 수 없습니다")

        # 셀렉터가 없으면 에러 처리
        if not self.selectors or not self.selectors.get('item'):
            print(f"[{self.site_name}] 셀렉터 미설정 - 크롤링 건너뜀")
            return

        # 공고 목록 아이템 찾기
        items = soup.select(self.selectors.get('item', ''))

        if not items:
            print(f"[{self.site_name}] 공고를 찾을 수 없습니다 - 크롤링 건너뜀")
            return

        for idx, item in enumerate(items[:20]):  # 최대 20개
            try:
                # 제목 추출
                title_selector = self.selectors.get('title', '')
                if title_selector:
                    title_elem = item.select_one(title_selector)
                    if title_elem:
                        if self.title_attr:
                            raw = title_elem.get(self.title_attr, '')
                            if self.title_clean_regex:
                                raw = re.sub(self.title_clean_regex, '', raw).strip()
                            title = self._sanitize_text(raw)
                        else:
                            title = self._sanitize_text(title_elem.get_text(strip=True))
                    else:
                        title = f'{self.site_name} 공고 {idx + 1}'
                else:
                    title = self._sanitize_text(
                        item.get_text(strip=True)[:200]) if item else f'{self.site_name} 공고 {idx + 1}'

                # 발주기관 추출
                agency_selector = self.selectors.get('agency', '')
                if agency_selector:
                    agency_elem = item.select_one(agency_selector)
                    agency = self._sanitize_text(agency_elem.get_text(
                        strip=True)) if agency_elem else self.site_name
                else:
                    agency = self.site_name

                # 링크 추출
                link_selector = self.selectors.get('link', 'a')
                if link_selector:
                    link_elem = item.select_one(link_selector)
                else:
                    link_elem = item.find('a')

                link = ''
                if link_elem:
                    href = link_elem.get('href', '')

                    # onclick/javascript: 기반 URL 추출
                    if self.onclick_pattern and self.url_template:
                        # href나 onclick 속성에서 ID 추출 시도 (link_elem 또는 상위 item의 onclick)
                        for search_text in [href, link_elem.get('onclick', ''), item.get('onclick', '')]:
                            if search_text:
                                m = re.search(self.onclick_pattern, search_text)
                                if m:
                                    link = self.url_template.format(id=m.group(1))
                                    break

                    if not link and href and href != '#' and not href.startswith('javascript:'):
                        # jsessionid 제거 (예: path;jsessionid=xxx?params)
                        if ';jsessionid=' in href:
                            href = href.split(';jsessionid=')[
                                0] + '?' + href.split('?', 1)[1] if '?' in href else href.split(';jsessionid=')[0]

                        # 상대 경로면 절대 경로로 변환
                        if href.startswith('/'):
                            link = self.base_url + href
                        elif href.startswith('http'):
                            link = href
                        else:
                            # 상대 경로: crawl_url의 디렉토리 경로 기준으로 변환
                            from urllib.parse import urljoin
                            link = urljoin(self.crawl_url, href)

                # 날짜 추출 (있으면)
                date_selector = self.selectors.get('date', '')
                if date_selector:
                    date_elem = item.select_one(date_selector)
                    date_text = date_elem.get_text(
                        strip=True) if date_elem else ''
                else:
                    # 셀렉터가 없으면 전체 텍스트에서 날짜 찾기
                    date_text = item.get_text(strip=True)

                # 날짜 범위 파싱 시도 (시작일~종료일)
                start_date, end_date = self._parse_date_range(date_text)

                # 날짜 범위 파싱 실패시 단일 날짜 파싱
                if start_date is None:
                    announced_date = self._parse_date(date_text)
                    # 마감일은 랜덤으로 생성 (실제 데이터가 없는 경우)
                    deadline_date = datetime.now() + timedelta(days=random.randint(7, 30))
                else:
                    announced_date = start_date
                    deadline_date = end_date

                # 공고번호 생성
                tender_number = self._generate_tender_number()

                # 공고 데이터 생성
                tender = {
                    'title': title[:200],  # 최대 200자
                    'agency': agency[:100],
                    'tender_number': tender_number,
                    'announced_date': announced_date,
                    'deadline_date': deadline_date,
                    'opening_date': deadline_date + timedelta(days=random.randint(1, 15)) if deadline_date else None,
                    'estimated_price': random.randint(50, 300) * 1000000,
                    'bid_method': '일반경쟁입찰',
                    'status': '일반',
                    'is_sme_only': False,
                    'source_site': self.site_name,
                    'url': link if link else f"{self.base_url}/detail?id={tender_number}"
                }

                self.results.append(tender)

            except Exception as e:
                print(f"[{self.site_name}] 아이템 {idx} 파싱 오류: {str(e)}")
                continue

    def _generate_sample_data(self):
        """샘플 데이터 생성"""
        num_tenders = random.randint(3, 8)

        for i in range(num_tenders):
            tender_number = self._generate_tender_number()

            tender = {
                'title': f'{self.site_name} 공고 샘플 {i + 1}',
                'agency': self.site_name,
                'tender_number': tender_number,
                'announced_date': datetime.now() - timedelta(days=random.randint(1, 10)),
                'deadline_date': datetime.now() + timedelta(days=random.randint(5, 25)),
                'opening_date': datetime.now() + timedelta(days=random.randint(6, 26)),
                'estimated_price': random.randint(50, 200) * 1000000,
                'bid_method': '일반경쟁입찰',
                'status': '일반',
                'is_sme_only': random.choice([True, False]),
                'source_site': self.site_name,
                'url': f"{self.base_url}/detail?id={tender_number}"
            }

            self.results.append(tender)

    def _generate_tender_number(self):
        """공고번호 생성"""
        # 사이트 이름을 영문으로 변환 (간단한 버전)
        site_prefix = ''.join([c for c in self.site_name if c.isalnum()])[:10]
        if not site_prefix:
            site_prefix = 'SITE'

        return f"{site_prefix.upper()}-{datetime.now().year}-{random.randint(10000, 99999)}"

    def _sanitize_text(self, text):
        """
        텍스트 정리: 특수문자, replacement character 등을 제거
        """
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

    def _parse_date(self, date_text):
        """날짜 문자열을 datetime으로 파싱"""
        if not date_text:
            return datetime.now() - timedelta(days=random.randint(1, 10))

        # 간단한 날짜 파싱 (YYYY-MM-DD, YYYY.MM.DD 등)
        date_patterns = [
            r'(\d{4})-(\d{1,2})-(\d{1,2})',
            r'(\d{4})\.(\d{1,2})\.(\d{1,2})',
            r'(\d{4})/(\d{1,2})/(\d{1,2})',
        ]

        for pattern in date_patterns:
            match = re.search(pattern, date_text)
            if match:
                try:
                    year, month, day = map(int, match.groups())
                    return datetime(year, month, day)
                except BaseException:
                    pass

        # 파싱 실패시 기본값
        return datetime.now() - timedelta(days=random.randint(1, 10))

    def _parse_date_range(self, text):
        """
        날짜 범위 문자열을 파싱하여 시작일과 종료일을 반환
        예: "신청기간 : 2025-12-15 16:27 ~ 2025-12-31 16:27"
        예: "2025.12.15 ~ 2025.12.31"

        Returns:
            tuple: (start_date, end_date) 또는 (None, None)
        """
        if not text:
            return None, None

        # 날짜 시간 범위 패턴: YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM
        pattern1 = (
            r'(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})\s*~\s*'
            r'(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})'
        )
        match = re.search(pattern1, text)
        if match:
            try:
                y1, m1, d1, h1, min1, y2, m2, d2, h2, min2 = map(
                    int, match.groups())
                start_date = datetime(y1, m1, d1, h1, min1)
                end_date = datetime(y2, m2, d2, h2, min2)
                return start_date, end_date
            except BaseException:
                pass

        # 날짜 범위 패턴 (시간 없이): YYYY-MM-DD ~ YYYY-MM-DD
        pattern2 = r'(\d{4})-(\d{1,2})-(\d{1,2})\s*~\s*(\d{4})-(\d{1,2})-(\d{1,2})'
        match = re.search(pattern2, text)
        if match:
            try:
                y1, m1, d1, y2, m2, d2 = map(int, match.groups())
                start_date = datetime(y1, m1, d1)
                end_date = datetime(y2, m2, d2)
                return start_date, end_date
            except BaseException:
                pass

        # 날짜 범위 패턴 (점 구분): YYYY.MM.DD ~ YYYY.MM.DD
        pattern3 = r'(\d{4})\.(\d{1,2})\.(\d{1,2})\s*~\s*(\d{4})\.(\d{1,2})\.(\d{1,2})'
        match = re.search(pattern3, text)
        if match:
            try:
                y1, m1, d1, y2, m2, d2 = map(int, match.groups())
                start_date = datetime(y1, m1, d1)
                end_date = datetime(y2, m2, d2)
                return start_date, end_date
            except BaseException:
                pass

        return None, None
