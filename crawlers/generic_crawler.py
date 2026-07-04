"""
범용 크롤러
설정 기반으로 다양한 사이트를 크롤링할 수 있는 범용 크롤러
"""

from .base_crawler import BaseCrawler
from datetime import datetime, timedelta
import hashlib
import random
import re
import unicodedata


class GenericCrawler(BaseCrawler):
    """
    설정 기반 범용 크롤러

    사이트 설정에 다음 정보가 포함되어야 함:
    - crawl_url: 크롤링할 페이지 URL
    - crawl_type: 'list' (공고 목록 페이지) 또는 'sample' (샘플 데이터 생성)
    - selectors: CSS 셀렉터 정보 (선택사항)
    """

    def __init__(self, site_name, site_config):
        """
        Args:
            site_name (str): 사이트 이름
            site_config (dict): 사이트 설정
                - url: 기본 URL
                - crawl_url: 크롤링 URL (선택)
                - crawl_type: 'list', 'sample' (기본값: 'sample')
                - selectors: CSS 셀렉터 설정 (선택)
                - verify_ssl: SSL 인증서 검증 여부 (선택, 기본값: True)
                - use_selenium: Selenium 사용 여부 (선택, 기본값: False)
                - encoding: 인코딩 (선택, 예: 'utf-8', 'euc-kr')
        """
        base_url = site_config.get('url', '')
        verify_ssl = site_config.get('verify_ssl', True)
        use_selenium = site_config.get('use_selenium', False)
        encoding = site_config.get('encoding', None)
        super().__init__(
            site_name,
            base_url,
            verify_ssl=verify_ssl,
            use_selenium=use_selenium,
            encoding=encoding)

        self.site_config = site_config
        self.crawl_url = site_config.get('crawl_url', base_url)
        self.crawl_type = site_config.get('crawl_type', 'sample')
        self.selectors = site_config.get('selectors', {})
        self.onclick_pattern = site_config.get('onclick_pattern', '')
        self.url_template = site_config.get('url_template', '')
        self.title_attr = site_config.get('title_attr', '')
        self.title_clean_regex = site_config.get('title_clean_regex', '')
        self.detail_price = site_config.get('detail_price', None)  # {selector, pattern}
        self.detail_deadline = site_config.get('detail_deadline', None)  # {label: "공고마감일자"} — dt/dd 구조
        self.default_agency = site_config.get('default_agency', '')  # 고정 수요기관명
        self.result_notice_pattern = site_config.get('result_notice_pattern', '')  # 결과공고 태깅 패턴 (수집은 하되 status='결과공고'로 마킹)
        # api_json 타입 전용 설정
        self.api_params = site_config.get('api_params', {})       # POST 파라미터 기본값
        self.api_items_key = site_config.get('api_items_key', '')  # 응답 JSON에서 목록 키
        self.api_total_key = site_config.get('api_total_key', '')  # 전체 건수 키
        self.api_page_param = site_config.get('api_page_param', 'pageIndex')   # 페이지 번호 파라미터명
        self.api_size_param = site_config.get('api_size_param', 'pageUnit')    # 페이지 크기 파라미터명
        self.api_page_size = site_config.get('api_page_size', 20)              # 페이지당 건수
        self.api_field_map = site_config.get('api_field_map', {})  # {응답필드: tender필드}
        # 다행 구조 지원: item이 특정 td일 때 이전/다음 tr에서 agency, date 추출
        _sel = self.selectors
        self.agency_prev_row_selector = _sel.get('agency_prev_row', '')   # 이전 tr에서 agency 추출
        self.date_next_row_selector = _sel.get('date_next_row', '')       # 다음 tr에서 announced_date 추출
        self.deadline_next_row_selector = _sel.get('deadline_next_row', '')  # 다음 tr에서 deadline_date 추출
        self.text_after_split = site_config.get('text_after_split', '')   # 텍스트에서 '|' 등 구분자 뒤 부분만 사용

    def crawl(self, **kwargs):
        """크롤링 실행"""
        self.reset()
        print(f"[{self.site_name}] 크롤링 시작...")
        print(f"  타입: {self.crawl_type}")

        try:
            if self.crawl_type == 'list':
                # 실제 웹페이지 크롤링
                self._crawl_list_page()
            elif self.crawl_type == 'api_json':
                # JSON POST API 크롤링
                self._crawl_api_json()
            elif self.crawl_type == 'sample':
                # 샘플 데이터 생성 (테스트 목적으로만 사용)
                print(f"[{self.site_name}] 샘플 모드는 비활성화되었습니다 - 크롤링 건너뜀")
            else:
                print(f"[{self.site_name}] 알 수 없는 크롤링 타입: {self.crawl_type}")

            print(f"[{self.site_name}] 완료: {len(self.results)}건 수집")

        except Exception as e:
            self.errors.append(f"크롤링 오류: {str(e)}")
            print(f"[{self.site_name}] 오류: {str(e)}")

        return self.get_results()

    def _crawl_api_json(self):
        """
        JSON POST API 크롤링 (fanfandaero 등 REST API 기반 사이트)

        settings.json 예시:
        {
            "crawl_type": "api_json",
            "crawl_url": "https://example.kr/api/list.do",
            "api_params": {"searchOrder": 1, ...},  # 고정 POST 파라미터
            "api_items_key": "sprtBizApplList",      # 응답에서 목록 키
            "api_total_key": "cntTot",               # 전체 건수 키
            "api_page_param": "pageIndex",           # 페이지 번호 파라미터명
            "api_size_param": "pageUnit",            # 페이지 크기 파라미터명
            "api_page_size": 20,                     # 페이지당 건수
            "api_field_map": {                       # 응답 필드 → tender 필드 매핑
                "title": "sprtBizNm",
                "tender_number": "sprtBizCd",
                "agency": "operInstNm",
                "announced_date": "rcritBgngYmd",
                "deadline_date": "rcritEndYmd",
                "url": "url"
            }
        }
        """
        if not self.api_items_key:
            self.errors.append("api_items_key가 설정되지 않았습니다")
            return
        if not self.api_field_map:
            self.errors.append("api_field_map이 설정되지 않았습니다")
            return

        import requests as _req

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': self.base_url,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
        }

        max_items = self.site_config.get('max_items', 200)
        page = 1

        while len(self.results) < max_items:
            params = dict(self.api_params)
            params[self.api_page_param] = page
            params[self.api_size_param] = self.api_page_size

            try:
                resp = _req.post(self.crawl_url, headers=headers, data=params, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.errors.append(f"API 요청 실패 (페이지 {page}): {e}")
                break

            items = data.get(self.api_items_key, [])
            if not items:
                break

            for item in items:
                if len(self.results) >= max_items:
                    break
                try:
                    tender = self._convert_api_item(item)
                    if tender:
                        self.results.append(tender)
                except Exception as e:
                    print(f"[{self.site_name}] 아이템 변환 오류: {e}")

            total = data.get(self.api_total_key, 0) if self.api_total_key else 0
            print(f"[{self.site_name}] 페이지 {page}: {len(items)}건 (누적 {len(self.results)}건 / 전체 {total}건)")

            if total and len(self.results) >= total:
                break
            if len(items) < self.api_page_size:
                break
            page += 1

    def _convert_api_item(self, item):
        """api_json 타입의 응답 아이템을 tender 형식으로 변환"""
        fm = self.api_field_map
        title_key = fm.get('title', '')
        title = self._sanitize_text(str(item.get(title_key, ''))) if title_key else ''
        if not title:
            return None

        agency_key = fm.get('agency', '')
        _agency_raw = item.get(agency_key) if agency_key else None
        agency = self._sanitize_text(str(_agency_raw)) if _agency_raw and _agency_raw != 'None' else ''
        if not agency:
            agency = self.default_agency or self.site_name

        num_key = fm.get('tender_number', '')
        tender_number = str(item.get(num_key, '')) if num_key else self._generate_tender_number(title)

        ann_key = fm.get('announced_date', '')
        announced_date = self._parse_date(str(item.get(ann_key, ''))) if ann_key else None

        dl_key = fm.get('deadline_date', '')
        deadline_date = self._parse_date(str(item.get(dl_key, ''))) if dl_key else None

        url_key = fm.get('url', '')
        raw_url = item.get(url_key) if url_key else None
        url_val = str(raw_url) if raw_url and raw_url != 'None' else ''
        if url_val and url_val.startswith('/'):
            url_val = self.base_url.rstrip('/') + url_val
        if not url_val and self.url_template:
            url_val = self.url_template.format(tender_number=tender_number)
        url_val = url_val or self.base_url

        return {
            'title': title[:200],
            'agency': agency[:100],
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': None,
            'estimated_price': None,
            'bid_method': '일반경쟁입찰',
            'status': '결과공고' if (self.result_notice_pattern and re.search(self.result_notice_pattern, title)) else '일반',
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': url_val,
        }

    def _build_page_url(self, url, param, page):
        """페이지 번호를 URL 쿼리 파라미터에 추가/변경"""
        from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        params[param] = [str(page)]
        new_query = urlencode({k: v[0] for k, v in params.items()})
        return urlunparse(parsed._replace(query=new_query))

    def _selenium_click_page(self, page):
        """Selenium으로 페이지 번호 링크 클릭 (JavaScript 페이지네이션 사이트)"""
        import time
        try:
            from selenium.webdriver.common.by import By
            # 페이지 번호 링크 찾기: 숫자 텍스트가 page인 a 태그
            links = self.driver.find_elements(By.XPATH,
                f"//a[normalize-space(text())='{page}'] | "
                f"//button[normalize-space(text())='{page}']"
            )
            for link in links:
                parent_class = (link.find_element(By.XPATH, '..').get_attribute('class') or '').lower()
                own_class = (link.get_attribute('class') or '').lower()
                # 페이지네이션 영역의 링크만 클릭 (nav, paging, pagination 클래스)
                if any(x in parent_class + own_class for x in ['pag', 'page', 'num', 'navi']):
                    self.driver.execute_script("arguments[0].click();", link)
                    time.sleep(2)
                    from bs4 import BeautifulSoup
                    return BeautifulSoup(self.driver.page_source, 'html.parser')
            # 클래스 무관하게 숫자 링크 직접 클릭
            if links:
                self.driver.execute_script("arguments[0].click();", links[0])
                time.sleep(2)
                from bs4 import BeautifulSoup
                return BeautifulSoup(self.driver.page_source, 'html.parser')
        except Exception as e:
            print(f"[{self.site_name}] Selenium 페이지 클릭 실패 (page={page}): {e}")
        return None

    def _crawl_list_page(self):
        """
        실제 웹페이지 크롤링 (페이지네이션 지원)

        selectors 설정 예시:
        {
            'item': '.notice-item',  # 공고 목록 아이템 셀렉터
            'title': '.title',       # 제목
            'agency': '.agency',     # 발주기관
            'date': '.date',         # 날짜
            'link': 'a'              # 링크
        }

        pagination 설정 예시:
        {
            'param': 'pageIndex',  # 페이지 번호 쿼리 파라미터명
            'start': 1             # 시작 페이지 번호 (기본: 1)
        }
        """
        if not self.selectors or not self.selectors.get('item'):
            print(f"[{self.site_name}] 셀렉터 미설정 - 크롤링 건너뜀")
            return

        max_items = self.site_config.get('max_items', 100)
        pagination = self.site_config.get('pagination', {})
        param_name = pagination.get('param') if pagination else None
        start_page = pagination.get('start', 1) if pagination else 1
        page_step = pagination.get('step', 1) if pagination else 1

        page = start_page
        seen_titles = set()
        # pagination.click: true 일 때만 Selenium DOM 클릭 방식 사용
        # (URL 파라미터가 서버에서 무시되는 JS 전용 사이트용)
        use_selenium_click = (self.use_selenium and pagination.get('click', False))

        while len(self.results) < max_items:
            # 현재 페이지 소스 가져오기
            if page == start_page:
                # 첫 페이지: 항상 원래 URL로 로드
                soup = self.fetch_page(self.crawl_url)
            elif use_selenium_click:
                # pagination.click=true 사이트 2페이지~: 번호 클릭
                soup = self._selenium_click_page(page)
            elif param_name:
                # URL 파라미터 방식 (Selenium/requests 모두 지원)
                # step이 설정된 경우 오프셋 기반 페이지네이션 지원 (예: Start=0,10,20...)
                page_value = start_page + (page - start_page) * page_step
                url = self._build_page_url(self.crawl_url, param_name, page_value)
                soup = self.fetch_page(url)
            else:
                break  # 페이지네이션 설정 없음

            if not soup:
                if page == start_page:
                    raise Exception("페이지를 가져올 수 없습니다")
                break

            items = soup.select(self.selectors.get('item', ''))
            if not items:
                if page == start_page:
                    print(f"[{self.site_name}] 공고를 찾을 수 없습니다 - 크롤링 건너뜀")
                break

            # 중복 페이지 감지 (잘못된 페이지 파라미터 또는 마지막 페이지 이후)
            if param_name and page > start_page:
                title_sel = self.selectors.get('title', '')
                page_titles = set()
                for item in items:
                    if title_sel:
                        el = item.select_one(title_sel)
                        if el:
                            t = el.get_text(strip=True)[:50]
                            if t:
                                page_titles.add(t)
                if page_titles and page_titles.issubset(seen_titles):
                    print(f"[{self.site_name}] 페이지 {page}: 중복 감지, 수집 종료")
                    break
                seen_titles |= page_titles
            elif param_name:
                # 첫 페이지 타이틀 초기화
                title_sel = self.selectors.get('title', '')
                for item in items:
                    if title_sel:
                        el = item.select_one(title_sel)
                        if el:
                            t = el.get_text(strip=True)[:50]
                            if t:
                                seen_titles.add(t)

            # 아이템 처리
            count_before = len(self.results)
            for idx, item in enumerate(items):
                if len(self.results) >= max_items:
                    break
                try:
                    self._process_item(item, idx)
                except Exception as e:
                    print(f"[{self.site_name}] 아이템 {idx} 파싱 오류: {str(e)}")
                    continue

            if page > start_page:
                added = len(self.results) - count_before
                print(f"[{self.site_name}] 페이지 {page}: {added}건 추가 (누적 {len(self.results)}건)")

            # 단일 페이지 모드 또는 아이템 없으면 종료
            if not param_name:
                break
            if len(self.results) == count_before:
                break

            page += 1

    def _process_item(self, item, idx):
        """공고 아이템 하나를 파싱하여 results에 추가"""

        # 제목 추출
        title_selector = self.selectors.get('title', '')
        title_elem = None
        if title_selector:
            title_elem = item.select_one(title_selector)
            if title_elem:
                if self.title_attr:
                    raw = title_elem.get(self.title_attr, '')
                else:
                    raw = title_elem.get_text(strip=True)
                if self.title_clean_regex:
                    raw = re.sub(self.title_clean_regex, '', raw).strip()
                title = self._sanitize_text(raw)
            else:
                # 셀렉터가 설정됐는데 요소를 못 찾으면 빈 행으로 간주 → 스킵
                return
        else:
            title = self._sanitize_text(
                item.get_text(strip=True)[:200]) if item else f'{self.site_name} 공고 {idx + 1}'

        # 발주기관 추출
        agency_selector = self.selectors.get('agency', '')
        if agency_selector:
            agency_elem = item.select_one(agency_selector)
            agency = self._sanitize_text(agency_elem.get_text(
                strip=True)) if agency_elem else (self.default_agency or self.site_name)
        else:
            agency = self.default_agency or self.site_name

        # 다행 구조: 이전 tr에서 기관명 추출 (agency_prev_row 설정 시)
        if self.agency_prev_row_selector and item.parent:
            _prev_tr = item.parent.find_previous_sibling('tr')
            if _prev_tr:
                _agency_elem = _prev_tr.select_one(self.agency_prev_row_selector)
                if _agency_elem:
                    _raw = _agency_elem.get_text(strip=True)
                    if self.text_after_split and self.text_after_split in _raw:
                        agency = self._sanitize_text(_raw.split(self.text_after_split)[-1])
                    else:
                        agency = self._sanitize_text(_raw)
            if not agency:
                agency = self.default_agency or self.site_name

        # 링크 추출
        link_selector = self.selectors.get('link', 'a')
        if link_selector:
            link_elem = item.select_one(link_selector)
        else:
            link_elem = item.find('a')

        link = ''
        href = ''
        if link_elem:
            href = link_elem.get('href', '')
            onclick_sources = [href, link_elem.get('onclick', ''), item.get('onclick', '')]
        else:
            # <a> 태그가 없고 onclick이 행(item) 자체에 있는 구조 (예: <tr onclick="...">)
            onclick_sources = [item.get('onclick', '')]

        # onclick/javascript: 기반 URL 추출
        if self.onclick_pattern and self.url_template:
            for search_text in onclick_sources:
                if search_text:
                    m = re.search(self.onclick_pattern, search_text)
                    if m:
                        groups = m.groups()
                        fmt_kwargs = {f'id{i+1}': g for i, g in enumerate(groups)}
                        fmt_kwargs['id'] = groups[0] if groups else ''
                        link = self.url_template.format(**fmt_kwargs)
                        break

        if link_elem:
            if not link and href and not href.startswith('#') and not href.startswith('javascript:'):
                # jsessionid 제거 (예: path;jsessionid=xxx?params)
                if ';jsessionid=' in href:
                    href = href.split(';jsessionid=')[
                        0] + '?' + href.split('?', 1)[1] if '?' in href else href.split(';jsessionid=')[0]

                # 상대 경로면 절대 경로로 변환
                if href.startswith('/'):
                    link = self.base_url + href
                elif href.startswith('http'):
                    link = href
                else:
                    from urllib.parse import urljoin
                    link = urljoin(self.crawl_url, href)

        # 날짜 추출 (있으면)
        date_selector = self.selectors.get('date', '')
        if date_selector:
            date_elem = item.select_one(date_selector)
            date_text = date_elem.get_text(strip=True) if date_elem else ''
        else:
            date_text = item.get_text(strip=True)

        # 다행 구조: 다음 tr에서 날짜 추출 (date_next_row 설정 시)
        _next_row_announced = None
        _next_row_deadline = None
        if (self.date_next_row_selector or self.deadline_next_row_selector) and item.parent:
            _next_tr = item.parent.find_next_sibling('tr')
            if _next_tr:
                if self.date_next_row_selector:
                    _de = _next_tr.select_one(self.date_next_row_selector)
                    if _de:
                        _dt = _de.get_text(strip=True)
                        if '|' in _dt:
                            _dt = _dt.split('|')[-1].strip()
                        _next_row_announced = self._parse_date(_dt)
                if self.deadline_next_row_selector:
                    _dd = _next_tr.select_one(self.deadline_next_row_selector)
                    if _dd:
                        _dlt = _dd.get_text(strip=True)
                        if '|' in _dlt:
                            _dlt = _dlt.split('|')[-1].strip()
                        _next_row_deadline = self._parse_date(_dlt)

        # 날짜 범위 파싱 시도 (시작일~종료일)
        start_date, end_date = self._parse_date_range(date_text)

        # 날짜 범위 파싱 실패시 단일 날짜 파싱
        if start_date is None:
            announced_date = _next_row_announced or self._parse_date(date_text)
            if _next_row_deadline:
                deadline_date = _next_row_deadline
            elif self.detail_deadline:
                # detail_deadline이 설정된 경우 상세 페이지에서 날짜를 가져오므로 초기값은 None
                deadline_date = None
            else:
                deadline_date = None
        else:
            announced_date = _next_row_announced or start_date
            deadline_date = _next_row_deadline or end_date

        # 공고번호 생성 — title 기반 결정론적 해시
        tender_number = self._generate_tender_number(title)

        # 상세 페이지 공통 fetch (detail_price 또는 detail_deadline 사용 시)
        estimated_price = None
        detail_url = link if link else None
        _detail_soup = None
        if detail_url and (self.detail_price or self.detail_deadline):
            try:
                import requests as _req
                from bs4 import BeautifulSoup as _BS
                _headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                _r = _req.get(detail_url, headers=_headers, timeout=8, verify=self.verify_ssl)
                _detail_soup = _BS(_r.text, 'html.parser')
            except Exception:
                pass

        # 상세 페이지에서 가격 추출 (detail_price 설정된 경우)
        if self.detail_price and _detail_soup:
            try:
                _sel = self.detail_price.get('selector', '')
                _pat = self.detail_price.get('pattern', '')
                _target = _detail_soup.select_one(_sel) if _sel else _detail_soup.body
                if _target and _pat:
                    _text = _target.get_text(separator='\n')
                    _m = re.search(_pat, _text)
                    if _m:
                        _price_str = _m.group(1).replace(',', '').replace(' ', '')
                        estimated_price = int(_price_str)
            except Exception:
                pass

        # 상세 페이지에서 마감일 추출 (detail_deadline 설정된 경우)
        # 설정 형식:
        #   {"label": "공고마감일자"}       — <dt>라벨</dt><dd>날짜</dd> 구조
        #   {"td_label": "마감일시:"}      — <td>라벨</td><td>날짜</td> 구조 (NIA 등)
        if self.detail_deadline and _detail_soup:
            try:
                _label = self.detail_deadline.get('label', '')
                _td_label = self.detail_deadline.get('td_label', '')
                if _label:
                    for _dt in _detail_soup.find_all('dt'):
                        if _label in _dt.get_text(strip=True):
                            _dd = _dt.find_next_sibling('dd')
                            if _dd:
                                _dd_text = _dd.get_text(strip=True)
                                if _dd_text:
                                    _parsed = self._parse_date(_dd_text)
                                    if _parsed:
                                        deadline_date = _parsed
                            break
                elif _td_label:
                    for _td in _detail_soup.find_all('td'):
                        if _td_label in _td.get_text(strip=True):
                            _next_td = _td.find_next_sibling('td')
                            if _next_td:
                                _val = _next_td.get_text(strip=True)
                                if _val:
                                    _parsed = self._parse_date(_val)
                                    if _parsed:
                                        deadline_date = _parsed
                            break
            except Exception:
                pass

        # 공고 데이터 생성
        tender = {
            'title': title[:200],
            'agency': agency[:100],
            'tender_number': tender_number,
            'announced_date': announced_date,
            'deadline_date': deadline_date,
            'opening_date': None,
            'estimated_price': estimated_price,
            'bid_method': '일반경쟁입찰',
            'status': '결과공고' if (self.result_notice_pattern and re.search(self.result_notice_pattern, title)) else '일반',
            'is_sme_only': False,
            'source_site': self.site_name,
            'url': link if link else (self.crawl_url or self.base_url)
        }

        self.results.append(tender)

    def _generate_sample_data(self):
        """샘플 데이터 생성"""
        num_tenders = random.randint(3, 8)

        for i in range(num_tenders):
            tender_number = self._generate_tender_number()

            tender = {
                'title': f'{self.site_name} 공고 샘플 {i + 1}',
                'agency': self.site_name,
                'tender_number': tender_number,
                'announced_date': datetime.now() - timedelta(days=random.randint(1, 10)),
                'deadline_date': datetime.now() + timedelta(days=random.randint(5, 25)),
                'opening_date': datetime.now() + timedelta(days=random.randint(6, 26)),
                'estimated_price': None,
                'bid_method': '일반경쟁입찰',
                'status': '일반',
                'is_sme_only': random.choice([True, False]),
                'source_site': self.site_name,
                'url': f"{self.base_url}/detail?id={tender_number}"
            }

            self.results.append(tender)

    def _generate_tender_number(self, title=None):
        """공고번호 생성 — 제목 기반 결정론적 해시로 중복 방지"""
        site_prefix = ''.join([c for c in self.site_name if c.isalnum()])[:10] or 'SITE'
        if title:
            h = hashlib.md5(title.encode('utf-8', errors='ignore')).hexdigest()[:8].upper()
            return f"{site_prefix}-{h}"
        # 제목 없는 경우(샘플 데이터)만 랜덤
        return f"{site_prefix}-{datetime.now().year}-{random.randint(10000, 99999)}"

    def _sanitize_text(self, text):
        """
        텍스트 정리: 특수문자, replacement character 등을 제거
        """
        if not text:
            return text

        # Replacement character (�, U+FFFD) 제거
        text = text.replace('\ufffd', '')

        # 기타 제어 문자 제거 (탭, 개행 제외)
        text = ''.join(char for char in text if unicodedata.category(
            char)[0] != 'C' or char in '\t\n\r')

        # 연속된 공백을 하나로
        text = re.sub(r'\s+', ' ', text)

        # 앞뒤 공백 제거
        text = text.strip()

        return text

    def _parse_date(self, date_text):
        """날짜 문자열을 datetime으로 파싱. 파싱 실패 시 None 반환."""
        if not date_text:
            return None

        # 4자리 연도 패턴 우선 (YYYY-MM-DD, YYYY.MM.DD 등)
        date_patterns_4y = [
            r'(\d{4})-(\d{1,2})-(\d{1,2})',
            r'(\d{4})\.(\d{1,2})\.(\d{1,2})',
            r'(\d{4})/(\d{1,2})/(\d{1,2})',
        ]
        for pattern in date_patterns_4y:
            match = re.search(pattern, date_text)
            if match:
                try:
                    year, month, day = map(int, match.groups())
                    return datetime(year, month, day)
                except BaseException:
                    pass

        # 2자리 연도 패턴 (YY.MM.DD, YY-MM-DD) — 예: 26.05.22 → 2026-05-22
        date_patterns_2y = [
            r'(?<!\d)(\d{2})\.(\d{2})\.(\d{2})(?!\d)',
            r'(?<!\d)(\d{2})-(\d{2})-(\d{2})(?!\d)',
        ]
        for pattern in date_patterns_2y:
            match = re.search(pattern, date_text)
            if match:
                try:
                    yy, month, day = map(int, match.groups())
                    year = 2000 + yy
                    return datetime(year, month, day)
                except BaseException:
                    pass

        return None

    def _parse_date_range(self, text):
        """
        날짜 범위 문자열을 파싱하여 시작일과 종료일을 반환
        예: "신청기간 : 2025-12-15 16:27 ~ 2025-12-31 16:27"
        예: "2025.12.15 ~ 2025.12.31"

        Returns:
            tuple: (start_date, end_date) 또는 (None, None)
        """
        if not text:
            return None, None

        # 날짜 시간 범위 패턴: YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM
        pattern1 = (
            r'(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})\s*~\s*'
            r'(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})'
        )
        match = re.search(pattern1, text)
        if match:
            try:
                y1, m1, d1, h1, min1, y2, m2, d2, h2, min2 = map(
                    int, match.groups())
                start_date = datetime(y1, m1, d1, h1, min1)
                end_date = datetime(y2, m2, d2, h2, min2)
                return start_date, end_date
            except BaseException:
                pass

        # 날짜 범위 패턴 (시간 없이): YYYY-MM-DD ~ YYYY-MM-DD
        pattern2 = r'(\d{4})-(\d{1,2})-(\d{1,2})\s*~\s*(\d{4})-(\d{1,2})-(\d{1,2})'
        match = re.search(pattern2, text)
        if match:
            try:
                y1, m1, d1, y2, m2, d2 = map(int, match.groups())
                start_date = datetime(y1, m1, d1)
                end_date = datetime(y2, m2, d2)
                return start_date, end_date
            except BaseException:
                pass

        # 날짜 범위 패턴 (점 구분): YYYY.MM.DD ~ YYYY.MM.DD
        pattern3 = r'(\d{4})\.(\d{1,2})\.(\d{1,2})\s*~\s*(\d{4})\.(\d{1,2})\.(\d{1,2})'
        match = re.search(pattern3, text)
        if match:
            try:
                y1, m1, d1, y2, m2, d2 = map(int, match.groups())
                start_date = datetime(y1, m1, d1)
                end_date = datetime(y2, m2, d2)
                return start_date, end_date
            except BaseException:
                pass

        # 2자리 연도 범위 패턴: YY.MM.DD ~ YY.MM.DD (예: 26.05.22 ~ 26.06.05)
        pattern4 = r'(?<!\d)(\d{2})\.(\d{2})\.(\d{2})\s*~\s*(\d{2})\.(\d{2})\.(\d{2})(?!\d)'
        match = re.search(pattern4, text)
        if match:
            try:
                y1, m1, d1, y2, m2, d2 = map(int, match.groups())
                start_date = datetime(2000 + y1, m1, d1)
                end_date = datetime(2000 + y2, m2, d2)
                return start_date, end_date
            except BaseException:
                pass

        # 2자리 연도 단일 범위: YY-MM-DD ~ YY-MM-DD
        pattern5 = r'(?<!\d)(\d{2})-(\d{2})-(\d{2})\s*~\s*(\d{2})-(\d{2})-(\d{2})(?!\d)'
        match = re.search(pattern5, text)
        if match:
            try:
                y1, m1, d1, y2, m2, d2 = map(int, match.groups())
                start_date = datetime(2000 + y1, m1, d1)
                end_date = datetime(2000 + y2, m2, d2)
                return start_date, end_date
            except BaseException:
                pass

        return None, None
