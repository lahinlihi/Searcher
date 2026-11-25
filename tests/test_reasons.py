"""이유 칩과 자격 확인 규칙 (제품 계약서 5부)."""
from datetime import datetime, timedelta

import pytest

import reasons as RS
from database import db, Bookmark


# ── 1단계: 이유 저장 ─────────────────────────────────────────────────────────

def test_options_cover_every_code_once():
    codes = [o['code'] for o in RS.options()]
    assert codes == list(RS.REASONS) and len(set(codes)) == 13
    assert {o['group'] for o in RS.options()} == {'ineligible', 'other', 'like', 'eligible'}
    assert RS.REASONS['license']['label'] == '업종·등록 요건' and RS.REASONS['eligible']['label'] == '자격 가능'


def test_clean():
    assert RS.clean(['size', 'region', 'size']) == ['size', 'region']
    assert RS.clean([]) == []
    for bad in (['nope'], 'size', None, [1], [['size']]):
        with pytest.raises(ValueError):
            RS.clean(bad)
    with pytest.raises(ValueError):
        RS.clean(['like_field'], groups=RS.DISMISS_GROUPS)
    assert RS.clean(['etc', 'license'], groups=RS.DISMISS_GROUPS) == ['etc', 'license']


def test_set_replaces_and_is_per_user(app, make_user, make_tender):
    a, b, t = make_user(), make_user(), make_tender()
    assert RS.set_reasons(a.id, t.id, ['size', 'region']) == ['size', 'region']
    RS.set_reasons(b.id, t.id, ['field'])
    assert RS.set_reasons(a.id, t.id, ['license']) == ['license']        # 통째로 바뀐다
    assert RS.get_reasons(a.id, [t.id]) == {t.id: ['license']}
    assert RS.get_reasons(b.id, [t.id]) == {t.id: ['field']}             # 남의 것은 그대로
    RS.set_reasons(a.id, t.id, [])
    assert RS.get_reasons(a.id, [t.id]) == {}


def test_get_reasons_returns_canonical_order(app, make_user, make_tender):
    u, t = make_user(), make_tender()
    RS.set_reasons(u.id, t.id, ['etc', 'size'])
    assert RS.get_reasons(u.id, [t.id]) == {t.id: ['size', 'etc']}
    assert RS.get_reasons(u.id, []) == {}


def test_set_rejects_unknown_code_without_changing_anything(app, make_user, make_tender):
    u, t = make_user(), make_tender()
    RS.set_reasons(u.id, t.id, ['size'])
    with pytest.raises(ValueError):
        RS.set_reasons(u.id, t.id, ['size', 'bogus'])
    assert RS.get_reasons(u.id, [t.id]) == {t.id: ['size']}


# ── 3단계: 규칙 후보 ─────────────────────────────────────────────────────────

def test_title_words():
    assert RS.title_words('2026년 우수 발명교육센터 담당교원 국외연수 운영 용역') == {'우수', '발명교육센터', '담당교원', '국외연수'}
    assert RS.title_words('[긴급] AI·빅데이터 교육 (2차)') == {'ai', '빅데이터', '교육'}
    assert RS.title_words('27년 제3회 A 사업') == set()
    assert RS.title_words(None) == set() and RS.title_words('') == set()


def test_norm_matches_title_search_rule():
    assert RS.norm('AI·빅 데이터(2차)') == 'ai빅데이터2차'


def _tag(u, make_tender, titles, reason, **kw):
    ts = [make_tender(title=t, **kw) for t in titles]
    for t in ts:
        RS.set_reasons(u.id, t.id, [reason])
    return ts


TRIPS = ['6급 핵심인재 국외연수 운영', '발명교육센터 담당교원 국외연수', 'SW 우수강사 국외연수 위탁']


def test_candidate_needs_three_evidence(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    _tag(u, make_tender, TRIPS[:2], 'license')
    assert RS.candidates(u.id) == []
    _tag(u, make_tender, TRIPS[2:], 'license')
    cands = RS.candidates(u.id)
    assert [(c['reason'], c['label'], c['words']) for c in cands] == [('license', '업종·등록 요건', ['국외연수'])]
    assert len(cands[0]['evidence']) == 3 and {e['title'] for e in cands[0]['evidence']} == set(TRIPS)


def test_candidate_dropped_by_counterexample(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    _tag(u, make_tender, TRIPS, 'license')
    liked = make_tender(title='공무원 국외연수 프로그램')
    db.session.add(Bookmark(user_id=u.id, tender_id=liked.id)); db.session.commit()
    assert RS.candidates(u.id) == []                                  # 담은 공고가 반례
    Bookmark.query.delete(); db.session.commit()
    assert len(RS.candidates(u.id)) == 1
    RS.set_reasons(u.id, liked.id, ['eligible'])
    assert RS.candidates(u.id) == []                                  # '자격 가능' 도 반례


def test_candidate_ignores_other_users(app, make_user, make_tender, make_prefs):
    me, other = make_user(), make_user()
    make_prefs(me, interest=['교육'])
    make_prefs(other, interest=['교육'])
    _tag(other, make_tender, TRIPS, 'license')
    assert RS.candidates(me.id) == []
    assert len(RS.candidates(other.id)) == 1


def test_candidate_skips_interest_keywords(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육', '국외'])
    _tag(u, make_tender, ['가나 교육 다라', '마바 교육 사아', '자차 교육 카타'], 'size')
    _tag(u, make_tender, TRIPS, 'license')              # '국외연수' 는 관심 키워드 '국외' 를 품는다
    assert RS.candidates(u.id) == []


def test_candidate_skips_non_rule_reasons(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    for reason in ('budget', 'cancelled', 'etc', 'like_field'):
        _tag(u, make_tender, [f'{reason} 해외탐방 {i}' for i in range(3)], reason)
    assert RS.candidates(u.id) == []


def test_candidate_disappears_when_evidence_removed(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    ts = _tag(u, make_tender, TRIPS, 'license')
    assert len(RS.candidates(u.id)) == 1
    RS.set_reasons(u.id, ts[0].id, [])
    assert RS.candidates(u.id) == []


def test_candidate_counts_live_tenders(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    old = datetime.now() - timedelta(days=40)
    _tag(u, make_tender, TRIPS, 'license', announced_date=old, deadline_date=old + timedelta(days=5))   # 근거는 지난 공고
    live = [make_tender(title='교직원 국외 연수 운영'), make_tender(title='청년 국외연수 지원')]          # 띄어 써도 걸린다
    make_tender(title='퇴직자 국외연수', announced_date=old, deadline_date=old + timedelta(days=5))      # 마감됨
    c = RS.candidates(u.id)[0]
    assert c['live_count'] == 2 and {e['id'] for e in c['live_examples']} == {t.id for t in live}


def test_candidate_hidden_once_rule_exists(app, make_user, make_tender, make_prefs):
    from database import ReasonRule
    u = make_user(); make_prefs(u, interest=['교육'])
    _tag(u, make_tender, TRIPS, 'license')
    for status in ('on', 'off', 'rejected'):
        ReasonRule.query.delete()
        db.session.add(ReasonRule(user_id=u.id, reason='license', words='["국외연수"]', status=status)); db.session.commit()
        assert RS.candidates(u.id) == [], status
