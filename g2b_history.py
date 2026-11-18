"""
나라장터 과거 수행이력 조회 (개찰결과 · 낙찰결과 · 계약현황)

한 공고와 "같은 사업"으로 보이는 과거 공고를 나라장터 API 에서 찾아, 각 건이
낙찰·유찰·계약 중 어느 상태로 끝났는지 정리한다. 화면(routes/history.py)과는
분리된 순수 조회 로직이라 Flask 없이 단독으로 부를 수 있다.

조회 흐름 (lookup):
    1. build_queries      공고명에서 검색어를 최대 3개 만든다
    2. fetch_bid_results  검색어 × (개찰결과, 낙찰결과) × 최근 36개월을 월 단위로 조회
    3. decide_status      공고번호별로 낙찰 / 유찰 / 상세없음 을 정한다
    4. keep_same_project  수요기관이 같고 공고명 유사도 70% 이상인 것만 남긴다
    5. find_contract      유찰·상세없음 건은 계약현황에서 후속 계약을 찾는다

API 호출량: 2단계가 최대 검색어 3 × API 2 × 36개월 = 216회다. 같은 키를 정기 크롤러도
쓰므로 호출자는 결과를 캐시하고 동시에 한 건만 조회해야 한다 (routes/history.py 가 한다).
개찰·낙찰 API 는 조회 기간이 한 달을 넘으면 07 오류(입력범위값 초과)를 돌려준다.
"""

import calendar
import difflib
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

RESULT_BASE = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService'
CNTRCT_BASE = 'https://apis.data.go.kr/1230000/ao/CntrctInfoService'

HISTORY_MONTHS = 36            # 조회 기간: 최근 3년
MAX_QUERIES = 3                # 검색어 수 상한 (API 호출량 관리)
SIMILARITY_THRESHOLD = 0.70    # 같은 사업으로 보는 공고명 유사도

# 검색어로 쓰기에 너무 흔한 단어
_QUERY_STOPWORDS = {'사업', '용역', '운영', '관리', '지원', '추진', '수행'}
# 계약명 비교에서 무시하는 단어
_CONTRACT_STOPWORDS = {'및', '의', '을', '를', '이', '가', '에', '에서', '으로', '로',
                       '용역', '사업', '위탁', '운영', '관리', '지원', '추진', '수행'}
_NOTICE_PREFIX = re.compile(
    r'^\s*[\(\[（【]?\s*(입찰공고|재공고|입찰재공고|재입찰|긴급공고|수정공고)\s*[\)\]）】]?\s*'
)


class G2BApiError(Exception):
    """나라장터 API 가 오류 코드를 돌려준 경우"""

    def __init__(self, code, msg):
        super().__init__(f'API 오류 ({code}): {msg}')
        self.code = code
        self.msg = msg


# ════════════════════════════════════════════════════════════ 공고명 다루기

