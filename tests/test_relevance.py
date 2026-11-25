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


def test_agency_mark():
    marks = {'서울': 'key', '서울시교육청': 'low', '한국콘텐츠진흥원': 'key'}
    assert R.agency_mark('부산광역시', None, marks) is None
    assert R.agency_mark('한국콘텐츠진흥원 본원', None, marks) == 'key'
    assert R.agency_mark('조달청', '한국콘텐츠진흥원', marks) == 'key'       # 수요기관도 본다
    assert R.agency_mark('서울시교육청 학교지원과', None, marks) == 'low'    # 더 긴 이름이 이긴다
    assert R.agency_mark(None, None, marks) is None
    assert R.agency_mark('서울', None, {}) is None
    assert R.agency_mark('KOCCA 본원', None, {'kocca': 'key'}) == 'key'       # 대소문자를 가리지 않는다


def test_agency_mark_same_length_prefers_low():
    # 길이가 같은 두 이름이 함께 걸리면 등록 순서와 상관없이 후순위를 따른다
    assert R.agency_mark('서울시 교육청', None, {'서울시': 'key', '교육청': 'low'}) == 'low'
    assert R.agency_mark('서울시 교육청', None, {'교육청': 'low', '서울시': 'key'}) == 'low'


def test_combine():
    assert R.combine(80.0, None) == 80.0
    assert R.combine(80.0, 60.0) == 70.0
    assert R.combine(100.0, 100.0) == 100.0
    assert R.combine(0.0, None) == 0.0


# ── Scorer ────────────────────────────────────────────────────────────────────

def _axis(i):
    v = np.zeros(tender_vectors.DIM, dtype=np.float32)
    v[i] = 1.0
    return v


def test_scorer_without_cases_uses_base_only(app, make_user, make_tender, make_prefs, vec_db):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = make_tender(title='AI 교육 운영 용역')
    r = R.Scorer(u.id, vec_conn=vec_db).score([t])[t.id]
    assert r['case'] is None and r['agency'] is None
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


def test_scorer_mark_never_changes_score(app, make_user, make_tender, make_prefs, add_mark, vec_db):
    """발주처는 적합도에 들어가지 않는다 — 중점이든 후순위든 같은 공고의 점수는 같다."""
    u = make_user(); make_prefs(u, interest=['교육'])
    add_mark(u, '중점기관', 'key')
    add_mark(u, '후순위기관', 'low')
    k, low, plain = (make_tender(title='AI 교육 운영 용역', agency=a) for a in ('중점기관', '후순위기관', '다른기관'))
    res = R.Scorer(u.id, vec_conn=vec_db).score([k, low, plain])
    assert res[k.id]['agency'] == 'key' and res[low.id]['agency'] == 'low' and res[plain.id]['agency'] is None
    assert res[k.id]['total'] == res[low.id]['total'] == res[plain.id]['total'] == round(res[plain.id]['base'], 1)


def test_scorer_zero_base_stays_zero(app, make_user, make_tender, make_prefs, add_mark, vec_db, bookmark):
    """키워드·유형이 하나도 안 잡힌 공고는 닮음이나 발주처 표시로 점수가 생기지 않는다. 결과공고도 늘 0 이다."""
    u = make_user(); make_prefs(u, interest=['교육'])
    add_mark(u, '테스트기관', 'key')
    goods = [make_tender(title=f'교육 사례 {i}', agency='다른기관') for i in range(5)]
    for g_ in goods:
        bookmark(u, g_)
    plain = make_tender(title='청사 보안', agency='테스트기관')              # 키워드 없음, 유형 '기타'
    result = make_tender(title='교육 운영 용역 선정 결과', agency='테스트기관', status='결과공고')
    tender_vectors.store(vec_db, [g_.id for g_ in goods] + [plain.id], [_axis(0)] * 6)
    res = R.Scorer(u.id, vec_conn=vec_db).score([plain, result])
    assert res[plain.id]['total'] == 0.0 and res[plain.id]['case'] is None and res[plain.id]['agency'] == 'key'
    assert res[result.id]['total'] == 0.0


def test_scorer_ignores_legacy_weight_without_mark(app, make_user, make_tender, make_prefs, vec_db):
    # 예전 값(weight)만 있고 표시(mark)가 없는 등록은 아무 영향이 없다
    from database import db, AgencyWeight
    u = make_user(); make_prefs(u, interest=['교육'])
    db.session.add(AgencyWeight(user_id=u.id, agency_name='테스트기관', weight=10.0)); db.session.commit()
    t = make_tender(title='AI 교육 운영 용역', agency='테스트기관')
    assert R.Scorer(u.id, vec_conn=vec_db).score([t])[t.id]['agency'] is None


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


def test_sort_low_agencies_last_and_key_first_on_ties(app, make_user, make_tender, make_prefs, add_mark, vec_db):
    """후순위 발주처의 공고는 점수가 더 높아도 맨 아래. 중점 발주처는 같은 점수일 때만 위 (더 새 공고보다도)."""
    u = make_user(); make_prefs(u, interest=['교육', 'AI'])
    add_mark(u, '중점기관', 'key')
    add_mark(u, '후순위기관', 'low')
    now = datetime.now()
    best_but_low = make_tender(title='AI 교육 운영 용역', agency='후순위기관', announced_date=now)
    plain_new = make_tender(title='교육 운영 용역', agency='다른기관', announced_date=now)
    key_old = make_tender(title='교육 운영 용역', agency='중점기관', announced_date=now - timedelta(days=3))
    weak = make_tender(title='청소 용역', agency='다른기관')
    s = R.Scorer(u.id, vec_conn=vec_db)
    scores = s.score([best_but_low, plain_new, key_old, weak])
    assert scores[best_but_low.id]['total'] > scores[plain_new.id]['total'] == scores[key_old.id]['total'] > 0
    assert [t.id for t in s.sort([weak, best_but_low, plain_new, key_old], scores)] == \
        [key_old.id, plain_new.id, weak.id, best_but_low.id]


def test_breakdown_keeps_none_case(app, make_user, make_tender, make_prefs, vec_db):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = make_tender(title='AI 교육 운영 용역')
    s = R.Scorer(u.id, vec_conn=vec_db)
    b = s.breakdown(s.score([t])[t.id])
    assert set(b) == {'keyword', 'type', 'case', 'agency', 'base'} and b['case'] is None
