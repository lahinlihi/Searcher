"""산업통상부 - 콘텐츠 로딩 대기"""
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time

print("="*70)
print("산업통상부 - 콘텐츠 로딩 대기 분석")
print("="*70)

URL = "https://www.motie.go.kr/kor/article/ATCL2826a2625"

chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--disable-gpu')
chrome_options.add_argument('--window-size=1920,1080')
chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
chrome_options.add_argument('--log-level=3')

print(f"\n페이지 로드: {URL}")

try:
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )

    driver.get(URL)
    print(f"페이지 타이틀: {driver.title}")

    # Wait for various possible selectors
    print("\n다양한 콘텐츠 로딩 대기...")

    possible_selectors = [
        (By.CSS_SELECTOR, "table tbody tr"),
        (By.CSS_SELECTOR, "ul.board-list li"),
        (By.CSS_SELECTOR, ".board-list"),
        (By.CSS_SELECTOR, ".notice-list"),
        (By.CSS_SELECTOR, ".article-list"),
        (By.CSS_SELECTOR, "div.bbs"),
        (By.CLASS_NAME, "board"),
        (By.TAG_NAME, "table")
    ]

    found_selector = None
    for by, selector in possible_selectors:
        try:
            element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((by, selector))
            )
            print(f"OK 발견: {selector}")
            found_selector = selector
            break
        except:
            print(f"FAIL 타임아웃: {selector}")

    if not found_selector:
        print("\n공지사항 콘텐츠를 찾지 못했습니다.")
        print("페이지 구조를 직접 분석합니다...")

    # 충분히 대기
    time.sleep(5)

    # 전체 HTML 가져오기
    html = driver.page_source
    print(f"\n전체 HTML 크기: {len(html):,} bytes")

    # 전체 HTML 저장
    with open('motie_full_with_wait.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print("전체 HTML 저장: motie_full_with_wait.html")

    # BeautifulSoup으로 분석
    soup = BeautifulSoup(html, 'html.parser')

    print(f"\nHTML 구조:")
    print(f"  table: {len(soup.find_all('table'))}개")
    print(f"  tbody: {len(soup.find_all('tbody'))}개")
    print(f"  tr: {len(soup.find_all('tr'))}개")
    print(f"  ul: {len(soup.find_all('ul'))}개")
    print(f"  li: {len(soup.find_all('li'))}개")
    print(f"  div: {len(soup.find_all('div'))}개")

    # 공고 관련 텍스트 검색
    print("\n'공고' 텍스트 검색:")
    text = soup.get_text()
    if '공고' in text:
        count = text.count('공고')
        print(f"  '공고' 발견: {count}회")

        # 공고가 포함된 링크 찾기
        links_with_notice = []
        for a in soup.find_all('a', href=True):
            if '공고' in a.get_text():
                links_with_notice.append(a)

        print(f"  '공고'가 포함된 링크: {len(links_with_notice)}개")
        if links_with_notice:
            for i, link in enumerate(links_with_notice[:5], 1):
                print(f"    {i}. {link.get_text(strip=True)[:60]}")
                print(f"       {link.get('href')}")
    else:
        print("  '공고' 텍스트를 찾을 수 없음")
        print("  이 페이지는 공고 목록 페이지가 아닐 수 있습니다.")

    driver.quit()

except Exception as e:
    print(f"\n오류: {str(e)}")
    import traceback
    traceback.print_exc()

print(f"\n{'='*70}")
print("분석 완료")
print("="*70)