def normalize_title(s):
    """공고명에서 해마다 바뀌는 부분(연도·차수·'(재공고)' 같은 접두어)을 떼어낸다."""
    s = re.sub(r'\[[^\]]+\]', '', s)
    s = re.sub(r'「[^」]*」', '', s)  # 홑낫표(「」) 부제 제거 (예: 「메타버스...」)
    s = re.sub(
        r'\(\s*(?:입찰재공고|입찰공고|입찰|재공고|재입찰|긴급|사전규격공개|사전규격'
        r'|일반용역|추가공고|정정공고|공고|변경)\s*\)',
        '', s, flags=re.IGNORECASE,
    )
    s = re.sub(r'\d{4}년도?', '', s)
    s = re.sub(r"'\d{2}년도?", '', s)
    s = re.sub(r'\(\s*20\d{2}\s*\)', '', s)
    s = re.sub(r'\b(?:19|20)\d{2}\b', '', s)   # 단독 연도 숫자 제거 (2026 등)
    s = re.sub(r'제\s*\d+\s*회차?', '', s)
    s = re.sub(r'\d+\s*차년도', '', s)
    s = re.sub(r'\d+\s*차\b', '', s)
    s = re.sub(r'^\(?\s*(?:입찰재공고|입찰공고|재공고|재입찰)\s*\)?[\s-]*', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def name_similarity(a, b):
    """정규화된 공고명 간 유사도 (0.0~1.0)"""
    a2, b2 = normalize_title(a), normalize_title(b)
    if not a2 or not b2:
        return 0.0
    return difflib.SequenceMatcher(None, a2, b2).ratio()


def _trailing_hangul(word):
    """단어 끝부분의 연속 한글 어근만 추출 (영문/괄호 수식어 접두 제거)
    예: "SW미래채움" → "미래채움" / "(SW)미래채움" → "미래채움"
    """
    m = re.search(r'[가-힣]+$', word)
    return m.group(0) if m else ''


def build_queries(title):
    """
    공고명에서 API 검색어를 만든다. 반환: 검색어 목록 (첫 번째가 주 검색어, 최대 3개)

    나라장터 bidNtceNm 파라미터는 "완전한 연속 부분문자열"만 매칭한다
    (여러 단어를 AND 로 찾아주는 게 아니라, 제출한 문자열이 실제 공고명 안에
     그 순서·간격 그대로 붙어 있어야만 매칭됨 — 실측으로 확인).
    그래서 서로 떨어져 있는 단어(예: "인천"...."SW미래채움")를 이어붙여 검색하면
    원문과 글자가 안 맞아 항상 0건이 된다. → 여러 단어 조합 대신 단일 토큰만 쓴다.

    문제는 프로그램명 앞에 붙는 수식어가 해마다 바뀐다는 것:
      "SW미래채움" / "AI·SW미래채움" / "소프트웨어(SW)미래채움" / "인천SW미래채움"
    → 앞에 붙은 영문·괄호 수식어만 다르고 핵심 한글 어근("미래채움")은 그대로다.
    → 가장 긴 단어(주 검색어)와 함께, 단어의 "끝부분 연속 한글"만 뽑은 보조 검색어도
      같이 조회해서 수식어가 바뀌어도 걸리게 한다.
    """
    clean = normalize_title(title)
    # 상·하반기 / 학기 표현 제거: 매년 같은 사업이 "상반기"/"하반기"로 나뉘어 공고될 때
    # 검색어에 "하반기"가 들어가면 "상반기" 공고가 조회되지 않는다
    clean = re.sub(r'[상하]반기', '', clean)
    clean = re.sub(r'[1-4]학기', '', clean)
    clean = re.sub(r'[·/~\-+·]', ' ', clean)
    words = re.sub(r'\s+', ' ', clean).strip().split()

    meaningful = [w for w in words if w not in _QUERY_STOPWORDS] or words
    by_length = sorted(set(meaningful), key=len, reverse=True)

    main_query = (by_length[0] if by_length else '')[:60]   # 주 검색어: 가장 긴 단어(그대로)

    # 상위 후보 단어들에서 "수식어 뗀 한글 어근"을 뽑는다. 주 검색어로 뽑힌 단어가 아니어도 된다
    # (예: 주 검색어가 "교육페스티벌"이어도 "SW미래채움"에서 뽑은 "미래채움"을 따로 조회)
    cores = sorted(
        {
            core
            for w in by_length
            for core in [_trailing_hangul(w)]
            if core and core != w and len(core) >= 2
        },
        key=len, reverse=True,
    )
    # 어근 후보가 모자라면(수식어-핵심어 패턴이 없는 제목) 두 번째·세 번째로 긴 단어로 채운다
    fallback = [w[:60] for w in by_length[1:3]]

    queries = []
    for q in [main_query, *cores, *fallback]:
        if q and q not in queries:
            queries.append(q)
        if len(queries) >= MAX_QUERIES:
            break
    return queries


def agency_match(tender_agency, tender_demand_agency, item):
    """
    발주처(수요기관)가 같은지 본다.

    API 응답에 기관 정보가 없으면 True — 이름 유사도만으로 판단하게 둔다.
    개찰결과는 ntceInsttNm, 낙찰결과는 dminsttNm 에 기관명이 온다.
    """
    item_agencies = [
        (item.get('ntceInsttNm') or '').strip(),   # 개찰결과 공고기관
        (item.get('demandOrgNm') or '').strip(),   # (일부 API)
        (item.get('dminsttNm') or '').strip(),     # 낙찰결과 수요기관
    ]
    item_agencies = [a for a in item_agencies if a]
    if not item_agencies:
        return True

    def _same(a, b):
        if not a or not b:
            return False
        a, b = a.strip(), b.strip()
        if a == b:
            return True
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        return len(shorter) >= 4 and shorter in longer

    return any(_same(tender_agency, ag) or _same(tender_demand_agency, ag) for ag in item_agencies)


# ════════════════════════════════════════════════════════════ API 호출

def month_periods(now, months=HISTORY_MONTHS):
    """이번 달부터 거슬러 올라가는 월별 (시작, 끝) 목록. 형식은 API 의 YYYYMMDDHHMM."""
    periods = []
    for offset in range(months):
        y, m = now.year, now.month - offset
        while m <= 0:
            m += 12
            y -= 1
        last_day = calendar.monthrange(y, m)[1]
        periods.append((f'{y}{m:02d}010000', f'{y}{m:02d}{last_day:02d}2359'))
    return periods


def parse_items(data):
    """응답 본문에서 항목 목록을 꺼낸다. (items 가 list 로도, {'item': ...} 로도 온다)"""
    raw = data.get('response', {}).get('body', {}).get('items')
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        inner = raw.get('item', [])
        return [inner] if isinstance(inner, dict) else (inner or [])
    return []


def safe_get(url, params, timeout=25):
    """
    GET 요청 → (items, error_str). 예외를 내지 않는다.

    - 429(할당량 초과): 즉시 포기 — 재시도해도 한도는 회복되지 않는다
    - 502/503(일시 오류): 최대 2회 재시도
    """
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 429:
                return [], '할당량초과(429)'
            if r.status_code in (502, 503):
                time.sleep(2 + attempt * 2)
                continue
            if r.status_code != 200:
                return [], f'HTTP {r.status_code}'
            text = r.text.strip()
            if not text or text.startswith('<'):
                return [], None
            data = r.json()
            # 나라장터의 비표준 오류 응답 (기간 한도 초과 등은 HTTP 200 에 이 키로 온다)
            if 'nkoneps.com.response.ResponseError' in data:
                header = data['nkoneps.com.response.ResponseError'].get('header', {})
                return [], f"{header.get('resultCode', '')}:{header.get('resultMsg', '')}"
            header = data.get('response', {}).get('header', {})
            code = str(header.get('resultCode', '') or '')
            msg = str(header.get('resultMsg', '') or '')
            if code and code not in ('00', '000'):
                return [], f'{code}:{msg}'
            return parse_items(data), None
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            return [], str(e)
    return [], '재시도 초과'


def fetch_bid_results(service_key, queries, periods):
    """
    개찰결과·낙찰결과를 검색어 × API × 월 조합으로 조회한다.

    반환: (openg_by_no, award_by_no, errors) — 앞의 둘은 {공고번호: [레코드, ...]}

    조합을 전부 하나의 스레드풀에 한꺼번에 넣는다. 검색어마다 따로 순차 실행하면
    8분 넘게 걸려 프록시(Cloudflare) 타임아웃에 걸린다 (실측).
    """
    endpoints = [
        ('openg', 'getOpengResultListInfoServcPPSSrch'),
        ('award', 'getScsbidListSttusServcPPSSrch'),
    ]

    def fetch_one(kind, endpoint, begin, end, query):
        items, err = safe_get(
            f'{RESULT_BASE}/{endpoint}',
            {'ServiceKey': service_key, 'type': 'json',
             'inqryDiv': '1', 'inqryBgnDt': begin, 'inqryEndDt': end,
             'bidNtceNm': query, 'pageNo': '1', 'numOfRows': '100'},
        )
        return kind, items, err

    by_kind = {'openg': {}, 'award': {}}
    errors = []
    quota_exceeded = False
    with ThreadPoolExecutor(max_workers=30) as pool:
        futures = [
            pool.submit(fetch_one, kind, endpoint, begin, end, query)
            for query in queries
            for kind, endpoint in endpoints
            for begin, end in periods
        ]
        for fut in as_completed(futures):
            if fut.cancelled():
                continue
            kind, items, err = fut.result()
            if err:
                if '429' in str(err) or '할당량' in str(err):
                    if not quota_exceeded:
                        # 한도 초과가 확인되면 아직 시작하지 않은 요청을 취소한다.
                        # 그대로 두면 차단된 키로 남은 요청 수백 건이 모두 나간다.
                        for f in futures:
                            f.cancel()
                    quota_exceeded = True
                errors.append(f'{kind}: {err}')
                continue
            for item in items:
                bid_no = item.get('bidNtceNo', '')
                if bid_no:
                    by_kind[kind].setdefault(bid_no, []).append(item)
            if quota_exceeded:
                break
    return by_kind['openg'], by_kind['award'], errors


# ════════════════════════════════════════════════════════════ 상태 판정

def _first_bidder(corp_raw):
    """개찰결과의 opengCorpInfo('업체명^..^..^금액^투찰률') 에서 업체명·금액·투찰률을 꺼낸다."""
    if not corp_raw:
        return {}
    parts = corp_raw.split('^')
    return {
        'name':   (parts[0] if len(parts) > 0 else '').strip(),
        'amount': int(parts[3]) if len(parts) > 3 and parts[3].strip().isdigit() else 0,
        'rate':   (parts[4] if len(parts) > 4 else '').strip(),
    }


def _winner_from_openg(openg_list):
    """개찰결과 레코드들에서 낙찰자 이름을 찾는다. (낙찰 표시 → 낙찰자명 → 첫 레코드 순)"""
    for rec in openg_list:
        if rec.get('sucsfBidYn') == 'Y':
            bidder = _first_bidder(rec.get('opengCorpInfo', ''))
            if bidder.get('name'):
                return bidder['name']
    for rec in openg_list:
        if rec.get('bidwinnrNm', ''):
            return rec['bidwinnrNm']
    if openg_list:
        return _first_bidder(openg_list[0].get('opengCorpInfo', '')).get('name', '')
    return ''


def decide_status(openg_by_no, award_by_no):
    """
    공고번호별로 최종 상태를 정한다.

    반환: (items, needs_contract_check)
      item['_status']  '낙찰' | 'fail'(유찰) | '상세없음'
      유찰이면 item['_fail_type'] = 'no_bidder'(무응찰) | 'sole_bidder'(단독응찰) | 'unknown'
    needs_contract_check 는 유찰·상세없음 건으로, 계약현황에서 후속 계약을 찾아볼 대상이다.
    """
    items = []
    needs_contract_check = []

    for bid_no in set(openg_by_no) | set(award_by_no):
        award_list = award_by_no.get(bid_no, [])
        openg_list = openg_by_no.get(bid_no, [])

        # 낙찰결과 대표 레코드: 낙찰자명이 있는 것을 우선
        award = next((r for r in award_list if r.get('bidwinnrNm')), None)
        if award is None and award_list:
            award = award_list[0]
        openg = openg_list[0] if openg_list else None

        base = award or openg or {}
        notice_url = base.get('bidNtceUrl') or base.get('bidNtceDtlUrl') or ''
        price = base.get('presmptPrce', '') or base.get('asignBdgtAmt', '')
        bidder_count = int(openg.get('prtcptCnum') or 0) if openg else 0

        if award:
            item = dict(award)
            item['_status'] = '낙찰'
            item['_presmptPrce'] = price
            winner = award.get('bidwinnrNm', '') or _winner_from_openg(openg_list)
            first_at_opening = _winner_from_openg(openg_list)   # 개찰 시 1순위(sucsfBidYn=Y)
            item['_winner_nm'] = winner
            item['_prtcpt_cnt'] = bidder_count
            # 개찰 1순위와 실제 낙찰자가 다를 때 (적격심사 탈락 후 차순위 낙찰)
            if first_at_opening and winner and first_at_opening != winner:
                item['_openg_candidate'] = first_at_opening
            if not item.get('bidNtceUrl'):
                item['bidNtceUrl'] = notice_url

        elif openg and openg.get('progrsDivCdNm', '') == '유찰':
            item = dict(openg)
            item['_status'] = 'fail'
            item['_fail_type'] = (
                'no_bidder' if bidder_count == 0 else
                'sole_bidder' if bidder_count == 1 else
                'unknown'
            )
            item['_presmptPrce'] = price
            item['_prtcpt_cnt'] = bidder_count
            if not item.get('bidNtceUrl'):
                item['bidNtceUrl'] = notice_url
            needs_contract_check.append(item)

        elif openg:
            item = dict(openg)
            item['_status'] = '낙찰'
            item['_presmptPrce'] = price
            item['_winner_nm'] = _winner_from_openg(openg_list)
            item['_prtcpt_cnt'] = bidder_count
            if not item.get('bidNtceUrl'):
                item['bidNtceUrl'] = notice_url

        else:
            # 공고번호는 있는데 개찰·낙찰 레코드가 모두 비어 있는 경우
            item = dict(base)
            item['bidNtceNo'] = bid_no
            item['_status'] = '상세없음'
            item['_presmptPrce'] = price
            item['_prtcpt_cnt'] = 0
            needs_contract_check.append(item)

        items.append(item)
    return items, needs_contract_check


# ════════════════════════════════════════════════════════════ 계약현황

def _contract_winner(corp_raw):
    """계약현황의 corpList('[..^..^..^업체명^..]') 에서 업체명을 꺼낸다."""
    if not corp_raw:
        return ''
    try:
        parts = corp_raw.strip('[]').split('^')
        return parts[3] if len(parts) > 3 else ''
    except Exception:
        return ''


def _contract_name_match(notice_name, contract_name):
    """공고명과 계약명이 같은 사업을 가리키는지 — 의미 있는 단어가 겹치는 수로 본다."""
    def keywords(name):
        return {w for w in name.split() if len(w) >= 2 and w not in _CONTRACT_STOPWORDS}
    b, c = keywords(notice_name), keywords(contract_name)
    if not b or not c:
        return False
    common = len(b & c)
    # 고유명사 1개라도 일치하면 매칭 (짧은 공고명 대응)
    return common >= 1 if len(b) <= 2 else common >= min(2, len(b))


def find_contract(service_key, item, now):
    """
    유찰·상세없음 공고의 후속 계약을 계약현황에서 찾는다. (API 1회)

    반환: {'winner', 'amount', 'date'} 또는 None
    """
    notice_name = item.get('bidNtceNm', '')
    if not notice_name:
        return None
    clean_name = _NOTICE_PREFIX.sub('', notice_name).strip()
    words = clean_name.split()
    keyword = ' '.join(words[:4]) if len(words) >= 4 else clean_name
    if len(keyword) < 4:
        return None

    today = now.strftime('%Y%m%d')
    raw_date = (item.get('bidNtceDt') or item.get('opengDt') or item.get('rlOpengDt') or '')
    search_from = re.sub(r'[^0-9]', '', raw_date)[:8] if raw_date else ''
    if not search_from or search_from > today:
        search_from = str(now.year - 3) + '0101'      # 날짜가 없으면 최근 3년
    try:
        # 낙찰 후 계약까지 최대 2년이 걸릴 수 있어 2년 범위로 찾는다
        search_to = min(str(int(search_from[:4]) + 2) + search_from[4:], today)
    except Exception:
        search_to = today

    contracts, _ = safe_get(
        f'{CNTRCT_BASE}/getCntrctInfoListServcPPSSrch',
        {'ServiceKey': service_key, 'type': 'json',
         'inqryDiv': '1', 'inqryBgnDate': search_from, 'inqryEndDate': search_to,
         'cntrctNm': keyword, 'pageNo': '1', 'numOfRows': '10'},
        timeout=20,
    )
    for c in contracts:
        if not _contract_name_match(notice_name, c.get('cntrctNm', '')):
            continue
        winner = _contract_winner(c.get('corpList', ''))
        amount = c.get('thtmCntrctAmt', '') or c.get('totCntrctAmt', '')
        if winner or amount:
            return {'winner': winner, 'amount': amount, 'date': c.get('cntrctDate', '')}
    return None


# ════════════════════════════════════════════════════════════ 전체 흐름

def lookup(title, agency, demand_agency, service_key):
    """
    한 공고의 과거 수행이력을 조회한다.

    반환: {'items', 'query', 'queries', 'original_title', 'errors', 'pblnc_api_ok'}
      items 의 각 건에는 API 원본 필드에 더해 아래가 붙는다.
        _status      '낙찰' | 'fail' | '계약' | '상세없음'
        _similarity  현재 공고명과의 유사도
        _winner_nm, _prtcpt_cnt, _presmptPrce, _fail_type, _openg_candidate, _followup_contract
    """
    title = title or ''
    agency = agency or ''
    demand_agency = demand_agency or ''
    now = datetime.now()

    queries = build_queries(title)
    openg_by_no, award_by_no, errors = fetch_bid_results(service_key, queries, month_periods(now))
    items, needs_contract_check = decide_status(openg_by_no, award_by_no)

    # 같은 사업만 남긴다: 수요기관이 같고 정규화 공고명 유사도가 기준 이상.
    # (검색은 공고명의 한 단어로 하므로 관련 없는 결과가 섞여 온다)
    title_norm = normalize_title(title)

    def same_project(item):
        return (name_similarity(title_norm, item.get('bidNtceNm', '')) >= SIMILARITY_THRESHOLD
                and agency_match(agency, demand_agency, item))

    # 계약현황 조회는 반드시 이 필터 뒤에 한다. 넓은 검색어("미래채움" 같은 일반 어근)는
    # 전국의 무관한 후보를 많이 끌어오는데, 계약현황은 동시 3개로만 도는 무거운 호출이라
    # 걸러질 후보까지 조회하면 3분 넘게 걸린다 (실측).
    targets = [it for it in needs_contract_check if same_project(it)]
    if targets:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(find_contract, service_key, it, now): it for it in targets}
            for fut in as_completed(futures):
                contract = fut.result()
                if contract:
                    futures[fut]['_status'] = '계약'
                    futures[fut]['_followup_contract'] = contract

    kept = []
    for item in items:
        if same_project(item):
            item['_similarity'] = round(name_similarity(title_norm, item.get('bidNtceNm', '')), 2)
            kept.append(item)

    # 개찰일/공고일 최신순
    kept.sort(key=lambda x: (x.get('rlOpengDt') or x.get('opengDt') or x.get('fnlSucsfDate')
                             or x.get('bidNtceDt') or ''), reverse=True)

    return {
        'items':          kept,
        'query':          queries[0] if queries else '',
        'queries':        queries,
        'original_title': title,
        'errors':         list(set(errors))[:5],
        'pblnc_api_ok':   True,
    }


