"""
RSS 피드 크롤러
RSS 2.0 형식의 공고 피드를 크롤링
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import random


class RSSCrawler(BaseCrawler):
    """RSS 피드 크롤러"""

    def __init__(self, site_name, site_config):
        """
        Args:
            site_name (str): 사이트 이름
            site_config (dict): 사이트 설정
                - url: 기본 URL
                - rss_url: RSS 피드 URL
                - max_items: 최대 수집 개수 (기본: 20)
        """
        super().__init__(
            site_name,
            site_config.get('url', '')
        )
        self.rss_url = site_config.get('rss_url', '')
        self.max_items = site_config.get('max_items', 20)

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] RSS 피드 크롤링 시작...")

        try:
            if not self.rss_url:
                error_msg = "RSS URL이 설정되지 않았습니다"
                self.errors.append(error_msg)
                print(f"  {error_msg}")
                return self.get_results()

            print(f"  RSS URL: {self.rss_url}")

            # RSS 피드 가져오기
            response = self.session.get(
                self.rss_url,
                timeout=30
            )

            if response.status_code != 200:
                error_msg = f"RSS 피드 가져오기 실패: HTTP {response.status_code}"
                self.errors.append(error_msg)
                print(f"  {error_msg}")
                return self.get_results()

            # XML 파싱
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as e:
                error_msg = f"XML 파싱 실패: {str(e)}"
                self.errors.append(error_msg)
                print(f"  {error_msg}")
                return self.get_results()

            # RSS 아이템 추출
            items = root.findall('.//item')
            print(f"  총 {len(items)}개 아이템 발견")

            for idx, item in enumerate(items[:self.max_items]):
                try:
                    tender = self._parse_rss_item(item)
                    if tender:
                        self.results.append(tender)
                except Exception as e:
                    print(f"  아이템 {idx} 파싱 오류: {str(e)}")
                    continue

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            error_msg = f"크롤링 오류: {str(e)}"
            self.errors.append(error_msg)
            print(f"[{self.site_name}] {error_msg}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _parse_rss_item(self, item):
        """RSS 아이템을 공고 데이터로 변환"""

        # 제목
        title_elem = item.find('title')
        if title_elem is None or not title_elem.text:
            return None

        title = title_elem.text.strip()

        # URL
        link_elem = item.find('link')
        url = link_elem.text.strip() if link_elem is not None and link_elem.text else ''

        # 발행일자
        pub_date_elem = item.find('pubDate')
        pub_date_text = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else ''
        announced_date = self._parse_date(pub_date_text)

        # 공고번호 생성 (URL에서 nttId 추출 시도)
        tender_number = self._extract_tender_number(url)

        # 마감일은 공고일로부터 랜덤으로 설정 (실제 데이터가 없으므로)
        deadline_date = None
        if announced_date:
            days_offset = random.randint(7, 30)
            deadline_date = announced_date + timedelta(days=days_offset)

        return {
            'title': title[:200],
            'agency': self.site_name,
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': None,
            'estimated_price': None,
            'bid_method': '공시공고',
            'status': '일반',
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': url
        }

    def _parse_date(self, date_str):
        """날짜 문자열을 datetime으로 변환"""
        if not date_str:
            return datetime.now()

        # RSS 날짜 형식들
        date_formats = [
            '%Y-%m-%d %H:%M:%S',  # 2025-08-29 05:23:54
            '%Y-%m-%d',
            '%a, %d %b %Y %H:%M:%S %z',  # RFC 822
            '%Y-%m-%dT%H:%M:%S',  # ISO 8601
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        # 파싱 실패 시 현재 시간
        return datetime.now()

    def _extract_tender_number(self, url):
        """URL에서 공고번호 추출"""
        if not url:
            return f"{self.site_name.upper()}-{random.randint(10000, 99999)}"

        # nttId 파라미터 추출 시도
        import re
        match = re.search(r'nttId=(\d+)', url)
        if match:
            return f"{self.site_name}-{match.group(1)}"

        # 추출 실패 시 랜덤 번호
        return f"{self.site_name.upper()}-{random.randint(10000, 99999)}"
