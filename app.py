from email_notifier import email_notifier, EmailNotifier
from settings_manager import settings_manager
from excel_exporter import excel_exporter
from data_manager import DataManager
from flask import Flask, render_template, request, jsonify, make_response
from flask_cors import CORS
from config import Config
from database import db, init_db, Tender, Filter, CrawlLog, Bookmark, TenderAnalysis
from datetime import datetime, timedelta
import json
import re
import threading

# ── 채용/참여모집 제외 패턴 ──────────────────────────────────────────────────
# 이 패턴이 제목에 포함되면 우리가 수행할 용역이 아님 → 점수 0 처리
_EXCLUDE_PATTERNS = [
    '채용 공고', '채용공고', '채용 모집', '채용안내',
    '참여업소 모집', '참여자 모집', '참여기업 모집', '참여업체 모집',
    '참여 모집', '입찰참가자격 사전심사',
]

# ── 사업 유형 분류 (복합 키워드 기반, 높은 우선순위 순) ──────────────────────
# 단일 키워드 대신 의미 있는 복합 구문만 사용 → 오분류 방지
# (유형명, 점수, 복합_패턴_목록)
_BUSINESS_TYPE_CATEGORIES = [
    ('교육운영', 50, [
        # 교육/연수/훈련 + 운영/위탁/수탁 조합
        '교육 운영', '교육운영', '교육 위탁', '교육위탁',
        '연수 운영', '연수운영', '훈련 운영', '훈련운영',
        # 프로그램·과정 운영
        '교육프로그램', '교육 프로그램', '교육과정 운영',
        '강의 운영', '강좌 운영', '직무교육 운영', '직무 교육 운영',
        '아카데미 운영', '캠프 운영',
        # 역량강화 운영
        '역량강화 프로그램', '역량강화교육', '역량강화 교육',
        # 교육 지원·수행 용역
        '교육 지원 용역', '교육지원 용역', '교육지원용역',
        '교육 용역', '교육용역', '연수 용역', '연수용역',
        '교육 수행', '훈련 수행', '연수 수행',
        '위탁교육', '교육 위탁운영',
        # 국외·해외 연수 운영
        '국외연수', '해외연수', '해외교육',
        # 교육 운영기관/수행기관 선정 (우리가 운영기관으로 참여하는 경우)
        '교육 운영기관', '교육 위탁기관', '교육 수행기관',
        '연수 기관 선정', '교육운영 위탁',
    ]),
    ('시설운영', 40, [
        # 센터/시설/공간 + 운영/위탁
        '센터 운영', '센터운영', '시설 운영', '시설운영',
        '공간 운영', '공간운영', '거점 운영', '거점운영',
        '시설물 관리', '시설물관리',
        '센터 위탁', '시설 위탁', '공간 위탁',
        '센터 수탁', '시설 수탁', '센터 위탁운영',
        '운영 위탁', '위탁 운영',
        # 지원사업 위탁 운영 (교육/행사 아닌 일반 사업 운영)
        '지원사업 운영', '사업 위탁', '프로그램 위탁',
    ]),
    ('콘텐츠개발', 35, [
        # 콘텐츠/교재/커리큘럼 개발·제작
        '콘텐츠 개발', '콘텐츠개발',
        '교재 개발', '교재개발',
        '교육 콘텐츠', '교육콘텐츠',
        '커리큘럼 개발', '커리큘럼개발',
        '교육과정 개발', '훈련과정 개발',
        '학습 콘텐츠', '학습콘텐츠',
        '영상 제작', '영상제작',
        '강의 콘텐츠', '이러닝 콘텐츠', '온라인 콘텐츠',
        '교육자료 개발', '교육 자료 개발',
        '동영상 강의 제작',
    ]),
    ('행사운영', 30, [
        # 행사/이벤트 + 운영/개최/진행
        '행사 운영', '행사운영', '행사 기획', '행사기획',
        '행사 진행', '행사진행', '행사 개최', '행사개최', '행사 주관',
        '박람회 운영', '박람회 개최',
        '포럼 운영', '포럼 개최',
        '세미나 운영', '세미나 개최',
        '설명회 운영', '설명회 개최',
        '발표회 운영', '컨퍼런스 운영', '컨퍼런스 개최',
        '심포지엄 운영', '심포지엄 개최',
        '워크숍 운영', '워크샵 운영',
        '토론회 운영', '토론회 개최',
        '경진대회 운영', '대회 운영', '대회 개최',
    ]),
    ('컨설팅', 20, [
        # 복합 패턴 우선
        '컨설팅 용역', '컨설팅용역', '컨설팅 지원', '컨설팅지원',
        '자문 용역', '자문용역',
        '진단 컨설팅', '진단컨설팅',
        '멘토링 지원', '멘토링지원', '코칭 프로그램',
        # 단독 용어 (충분히 구체적)
        '컨설팅', '자문', '멘토링', '코칭',
    ]),
    ('연구용역', 10, [
        # 연구 관련 복합 패턴
        '연구용역', '연구 용역',
        '학술연구', '학술 연구',
        '조사연구', '조사 연구',
        '실태조사', '실태 조사',
        '타당성 조사', '타당성조사',
        '수요조사', '수요 조사',
        '기초연구', '정책연구', '기획연구',
        '학술 용역', '연구 보고서',
    ]),
]

# ── 핵심 키워드 (2배 가중치) ─────────────────────────────────────────────────
# 등장만 해도 강한 관련성을 시사하는 키워드 → 일반 키워드(1배) 대비 2배
_CORE_KEYWORDS = {
    # 디지털/AI 기술
    'AI', 'AX', '인공지능', '4차산업', 'IOT', 'IT', '데이터',
    # 교육/훈련 핵심 (우리 주력 서비스)
    '교육', '역량강화', '직무', '트레이닝',
    # 주요 대상 사업체
    '중소기업', '소상공인', '소공인',
    # 주요 대상 연령층
    '장년', '노인', '실버', '노년',
    # 핵심 이슈/산업
    'ESG', '바이오', '헬스',
}

# ── 키워드 시너지 조합 (두 그룹이 함께 등장시 보너스) ────────────────────────
# (그룹A, 그룹B, 점수) → 최고 조합 1개만 적용 (누적 없음)
_SYNERGY_COMBOS = [
    # ★ AI/디지털 + 교육 = 핵심 사업 조합 (최고점)
    ({'AI', 'AX', '인공지능', '4차산업', 'IOT', 'IT', '데이터'},
     {'교육', '트레이닝', '역량강화', '직무'}, 15),
    # ★ 중기/소공인 + 교육/컨설팅
    ({'중소기업', '소상공인', '소공인'},
     {'교육', '트레이닝', '역량강화', '직무', '컨설팅'}, 12),
    # ★ 시니어(장년/노인) + 교육/일자리
    ({'장년', '노인', '실버', '노년'},
     {'교육', '트레이닝', '역량강화', '직무', '일자리'}, 10),
    # ◆ 청년 + 디지털/AI
    ({'청년'},
     {'AI', 'AX', '4차산업', 'IOT', 'IT', '데이터', 'ESG'}, 8),
    # ◆ 전환/미래 + 교육
    ({'전환', 'AX', '미래'},
     {'교육', '역량강화', '직무', '트레이닝'}, 7),
    # ◇ 취업/일자리 + 교육/직무
    ({'일자리', '직업', '진로', '채용'},
     {'교육', '트레이닝', '직무', '역량강화'}, 5),
]

