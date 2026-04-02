"""
행정안전부 관보 대통령공고 API 크롤러
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET


class MOISPredeceCrawler(BaseCrawler):
    """행정안전부 대통령공고 크롤러"""

    def __init__(self, site_config):
        """
        Args:
            site_config (dict): 사이트 설정
                - service_key: API 인증키
                - days_range: 조회 기간 (기본: 1460일 = 4년)
                - num_of_rows: 한번에 가져올 개수 (기본: 100)
        """
        super().__init__(
            '행정안전부 대통령공고',
            'https://www.mois.go.kr'
        )
        self.api_url = 'https://apis.data.go.kr/1741000/ApiPredeceService/getApiPredeceList'
        self.service_key = site_config.get('service_key', '')
        self.days_range = site_config.get('days_range', 1460)  # 기본 4년
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

            # 날짜 범위 계산 (대통령공고는 자주 발행되지 않아 기본 4년)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=self.days_range)

            print(f"  조회 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")

            # API 호출
            page = 1
            total_collected = 0

            while True:
                params = {
                    'serviceKey': self.service_key,
                    'pageNo': str(page),
                    'pageSize': str(self.num_of_rows),
                    'reqFrom': start_date.strftime('%Y%m%d'),
                    'reqTo': end_date.strftime('%Y%m%d'),
                    'type': '0'  # XML
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
                result_code = root.find('resultCode')
                result_msg = root.find('resultMsg')

                if result_code is not None and result_code.text != '0':
                    if result_code.text == '10':  # NO_CONTENTS
                        print(f"  페이지 {page}: 데이터 없음")
                    else:
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
                        tender = self._parse_item(item)
                        if tender:
                            self.results.append(tender)
                            total_collected += 1
                    except Exception as e:
                        print(f"    항목 파싱 오류: {str(e)}")
                        continue

                # 다음 페이지
                total_count_elem = root.find('totalCount')
                if total_count_elem is not None:
                    total_count = int(total_count_elem.text)
                    if page * self.num_of_rows >= total_count:
                        print(f"  전체 {total_count}건 중 {total_collected}건 수집 완료")
                        break

                page += 1

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            error_msg = f"크롤링 오류: {str(e)}"
            self.errors.append(error_msg)
            print(f"[{self.site_name}] {error_msg}")
            import traceback
            traceback.print_exc()

        return self.get_results()

    def _parse_item(self, item):
        """XML item을 공고 데이터로 변환"""

        # 컨텐츠 순번 (공고번호로 사용)
        seq_no_elem = item.find('cntntSeqNo')
        seq_no = seq_no_elem.text.strip() if seq_no_elem is not None and seq_no_elem.text else ''

        # 제목
        title_elem = item.find('cntntSj')
        if title_elem is None or not title_elem.text:
            return None
        title = title_elem.text.strip()

        # 발행일자
        pub_date_elem = item.find('hopePblictDt')
        pub_date_text = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else ''
        announced_date = self._parse_date(pub_date_text)

        # 발행기관
        agency_elem = item.find('pblcnInstNm')
        agency = agency_elem.text.strip() if agency_elem is not None and agency_elem.text else '행정안전부'

        # PDF 경로
        pdf_path_elem = item.find('pdfFilePath')
        pdf_path = pdf_path_elem.text.strip() if pdf_path_elem is not None and pdf_path_elem.text else ''

        # URL 생성
        url = ''
        if pdf_path:
            # PDF 경로를 절대 URL로 변환
            if not pdf_path.startswith('http'):
                url = f'https://www.gwangbo.go.kr{pdf_path}'

        # 근거법령
        basis_law_elem = item.find('basisLawNm')
        basis_law = basis_law_elem.text.strip() if basis_law_elem is not None and basis_law_elem.text else ''

        # 공고번호 생성
        tender_number = f"MOIS-{seq_no[-10:]}" if seq_no else f"MOIS-{announced_date.strftime('%Y%m%d')}" if announced_date else 'MOIS-UNKNOWN'

        return {
            'title': title[:200],
            'agency': agency,
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': None,  # 대통령공고는 마감일이 없음
            'opening_date': None,
            'estimated_price': None,
            'bid_method': f'대통령공고 ({basis_law})' if basis_law else '대통령공고',
            'status': '일반',
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': url
        }

    def _parse_date(self, date_str):
        """날짜 문자열을 datetime으로 변환"""
        if not date_str:
            return None

        # 날짜 형식들
        date_formats = [
            '%Y.%m.%d',
            '%Y-%m-%d',
            '%Y%m%d',
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        return None
