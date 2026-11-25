from datetime import datetime, timedelta

import numpy as np

import relevance as R
import tender_vectors


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


# ── Scorer ────────────────────────────────────────────────────────────────────

def _axis(i):
    v = np.zeros(tender_vectors.DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def test_scorer_without_cases_uses_base_only(app, make_user, make_tender, make_prefs, vec_db):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = make_tender(title='AI 교육 운영 용역')
    r = R.Scorer(u.id, vec_conn=vec_db).score([t])[t.id]
    assert r['case'] is None and r['agency'] == 0.0
    assert r['base'] > 0 and r['total'] == round(r['base'], 1)
    assert r['nearest_case'] is None


def test_scorer_no_keywords_gives_zero(app, make_user, make_tender, vec_db):
    u = make_user(); t = make_tender(title='AI 교육 운영 용역')
    assert R.Scorer(u.id, vec_conn=vec_db).score([t])[t.id]['total'] == 0.0


def test_scorer_mixes_case_when_five_cases(app, make_user, make_tender, make_prefs, vec_db, bookmark):
    u = make_user(); make_prefs(u, interest=['교육'])
    goods = [make_tender(title=f'교육 사례 {i}') for i in range(5)]
    for g_ in goods:
        bookmark(u, g_)
    a, b, c = (make_tender(title='AI 교육 운영 용역 가'), make_tender(title='AI 교육 운영 용역 나'),
               make_tender(title='AI 교육 운영 용역 다'))
    tender_vectors.store(vec_db, [g_.id for g_ in goods] + [a.id, b.id],
                         [_axis(0)] * 5 + [_axis(0), _axis(1)])
    res = R.Scorer(u.id, vec_conn=vec_db).score([a, b, c])
    assert res[a.id]['case'] == 100.0 and res[b.id]['case'] == 0.0
    # base 는 화면용으로 소수 1자리에 맞춘 값이라 0.05 까지 어긋날 수 있다
    assert abs(res[a.id]['total'] - (res[a.id]['base'] * 0.5 + 50.0)) <= 0.051
    assert abs(res[b.id]['total'] - res[b.id]['base'] * 0.5) <= 0.051
    assert res[c.id]['case'] is None and res[c.id]['total'] == round(res[c.id]['base'], 1)   # 벡터 없는 공고
    assert res[a.id]['nearest_case']['id'] in {g_.id for g_ in goods}


def test_scorer_four_cases_does_not_mix(app, make_user, make_tender, make_prefs, vec_db, bookmark):
    u = make_user(); make_prefs(u, interest=['교육'])
    goods = [make_tender(title=f'교육 사례 {i}') for i in range(4)]
    for g_ in goods:
        bookmark(u, g_)
    a = make_tender(title='AI 교육 운영 용역')
    tender_vectors.store(vec_db, [g_.id for g_ in goods] + [a.id], [_axis(0)] * 5)
    r = R.Scorer(u.id, vec_conn=vec_db).score([a])[a.id]
    assert r['case'] is None and r['total'] == round(r['base'], 1)


def test_scorer_excludes_self_from_cases(app, make_user, make_tender, make_prefs, vec_db, bookmark):
    # 담은 공고 자신을 점수 낼 때 자기 벡터는 비교에서 빠진다: 남은 넷 중 둘만 같으므로 상위 3 평균 = 2/3
    u = make_user(); make_prefs(u, interest=['교육'])
    goods = [make_tender(title=f'교육 사례 {i}') for i in range(5)]
    for g_ in goods:
        bookmark(u, g_)
    tender_vectors.store(vec_db, [g_.id for g_ in goods], [_axis(0)] * 3 + [_axis(1)] * 2)
    r = R.Scorer(u.id, vec_conn=vec_db).score([goods[0]])[goods[0].id]
    assert r['case'] == round(R.case_to_100(2 / 3), 1)


def test_scorer_applies_agency_adjust(app, make_user, make_tender, make_prefs, add_adjust, vec_db):
    u = make_user(); make_prefs(u, interest=['교육'])
    add_adjust(u, '테스트기관', 20.0)
    t = make_tender(title='AI 교육 운영 용역', agency='테스트기관')
    other = make_tender(title='AI 교육 운영 용역', agency='다른기관')
    res = R.Scorer(u.id, vec_conn=vec_db).score([t, other])
    r = res[t.id]
    assert r['agency'] == 20.0 and r['total'] == min(100.0, round(r['base'] + 20.0, 1))
    assert res[other.id]['agency'] == 0.0 and res[other.id]['total'] == round(res[other.id]['base'], 1)


def test_scorer_ignores_legacy_weight_without_adjust(app, make_user, make_tender, make_prefs, vec_db):
    # 예전 값(weight)만 있고 새 값(adjust)이 없는 등록은 점수를 움직이지 않는다
    from database import db, AgencyWeight
    u = make_user(); make_prefs(u, interest=['교육'])
    db.session.add(AgencyWeight(user_id=u.id, agency_name='테스트기관', weight=10.0)); db.session.commit()
    t = make_tender(title='AI 교육 운영 용역', agency='테스트기관')
    assert R.Scorer(u.id, vec_conn=vec_db).score([t])[t.id]['agency'] == 0.0


def test_scorer_survives_broken_vector_db(app, make_user, make_tender, make_prefs, bookmark):
    class Broken:
        def execute(self, *a, **k):
            raise RuntimeError('벡터 DB 고장')
    u = make_user(); make_prefs(u, interest=['교육'])
    for i in range(5):
        bookmark(u, make_tender(title=f'교육 사례 {i}'))
    t = make_tender(title='AI 교육 운영 용역')
    r = R.Scorer(u.id, vec_conn=Broken()).score([t])[t.id]
    assert r['case'] is None and r['total'] == round(r['base'], 1)


def test_sort_orders_by_total_then_date(app, make_user, make_tender, make_prefs, vec_db):
    u = make_user(); make_prefs(u, interest=['교육'])
    now = datetime.now()
    low = make_tender(title='청소 용역')                                     # 키워드 없음 → 0
    old = make_tender(title='AI 교육 운영 용역', announced_date=now - timedelta(days=3))
    new = make_tender(title='AI 교육 운영 용역', announced_date=now)
    assert [t.id for t in R.Scorer(u.id, vec_conn=vec_db).sort([low, old, new])] == [new.id, old.id, low.id]


def test_breakdown_keeps_none_case(app, make_user, make_tender, make_prefs, vec_db):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = make_tender(title='AI 교육 운영 용역')
    s = R.Scorer(u.id, vec_conn=vec_db)
    b = s.breakdown(s.score([t])[t.id])
    assert set(b) == {'keyword', 'type', 'case', 'agency', 'base'} and b['case'] is None
