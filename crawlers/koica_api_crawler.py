"""
한국국제협력단(KOICA) 조달정보 API 크롤러
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET


class KOICAApiCrawler(BaseCrawler):
    """KOICA 조달정보 크롤러"""

    def __init__(self, site_config):
        """
        Args:
            site_config (dict): 사이트 설정
                - service_key: API 인증키
                - years_range: 조회 년도 수 (기본: 2년)
                - num_of_rows: 한번에 가져올 개수 (기본: 100)
        """
        super().__init__(
            'KOICA 조달정보',
            'http://www.koica.go.kr'
        )
        # HTTP 사용 (HTTPS 아님)
        self.base_url = 'http://openapi.koica.go.kr/api/ws/PrcureService'
        self.service_key = site_config.get('service_key', '')
        self.years_range = site_config.get('years_range', 2)
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

            current_year = datetime.now().year

            # 여러 년도 조회
            for year in range(current_year - self.years_range + 1, current_year + 1):
                print(f"  {year}년 조달계획 조회 중...")
                self._crawl_year_plan(year)

            # 입찰정보 조회
            print(f"  입찰정보 조회 중...")
            self._crawl_bid_info()

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            error_msg = f"크롤링 오류: {str(e)}"
            self.errors.append(error_msg)
            print(f"[{self.site_name}] {error_msg}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _crawl_year_plan(self, year):
        """년간 발주계획 조회"""
        url = f"{self.base_url}/getOrprPlanInfoList"
        page = 1

        while True:
            params = {
                'serviceKey': self.service_key,
                'P_YEAR': str(year),
                'P_PAGE_NO': str(page),
                'P_PAGE_SIZE': str(self.num_of_rows)
            }

            try:
                response = self.session.get(url, params=params, timeout=30)

                if response.status_code != 200:
                    error_msg = f"{year}년 발주계획 조회 실패: HTTP {response.status_code}"
                    self.errors.append(error_msg)
                    print(f"    {error_msg}")
                    break

                # XML 파싱
                try:
                    root = ET.fromstring(response.content)
                except ET.ParseError as e:
                    error_msg = f"XML 파싱 실패: {str(e)}"
                    self.errors.append(error_msg)
                    print(f"    {error_msg}")
                    break

                # 결과 코드 확인
                result_code = root.find('.//RESULT_CODE')
                if result_code is not None and result_code.text != '00':
                    result_msg = root.find('.//RESULT_MSG')
                    error_msg = f"API 오류: {result_code.text} - {result_msg.text if result_msg is not None else 'Unknown'}"
                    self.errors.append(error_msg)
                    print(f"    {error_msg}")
                    break

                # 데이터 추출
                items = root.findall('.//item')
                if not items:
                    print(f"    페이지 {page}: 데이터 없음")
                    break

                print(f"    페이지 {page}: {len(items)}건 처리 중...")

                for item in items:
                    try:
                        tender = self._parse_year_plan_item(item, year)
                        if tender:
                            self.results.append(tender)
                    except Exception as e:
                        print(f"      항목 파싱 오류: {str(e)}")
                        continue

                # 총 개수 확인
                total_count_elem = root.find('.//TOTAL_COUNT')
                if total_count_elem is not None:
                    total_count = int(total_count_elem.text)
                    if page * self.num_of_rows >= total_count:
                        break

                page += 1

            except Exception as e:
                error_msg = f"{year}년 페이지 {page} 조회 오류: {str(e)}"
                self.errors.append(error_msg)
                print(f"    {error_msg}")
                break

    def _crawl_bid_info(self):
        """입찰정보 조회"""
        url = f"{self.base_url}/getBidPblancInfoList"
        page = 1

        while True:
            params = {
                'serviceKey': self.service_key,
                'pageNo': str(page),
                'numOfRows': str(self.num_of_rows)
            }

            try:
                response = self.session.get(url, params=params, timeout=30)

                if response.status_code != 200:
                    error_msg = f"입찰정보 조회 실패: HTTP {response.status_code}"
                    self.errors.append(error_msg)
                    print(f"    {error_msg}")
                    break

                # XML 파싱
                try:
                    root = ET.fromstring(response.content)
                except ET.ParseError as e:
                    error_msg = f"XML 파싱 실패: {str(e)}"
                    self.errors.append(error_msg)
                    print(f"    {error_msg}")
                    break

                # 결과 코드 확인
                result_code = root.find('.//RESULT_CODE')
                if result_code is not None and result_code.text != '00':
                    result_msg = root.find('.//RESULT_MSG')
                    error_msg = f"API 오류: {result_code.text} - {result_msg.text if result_msg is not None else 'Unknown'}"
                    self.errors.append(error_msg)
                    print(f"    {error_msg}")
                    break

                # 데이터 추출
                items = root.findall('.//item')
                if not items:
                    print(f"    페이지 {page}: 데이터 없음")
                    break

                print(f"    페이지 {page}: {len(items)}건 처리 중...")

                for item in items:
                    try:
                        tender = self._parse_bid_info_item(item)
                        if tender:
                            self.results.append(tender)
                    except Exception as e:
                        print(f"      항목 파싱 오류: {str(e)}")
                        continue

                # 총 개수 확인
                total_count_elem = root.find('.//TOTAL_COUNT')
                if total_count_elem is not None:
                    total_count = int(total_count_elem.text)
                    if page * self.num_of_rows >= total_count:
                        break

                page += 1

            except Exception as e:
                error_msg = f"입찰정보 페이지 {page} 조회 오류: {str(e)}"
                self.errors.append(error_msg)
                print(f"    {error_msg}")
                break

    def _parse_year_plan_item(self, item, year):
        """년간 발주계획 item을 공고 데이터로 변환"""

        # 사업명
        bsns_nm_elem = item.find('BSNS_NM')
        if bsns_nm_elem is None or not bsns_nm_elem.text:
            return None
        title = bsns_nm_elem.text.strip()

        # 부서명
        dept_nm_elem = item.find('DEPT_NM')
        agency = dept_nm_elem.text.strip() if dept_nm_elem is not None and dept_nm_elem.text else 'KOICA'

        # 발주시기 (YYYYMM)
        orpr_era_elem = item.find('ORPR_ERA_YM')
        orpr_era_text = orpr_era_elem.text.strip() if orpr_era_elem is not None and orpr_era_elem.text else ''
        announced_date = self._parse_date_ym(orpr_era_text) if orpr_era_text else None

        # 계약방법
        cntrct_mth_elem = item.find('CNTRCT_MTH_CD')
        bid_method = cntrct_mth_elem.text.strip() if cntrct_mth_elem is not None and cntrct_mth_elem.text else '일반경쟁'

        # 조달구분
        prcure_se_elem = item.find('PRCURE_SE_CD')
        prcure_se = prcure_se_elem.text.strip() if prcure_se_elem is not None and prcure_se_elem.text else ''

        # 공고번호 생성
        rnum_elem = item.find('RNUM')
        rnum = rnum_elem.text.strip() if rnum_elem is not None and rnum_elem.text else ''
        tender_number = f"KOICA-{year}-{rnum}" if rnum else f"KOICA-{year}-PLAN"

        return {
            'title': title[:200],
            'agency': agency,
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': None,
            'opening_date': None,
            'estimated_price': None,
            'bid_method': f'{bid_method} ({prcure_se})' if prcure_se else bid_method,
            'status': '발주계획',
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': 'http://www.koica.go.kr'
        }

    def _parse_bid_info_item(self, item):
        """입찰정보 item을 공고 데이터로 변환"""

        # 제목 추출 (필드명은 문서 확인 필요)
        title_elem = item.find('TITLE') or item.find('BID_TITLE') or item.find('BSNS_NM')
        if title_elem is None or not title_elem.text:
            return None
        title = title_elem.text.strip()

        # 기관명
        agency_elem = item.find('AGENCY') or item.find('DEPT_NM')
        agency = agency_elem.text.strip() if agency_elem is not None and agency_elem.text else 'KOICA'

        # 공고번호
        bid_no_elem = item.find('BID_NO') or item.find('RNUM')
        bid_no = bid_no_elem.text.strip() if bid_no_elem is not None and bid_no_elem.text else ''
        tender_number = f"KOICA-{bid_no}" if bid_no else 'KOICA-BID'

        # 날짜
        date_elem = item.find('BID_DATE') or item.find('PBLNC_DT')
        date_text = date_elem.text.strip() if date_elem is not None and date_elem.text else ''
        announced_date = self._parse_date(date_text) if date_text else None

        return {
            'title': title[:200],
            'agency': agency,
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': None,
            'opening_date': None,
            'estimated_price': None,
            'bid_method': '입찰공고',
            'status': '일반',
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': 'http://www.koica.go.kr'
        }

    def _parse_date_ym(self, date_str):
        """YYYYMM 형식 날짜를 datetime으로 변환"""
        if not date_str or len(date_str) != 6:
            return None

        try:
            year = int(date_str[:4])
            month = int(date_str[4:6])
            return datetime(year, month, 1)
        except ValueError:
            return None

    def _parse_date(self, date_str):
        """날짜 문자열을 datetime으로 변환"""
        if not date_str:
            return None

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
