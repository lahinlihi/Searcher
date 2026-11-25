"""적합도 점수의 새 눈금 (제품 계약서 3부).

scoring.py 가 내는 키워드·유형 점수를 0~100 으로 다시 편다. 발주처는 기본 점수에 넣지 않고,
등록된 발주처만 가감점으로 더하거나 뺀다. 이 파일은 DB 를 모른다 — 숫자만 받는 순수 함수다.
"""

KEYWORD_FULL_X = 3.0     # 정확 일치 3건 분량(가중 합 3.0)이면 키워드 만점
KEYWORD_MAX = 45.0
TYPE_DEFAULT_MAX = 25.0
CASE_SIM_LO = 0.35       # 담은 공고와의 닮음이 이 값이면 사례 점수 0
CASE_SIM_HI = 0.80       # 이 값이면 100
CASE_MIX = 0.5           # 사례 점수가 차지하는 몫
ADJUST_MIN = -30.0
ADJUST_MAX = 30.0


def type_max(type_weights):
    """계정의 유형 만점. 사용자가 정한 유형 점수(2.0 초과) 가운데 가장 큰 값, 없으면 25."""
    vals = [float(v) for v in (type_weights or {}).values() if v is not None and float(v) > 2.0]
    return max(vals) if vals else TYPE_DEFAULT_MAX


def base_score(keyword_raw, type_score, tmax):
    """키워드(0~45 원점수)와 유형 점수로 0~100 기본 점수를 낸다."""
    kw = KEYWORD_MAX * min(1.0, (float(keyword_raw or 0) / 10.0) / KEYWORD_FULL_X)
    total = (kw + float(type_score or 0)) / (KEYWORD_MAX + float(tmax)) * 100.0
    return max(0.0, min(100.0, total))


def case_to_100(sim):
    """담은 공고와의 닮음(코사인)을 0~100 으로 옮긴다."""
    t = (float(sim) - CASE_SIM_LO) / (CASE_SIM_HI - CASE_SIM_LO)
    return max(0.0, min(1.0, t)) * 100.0


def agency_adjust(agency, demand_agency, adjusts):
    """등록된 발주처 이름이 발주기관·수요기관에 들어 있으면 그 가감점. 여럿이면 가장 긴 이름의 값."""
    if not adjusts:
        return 0.0
    text = f"{agency or ''} {demand_agency or ''}".lower()
    best_name, best = '', 0.0
    for name, value in adjusts.items():
        n = (name or '').strip().lower()
        if n and n in text and len(n) > len(best_name):
            best_name, best = n, float(value)
    return best


def combine(base, case100, adjust):
    """기본 점수에 사례 점수를 섞고 발주처 가감점을 더한다. 0~100, 소수 1자리."""
    mixed = float(base) if case100 is None else float(base) * (1 - CASE_MIX) + float(case100) * CASE_MIX
    return round(max(0.0, min(100.0, mixed + float(adjust or 0))), 1)