# ════════════════════════════════════════════════════════════ 투찰업체 목록

# 서비스 주소가 바뀐 적이 있어 두 곳을 차례로 시도한다
_BIDDER_ENDPOINTS = [
    'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpnBidResultList',
    'http://apis.data.go.kr/1230000/BidResultService/getOpnBidResultList',
]


def _first_value(record, *keys, default=''):
    """API 버전에 따라 필드명이 달라서, 후보 키 중 값이 있는 첫 번째를 쓴다."""
    for k in keys:
        if record.get(k):
            return record[k]
    return default


def fetch_bidders(service_key, bid_no, bid_seq):
    """
    한 입찰 공고의 투찰업체 목록 (개찰결과목록조회 getOpnBidResultList).

    반환: {'bidders': [...], 'winner_nm': str, 'count': int} — 순위순 정렬
    API 가 오류 코드를 주면 G2BApiError.
    """
    params = {'ServiceKey': service_key, 'type': 'json', 'bidNtceNo': bid_no,
              'bidNtceOrd': bid_seq, 'pageNo': '1', 'numOfRows': '200'}
    records = None
    code = msg = ''
    for url in _BIDDER_ENDPOINTS:
        data = requests.get(url, params=params, timeout=15).json()
        header = data.get('response', {}).get('header', {})
        code = str(header.get('resultCode', '') or data.get('resultCode', ''))
        msg = header.get('resultMsg', '') or data.get('resultMsg', '')
        if code and code != '00':
            continue
        raw = data.get('response', {}).get('body', {}).get('items')
        inner = raw.get('item', []) if isinstance(raw, dict) else raw
        records = [inner] if isinstance(inner, dict) else (inner if isinstance(inner, list) else [])
        break
    if records is None:
        raise G2BApiError(code, msg)

    bidders = []
    winner_nm = ''
    for rec in records:
        name = _first_value(rec, 'corpNm', 'bidcorpNm', 'corNm').strip()
        if not name:
            continue
        try:
            amount = int(str(_first_value(rec, 'bidprcAmt', 'bidAmt', 'bidprcPrice', default=0)).replace(',', ''))
        except (ValueError, TypeError):
            amount = 0
        is_winner = str(_first_value(rec, 'sucsfBidYn', 'bidwinnrYn')).upper() == 'Y'
        if is_winner and not winner_nm:
            winner_nm = name
        bidders.append({
            'name': name,
            'rank': _first_value(rec, 'rnk', 'bidprcRank', 'rank'),
            'bizNo': _first_value(rec, 'bizno', 'corpRegNo', 'brno').strip(),
            'amount': amount,
            'rate': str(_first_value(rec, 'bidprcRate', 'bidRate')).strip(),
            'is_winner': is_winner,
        })

    def _rank(b):
        try:
            return int(b['rank'])
        except (ValueError, TypeError):
            return 9999
    bidders.sort(key=_rank)
    return {'bidders': bidders, 'winner_nm': winner_nm, 'count': len(bidders)}