# 한국 행정구역명 (점수 계산 시 제목에서 제거)
_KOREAN_LOCATIONS = sorted([
    '서울특별시', '부산광역시', '대구광역시', '인천광역시', '광주광역시',
    '대전광역시', '울산광역시', '세종특별자치시', '경기도', '강원특별자치도',
    '강원도', '충청북도', '충청남도', '전라북도', '전북특별자치도',
    '전라남도', '경상북도', '경상남도', '제주특별자치도', '제주도',
    '서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
    '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
], key=len, reverse=True)

app = Flask(__name__)
app.config.from_object(Config)

# CORS 설정
CORS(app)

# 데이터베이스 초기화
init_db(app)

# 스케줄러 초기화 (필요할 때만 import)
crawler_scheduler = None

# Phase 3 모듈 초기화

data_manager = DataManager(app)


# 공휴일 데이터 (2026년 기준)
HOLIDAYS_2026 = [
    datetime(2026, 1, 1).date(),   # 신정
    datetime(2026, 1, 28).date(),  # 설날 연휴
    datetime(2026, 1, 29).date(),  # 설날
    datetime(2026, 1, 30).date(),  # 설날 연휴
    datetime(2026, 3, 1).date(),   # 삼일절
    datetime(2026, 4, 5).date(),   # 식목일
    datetime(2026, 5, 5).date(),   # 어린이날
    datetime(2026, 5, 24).date(),  # 부처님오신날
    datetime(2026, 6, 6).date(),   # 현충일
    datetime(2026, 8, 15).date(),  # 광복절
    datetime(2026, 9, 26).date(),  # 추석 연휴
    datetime(2026, 9, 27).date(),  # 추석
    datetime(2026, 9, 28).date(),  # 추석 연휴
    datetime(2026, 10, 3).date(),  # 개천절
    datetime(2026, 10, 9).date(),  # 한글날
    datetime(2026, 12, 25).date(),  # 크리스마스
]


def is_workday(date):
    """영업일인지 확인 (주말 및 공휴일 제외)"""
    if date.weekday() >= 5:  # 토요일(5), 일요일(6)
        return False
    if date.date() in HOLIDAYS_2026:
        return False
    return True


def get_last_workday(from_date=None):
    """
    마지막 영업일 가져오기
    from_date 기준으로 바로 이전 영업일을 반환
    """
    if from_date is None:
        from_date = datetime.now()

    # 전날부터 시작하여 영업일 찾기
    current = from_date - timedelta(days=1)

    # 최대 10일 전까지만 검색 (긴 연휴 대비)
    for _ in range(10):
        if is_workday(current):
            return current.replace(hour=0, minute=0, second=0, microsecond=0)
        current -= timedelta(days=1)

    # 찾지 못한 경우 7일 전 반환 (fallback)
    return (
        from_date -
        timedelta(
            days=7)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0)


# 관심 키워드 로드 함수
def load_interest_keywords():
    """설정 파일에서 관심 키워드 로드 (쉼표 구분 문자열도 개별 키워드로 분리)"""
    try:
        with open('data/settings.json', 'r', encoding='utf-8') as f:
            settings = json.load(f)
            raw = settings.get('user_preferences', {}).get('interest_keywords', [])
            keywords = []
            for item in raw:
                for kw in str(item).split(','):
                    kw = kw.strip()
                    if kw:
                        keywords.append(kw)
            return keywords
    except BaseException:
        return []


def load_exclude_keywords():
    """설정 파일에서 제외 키워드 로드"""
    try:
        with open('data/settings.json', 'r', encoding='utf-8') as f:
            settings = json.load(f)
            return settings.get(
                'user_preferences', {}).get(
                'exclude_keywords', [])
    except BaseException:
        return []


def load_budget_range():
    """설정 파일에서 금액 범위 로드 (단위: 원). min/max 중 None이면 제한 없음"""
    try:
        with open('data/settings.json', 'r', encoding='utf-8') as f:
            settings = json.load(f)
            return settings.get('user_preferences', {}).get('budget_range', {})
    except BaseException:
        return {}


def _clean_title_for_scoring(title, agency=None):
    """
    점수 계산용 제목 정제
    - 발주처명 구성 단어 제거
    - 한국 행정구역명 제거 (OO시/구/군/읍/면 패턴 포함)
    """
    cleaned = title

    # 발주처명 단어 제거 (괄호 제거 후 2글자 이상 단어)
    if agency:
        agency_words = re.sub(r'[()（）\[\]【】]', ' ', agency).split()
        for word in agency_words:
            if len(word) >= 2:
                cleaned = cleaned.replace(word, ' ')

    # 광역시도/약칭 제거
    for loc in _KOREAN_LOCATIONS:
        cleaned = cleaned.replace(loc, ' ')

    # OO시/구/군/읍/면 패턴 제거 (2~4글자 한글 + 행정구역 단위)
    cleaned = re.sub(r'[가-힣]{1,4}[시구군읍면](?=[\s\W]|$)', ' ', cleaned)

    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned if cleaned else title


def _keyword_match_weight(keyword, title):
    """
    키워드가 제목 내 어느 위치에 등장하는지에 따른 경계 가중치

    1.0  = 완전 독립 단어  (예: "AI", "교육")
    0.75 = 단어 앞부분    (예: "교육운영" → 교육, "AI기반" → AI)
    0.6  = 단어 뒷부분    (예: "중장년" → 장년, "취업지원센터" → 센터)
    0.5  = 단어 중간 포함 (예: "취업지원센터" → 지원)
    → 복합어 내 포함된 키워드는 낮은 가중치로 오분류 방지
    """
    kw = keyword.lower()
    for token in re.split(r'\s+', title.lower()):
        if token == kw:
            return 1.0
        if token.startswith(kw):
            return 0.75
        if token.endswith(kw):
            return 0.6
    return 0.5  # 복합어 중간 (예: 취업지원센터 → 지원)


def _synergy_bonus(title_lower):
    """
    키워드 조합 시너지 점수 (최대 15점)
    _SYNERGY_COMBOS 중 가장 높은 조합 1개만 적용 (누적 없음)
    → 단독 키워드 수보다 '어떤 조합이 함께 등장하는지'가 중요
    """
    best = 0
    for group_a, group_b, pts in _SYNERGY_COMBOS:
        if (any(k.lower() in title_lower for k in group_a) and
                any(k.lower() in title_lower for k in group_b)):
            best = max(best, pts)
    return best


def _detect_business_type(title):
    """복합 패턴 기반 사업 유형 감지 → (유형명, 원점수) 반환"""
    for type_name, score, patterns in _BUSINESS_TYPE_CATEGORIES:
        for pattern in patterns:
            if pattern in title:
                return type_name, score
    return '기타', 0


def _priority_score(tender):
    """
    시간·규모 우선순위 점수 (최대 10.0점)

    ① 마감 긴급도 (0-7점) — 전체 공고 유형에 적용
       - 0-6일:  7.0 → 4.0  (0.5점/일, 긴급)
       - 7-14일: 3.5 → 1.75 (0.25점/일, 주의)
       - 15일+:  1.7 → 0.5  (0.05점/일, 여유)
       - 마감 미정: 3.5점 (중간값)
       - 마감 경과: 0.0점

    ② 사업 규모 보너스 (0-3점) — 사전규격 동점 차별화에 핵심
       10억+ → 3.0 / 5억+ → 2.5 / 1억+ → 2.0 /
       5천만+ → 1.5 / 1천만+ → 1.0 / 그 이하 → 0.5
    """
    # ① 긴급도
    days_left = None
    if tender.deadline_date:
        days_left = (tender.deadline_date - datetime.now()).days

    if days_left is None:
        urgency = 3.5
    elif days_left < 0:
        urgency = 0.0
    else:
        d = int(days_left)
        if d <= 6:
            urgency = 7.0 - d * 0.5                        # 7.0 → 4.0
        elif d <= 14:
            urgency = 3.5 - (d - 7) * 0.25                 # 3.5 → 1.75
        else:
            urgency = max(0.5, 1.75 - (d - 14) * 0.05)    # 1.7 → 0.5

    # ② 규모 보너스
    price = tender.estimated_price or 0
    if price >= 1_000_000_000:
        price_bonus = 3.0
    elif price >= 500_000_000:
        price_bonus = 2.5
    elif price >= 100_000_000:
        price_bonus = 2.0
    elif price >= 50_000_000:
        price_bonus = 1.5
    elif price >= 10_000_000:
        price_bonus = 1.0
    elif price > 0:
        price_bonus = 0.5
    else:
        price_bonus = 0.0

    return min(10.0, round(urgency + price_bonus, 2))


