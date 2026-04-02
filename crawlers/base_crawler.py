"""
기본 크롤러 클래스
모든 크롤러의 베이스 클래스
"""

from abc import ABC, abstractmethod
from datetime import datetime
import time
import requests
from bs4 import BeautifulSoup
import urllib3


class BaseCrawler(ABC):
    """크롤러 기본 클래스"""

    def __init__(
            self,
            site_name,
            base_url,
            verify_ssl=True,
            use_selenium=False,
            encoding=None):
        self.site_name = site_name
        self.base_url = base_url
        self.verify_ssl = verify_ssl
        self.use_selenium = use_selenium
        self.encoding = encoding
        self.driver = None

        # SSL 검증 우회 시 경고 비활성화
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
        })
        self.results = []
        self.errors = []

    def _init_selenium_driver(self):
        """Selenium 드라이버 초기화"""
        if self.driver:
            return

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager
            import os

            chrome_options = Options()
            chrome_options.add_argument('--headless')  # 백그라운드 실행
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument(
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

            # 로그 비활성화
            chrome_options.add_experimental_option(
                'excludeSwitches', ['enable-logging'])
            chrome_options.add_argument('--log-level=3')

            # SSL 검증 우회
            if not self.verify_ssl:
                chrome_options.add_argument('--ignore-certificate-errors')

            # ChromeDriverManager가 Chrome 버전에 맞는 드라이버를 자동으로 설치/캐시 관리
            try:
                driver_path = ChromeDriverManager().install()
                print(f"[Selenium] ChromeDriver 준비 완료: {driver_path}")
            except Exception as install_error:
                raise Exception(
                    f"ChromeDriver를 설치할 수 없습니다: {install_error}") from install_error

            service = Service(driver_path)
            self.driver = webdriver.Chrome(
                service=service, options=chrome_options)
            self.driver.set_page_load_timeout(30)

        except Exception as e:
            self.errors.append(f"Selenium 드라이버 초기화 실패: {str(e)}")
            raise

    def _close_selenium_driver(self):
        """Selenium 드라이버 종료"""
        if self.driver:
            try:
                self.driver.quit()
                self.driver = None
            except Exception as e:
                self.errors.append(f"Selenium 드라이버 종료 실패: {str(e)}")

    @abstractmethod
    def crawl(self, **kwargs):
        """
        크롤링 실행 (하위 클래스에서 구현)

        Returns:
            list: 크롤링된 공고 데이터 리스트
        """

    def fetch_page(self, url, timeout=30, wait_time=3):
        """
        페이지 HTML 가져오기

        Args:
            url (str): 페이지 URL
            timeout (int): 타임아웃 (초)
            wait_time (int): Selenium 사용 시 페이지 로드 대기 시간 (초)

        Returns:
            BeautifulSoup: 파싱된 HTML 또는 None
        """
        try:
            if self.use_selenium:
                # Selenium으로 페이지 가져오기 (JavaScript 실행)
                if not self.driver:
                    self._init_selenium_driver()

                self.driver.get(url)
                time.sleep(wait_time)  # JavaScript 로딩 대기

                html = self.driver.page_source
                return BeautifulSoup(html, 'html.parser')
            else:
                # 기존 requests 방식
                response = self.session.get(
                    url, timeout=timeout, verify=self.verify_ssl)
                response.raise_for_status()

                # 인코딩 설정
                if self.encoding:
                    # 사이트별로 지정된 인코딩 사용
                    response.encoding = self.encoding
                elif response.encoding is None or response.encoding == 'ISO-8859-1':
                    # 인코딩 자동 감지
                    response.encoding = response.apparent_encoding

                # 한국 사이트의 경우 UTF-8이 아니면 EUC-KR 시도
                if response.encoding and 'euc' not in response.encoding.lower(
                ) and 'ut' not in response.encoding.lower():
                    # 일반적인 한국 사이트 인코딩 시도
                    try:
                        response.encoding = 'utf-8'
                        response.text
                        # UTF-8로 디코딩이 실패하면 EUC-KR 시도
                    except BaseException:
                        response.encoding = 'euc-kr'

                return BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            self.errors.append(f"페이지 로드 실패 ({url}): {str(e)}")
            return None

    def post_request(self, url, data, timeout=30):
        """
        POST 요청

        Args:
            url (str): 요청 URL
            data (dict): POST 데이터
            timeout (int): 타임아웃 (초)

        Returns:
            Response: 응답 객체 또는 None
        """
        try:
            response = self.session.post(
                url, data=data, timeout=timeout, verify=self.verify_ssl)
            response.raise_for_status()
            return response
        except Exception as e:
            self.errors.append(f"POST 요청 실패 ({url}): {str(e)}")
            return None

    def parse_date(self, date_str):
        """
        날짜 문자열 파싱

        Args:
            date_str (str): 날짜 문자열 (예: "2024-12-17")

        Returns:
            datetime: 파싱된 날짜 또는 None
        """
        if not date_str:
            return None

        # 공백 및 특수문자 제거
        date_str = date_str.strip().replace('.', '-').replace('/', '-')

        # 여러 포맷 시도
        formats = [
            '%Y-%m-%d',
            '%Y%m%d',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        self.errors.append(f"날짜 파싱 실패: {date_str}")
        return None

    def parse_price(self, price_str):
        """
        가격 문자열 파싱

        Args:
            price_str (str): 가격 문자열 (예: "500,000,000원")

        Returns:
            int: 파싱된 가격 (원) 또는 None
        """
        if not price_str:
            return None

        try:
            # 숫자만 추출
            price_str = price_str.replace(
                ',',
                '').replace(
                '원',
                '').replace(
                ' ',
                '')

            # 단위 처리
            if '억' in price_str:
                parts = price_str.split('억')
                value = float(parts[0]) * 100000000
                if len(parts) > 1 and parts[1]:
                    value += float(parts[1]) * \
                        10000 if '만' in parts[1] else float(parts[1])
                return int(value)
            elif '만' in price_str:
                parts = price_str.split('만')
                return int(float(parts[0]) * 10000)
            else:
                return int(float(price_str))
        except Exception as e:
            self.errors.append(f"가격 파싱 실패: {price_str} - {str(e)}")
            return None

    def clean_text(self, text):
        """
        텍스트 정리

        Args:
            text (str): 원본 텍스트

        Returns:
            str: 정리된 텍스트
        """
        if not text:
            return ""

        # 공백 정리
        text = ' '.join(text.split())
        return text.strip()

    def sleep(self, seconds=1):
        """
        대기 (서버 부하 방지)

        Args:
            seconds (int): 대기 시간 (초)
        """
        time.sleep(seconds)

    def get_results(self):
        """
        크롤링 결과 반환

        Returns:
            dict: 결과 및 에러 정보
        """
        return {
            'success': len(self.errors) == 0,
            'site': self.site_name,
            'count': len(self.results),
            'data': self.results,
            'errors': self.errors
        }

    def reset(self):
        """결과 및 에러 초기화"""
        self.results = []
        self.errors = []

    def __del__(self):
        """소멸자 - Selenium 드라이버 정리"""
        self._close_selenium_driver()
