"""
한국과학기술연구원(KIST) 입찰정보 API 크롤러
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import urllib3


# SSL 경고 비활성화 (자체 서명 인증서 사용 가능)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class KISTBidCrawler(BaseCrawler):
    """KIST 입찰정보 크롤러"""

    def __init__(self, site_config):
        """
        Args:
            site_config (dict): 사이트 설정
                - service_key: API 인증키
                - days_range: 조회 기간 (기본: 90일)
                - num_of_rows: 한번에 가져올 개수 (기본: 100)
                - use_https: HTTPS 사용 여부 (기본: True)
        """
        super().__init__(
            'KIST 입찰정보',
            'http://www.kist.re.kr'
        )

        # HTTP/HTTPS 선택
        protocol = 'https' if site_config.get('use_https', True) else 'http'
        self.base_url = f'{protocol}://161.122.37.103:6736/openapi-data/service/bid'
        self.service_key = site_config.get('service_key', '')
        self.days_range = site_config.get('days_range', 90)
        self.num_of_rows = site_config.get('num_of_rows', 100)

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] API 크롤링 시작...")

        try:
            if not self.service_key:
                error_msg = "API 인증키가 설정되지 않았습니다"
                self.errors.append(error_msg)
                print(f"  {error_msg}")
                return self.get_results()

            # 날짜 범위 계산
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.days_range)

            print(f"  조회 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")

            # 입찰공고 조회
            self._crawl_bid_notices(start_date, end_date)

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            error_msg = f"크롤링 오류: {str(e)}"
            self.errors.append(error_msg)
            print(f"[{self.site_name}] {error_msg}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _crawl_bid_notices(self, start_date, end_date):
        """입찰공고 조회"""
        url = f"{self.base_url}/bidNotice"
        page = 1
        total_collected = 0

        while True:
            params = {
                'serviceKey': self.service_key,
                'pageNo': str(page),
                'numOfRows': str(self.num_of_rows),
                'appBeginDate': start_date.strftime('%Y%m%d'),
                'appEndDate': end_date.strftime('%Y%m%d')
            }

            try:
                # SSL 검증 비활성화 (내부 네트워크용)
                response = self.session.get(
                    url,
                    params=params,
                    timeout=30,
                    verify=False
                )

                if response.status_code != 200:
                    error_msg = f"API 호출 실패: HTTP {response.status_code}"
                    self.errors.append(error_msg)
                    print(f"  {error_msg}")
                    break

                # XML 파싱
                try:
                    root = ET.fromstring(response.content)
                except ET.ParseError as e:
                    error_msg = f"XML 파싱 실패: {str(e)}"
                    self.errors.append(error_msg)
                    print(f"  {error_msg}")
                    break

                # 결과 코드 확인
                header = root.find('.//header')
                if header is not None:
                    result_code = header.find('resultCode')
                    result_msg = header.find('resultMsg')

                    if result_code is not None and result_code.text != '00':
                        error_msg = f"API 오류: {result_code.text} - {result_msg.text if result_msg is not None else 'Unknown'}"
                        self.errors.append(error_msg)
                        print(f"  {error_msg}")
                        break

                # 데이터 추출
                items = root.findall('.//item')
                if not items:
                    print(f"  페이지 {page}: 더 이상 데이터 없음")
                    break

                print(f"  페이지 {page}: {len(items)}건 처리 중...")

                for item in items:
                    try:
                        tender = self._parse_bid_notice(item)
                        if tender:
                            self.results.append(tender)
                            total_collected += 1
                    except Exception as e:
                        print(f"    항목 파싱 오류: {str(e)}")
                        continue

                # 총 개수 확인
                total_count_elem = root.find('.//totalCount')
                if total_count_elem is not None:
                    total_count = int(total_count_elem.text)
                    if page * self.num_of_rows >= total_count:
                        print(f"  전체 {total_count}건 중 {total_collected}건 수집 완료")
                        break

                page += 1

            except Exception as e:
                error_msg = f"페이지 {page} 조회 오류: {str(e)}"
                self.errors.append(error_msg)
                print(f"  {error_msg}")
                break

    def _parse_bid_notice(self, item):
        """XML item을 공고 데이터로 변환"""

        # 일련번호
        serial_no_elem = item.find('serialNo')
        serial_no = serial_no_elem.text.strip() if serial_no_elem is not None and serial_no_elem.text else ''

        # 제목
        title_elem = item.find('title')
        if title_elem is None or not title_elem.text:
            return None
        title = title_elem.text.strip()

        # 품의번호
        req_no_elem = item.find('reqNo')
        req_no = req_no_elem.text.strip() if req_no_elem is not None and req_no_elem.text else ''

        # 구분 (내자구매/외자구매 등)
        type_elem = item.find('type')
        bid_type = type_elem.text.strip() if type_elem is not None and type_elem.text else ''

        # 입찰방법
        bid_method_elem = item.find('bidMethod')
        bid_method = bid_method_elem.text.strip() if bid_method_elem is not None and bid_method_elem.text else '일반경쟁'

        # 진행상황
        bid_status_elem = item.find('bidStatus')
        bid_status = bid_status_elem.text.strip() if bid_status_elem is not None and bid_status_elem.text else ''

        # 입찰등록시작일
        app_begin_elem = item.find('appBeginDate')
        app_begin_text = app_begin_elem.text.strip() if app_begin_elem is not None and app_begin_elem.text else ''
        announced_date = self._parse_date(app_begin_text)

        # 입찰등록마감일
        app_end_elem = item.find('appEndDate')
        app_end_text = app_end_elem.text.strip() if app_end_elem is not None and app_end_elem.text else ''

        # 입찰제출마감일
        bid_end_elem = item.find('bidEndDate')
        bid_end_text = bid_end_elem.text.strip() if bid_end_elem is not None and bid_end_elem.text else ''
        deadline_date = self._parse_date(bid_end_text) if bid_end_text else self._parse_date(app_end_text)

        # 입찰제출시작일 (개찰일로 사용)
        bid_begin_elem = item.find('bidBeginDate')
        bid_begin_text = bid_begin_elem.text.strip() if bid_begin_elem is not None and bid_begin_elem.text else ''
        opening_date = self._parse_date(bid_begin_text)

        # 공고번호 생성
        tender_number = f"KIST-{serial_no}" if serial_no else f"KIST-{req_no}" if req_no else f"KIST-{announced_date.strftime('%Y%m%d')}" if announced_date else 'KIST-UNKNOWN'

        # 상태 결정
        status = '긴급' if '긴급' in title else '일반'

        return {
            'title': title[:200],
            'agency': 'KIST',
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': opening_date,
            'estimated_price': None,
            'bid_method': f'{bid_method} ({bid_type})' if bid_type else bid_method,
            'status': status,
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': f'http://www.kist.re.kr'  # KIST는 상세 URL을 제공하지 않음
        }

    def _parse_date(self, date_str):
        """날짜 문자열을 datetime으로 변환"""
        if not date_str:
            return None

        # 날짜 형식들
        date_formats = [
            '%Y%m%d',
            '%Y-%m-%d',
            '%Y.%m.%d',
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        return None
