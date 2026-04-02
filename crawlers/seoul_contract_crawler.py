"""서울시 계약정보 크롤러"""
import time
import re
from datetime import datetime
from bs4 import BeautifulSoup
from crawlers.base_crawler import BaseCrawler


class SeoulContractCrawler(BaseCrawler):
    """서울특별시 계약정보 크롤러"""

    def __init__(self, db_session):
        super().__init__(
            site_name="서울시_계약정보",
            base_url="https://contract.seoul.go.kr",
            verify_ssl=True,
            use_selenium=True,
            encoding=None
        )
        self.db_session = db_session

    def crawl(self):
        """크롤링 실행"""
        url = "https://contract.seoul.go.kr/new1/views/pubBidInfo.do"

        try:
            print(f"[{self.site_name}] 크롤링 시작: {url}")

            # Selenium 초기화
            self._init_selenium_driver()
            self.driver.get(url)

            # 페이지 로딩 대기
            time.sleep(5)

            # 페이지 소스 파싱
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # 테이블 찾기
            table = soup.find('table', class_='list-tbl-01')
            if not table:
                print(f"[{self.site_name}] 테이블을 찾을 수 없습니다.")
                return []

            tbody = table.find('tbody')
            if not tbody:
                print(f"[{self.site_name}] tbody를 찾을 수 없습니다.")
                return []

            all_rows = tbody.find_all('tr')
            tenders = []

            # 3개의 tr이 하나의 공고를 구성
            i = 0
            while i < len(all_rows) - 2:
                try:
                    agency_row = all_rows[i]
                    title_row = all_rows[i + 1]
                    date_row = all_rows[i + 2]

                    # 기관명 추출
                    agency_td = agency_row.find('td', class_='settxt')
                    if not agency_td:
                        i += 3
                        continue

                    # "사업소 | 도로사업소" 형식에서 기관명 추출
                    agency_text = agency_td.get_text(strip=True)
                    agency_parts = agency_text.split('|')
                    if len(agency_parts) >= 2:
                        agency = agency_parts[-1].strip()
                    else:
                        agency = agency_text.replace(
                            '<!--기관명 : -->', '').strip()

                    # 제목 및 링크 추출
                    title_td = title_row.find('td', class_='setst')
                    if not title_td:
                        i += 3
                        continue

                    title_link = title_td.find('a')
                    if not title_link:
                        i += 3
                        continue

                    title_b = title_link.find('b')
                    title = title_b.get_text(
                        strip=True) if title_b else title_link.get_text(
                        strip=True)

                    # onclick에서 공고번호 추출
                    onclick = title_link.get('onclick', '')
                    # javascript:bidPopup_getBidInfoDtlUrl('5', 'R26BK01272482', '000', '2')
                    tender_number_match = re.search(
                        r"'([^']+)',\s*'([^']+)'", onclick)
                    if tender_number_match:
                        tender_number = tender_number_match.group(2)
                    else:
                        tender_number = f"SEOUL_{i // 3}"

                    # URL 구성
                    detail_url = f"https://contract.seoul.go.kr/new1/views/pubBidInfo.do?bidNo={tender_number}"

                    # 날짜 정보 추출
                    date_tds = date_row.find_all('td', class_='daily')
                    announced_date = None
                    deadline_date = None
                    opening_date = None

                    for td in date_tds:
                        text = td.get_text(strip=True)
                        if '공고일자' in text:
                            date_str = text.split('|')[-1].strip()
                            announced_date = self._parse_date(date_str)
                        elif '입찰게시일' in text:
                            date_str = text.split('|')[-1].strip()
                            deadline_date = self._parse_date(date_str)
                        elif '개찰일시' in text:
                            date_str = text.split('|')[-1].strip()
                            opening_date = self._parse_date(date_str)

                    # 공고 데이터 생성
                    tender_data = {
                        'title': title,
                        'agency': agency if agency else '서울특별시',
                        'tender_number': tender_number,
                        'announced_date': announced_date,
                        'deadline_date': deadline_date,
                        'opening_date': opening_date,
                        'estimated_price': None,
                        'bid_method': '용역',  # 기본값
                        'status': '일반',
                        'source_site': self.site_name,
                        'url': detail_url
                    }

                    tenders.append(tender_data)

                except Exception as e:
                    print(f"[{self.site_name}] 공고 파싱 오류 (행 {i}): {e}")

                i += 3  # 다음 공고로 이동 (3개 행 건너뛰기)

            print(f"[{self.site_name}] 크롤링 완료: {len(tenders)}건")

            # DB에 저장
            from database import Tender
            new_count = 0
            for tender_data in tenders:
                # 중복 체크
                existing = Tender.query.filter_by(
                    tender_number=tender_data['tender_number']
                ).first()

                if not existing:
                    new_tender = Tender(**tender_data)
                    self.db_session.add(new_tender)
                    new_count += 1

            self.db_session.commit()
            print(f"[{self.site_name}] 새로운 공고: {new_count}건")

            return tenders

        except Exception as e:
            print(f"[{self.site_name}] 크롤링 오류: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            self._close_selenium_driver()

    def _parse_date(self, date_str):
        """날짜 문자열을 datetime으로 변환"""
        try:
            # "2026-01-14" 형식
            return datetime.strptime(date_str, '%Y-%m-%d')
        except BaseException:
            return None
