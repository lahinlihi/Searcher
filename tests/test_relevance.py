import relevance as R


def test_type_max():
    assert R.type_max(None) == 25.0
    assert R.type_max({}) == 25.0
    assert R.type_max({'교육운영': 45, '행사운영': 15}) == 45.0
    assert R.type_max({'교육운영': 1.2}) == 25.0        # 2.0 이하 값은 예전 배율 방식 — 만점 계산에 넣지 않는다


def test_base_score_matches_measured_examples():
    # 2026-11-25 측정: 계정 5 최고점 24.6+25 → 88.4, 20.0+25 → 78.6 / 계정 1 은 발주처를 빼고 다시 계산
    assert round(R.base_score(24.6, 25.0, 25.0), 1) == 88.4
    assert round(R.base_score(20.0, 25.0, 25.0), 1) == 78.6
    assert R.base_score(45.0, 25.0, 25.0) == 100.0       # x = 4.5 ≥ 3.0 → 키워드 만점
    assert R.base_score(30.0, 45.0, 45.0) == 100.0
    assert R.base_score(0.0, 0.0, 25.0) == 0.0


def test_case_to_100():
    assert R.case_to_100(0.35) == 0.0 and R.case_to_100(0.2) == 0.0
    assert R.case_to_100(0.80) == 100.0 and R.case_to_100(0.95) == 100.0
    assert round(R.case_to_100(0.575), 1) == 50.0


def test_agency_adjust():
    adj = {'서울': 10.0, '서울시교육청': -30.0, '한국콘텐츠진흥원': 20.0}
    assert R.agency_adjust('부산광역시', None, adj) == 0.0
    assert R.agency_adjust('한국콘텐츠진흥원 본원', None, adj) == 20.0
    assert R.agency_adjust('조달청', '한국콘텐츠진흥원', adj) == 20.0      # 수요기관도 본다
    assert R.agency_adjust('서울시교육청 학교지원과', None, adj) == -30.0   # 더 긴 이름이 이긴다
    assert R.agency_adjust(None, None, adj) == 0.0
    assert R.agency_adjust('서울', None, {}) == 0.0


def test_combine():
    assert R.combine(80.0, None, 0.0) == 80.0
    assert R.combine(80.0, 60.0, 0.0) == 70.0
    assert R.combine(80.0, None, 20.0) == 100.0
    assert R.combine(95.0, None, 20.0) == 100.0          # 위로 자름
    assert R.combine(20.0, None, -30.0) == 0.0           # 아래로 자름
    assert R.combine(80.0, 60.0, -30.0) == 40.0
