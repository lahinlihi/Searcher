"""
중소벤처 24 (중소기업기술정보진흥원) API 크롤러
사업공고정보 조회 API
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import json


class SMB24ApiCrawler(BaseCrawler):
    """중소벤처 24 API 크롤러"""

    def __init__(self, site_config):
        """
        Args:
            site_config (dict): 사이트 설정
                - service_key: API 인증키 (URL 인코딩된 상태)
                - days_range: 조회 기간 (기본: 30일)
        """
        super().__init__(
            '중소벤처 24',
            'https://www.smes.go.kr'
        )
        self.service_key = site_config.get('service_key', '')
        self.days_range = site_config.get('days_range', 30)
        self.api_url = 'https://www.smes.go.kr/fnct/apiReqst/extPblancInfo'

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")

        try:
            # 날짜 범위 설정 (최근 N일)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.days_range)

            # 날짜를 yyyyMMdd 형식으로 변환
            start_dt = start_date.strftime('%Y%m%d')
            end_dt = end_date.strftime('%Y%m%d')

            print(f"  조회기간: {start_dt} ~ {end_dt}")

            # API 호출
            params = {
                'token': self.service_key,
                'strDt': start_dt,
                'endDt': end_dt,
                'html': 'no'  # HTML 태그 제외
            }

            response = self.session.get(
                self.api_url,
                params=params,
                timeout=30
            )

            if response.status_code != 200:
                error_msg = f"API 호출 실패: HTTP {response.status_code}"
                self.errors.append(error_msg)
                print(f"  {error_msg}")
                return self.get_results()

            # JSON 파싱
            try:
                result = response.json()
            except json.JSONDecodeError as e:
                error_msg = f"JSON 파싱 실패: {str(e)}"
                self.errors.append(error_msg)
                print(f"  {error_msg}")
                return self.get_results()

            # 결과 코드 확인
            result_code = result.get('resultCd', '')
            result_msg = result.get('resultMsg', '')

            if result_code != '0':
                error_msg = f"API 오류: {result_code} - {result_msg}"
                self.errors.append(error_msg)
                print(f"  {error_msg}")
                return self.get_results()

            # 공고 데이터 추출
            data_list = result.get('data', [])
            print(f"  전체 {len(data_list)}건")

            for item in data_list:
                try:
                    tender = self._parse_item(item)
                    if tender:
                        self.results.append(tender)
                except Exception as e:
                    print(f"  항목 파싱 오류: {str(e)}")
                    continue

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            error_msg = f"크롤링 오류: {str(e)}"
            self.errors.append(error_msg)
            print(f"[{self.site_name}] {error_msg}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _parse_item(self, item):
        """JSON 아이템을 공고 데이터로 변환"""

        # 공고번호
        pbllanc_seq = str(item.get('pblancSeq', ''))
        if not pbllanc_seq:
            return None

        # 제목
        title = item.get('pblancNm', '').strip()
        if not title:
            return None

        # 발주기관 (지원기관)
        agency = item.get('sportInsttNm', '중소기업기술정보진흥원').strip()

        # 날짜 파싱
        announced_date = self._parse_date(item.get('creatDt', ''))
        deadline_date = self._parse_date_only(item.get('pblancEndDt', ''))
        opening_date = self._parse_date_only(item.get('pblancBgnDt', ''))

        # 추정가격 (지원금액 범위)
        estimated_price = None
        try:
            max_sport_amt = item.get('maxSportAmt')
            if max_sport_amt and int(max_sport_amt) > 0:
                estimated_price = int(max_sport_amt)
        except (TypeError, ValueError):
            pass

        # 입찰방법 (지원유형)
        bid_method = item.get('sportType', '').strip()
        if not bid_method:
            bid_method = '사업공고'

        # 상태 (사업유형)
        status = '일반'
        biz_type = item.get('bizType', '').strip()
        if '창업' in biz_type:
            status = '창업지원'
        elif '기술' in biz_type:
            status = '기술지원'

        # 공고 URL (API가 간혹 https://domain.comhttps://domain.com/... 형태 반환)
        url = item.get('pblancDtlUrl', '').strip()
        if url:
            second_http = url.find('http', 1)
            if second_http > 0:
                url = url[second_http:]
        if not url:
            url = f"https://www.smes.go.kr/pblancDetail/{pbllanc_seq}"

        return {
            'title': title[:200],
            'agency': agency[:100],
            'tender_number': f"SMB24-{pbllanc_seq}",
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': opening_date,
            'estimated_price': estimated_price,
            'bid_method': bid_method[:50] if bid_method else '사업공고',
            'status': status,
            'is_sme_only': True,  # 중소벤처 전용
            'source_site': self.site_name,
            'url': url
        }

    def _parse_date(self, date_str):
        """날짜시간 문자열을 datetime으로 변환 (yyyy-MM-dd HH:mm:ss)"""
        if not date_str:
            return None

        try:
            # "2022-10-25 14:10:45" 형식
            return datetime.strptime(date_str.strip(), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None

    def _parse_date_only(self, date_str):
        """날짜 문자열을 datetime으로 변환 (yyyy-MM-dd)"""
        if not date_str:
            return None

        try:
            # "2022-11-30" 형식
            return datetime.strptime(date_str.strip(), '%Y-%m-%d')
        except ValueError:
            return None