def _score_and_type(tender, include_keywords):
    """
    적합도 점수(소수점 1자리, 최대 100.0점) + 사업 유형 계산

    ── 키워드 점수 45점 (A+B+C 혼합) ──────────────────────────────────────
    A: 밀도 보정 — 제목 의미단어 수 기반 패널티 (긴 제목일수록 낮아짐)
       density_factor = 1 / (단어수 ^ 0.25)
    B: 핵심 키워드 2배 가중치 — AI, 교육, 중소기업, 장년 등
       복합어 내 등장은 0.5~0.75 감점 (취업지원센터→지원 = 0.5)
    C: 시너지 조합 보너스 — 고정 점수, 제목 길이 무관
       (AI+교육=15점), (중소기업+교육=12점), (장년+교육=10점) 등 최대 15점

    A×B 기반 점수 (최대 30점) + C 시너지 보너스 (최대 15점) = 최대 45점

    ── 사업 유형 점수 45점 ───────────────────────────────────────────────
    교육운영(45) > 시설운영(36) > 콘텐츠개발(31.5) > 행사운영(27) >
    컨설팅(18) > 연구용역(9) > 기타(0)  * 복합 패턴 기반, 오분류 방지

    ── 우선순위 점수 10점 ───────────────────────────────────────────────
    마감 긴급도(0-7점) + 사업 규모 보너스(0-3점) → 동점 최소화 (소수점 표시)
    """
    if not include_keywords or not tender.title:
        return 0, '기타'

    cleaned = _clean_title_for_scoring(tender.title, tender.agency)

    # 채용·참여모집 공고 제외
    for pattern in _EXCLUDE_PATTERNS:
        if pattern in cleaned:
            return 0, '기타'

    cleaned_lower = cleaned.lower()

    # ── A×B: 가중치 적용 키워드 밀도 점수 (최대 30점) ──────────────────
    matched = []
    weighted_sum = 0.0
    for kw in include_keywords:
        if kw.lower() not in cleaned_lower:
            continue
        matched.append(kw)
        core_mult = 2.0 if kw in _CORE_KEYWORDS else 1.0   # B: 핵심 2배
        boundary_w = _keyword_match_weight(kw, cleaned)     # A: 경계 가중치
        weighted_sum += core_mult * boundary_w

    if not matched:
        return 0, '기타'

    # A: 제목 길이 밀도 보정 (의미 단어 수 기준, 최소 4단어로 고정)
    word_count = max(4, len([w for w in cleaned.split() if len(w) >= 2]))
    density_factor = 1.0 / (word_count ** 0.25)
    ab_score = min(weighted_sum * density_factor * 10, 30)

    # ── C: 시너지 조합 보너스 (최대 15점, 길이와 무관한 고정 점수) ──────
    syn_score = _synergy_bonus(cleaned_lower)

    keyword_score = min(ab_score + syn_score, 45)

    # ── 사업 유형 점수 ───────────────────────────────────────────────────
    type_name, raw_type_score = _detect_business_type(cleaned)
    type_score = raw_type_score * 0.9   # 50→45, 40→36, 35→31.5, 30→27, 20→18, 10→9

    # ── 우선순위 점수 ────────────────────────────────────────────────────
    priority = _priority_score(tender)

    total = min(100.0, round(keyword_score + type_score + priority, 1))
    return total, type_name


def calculate_relevance_score(tender, include_keywords):
    return _score_and_type(tender, include_keywords)[0]


def smart_sort_tenders_by_keyword_count(tenders, include_keywords):
    """
    관련성 점수 기반 정렬
    1순위: 관련성 점수 (높을수록)
    2순위: 공고일 (최신순)
    3순위: 금액 (높을수록)
    """
    def sort_key(tender):
        score = calculate_relevance_score(tender, include_keywords)
        if tender.announced_date:
            try:
                date_ord = tender.announced_date.toordinal()
            except Exception:
                date_ord = 0
        else:
            date_ord = 0
        price = tender.estimated_price if tender.estimated_price else 0
        return (-score, -date_ord, -price)

    return sorted(tenders, key=sort_key)


# 스마트 정렬 함수
def smart_sort_tenders(tenders, interest_keywords=None):
    """
    공고를 스마트하게 정렬
    1. 마감일이 지나지 않은 공고 우선
    2. 관심 키워드 매칭 점수 높은 순
    3. 공고일 최신순
    """
    if interest_keywords is None:
        interest_keywords = load_interest_keywords()

    now = datetime.now()

    def sort_key(tender):
        # 1. 마감일 체크 (지나지 않은 공고 = 0, 지난 공고 = 1)
        is_expired = 1 if (
            tender.deadline_date and tender.deadline_date < now) else 0

        # 2. 관심 키워드 매칭 점수 (높을수록 우선)
        keyword_score = 0
        if interest_keywords and tender.title:
            title_lower = tender.title.lower()
            for keyword in interest_keywords:
                if keyword.lower() in title_lower:
                    keyword_score += 1
        keyword_score = -keyword_score  # 내림차순을 위해 음수로

        # 3. 공고일 (최신순) — timestamp() 대신 ordinal 사용 (Windows 호환, 연도 3000+ 안전)
        if tender.announced_date:
            try:
                date_ord = tender.announced_date.toordinal()
            except Exception:
                date_ord = 0
        else:
            date_ord = 0

        return (is_expired, keyword_score, -date_ord)

    return sorted(tenders, key=sort_key)


# ============= 템플릿 필터 =============

@app.template_filter('format_price')
def format_price_filter(price):
    """가격 포맷 필터"""
    if not price:
        return '미정'

    if price >= 100000000:
        return f'{price / 100000000:.1f}억원'
    elif price >= 10000000:
        return f'{price / 10000000:.1f}천만원'
    elif price >= 10000:
        return f'{price / 10000:.0f}만원'
    else:
        return f'{price:,}원'


# ============= 페이지 라우트 =============

@app.route('/test')
def test():
    """테스트 엔드포인트"""
    return 'Server is working!'


@app.route('/')
def index():
    """메인 대시보드"""
    return render_template('dashboard.html')


@app.route('/search')
def search_page():
    """검색 페이지"""
    return render_template('search.html')


@app.route('/filters')
def filters_page():
    """필터 관리 페이지"""
    return render_template('filters.html')


@app.route('/settings')
def settings_page():
    """설정 페이지"""
    return render_template('settings.html')


@app.route('/bookmarks')
def bookmarks_page():
    """관심공고 페이지"""
    return render_template('bookmarks.html')


@app.route('/logs')
def logs_page():
    """로그 페이지"""
    return render_template('logs.html')


