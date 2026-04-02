"""
나라장터(G2B) 공공데이터 API 크롤러
조달청 공공데이터포털 API를 사용하여 입찰공고 데이터 수집

API 문서: 조달청_OpenAPI참고자료_나라장터_입찰공고정보서비스.docx 참조
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import requests
import json


class G2BApiCrawler(BaseCrawler):
    """
    나라장터 입찰공고정보서비스 API 크롤러

    공공데이터포털(data.go.kr)에서 제공하는 나라장터 입찰공고 API 사용

    Required config:
        - service_key: 공공데이터포털 서비스 인증키
        - bid_type: 'cnstwk' (공사), 'servc' (용역), 'thng' (물품), 'frgcpt' (외자)
    """

    # API 기본 정보
    BASE_URL = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService"

    # API 오퍼레이션 (업무구분별)
    API_ENDPOINTS = {
        'cnstwk': '/getBidPblancListInfoCnstwk',      # 공사
        'servc': '/getBidPblancListInfoServc',         # 용역
        'thng': '/getBidPblancListInfoThng',           # 물품
        'frgcpt': '/getBidPblancListInfoFrgcpt',       # 외자
    }

    # 업무구분 한글명
    BID_TYPE_NAMES = {
        'cnstwk': '공사',
        'servc': '용역',
        'thng': '물품',
        'frgcpt': '외자'
    }

    def __init__(self, site_name, site_config):
        """
        Args:
            site_name (str): 사이트 이름
            site_config (dict): 사이트 설정
                - service_key: API 서비스키 (필수)
                - bid_type: 'cnstwk', 'servc', 'thng', 'frgcpt' (기본: 'thng')
                - num_of_rows: 한 번에 가져올 결과 수 (기본: 100, 최대 999)
                - days_range: 조회할 일자 범위 (기본: 7일)
        """
        base_url = self.BASE_URL
        super().__init__(site_name, base_url)

        self.service_key = site_config.get('service_key', '')
        self.bid_type = site_config.get('bid_type', 'thng')
        self.num_of_rows = min(site_config.get('num_of_rows', 100), 999)
        self.days_range = site_config.get('days_range', 7)

        # API 엔드포인트 설정
        self.endpoint = self.API_ENDPOINTS.get(
            self.bid_type, self.API_ENDPOINTS['thng'])
        self.bid_type_name = self.BID_TYPE_NAMES.get(self.bid_type, '물품')

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()

        if not self.service_key:
            self.errors.append("서비스 키가 설정되지 않았습니다")
            return self.get_results()

        print(f"[{self.site_name}] 나라장터 API 크롤링 시작...")
        print(f"  업무구분: {self.bid_type_name}")
        print(f"  조회 기간: 최근 {self.days_range}일")

        try:
            # 날짜 범위 설정 (최근 N일)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.days_range)

            # API 호출
            all_data = self._fetch_api_data(start_date, end_date)

            # 데이터 변환
            for item in all_data:
                tender = self._convert_to_tender(item)
                if tender:
                    self.results.append(tender)

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            self.errors.append(f"크롤링 오류: {str(e)}")
            print(f"[{self.site_name}] 오류: {str(e)}")

        return self.get_results()

    def _fetch_api_data(self, start_date, end_date):
        """
        API 데이터 가져오기 (페이지네이션 처리)

        Args:
            start_date (datetime): 시작 날짜
            end_date (datetime): 종료 날짜

        Returns:
            list: 전체 데이터 리스트
        """
        all_items = []
        page_no = 1

        while True:
            # API 요청 파라미터
            params = {
                'ServiceKey': self.service_key,
                'numOfRows': self.num_of_rows,
                'pageNo': page_no,
                'type': 'json',  # JSON 형식으로 요청
                'inqryDiv': '1',  # 조회구분: 1=등록일시
                # YYYYMMDDHHMM
                'inqryBgnDt': start_date.strftime('%Y%m%d0000'),
                'inqryEndDt': end_date.strftime('%Y%m%d2359')
            }

            try:
                # API 호출
                url = self.BASE_URL + self.endpoint
                response = requests.get(url, params=params, timeout=30)
                if response.status_code == 429:
                    self.errors.append(
                        f"API 요청 한도 초과 (429 Too Many Requests): 일일 호출 한도를 초과했습니다. 내일 다시 시도하세요.")
                    break
                response.raise_for_status()

                # JSON 파싱
                data = response.json()

                # 응답 확인
                if 'response' not in data:
                    self.errors.append(f"잘못된 응답 형식: {data}")
                    break

                header = data['response'].get('header', {})
                result_code = header.get('resultCode', '')
                result_msg = header.get('resultMsg', '')

                if result_code != '00':
                    self.errors.append(
                        f"API 오류 (코드: {result_code}): {result_msg}")
                    break

                # 데이터 추출
                body = data['response'].get('body', {})
                items = body.get('items', [])

                # items가 딕셔너리인 경우 (단일 항목)
                if isinstance(items, dict):
                    items = [items]
                elif not items:
                    items = []

                # item 필드 확인 (실제 데이터는 items 안의 item에 있을 수 있음)
                if items and isinstance(items, list) and len(items) > 0:
                    first_item = items[0]
                    if 'item' in first_item:
                        # items가 {'item': [...]} 형태인 경우
                        items = first_item['item']
                        if isinstance(items, dict):
                            items = [items]

                if not items:
                    break  # 더 이상 데이터 없음

                all_items.extend(items)

                # 페이지네이션 확인
                total_count = int(body.get('totalCount', 0))
                current_count = page_no * self.num_of_rows

                print(f"  페이지 {page_no}: {len(items)}건 (전체 {total_count}건)")

                if current_count >= total_count:
                    break  # 모든 데이터 수집 완료

                page_no += 1

            except requests.exceptions.RequestException as e:
                self.errors.append(f"API 요청 실패 (페이지 {page_no}): {str(e)}")
                break
            except json.JSONDecodeError as e:
                self.errors.append(f"JSON 파싱 실패 (페이지 {page_no}): {str(e)}")
                break
            except Exception as e:
                self.errors.append(f"알 수 없는 오류 (페이지 {page_no}): {str(e)}")
                break

        return all_items

    def _convert_to_tender(self, item):
        """
        API 응답 데이터를 tender 형식으로 변환

        Args:
            item (dict): API 응답 항목

        Returns:
            dict: tender 데이터 또는 None
        """
        try:
            # 입찰공고번호
            tender_number = item.get('bidNtceNo', '')

            # 입찰공고차수
            item.get('bidNtceOrd', '00')

            # 입찰공고명
            title = item.get('bidNtceNm', '')

            # 발주기관
            agency = item.get('dminsttNm', '') or item.get('ntceInsttNm', '미상')

            # 실수요기관 (발주기관과 다를 경우 표시)
            demand_agency = self.clean_text(item.get('rlDminsttNm', '') or '')[:100] or None

            # 입찰공고일자
            bid_date_str = item.get('bidNtceDt', '')
            announced_date = self.parse_date(
                bid_date_str) if bid_date_str else None

            # 개찰일자
            opening_date_str = item.get('opengDt', '')
            opening_date = self.parse_date(
                opening_date_str) if opening_date_str else None

            # 입찰서제출마감일시
            deadline_str = item.get(
                'bidClseDate', '') or item.get(
                'bidClseDt', '')
            deadline_date = self.parse_date(
                deadline_str) if deadline_str else opening_date

            # 추정가격
            estimated_price_str = item.get(
                'asignBdgtAmt', '') or item.get(
                'presmptPrce', '')
            estimated_price = self._parse_amount(estimated_price_str)

            # 계약방법
            bid_method = item.get('cntrctCnclsMthdNm', '일반경쟁입찰')

            # 중소기업 제한 여부
            is_sme_only = item.get('rgnlmtdYn', 'N') == 'Y'

            # URL - API가 제공하는 공식 URL 사용 (나라장터 공개 링크)
            # bidNtceUrl: 입찰공고 URL (R26BK 타입 등)
            # bidNtceDtlUrl: 입찰공고 상세 URL
            url = item.get('bidNtceUrl') or item.get('bidNtceDtlUrl')

            if not url:
                url = "https://www.g2b.go.kr"

            # 공고 상태
            status = item.get('ntceKindNm', '일반')

            tender = {
                'title': self.clean_text(title)[:200],
                'agency': self.clean_text(agency)[:100],
                'demand_agency': demand_agency,
                'tender_number': tender_number,
                'announced_date': announced_date,
                'deadline_date': deadline_date,
                'opening_date': opening_date,
                'estimated_price': estimated_price,
                'bid_method': bid_method,
                'status': status,
                'is_sme_only': is_sme_only,
                'source_site': self.site_name,
                'url': url
                # category 필드는 DB 모델에 없으므로 제외
            }

            return tender

        except Exception as e:
            self.errors.append(f"데이터 변환 오류: {str(e)}")
            return None

    def _parse_amount(self, amount_str):
        """
        금액 문자열 파싱

        Args:
            amount_str (str): 금액 문자열

        Returns:
            int: 파싱된 금액 (원) 또는 None
        """
        if not amount_str:
            return None

        try:
            # 숫자만 추출
            amount_str = ''.join(filter(str.isdigit, str(amount_str)))
            if amount_str:
                return int(amount_str)
        except BaseException:
            pass

        return None

    def parse_date(self, date_str):
        """
        날짜 문자열 파싱 (YYYYMMDD, YYYY-MM-DD 형식 지원)

        Args:
            date_str (str): 날짜 문자열

        Returns:
            datetime: 파싱된 날짜 또는 None
        """
        if not date_str:
            return None

        # 공백 및 특수문자 제거
        date_str = str(date_str).strip().replace(
            '-',
            '').replace(
            '.',
            '').replace(
            '/',
            '').replace(
                ':',
            '')

        try:
            # YYYYMMDD 형식 (8자리)
            if len(date_str) >= 8:
                return datetime.strptime(date_str[:8], '%Y%m%d')
            # YYYYMMDDHHMM 형식 (12자리)
            elif len(date_str) >= 12:
                return datetime.strptime(date_str[:12], '%Y%m%d%H%M')
        except ValueError:
            pass

        # 기본 파서로 시도
        return super().parse_date(date_str)
