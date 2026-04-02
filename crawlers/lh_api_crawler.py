"""
한국토지주택공사(LH) Open API 크롤러
입찰공고정보 조회 API
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET


class LHApiCrawler(BaseCrawler):
    """LH Open API 크롤러"""

    def __init__(self, site_config):
        """
        Args:
            site_config (dict): 사이트 설정
                - service_key: API 인증키
                - num_of_rows: 한 페이지 결과 수 (기본: 100)
                - days_range: 조회 기간 (기본: 30일)
        """
        super().__init__(
            'LH 입찰정보',
            'http://openapi.ebid.lh.or.kr'
        )
        self.service_key = site_config.get('service_key', '')
        self.num_of_rows = site_config.get('num_of_rows', 100)
        self.days_range = site_config.get('days_range', 30)
        # HTTP 사용 (HTTPS 아님)
        self.api_url = 'http://openapi.ebid.lh.or.kr/ebid.com.openapi.service.OpenBidInfoList.dev'

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")

        try:
            # 날짜 범위 설정 (최근 N일)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.days_range)

            # 날짜를 YYYYMMDD 형식으로 변환
            start_dt = start_date.strftime('%Y%m%d')
            end_dt = end_date.strftime('%Y%m%d')

            print(f"  조회기간: {start_dt} ~ {end_dt}")

            # API 호출
            page_no = 1
            total_count = 0

            while True:
                params = {
                    'serviceKey': self.service_key,
                    'numOfRows': str(self.num_of_rows),
                    'pageNo': str(page_no),
                    'tndrbidRegDtStart': start_dt,
                    'tndrbidRegDtEnd': end_dt
                }

                print(f"  페이지 {page_no} 조회 중...")

                response = self.session.get(
                    self.api_url,
                    params=params,
                    timeout=30
                )

                if response.status_code != 200:
                    error_msg = f"API 호출 실패: HTTP {response.status_code}"
                    self.errors.append(error_msg)
                    print(f"  {error_msg}")
                    break

                # XML 파싱 (EUC-KR 인코딩 처리)
                try:
                    # EUC-KR을 UTF-8로 변환하고 XML 선언부 수정
                    xml_text = response.content.decode('euc-kr')
                    # XML 선언부의 인코딩을 UTF-8로 변경
                    xml_text = xml_text.replace('encoding="EUC-KR"', 'encoding="UTF-8"')
                    root = ET.fromstring(xml_text.encode('utf-8'))
                except ET.ParseError as e:
                    error_msg = f"XML 파싱 실패: {str(e)}"
                    self.errors.append(error_msg)
                    print(f"  {error_msg}")
                    break

                # 결과 코드 확인
                header = root.find('.//header')
                if header is not None:
                    result_code = header.findtext('resultCode', '')
                    result_msg = header.findtext('resultMsg', '')

                    if result_code != '00':
                        error_msg = f"API 오류: {result_code} - {result_msg}"
                        self.errors.append(error_msg)
                        print(f"  {error_msg}")
                        break

                    # 전체 결과 수 확인 (첫 페이지에서만)
                    if page_no == 1:
                        total_count = int(header.findtext('totalCount', '0'))
                        print(f"  전체 {total_count}건")

                # 공고 데이터 추출
                body = root.find('.//body')
                if body is None:
                    break

                items = body.findall('.//item')
                if not items:
                    break

                for item in items:
                    try:
                        tender = self._parse_item(item)
                        if tender:
                            self.results.append(tender)
                    except Exception as e:
                        print(f"  항목 파싱 오류: {str(e)}")
                        continue

                # 더 이상 데이터가 없으면 종료
                if len(items) < self.num_of_rows:
                    break

                page_no += 1

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            error_msg = f"크롤링 오류: {str(e)}"
            self.errors.append(error_msg)
            print(f"[{self.site_name}] {error_msg}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _parse_item(self, item):
        """XML 아이템을 공고 데이터로 변환"""

        # 공고번호
        bid_num = item.findtext('bidNum', '').strip()
        bid_degree = item.findtext('bidDegree', '').strip()
        tender_number = f"{bid_num}-{bid_degree}" if bid_degree else bid_num

        # 제목
        title = item.findtext('bidnmKor', '').strip()
        if not title:
            return None

        # 발주기관 (담당지역본부)
        agency = item.findtext('zoneHqCd', 'LH 한국토지주택공사').strip()

        # 날짜 파싱
        announced_date = self._parse_date(item.findtext('tndrbidRegDt', ''))
        deadline_date = self._parse_datetime(
            item.findtext('tndrdocAcptEndDtm', ''))
        opening_date = self._parse_datetime(item.findtext('openDtm', ''))

        # 추정가격
        estimated_price = self._parse_price(item.findtext('presmtPrc', '0'))

        # 입찰방법
        bid_method = item.findtext('tndrCtrctMedCd', '').strip()
        if not bid_method:
            bid_method = '제한경쟁입찰'

        # 상태
        status = '일반'
        bid_kind = item.findtext('bidKind', '').strip()
        if '사전' in bid_kind:
            status = '사전규격'

        # 공고 URL
        url = f"https://ebid.lh.or.kr/sis.do?cmd=SPBBCH1R6&tndrbidRegNo={bid_num}&tndrbidDegree={bid_degree}"

        return {
            'title': title[:200],
            'agency': agency[:100],
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': opening_date,
            'estimated_price': estimated_price,
            'bid_method': bid_method,
            'status': status,
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': url
        }

    def _parse_date(self, date_str):
        """날짜 문자열을 datetime으로 변환 (YYYYMMDD)"""
        if not date_str or len(date_str) < 8:
            return None

        try:
            return datetime.strptime(date_str[:8], '%Y%m%d')
        except ValueError:
            return None

    def _parse_datetime(self, datetime_str):
        """날짜시간 문자열을 datetime으로 변환 (YYYY/MM/DD HH:MM)"""
        if not datetime_str:
            return None

        try:
            # "2016/12/19 11:10" 형식
            return datetime.strptime(datetime_str.strip(), '%Y/%m/%d %H:%M')
        except ValueError:
            return None

    def _parse_price(self, price_str):
        """가격 문자열을 숫자로 변환"""
        if not price_str:
            return None

        try:
            return int(price_str.replace(',', ''))
        except ValueError:
            return None
