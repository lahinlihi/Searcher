from database import UserPreference
from datetime import datetime, timedelta
import json
import re

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
        '역량강화 사업', '역량강화사업', '역량강화 지원사업',
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
        # 인력양성·인재육성 (기타채널: 과기정통부·NIA·정보통신산업진흥원 등)
        '인력양성', '인력 양성', '양성 교육', '교육 사업',
        '연수사업', '인력교류사업', '훈련사업',
        '인재양성', '인재 양성', '전문인력 양성',
        # 강사·튜터 관련
        '강사 양성', '강사양성', '튜터 양성', '교강사',
        '강사 풀', '강사풀', '강사 Pool',
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
        # 콘텐츠 제작지원 (기타채널: 한국콘텐츠진흥원·정보통신산업진흥원 등)
        '콘텐츠 제작', '콘텐츠제작', '콘텐츠 제작지원', '콘텐츠제작지원',
        '디지털콘텐츠', '디지털 콘텐츠',
        '제작 지원사업', '제작지원사업',
        # 시스템·서비스 개발·구축 (SW/IT 분야 콘텐츠 유형)
        '시스템 개발', '시스템개발', '플랫폼 개발', '플랫폼개발',
        '서비스 개발', '서비스개발', '앱 개발', '앱개발',
        'SW 개발', '소프트웨어 개발',
        # IT 시스템·서비스 구축 (NIA·과기정통부·정보통신산업진흥원 스타일)
        '시스템 구축', '시스템구축', '플랫폼 구축', '플랫폼구축',
        '서비스 구축', '서비스개선', '서비스 개선', '서비스 확대',
        '데이터셋 구축', '데이터 구축', 'ISP 사업',
        '디지털 서비스', '디지털서비스',
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
        # 스타트업·투자 관련 행사 (기타채널: 정보통신산업진흥원·콘텐츠진흥원 등)
        '쇼케이스 운영', '쇼케이스 개최', '쇼케이스 참가',
        '투자유치 쇼케이스', '투자 유치 행사', '비즈매칭',
        '데모데이 운영', '해커톤 운영', '해커톤 개최',
        '공모전 운영', '공모전 개최', '경연대회 운영',
        '피칭 행사', '피칭 대회',
        '페스티벌 운영', '페스티벌 개최',
    ]),
    ('사업운영', 35, [
        # 수행기관·운영기관 선정 (교육·행사·시설 특정이 아닌 일반 사업)
        '수행기관 선정', '수행기관 모집', '운영기관 선정',
        '전담기관 선정', '전담기관 운영',
        '사업단 운영', '사업단운영',
        '사업수행기관 선정', '주관기관 선정',
        # 프로그램·서비스 운영 (일반)
        '프로그램 운영', '프로그램운영',
        '서비스 운영', '서비스운영',
        '플랫폼 운영', '플랫폼운영',
        '홈페이지 운영', '시스템 운영위탁',
        # 사업 수탁·위탁 (교육·시설·행사 아닌 일반)
        '사업 수탁', '사업수탁', '수탁사업',
        '사업 운영기관', '사업 운영 위탁',
        # 거점·허브·센터 운영지원
        '허브 운영', '허브운영',
        '운영지원기관', '운영 지원 기관',
        # 사업지원단·추진단 운영
        '사업지원단', '추진단 운영', '사업 추진단',
    ]),
    ('지원사업 신청', 5, [
        # 기업·단체 지원/모집 공고 (우리가 수혜 대상인 경우)
        '지원기업 모집', '참여기업 모집', '신청기업 모집',
        '입주기업 모집', '입주기업 선정', '입주기업',
        '수혜기업', '지원대상 기업',
        # 바우처·보조금·지원금 신청
        '바우처 신청', '바우처 공고', '디지털바우처',
        '지원금 신청', '보조금 신청', '지원금 모집',
        # 창업·사업화 지원 신청
        '사업화 지원사업', '창업지원사업 신청',
        '스타트업 지원사업', '벤처 지원사업',
        '창업 보육', '입주 신청',
        # 투자·융자 신청
        '융자 신청', '정책자금 신청', '융자사업 신청',
        '투자 유치 지원사업',
        # 인증·포상 신청
        '우수기업 신청', '인증 신청 공고', '포상 신청',
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
        # 연구개발·기술개발 과제 공모 (기타채널: 과기정통부·NIA 등)
        '연구개발사업', '연구개발 사업', '기술개발사업', '기술개발 사업',
        '원천기술개발', '원천기술 개발',
        '신규과제 공모', '신규 과제 공모', '과제 공모',
        '위탁연구', '위탁 연구',
        'R&D 사업', 'R&D사업',
        # 방안 수립·분석·평가 연구 (NIA 스타일)
        '방안 수립', '방안 연구', '방안수립',
        '연구 수행', '연구 추진',
        '분석 연구', '연구 분석',
        # 용역·실증·과제 사업 (NIA/과기정통부 공모 스타일)
        '용역사업', '용역 사업',
        '실증사업', '실증 사업', '개발·실증', '개발 실증',
        '신규 공모', '사업 공모', '사업 참여 공고',
        '과제 모집', '신규과제 모집',
        '장학금 사업',
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
def _get_user_pref(user_id):
    """user_id에 해당하는 UserPreference 반환. 없으면 빈 객체 반환"""
    if user_id is None:
        return None
    return UserPreference.query.filter_by(user_id=user_id).first()


def load_interest_keywords(user_id=None):
    """사용자별 관심 키워드 로드"""
    try:
        if user_id is not None:
            pref = UserPreference.query.filter_by(user_id=user_id).first()
            if pref:
                return pref.get_interest_keywords()
        # fallback: settings.json (레거시)
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


def load_exclude_keywords(user_id=None):
    """사용자별 제외 키워드 로드"""
    try:
        if user_id is not None:
            pref = UserPreference.query.filter_by(user_id=user_id).first()
            if pref:
                return pref.get_exclude_keywords()
        with open('data/settings.json', 'r', encoding='utf-8') as f:
            settings = json.load(f)
            return settings.get('user_preferences', {}).get('exclude_keywords', [])
    except BaseException:
        return []


def load_budget_range(user_id=None):
    """사용자별 금액 범위 로드"""
    try:
        if user_id is not None:
            pref = UserPreference.query.filter_by(user_id=user_id).first()
            if pref:
                return pref.get_budget_range()
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


def _score_and_type(tender, include_keywords, type_weights=None):
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

    ── 사업 유형 점수 (사용자 설정, 기본 25점) ────────────────────────────
    최우선(45) / 선호(35) / 보통(25, 기본값) / 낮음(15) / 제외(0)
    * type_weights에 직접 점수로 저장. 설정 없으면 25점(보통).

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
    if type_name == '기타':
        type_score = 0.0
    else:
        raw_user_w = (type_weights or {}).get(type_name)
        if raw_user_w is None:
            type_score = 25.0                           # 기본값: 보통 25점
        elif float(raw_user_w) > 2.0:
            type_score = float(raw_user_w)              # 신규: 직접 점수 (45/35/25/15/0)
        else:
            type_score = raw_type_score * 0.9 * float(raw_user_w)  # 레거시: 배율

    # ── 우선순위 점수 ────────────────────────────────────────────────────
    priority = _priority_score(tender)

    total = min(100.0, round(keyword_score + type_score + priority, 1))
    return total, type_name


def calculate_relevance_score(tender, include_keywords, type_weights=None):
    return _score_and_type(tender, include_keywords, type_weights)[0]


def smart_sort_tenders_by_keyword_count(tenders, include_keywords, type_weights=None):
    """
    관련성 점수 기반 정렬
    1순위: 관련성 점수 (높을수록)
    2순위: 공고일 (최신순)
    3순위: 금액 (높을수록)
    """
    def sort_key(tender):
        score = calculate_relevance_score(tender, include_keywords, type_weights)
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