@app.route('/tender/<int:tender_id>')
def tender_detail(tender_id):
    """공고 상세 페이지"""
    tender = Tender.query.get_or_404(tender_id)

    # 마감까지 남은 일수 계산
    days_left = 0
    if tender.deadline_date:
        delta = tender.deadline_date - datetime.now()
        days_left = delta.days

    # 일반입찰이고 마감일이 지났으면 is_expired=True (사전규격은 항상 False)
    is_expired = (tender.status != '사전규격') and (days_left < 0)

    return render_template('detail.html', tender=tender, days_left=days_left, is_expired=is_expired)


@app.route('/api/tender/<int:tender_id>/related')
def api_tender_related(tender_id):
    """
    연관 공고 검색: 제목 앞 15자가 같은 공고를 찾아 반환.
    사전규격 ↔ 일반입찰을 서로 연결하는 데 사용.
    """
    tender = Tender.query.get_or_404(tender_id)

    # 제목 첫 15자로 같은 사업의 다른 공고 탐색
    title_key = tender.title[:15]
    related = Tender.query.filter(
        Tender.id != tender_id,          # 자기 자신 제외
        Tender.title.contains(title_key) # 제목 앞부분 일치
    ).order_by(
        # 상태가 다른 것(사전규격 ↔ 일반) 우선 표시
        db.case((Tender.status == '사전규격', 0), else_=1).label('status_order'),
        Tender.announced_date.desc()
    ).limit(5).all()

    result = []
    for t in related:
        dl = None
        if t.deadline_date:
            dl = (t.deadline_date - datetime.now()).days
        result.append({
            'id': t.id,
            'title': t.title,
            'status': t.status,
            'source_site': t.source_site,
            'deadline_date': t.deadline_date.strftime('%Y-%m-%d') if t.deadline_date else None,
            'days_left': dl,
        })
    return jsonify(result)


# ============= API 엔드포인트 =============

