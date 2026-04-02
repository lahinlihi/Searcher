"""
한국과학기술연구원(KIST) 일반공지 크롤러
"""

from .base_crawler import BaseCrawler
from datetime import datetime
from bs4 import BeautifulSoup
import re


class KISTNoticeCrawler(BaseCrawler):
    """KIST 일반공지 크롤러 (입찰/연구과제 공고 필터링)"""

    def __init__(self, site_config):
        """
        Args:
            site_config (dict): 사이트 설정
                - max_pages: 최대 페이지 수 (기본: 5)
                - keywords: 필터링 키워드 리스트 (기본: ['공고', '입찰', '연구과제', '위탁'])
        """
        super().__init__(
            'KIST 일반공지',
            'https://kist.re.kr'
        )
        self.notice_url = 'https://kist.re.kr/ko/notice/general-notice.do'
        self.max_pages = site_config.get('max_pages', 5)
        self.filter_keywords = site_config.get('keywords', ['공고', '입찰', '연구과제', '위탁', '공동'])

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] 웹 크롤링 시작...")
        print(f"  필터 키워드: {', '.join(self.filter_keywords)}")

        try:
            for page in range(1, self.max_pages + 1):
                # 페이지 파라미터 설정
                params = {
                    'article.offset': (page - 1) * 10,
                    'articleLimit': 10
                }

                # User-Agent 헤더 필수
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }

                response = self.session.get(
                    self.notice_url,
                    params=params,
                    headers=headers,
                    timeout=30
                )

                if response.status_code != 200:
                    error_msg = f"페이지 {page} 접근 실패: HTTP {response.status_code}"
                    self.errors.append(error_msg)
                    print(f"  {error_msg}")
                    break

                # HTML 파싱
                soup = BeautifulSoup(response.text, 'html.parser')

                # 게시글 목록 추출
                tbody = soup.find('tbody')
                if not tbody:
                    print(f"  페이지 {page}: tbody 찾을 수 없음")
                    break

                rows = tbody.find_all('tr', recursive=False)
                if not rows:
                    print(f"  페이지 {page}: 더 이상 데이터 없음")
                    break

                print(f"  페이지 {page}: {len(rows)}건 처리 중...")

                page_collected = 0
                for row in rows:
                    try:
                        tender = self._parse_notice(row)
                        if tender:
                            # 키워드 필터링
                            if self._should_include(tender['title']):
                                self.results.append(tender)
                                page_collected += 1
                    except Exception as e:
                        print(f"    항목 파싱 오류: {str(e)}")
                        continue

                print(f"    → 필터링 후 {page_collected}건 수집")

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            error_msg = f"크롤링 오류: {str(e)}"
            self.errors.append(error_msg)
            print(f"[{self.site_name}] {error_msg}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _parse_notice(self, row):
        """게시글 행을 공고 데이터로 변환"""

        # 제목 및 링크
        title_box = row.find('div', class_='b-title-box')
        if not title_box:
            return None

        link = title_box.find('a')
        if not link or not link.get_text(strip=True):
            return None

        title = link.get_text(strip=True)
        href = link.get('href', '')

        # 절대 URL 생성
        if href and not href.startswith('http'):
            url = f"{self.base_url}/ko/notice/general-notice.do{href}"
        else:
            url = href if href else ''

        # 날짜
        date_elem = row.find('span', class_='b-date')
        date_text = date_elem.get_text(strip=True) if date_elem else ''
        announced_date = self._parse_date(date_text)

        # 작성자 (부서명)
        writer_elem = row.find('span', class_='b-writer')
        writer = writer_elem.get_text(strip=True) if writer_elem else 'KIST'

        # 번호 추출
        num_box = row.find('td', class_='b-num-box')
        num = num_box.get_text(strip=True) if num_box else ''

        # 공고번호 생성
        tender_number = f"KIST-{num}" if num and num.isdigit() else f"KIST-{announced_date.strftime('%Y%m%d')}" if announced_date else 'KIST-UNKNOWN'

        return {
            'title': title[:200],
            'agency': writer if writer != 'KIST' else 'KIST',
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': None,  # 상세 페이지에서만 확인 가능
            'opening_date': None,
            'estimated_price': None,
            'bid_method': '공고',
            'status': '일반',
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': url
        }

    def _should_include(self, title):
        """제목에 필터 키워드가 포함되어 있는지 확인"""
        if not self.filter_keywords:
            return True

        title_lower = title.lower()
        for keyword in self.filter_keywords:
            if keyword.lower() in title_lower:
                return True

        return False

    def _parse_date(self, date_str):
        """날짜 문자열을 datetime으로 변환"""
        if not date_str:
            return None

        # KIST 날짜 형식: YY.MM.DD (예: 26.01.20)
        try:
            # YY.MM.DD 형식
            if re.match(r'^\d{2}\.\d{2}\.\d{2}$', date_str):
                year = int(date_str[:2])
                # 2000년대로 변환 (00-99 -> 2000-2099)
                full_year = 2000 + year
                return datetime.strptime(f"{full_year}.{date_str[3:]}", '%Y.%m.%d')
        except ValueError:
            pass

        # 다른 형식들
        date_formats = [
            '%Y.%m.%d',
            '%Y-%m-%d',
            '%Y/%m/%d',
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        return None