@app.route('/api/dashboard')
def api_dashboard():
    """대시보드 데이터 조회"""
    try:
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        # 월요일이면 금요일부터, 아니면 1일전부터
        if now.weekday() == 0:  # 월요일
            start_date = get_last_workday(now)  # 금요일
        else:
            start_date = yesterday

        # 포함/제외 키워드 및 금액 범위 로드
        include_keywords = load_interest_keywords()
        exclude_keywords = load_exclude_keywords()
        budget_range = load_budget_range()

        # 공통 필터 준비
        kw_filter = db.or_(*[Tender.title.contains(kw) for kw in include_keywords]) if include_keywords else None
        br_min = budget_range.get('min')
        br_max = budget_range.get('max')

        # 1. 신규공고: announced_date 기준 1일전~당일 (수의계약 제외)
        new_today = Tender.query.filter(
            Tender.announced_date >= yesterday,
            Tender.announced_date <= now,
            ~Tender.bid_method.contains('수의계약')
        ).count()

        # 2. 사전규격: 마감일이 지나지 않은 모든 공고
        pre_announcement = Tender.query.filter(
            Tender.status == '사전규격',
            Tender.deadline_date >= now
        ).count()

        # 3. 마감 임박 (3일 이내): 수의계약 제외, 마감일 안 지난 공고
        deadline_soon = Tender.query.filter(
            Tender.deadline_date >= now,
            Tender.deadline_date <= now + timedelta(days=3),
            ~Tender.bid_method.contains('수의계약')
        ).count()

        # 4. 총 공고: 수의계약 제외, 마감일 안 지난 공고
        total_tenders = Tender.query.filter(
            Tender.deadline_date >= now,
            ~Tender.bid_method.contains('수의계약')
        ).count()

        # 5. 사전규격: 나라장터 사전규격 중 마감 안 지난 것, 키워드 매칭 순, 20개
        pre_new_query = Tender.query.filter(
            Tender.deadline_date >= now,
            Tender.status == '사전규격',
            db.or_(
                Tender.source_site.contains('나라장터'),
                Tender.source_site.contains('g2b')
            )
        )
        # 제외 키워드 + 관심 키워드 + 금액 범위 필터
        for keyword in exclude_keywords:
            pre_new_query = pre_new_query.filter(~Tender.title.contains(keyword))
        if kw_filter is not None:
            pre_new_query = pre_new_query.filter(kw_filter)
        if br_min:
            pre_new_query = pre_new_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price >= br_min))
        if br_max:
            pre_new_query = pre_new_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price <= br_max))

        all_pre_new = pre_new_query.all()
        sorted_pre_new = smart_sort_tenders_by_keyword_count(
            all_pre_new, include_keywords)
        pre_tenders = sorted_pre_new[:20]

        # 6. 신규공고(기타 채널): 금~오늘, 나라장터 제외, 수의계약 제외, 마감 안 지난 것
        new_query = Tender.query.filter(
            Tender.announced_date >= start_date,
            Tender.announced_date <= now,
            Tender.status != '사전규격',
            Tender.deadline_date >= now,           # 마감일 지난 공고 제외
            ~Tender.bid_method.contains('수의계약'),  # 수의계약 제외
            ~Tender.source_site.contains('나라장터'),
            ~Tender.source_site.like('%g2b%')
        )
        # 제외 키워드 + 관심 키워드 + 금액 범위 필터
        for keyword in exclude_keywords:
            new_query = new_query.filter(~Tender.title.contains(keyword))
        if kw_filter is not None:
            new_query = new_query.filter(kw_filter)
        if br_min:
            new_query = new_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price >= br_min))
        if br_max:
            new_query = new_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price <= br_max))

        all_new = new_query.all()
        sorted_new = smart_sort_tenders_by_keyword_count(
            all_new, include_keywords)
        recent_tenders = sorted_new[:20]

        seven_days_ago = now - timedelta(days=7)

        # 7. 신규공고(나라장터 API): 최근 7일, 수의계약 제외, 마감 안 지난 것 + 3중 필터
        urgent_query = Tender.query.filter(
            Tender.announced_date >= seven_days_ago,
            Tender.announced_date <= now,
            Tender.status != '사전규격',
            Tender.deadline_date >= now,
            ~Tender.bid_method.contains('수의계약'),
            db.or_(
                Tender.source_site.contains('나라장터 API'),
                Tender.source_site.like('%g2b_api%')
            )
        )
        for keyword in exclude_keywords:
            urgent_query = urgent_query.filter(~Tender.title.contains(keyword))
        if kw_filter is not None:
            urgent_query = urgent_query.filter(kw_filter)
        if br_min:
            urgent_query = urgent_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price >= br_min))
        if br_max:
            urgent_query = urgent_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price <= br_max))

        all_urgent = urgent_query.all()
        sorted_urgent = smart_sort_tenders_by_keyword_count(all_urgent, include_keywords)
        urgent_tenders = sorted_urgent[:20]

        # 전체 필터 적용 후 총 건수 (배지용)
        keyword_match_count = len(all_pre_new) + len(all_urgent) + len(all_new)

        response_data = {
            'summary': {
                'new_today': new_today,
                'pre_announcement': pre_announcement,
                'deadline_soon': deadline_soon,
                'total': total_tenders,
                'keyword_match': keyword_match_count},
            'pre_tenders': [
                {**t.to_dict(interest_keywords=include_keywords),
                 **dict(zip(('relevance_score', 'business_type'), _score_and_type(t, include_keywords)))}
                for t in pre_tenders],
            'urgent_tenders': [
                {**t.to_dict(interest_keywords=include_keywords),
                 **dict(zip(('relevance_score', 'business_type'), _score_and_type(t, include_keywords)))}
                for t in urgent_tenders],
            'recent_tenders': [
                {**t.to_dict(interest_keywords=include_keywords),
                 **dict(zip(('relevance_score', 'business_type'), _score_and_type(t, include_keywords)))}
                for t in recent_tenders],
            'include_keywords': include_keywords,
            'exclude_keywords': exclude_keywords}

        return jsonify(response_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tenders')
def api_tenders():
    """공고 목록 조회 (필터링, 페이징)"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get(
            'per_page', Config.ITEMS_PER_PAGE, type=int)

        # 필터 파라미터
        filter_id = request.args.get('filter_id', type=int)
        include_keywords = request.args.get('include_keywords', '')
        exclude_keywords = request.args.get('exclude_keywords', '')
        status = request.args.get('status', '')
        # keyword_logic는 현재 사용하지 않음 (하드코딩된 로직 사용)
        # keyword_logic = request.args.get('keyword_logic', 'OR')

        # 날짜 필터 파라미터
        announced_date_from = request.args.get('announced_date_from', '')
        announced_date_to = request.args.get('announced_date_to', '')
        deadline_date_from = request.args.get('deadline_date_from', '')
        deadline_date_to = request.args.get('deadline_date_to', '')

        # 수의계약은 검색 결과에서 기본 제외
        query = Tender.query.filter(~Tender.bid_method.contains('수의계약'))

        # 필터 적용
        if filter_id:
            filter_preset = Filter.query.get(filter_id)
            if filter_preset:
                # 키워드 필터링
                include_kw = json.loads(
                    filter_preset.include_keywords) if filter_preset.include_keywords else []
                exclude_kw = json.loads(
                    filter_preset.exclude_keywords) if filter_preset.exclude_keywords else []

                for keyword in include_kw:
                    query = query.filter(Tender.title.contains(keyword))

                for keyword in exclude_kw:
                    query = query.filter(~Tender.title.contains(keyword))

                # 가격 필터
                if filter_preset.min_price:
                    query = query.filter(
                        Tender.estimated_price >= filter_preset.min_price)
                if filter_preset.max_price:
                    query = query.filter(
                        Tender.estimated_price <= filter_preset.max_price)

                # 마감일 필터
                if filter_preset.days_before_deadline:
                    deadline = datetime.now() + timedelta(days=filter_preset.days_before_deadline)
                    query = query.filter(Tender.deadline_date <= deadline)

        # 직접 키워드 필터 (특수문자로 AND/OR 구분)
        # 예: "AI+교육, 시스템" → (AI AND 교육) OR 시스템
        if include_keywords:
            # 쉼표로 split → OR 그룹들
            or_groups = [g.strip()
                         for g in include_keywords.split(',') if g.strip()]

            if or_groups:
                or_conditions = []

                for group in or_groups:
                    # + 기호로 split → AND 키워드들
                    and_keywords = [k.strip()
                                    for k in group.split('+') if k.strip()]

                    if len(and_keywords) == 1:
                        # 단일 키워드: 그냥 포함 조건
                        or_conditions.append(
                            Tender.title.contains(
                                and_keywords[0]))
                    else:
                        # 여러 키워드: 모두 포함해야 함 (AND)
                        and_conditions = [
                            Tender.title.contains(k) for k in and_keywords]
                        or_conditions.append(db.and_(*and_conditions))

                # 모든 OR 조건들을 OR로 묶음
                if len(or_conditions) == 1:
                    query = query.filter(or_conditions[0])
                else:
                    query = query.filter(db.or_(*or_conditions))

        if exclude_keywords:
            # 제외 키워드는 각각 제외 (하나라도 포함되면 제외)
            for keyword in exclude_keywords.split(','):
                if keyword.strip():
                    query = query.filter(
                        ~Tender.title.contains(
                            keyword.strip()))

        # 상태 필터
        if status:
            query = query.filter_by(status=status)

        # 기본 날짜 범위 설정 (마감일 기준 오늘부터 1달)
        # 사용자가 날짜 필터를 하나도 지정하지 않은 경우에만 적용
        if not (
                announced_date_from or announced_date_to or deadline_date_from or deadline_date_to):
            today = datetime.now()
            one_month_later = today + timedelta(days=30)
            query = query.filter(Tender.deadline_date >= today)
            query = query.filter(Tender.deadline_date <= one_month_later)

        # 날짜 필터 적용
        if announced_date_from:
            try:
                from_date = datetime.strptime(announced_date_from, '%Y-%m-%d')
                query = query.filter(Tender.announced_date >= from_date)
            except ValueError:
                pass

        if announced_date_to:
            try:
                to_date = datetime.strptime(announced_date_to, '%Y-%m-%d')
                # 해당 날짜의 끝까지 포함
                to_date = to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(Tender.announced_date <= to_date)
            except ValueError:
                pass

        if deadline_date_from:
            try:
                from_date = datetime.strptime(deadline_date_from, '%Y-%m-%d')
                query = query.filter(Tender.deadline_date >= from_date)
            except ValueError:
                pass

        if deadline_date_to:
            try:
                to_date = datetime.strptime(deadline_date_to, '%Y-%m-%d')
                # 해당 날짜의 끝까지 포함
                to_date = to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(Tender.deadline_date <= to_date)
            except ValueError:
                pass

        # 모든 결과 가져오기 (스마트 정렬을 위해)
        all_tenders = query.all()

        # 스마트 정렬 적용
        sorted_tenders = smart_sort_tenders(all_tenders)

        # 수동 페이징
        total = len(sorted_tenders)
        start = (page - 1) * per_page
        end = start + per_page
        items = sorted_tenders[start:end]

        # 페이징 객체와 유사한 구조 생성
        class ManualPagination:
            def __init__(self, items, page, per_page, total):
                self.items = items
                self.page = page
                self.per_page = per_page
                self.total = total
                self.pages = (total + per_page - 1) // per_page
                self.has_prev = page > 1
                self.has_next = page < self.pages

        pagination = ManualPagination(items, page, per_page, total)

        # 관심 키워드 로드
        interest_keywords = load_interest_keywords()

        return jsonify({
            'tenders': [t.to_dict(interest_keywords=interest_keywords) for t in pagination.items],
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page,
            'interest_keywords': interest_keywords
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/filters', methods=['GET', 'POST'])
def api_filters():
    """필터 목록 조회 또는 새 필터 생성"""
    if request.method == 'GET':
        filters = Filter.query.all()
        return jsonify([f.to_dict() for f in filters])

    elif request.method == 'POST':
        try:
            data = request.json

            # 기본 필터로 설정하는 경우, 다른 필터의 기본값 해제
            if data.get('is_default'):
                Filter.query.update({'is_default': False})

            new_filter = Filter(
                name=data['name'],
                is_default=data.get('is_default', False),
                include_keywords=json.dumps(data.get('include_keywords', [])),
                exclude_keywords=json.dumps(data.get('exclude_keywords', [])),
                regions=json.dumps(data.get('regions', [])),
                categories=json.dumps(data.get('categories', [])),
                min_price=data.get('min_price'),
                max_price=data.get('max_price'),
                days_before_deadline=data.get('days_before_deadline'),
                priority_pre_announcement=data.get(
                    'priority_pre_announcement', True),
                sme_only=data.get('sme_only', False)
            )

            db.session.add(new_filter)
            db.session.commit()

            return jsonify(new_filter.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500


@app.route('/api/filters/<int:filter_id>', methods=['PUT', 'DELETE'])
def api_filter_detail(filter_id):
    """필터 수정 또는 삭제"""
    filter_obj = Filter.query.get_or_404(filter_id)

    if request.method == 'PUT':
        try:
            data = request.json

            # 기본 필터로 설정하는 경우, 다른 필터의 기본값 해제
            if data.get('is_default') and not filter_obj.is_default:
                Filter.query.filter(Filter.id != filter_id).update(
                    {'is_default': False})

            filter_obj.name = data.get('name', filter_obj.name)
            filter_obj.is_default = data.get(
                'is_default', filter_obj.is_default)
            filter_obj.include_keywords = json.dumps(
                data.get('include_keywords', []))
            filter_obj.exclude_keywords = json.dumps(
                data.get('exclude_keywords', []))
            filter_obj.regions = json.dumps(data.get('regions', []))
            filter_obj.categories = json.dumps(data.get('categories', []))
            filter_obj.min_price = data.get('min_price')
            filter_obj.max_price = data.get('max_price')
            filter_obj.days_before_deadline = data.get('days_before_deadline')
            filter_obj.priority_pre_announcement = data.get(
                'priority_pre_announcement', True)
            filter_obj.sme_only = data.get('sme_only', False)

            db.session.commit()
            return jsonify(filter_obj.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    elif request.method == 'DELETE':
        try:
            db.session.delete(filter_obj)
            db.session.commit()
            return jsonify({'message': '필터가 삭제되었습니다.'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500


@app.route('/api/logs')
def api_logs():
    """크롤링 로그 조회"""
    logs = CrawlLog.query.order_by(CrawlLog.started_at.desc()).limit(20).all()
    return jsonify([log.to_dict() for log in logs])


@app.route('/api/stats')
def api_stats():
    """통계 데이터"""
    try:
        now = datetime.now()

        # 수집 채널별 공고 수 (announced_date 기준, 마감 안 지난 공고만)
        source_stats = db.session.query(
            Tender.source_site,
            db.func.count(Tender.id)
        ).filter(
            Tender.deadline_date >= now
        ).group_by(Tender.source_site)\
         .order_by(db.func.count(Tender.id).desc())\
         .all()

        # 최근 7일간 일별 공고 수 (announced_date 기준)
        seven_days_ago = now - timedelta(days=7)
        daily_stats = db.session.query(
            db.func.date(Tender.announced_date),
            db.func.count(Tender.id)
        ).filter(
            Tender.announced_date >= seven_days_ago,
            Tender.announced_date <= now
        ).group_by(db.func.date(Tender.announced_date))\
         .all()

        return jsonify({
            'source_stats': [{'source': s, 'count': c} for s, c in source_stats],
            'daily_stats': [{'date': str(d), 'count': c} for d, c in daily_stats]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookmarks', methods=['GET'])
def api_bookmarks():
    """관심공고 목록 조회 (공고 상세 + 적합도 점수 포함)"""
    try:
        include_keywords = load_interest_keywords()
        bookmarks = Bookmark.query.order_by(Bookmark.created_at.desc()).all()
        result = []
        for b in bookmarks:
            tender = b.tender
            if not tender:
                continue
            score, btype = _score_and_type(tender, include_keywords)
            label_bonus = Bookmark.LABEL_BONUS.get(b.label or '', 0)
            d = tender.to_dict(interest_keywords=include_keywords)
            d['relevance_score'] = min(100.0, round(score + label_bonus, 1))
            d['label_bonus'] = label_bonus
            d['business_type'] = btype
            d['bookmark_id'] = b.id
            d['bookmark_label'] = b.label or ''
            d['bookmark_note'] = b.user_note or ''
            d['bookmarked_at'] = b.created_at.isoformat()
            result.append(d)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookmarks/toggle', methods=['POST'])
def api_bookmark_toggle():
    """관심공고 토글 (추가/삭제)"""
    try:
        data = request.json or {}
        tender_id = data.get('tender_id')
        if not tender_id:
            return jsonify({'error': 'tender_id 필요'}), 400

        existing = Bookmark.query.filter_by(tender_id=tender_id).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify({'bookmarked': False})
        else:
            bookmark = Bookmark(tender_id=tender_id, user_note='')
            db.session.add(bookmark)
            db.session.commit()
            return jsonify({'bookmarked': True, 'bookmark_id': bookmark.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookmarks/<int:bookmark_id>/label', methods=['POST'])
def api_bookmark_label(bookmark_id):
    """관심공고 라벨 설정"""
    try:
        data = request.json or {}
        label = data.get('label', '')
        valid_labels = [k for k, _ in Bookmark.LABEL_CHOICES] + ['']
        if label not in valid_labels:
            return jsonify({'error': '유효하지 않은 라벨'}), 400
        b = Bookmark.query.get_or_404(bookmark_id)
        b.label = label or None
        db.session.commit()
        return jsonify({'label': b.label, 'label_bonus': Bookmark.LABEL_BONUS.get(b.label or '', 0)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/bookmarks/ids', methods=['GET'])
def api_bookmark_ids():
    """북마크된 tender_id 목록"""
    try:
        ids = [b.tender_id for b in Bookmark.query.with_entities(Bookmark.tender_id).all()]
        return jsonify(ids)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/search', methods=['POST'])
def api_search():
    """즉시 검색 시작 (크롤링)"""
    # crawler_scheduler는 읽기만 하므로 global 선언 불필요
    if not crawler_scheduler:
        return jsonify({'error': '스케줄러가 초기화되지 않았습니다.'}), 500

    try:
        # 백그라운드에서 크롤링 실행
        def run_crawl():
            result = crawler_scheduler.run_manual_crawl()
            print(f"[수동 크롤링] 결과: {result}")

        thread = threading.Thread(target=run_crawl)
        thread.daemon = True
        thread.start()

        return jsonify({
            'message': '크롤링이 시작되었습니다. 잠시 후 결과를 확인하세요.',
            'status': 'started'
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/crawl/status')
def api_crawl_status():
    """최근 크롤링 상태 조회"""
    try:
        latest_log = CrawlLog.query.order_by(
            CrawlLog.started_at.desc()).first()
        if latest_log:
            return jsonify(latest_log.to_dict())
        else:
            return jsonify({'message': '크롤링 기록이 없습니다.'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============= Phase 3: 데이터 관리 API =============

@app.route('/api/data/delete-old', methods=['POST'])
def api_delete_old_tenders():
    """오래된 공고 삭제"""
    try:
        days = request.json.get('days', 30)
        count = data_manager.delete_old_tenders(days)
        return jsonify({'message': f'{count}건의 공고를 삭제했습니다.', 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/data/clear-tenders', methods=['POST'])
def api_clear_tenders():
    """크롤링 데이터(공고)만 삭제 - 설정, 필터, 북마크 유지"""
    try:
        count = Tender.query.count()
        Tender.query.delete()
        db.session.commit()
        return jsonify({'message': f'크롤링 데이터 {count}건을 삭제했습니다.', 'count': count})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/data/reset', methods=['POST'])
def api_reset_database():
    """데이터베이스 초기화"""
    try:
        keep_filters = request.json.get('keep_filters', True)
        result = data_manager.reset_database(keep_filters)

        if result:
            return jsonify({
                'message': '데이터베이스가 초기화되었습니다.',
                'result': result
            })
        else:
            return jsonify({'error': '초기화 실패'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/data/stats')
def api_database_stats():
    """데이터베이스 통계"""
    try:
        stats = data_manager.get_database_stats()
        if stats:
            return jsonify(stats)
        else:
            return jsonify({'error': '통계 조회 실패'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/data/cleanup', methods=['POST'])
def api_cleanup_data():
    """데이터 정리 (중복 제거)"""
    try:
        count = data_manager.cleanup_duplicates()
        return jsonify(
            {'message': f'{count}건의 중복 공고를 삭제했습니다.', 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============= Phase 3: Excel 내보내기 API =============

@app.route('/api/export/csv')
def api_export_csv():
    """CSV로 내보내기"""
    try:
        # 필터링된 공고 조회
        include_keywords = request.args.get('include_keywords', '')
        exclude_keywords = request.args.get('exclude_keywords', '')
        status = request.args.get('status', '')

        query = Tender.query

        if include_keywords:
            for keyword in include_keywords.split(','):
                query = query.filter(Tender.title.contains(keyword.strip()))

        if exclude_keywords:
            for keyword in exclude_keywords.split(','):
                query = query.filter(~Tender.title.contains(keyword.strip()))

        if status:
            query = query.filter_by(status=status)

        tenders = query.order_by(
            db.case((Tender.status == '사전규격', 1), else_=2),
            Tender.deadline_date.asc()
        ).all()

        # 딕셔너리로 변환
        tender_dicts = [t.to_dict() for t in tenders]

        # CSV 생성
        csv_content = excel_exporter.export_to_csv(tender_dicts)

        # 응답 생성
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
        response.headers['Content-Disposition'] = f'attachment; filename=tenders_{
            datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/excel')
def api_export_excel():
    """Excel HTML로 내보내기"""
    try:
        # 공고 조회 (CSV와 동일)
        include_keywords = request.args.get('include_keywords', '')
        status = request.args.get('status', '')

        query = Tender.query

        if include_keywords:
            for keyword in include_keywords.split(','):
                query = query.filter(Tender.title.contains(keyword.strip()))

        if status:
            query = query.filter_by(status=status)

        tenders = query.order_by(
            db.case((Tender.status == '사전규격', 1), else_=2),
            Tender.deadline_date.asc()
        ).all()

        tender_dicts = [t.to_dict() for t in tenders]

        # Excel HTML 생성
        html_content = excel_exporter.export_to_excel_html(tender_dicts)

        response = make_response(html_content)
        response.headers['Content-Type'] = 'application/vnd.ms-excel; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=tenders_{
            datetime.now().strftime("%Y%m%d_%H%M%S")}.xls'

        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============= Phase 3: 설정 관리 API =============

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    """설정 조회/저장"""
    if request.method == 'GET':
        try:
            settings = settings_manager.load_settings()
            return jsonify(settings)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            new_settings = request.json
            # gemini_api_key는 별도 엔드포인트로 관리 — 폼에 없으면 기존 값 유지
            if 'gemini_api_key' not in new_settings:
                new_settings['gemini_api_key'] = settings_manager.get('gemini_api_key', '')
            success = settings_manager.save_settings(new_settings)

            if success:
                return jsonify({'message': '설정이 저장되었습니다.'})
            else:
                return jsonify({'error': '설정 저장 실패'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/settings/validate', methods=['POST'])
def api_validate_settings():
    """설정 유효성 검사"""
    try:
        temp_settings = request.json
        # 임시로 설정 업데이트
        original_settings = settings_manager.settings
        settings_manager.settings = temp_settings

        is_valid, errors = settings_manager.validate_settings()

        # 원래 설정 복원
        settings_manager.settings = original_settings

        return jsonify({
            'valid': is_valid,
            'errors': errors
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============= 에러 핸들러 =============

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/interest-keywords', methods=['GET', 'POST'])
def api_interest_keywords():
    """관심 키워드 조회/저장"""
    if request.method == 'GET':
        try:
            keywords = load_interest_keywords()
            exclude_keywords = load_exclude_keywords()
            budget_range = load_budget_range()
            return jsonify({
                'keywords': keywords,
                'exclude_keywords': exclude_keywords,
                'budget_range': budget_range
            })
        except Exception as e:
            print(f"[오류] 관심 키워드 로드 실패: {str(e)}")
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json
            keywords = data.get('keywords', [])
            # 제외 키워드와 금액 범위도 함께 저장
            exclude_kws = data.get('exclude_keywords', None)
            budget_range = data.get('budget_range', None)

            # 설정 파일 로드 (파일이 없으면 기본 설정 사용)
            import os
            settings_file = 'data/settings.json'
            os.makedirs('data', exist_ok=True)

            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            else:
                settings = {
                    'crawl': {'auto_enabled': True, 'times': ['09:00', '17:00'], 'sites': {}, 'sites_config': {}},
                    'notification': {'email_enabled': False, 'email_address': '', 'deadline_alert': False, 'deadline_days': 3},
                    'data': {'auto_cleanup': False, 'retention_days': 30},
                    'display': {'items_per_page': 20, 'theme': 'light'}
                }

            if 'user_preferences' not in settings:
                settings['user_preferences'] = {}

            # 관심 키워드 업데이트
            settings['user_preferences']['interest_keywords'] = keywords
            # 제외 키워드 업데이트 (전달된 경우만)
            if exclude_kws is not None:
                settings['user_preferences']['exclude_keywords'] = exclude_kws
            # 금액 범위 업데이트 (전달된 경우만)
            if budget_range is not None:
                settings['user_preferences']['budget_range'] = budget_range

            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            return jsonify({'message': '키워드 필터가 저장되었습니다.',
                            'keywords': keywords,
                            'exclude_keywords': settings['user_preferences'].get('exclude_keywords', []),
                            'budget_range': settings['user_preferences'].get('budget_range', {})})
        except Exception as e:
            print(f"[오류] 키워드 필터 저장 실패: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500


@app.route('/api/email-settings', methods=['GET', 'POST'])
def api_email_settings():
    """이메일 알림 설정 조회/저장"""
    if request.method == 'GET':
        try:
            # 설정 파일 로드
            with open('data/settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)

            email_settings = settings.get('email_notification', {})
            return jsonify({'settings': email_settings})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            data = request.json

            # 설정 파일 로드
            with open('data/settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)

            # 이메일 설정 업데이트
            settings['email_notification'] = {
                'enabled': data.get('enabled', False),
                'email_service': data.get('email_service', 'gmail'),
                'sender_email': data.get('sender_email', ''),
                'sender_password': data.get('sender_password', ''),
                'recipient_email': data.get('recipient_email', ''),
                'new_tender_alert': data.get('new_tender_alert', False),
                'deadline_alert': data.get('deadline_alert', False),
                'keyword_alert': data.get('keyword_alert', False)
            }

            # 설정 파일 저장
            with open('data/settings.json', 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            # EmailNotifier 설정 업데이트
            if settings['email_notification']['enabled']:
                email_notifier.configure(
                    settings['email_notification']['sender_email'],
                    settings['email_notification']['sender_password'],
                    settings['email_notification']['recipient_email'],
                    settings['email_notification']['email_service']
                )
            else:
                email_notifier.enabled = False

            return jsonify({'message': '이메일 설정이 저장되었습니다.'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/test-email', methods=['POST'])
def api_test_email():
    """테스트 이메일 발송"""
    try:
        data = request.json
        email_service = data.get('email_service', 'gmail')
        sender_email = data.get('sender_email')
        sender_password = data.get('sender_password')
        recipient_email = data.get('recipient_email')

        if not all([sender_email, sender_password, recipient_email]):
            return jsonify({'error': '모든 이메일 정보를 입력해야 합니다.'}), 400

        # 임시 EmailNotifier 생성
        test_notifier = EmailNotifier()
        test_notifier.configure(
            sender_email,
            sender_password,
            recipient_email,
            email_service)

        # 테스트 이메일 발송
        success = test_notifier.send_test_email()

        if success:
            return jsonify({'message': '테스트 이메일이 발송되었습니다.'})
        else:
            return jsonify({'error': '이메일 발송에 실패했습니다.'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# 분석 진행 중인 tender_id 추적 (중복 실행 방지)
_analysis_in_progress = set()
_analysis_lock = threading.Lock()


def _run_analysis_background(tender_id, tender_url, tender_title, source_site, api_key):
    """백그라운드 스레드에서 분석 실행 후 DB 저장"""
    with app.app_context():
        try:
            from document_analyzer import analyze_tender as _analyze
            result = _analyze(
                tender_url=tender_url,
                tender_title=tender_title,
                api_key=api_key,
                source_site=source_site,
            )
            secs = result.get('gemini_sections')
            model = secs.get('_model') if isinstance(secs, dict) else None
            payload = dict(
                files_found=json.dumps(result.get('files_found', []), ensure_ascii=False),
                text_length=result.get('text_length', 0),
                rule_extract=json.dumps(result.get('rule_extract', {}), ensure_ascii=False),
                gemini_sections=json.dumps(secs, ensure_ascii=False),
                model_used=model,
                error=result.get('error'),
                updated_at=datetime.utcnow(),
            )
            existing = TenderAnalysis.query.filter_by(tender_id=tender_id).first()
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
            else:
                db.session.add(TenderAnalysis(tender_id=tender_id, **payload))
            db.session.commit()
            app.logger.info(f'분석 완료 및 저장: tender_id={tender_id}')
        except Exception as e:
            app.logger.error(f'백그라운드 분석 오류 (tender_id={tender_id}): {e}')
        finally:
            with _analysis_lock:
                _analysis_in_progress.discard(tender_id)


@app.route('/api/tender/<int:tender_id>/analyze')
def api_analyze_tender(tender_id):
    """
    공고 첨부파일(RFP) AI 분석.
    - 캐시 있음 → 즉시 반환
    - 캐시 없음 → 백그라운드 분석 시작 후 {"status":"processing"} 즉시 반환
    - 클라이언트는 2초마다 폴링해서 완료 확인
    """
    try:
        tender = Tender.query.get_or_404(tender_id)
        force = request.args.get('force', '0') == '1'

        # ── 캐시 조회 ──────────────────────────────────────────────────────
        if not force:
            cached = TenderAnalysis.query.filter_by(tender_id=tender_id).first()
            if cached:
                return jsonify(cached.to_dict())

        # ── 이미 분석 중이면 즉시 processing 반환 ─────────────────────────
        with _analysis_lock:
            already_running = tender_id in _analysis_in_progress
            if not already_running:
                _analysis_in_progress.add(tender_id)

        if already_running:
            return jsonify({'status': 'processing', 'message': '분석이 진행 중입니다. 잠시 후 다시 확인합니다.'})

        # ── Gemini API 키 로드 ────────────────────────────────────────────
        api_key = settings_manager.get('gemini_api_key', '').strip() or None

        # ── 백그라운드 스레드에서 분석 시작 ──────────────────────────────
        t = threading.Thread(
            target=_run_analysis_background,
            args=(tender_id, tender.url, tender.title, tender.source_site or '', api_key),
            daemon=True,
        )
        t.start()

        return jsonify({'status': 'processing', 'message': '분석을 시작했습니다. 자동으로 결과를 불러옵니다…'})

    except Exception as e:
        with _analysis_lock:
            _analysis_in_progress.discard(tender_id)
        return jsonify({'error': str(e)}), 500


@app.route('/api/settings/gemini-key', methods=['GET', 'POST'])
def api_gemini_key():
    """Gemini API 키 조회/저장"""
    if request.method == 'GET':
        try:
            key = settings_manager.get('gemini_api_key', '')
            masked = key[:8] + '...' if len(key) > 8 else ('설정됨' if key else '')
            return jsonify({'has_key': bool(key), 'masked': masked})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        try:
            data = request.json or {}
            new_key = data.get('api_key', '').strip()
            settings_manager.set('gemini_api_key', new_key)
            return jsonify({'message': 'Gemini API 키가 저장되었습니다.'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500


# =============================================================
# Sync API — 팀원 인스턴스가 공고 데이터를 가져가는 엔드포인트
# =============================================================

@app.route('/api/sync/tenders')
def api_sync_tenders():
    """
    팀원 앱이 호출하여 최신 공고 데이터를 가져가는 엔드포인트.
    settings.json 의 sync.token 과 일치하는 요청만 허용.

    Query params:
        token   : 인증 토큰 (필수)
        since   : ISO datetime — 이 시각 이후 생성된 공고만 반환 (선택)
        limit   : 최대 건수 (기본 500, 최대 2000)
    """
    # ── 인증 ──────────────────────────────────────────────────
    expected = settings_manager.get('sync.token', '')
    if not expected:
        return jsonify({'error': 'Sync not enabled on this server'}), 403

    token = request.args.get('token') or request.headers.get('X-Sync-Token', '')
    if token != expected:
        return jsonify({'error': 'Unauthorized'}), 401

    # ── 파라미터 ───────────────────────────────────────────────
    since_str = request.args.get('since')
    try:
        since = datetime.fromisoformat(since_str) if since_str else datetime.now() - timedelta(days=30)
    except ValueError:
        since = datetime.now() - timedelta(days=30)

    limit = min(int(request.args.get('limit', 500)), 2000)

    # ── 쿼리 ───────────────────────────────────────────────────
    tenders = (
        Tender.query
        .filter(Tender.created_at >= since)
        .order_by(Tender.created_at.desc())
        .limit(limit)
        .all()
    )

    return jsonify({
        'count': len(tenders),
        'since': since.isoformat(),
        'synced_at': datetime.now().isoformat(),
        'tenders': [t.to_dict() for t in tenders]
    })


# ============= 포트 정리 =============

def _free_port(port: int) -> None:
    """시작 전 해당 포트를 점유한 프로세스를 안전하게 종료한다."""
    import psutil
    import os
    current_pid = os.getpid()
    targets = []
    try:
        for conn in psutil.net_connections(kind='tcp'):
            if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                if conn.pid and conn.pid != current_pid:
                    targets.append(conn.pid)
    except (psutil.AccessDenied, AttributeError):
        pass

    for pid in set(targets):
        try:
            proc = psutil.Process(pid)
            print(f"[서버] 포트 {port} 점유 프로세스(PID {pid}: {proc.name()}) 종료 중...")
            proc.terminate()          # SIGTERM → 정상 종료 시도
            proc.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            try:
                proc.kill()           # 응답 없으면 SIGKILL
                proc.wait(timeout=3)
            except psutil.NoSuchProcess:
                pass
        except psutil.AccessDenied:
            print(f"[서버] PID {pid} 종료 권한 없음 — 다른 포트를 사용하거나 관리자로 실행하세요.")


# ============= 메인 =============

if __name__ == '__main__':
    print("=" * 50)
    print("입찰공고 통합 검색 시스템 시작")
    print(f"서버 주소: http://localhost:{Config.PORT}")
    print("=" * 50)

    # 포트 점유 프로세스 정리 (좀비 소켓 방지)
    _free_port(Config.PORT)

    # 설정 파일 로드
    settings_manager.load_settings()

    crawler_scheduler = None
    # 스케줄러 시작
    if Config.AUTO_CRAWL_ENABLED:
        from scheduler import CrawlScheduler
        crawler_scheduler = CrawlScheduler(app)
        crawler_scheduler.start()

    try:
        from waitress import serve
        print(f"[서버] waitress WSGI 서버로 시작합니다 (port {Config.PORT})")
        serve(app, host=Config.HOST, port=Config.PORT, threads=8,
              connection_limit=200, cleanup_interval=30, channel_timeout=120)
    except ImportError:
        print("[서버] waitress 미설치 — Flask 개발 서버로 폴백합니다")
        app.run(host=Config.HOST, port=Config.PORT, debug=False,
                threaded=True, use_reloader=False)
    finally:
        # 서버 종료 시 스케줄러도 중지
        if crawler_scheduler:
            crawler_scheduler.stop()
