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


def test_candidate_dropped_when_word_is_too_common_among_live_tenders(app, make_user, make_tender, make_prefs, monkeypatch):
    """시험 서버에서 본 문제: '위탁용역' 같은 흔한 낱말이 후보로 올라와 진행 중 공고 92건에 걸렸다.
    한 번에 너무 많은 공고에 표시가 붙는 낱말은 겨냥한 규칙이 아니다 — 후보로 올리지 않는다."""
    u = make_user(); make_prefs(u, interest=['교육'])
    old = datetime.now() - timedelta(days=40)
    _tag(u, make_tender, TRIPS, 'license', announced_date=old, deadline_date=old + timedelta(days=5))
    for i in range(3):
        make_tender(title=f'공무원 국외연수 {i}')
    assert len(RS.candidates(u.id)) == 1                    # 진행 중 3건 — 문턱 아래
    monkeypatch.setattr(RS, 'GENERIC_LIVE_MAX', 2)
    assert RS.candidates(u.id) == []                        # 문턱을 넘으면 후보가 아니다
    assert '위탁용역' in RS.STOP_WORDS


def test_candidate_hidden_once_rule_exists(app, make_user, make_tender, make_prefs):
    from database import ReasonRule
    u = make_user(); make_prefs(u, interest=['교육'])
    _tag(u, make_tender, TRIPS, 'license')
    for status in ('on', 'off', 'rejected'):
        ReasonRule.query.delete()
        db.session.add(ReasonRule(user_id=u.id, reason='license', words='["국외연수"]', status=status)); db.session.commit()
        assert RS.candidates(u.id) == [], status


# ── 4단계: 규칙·표시·반례 ────────────────────────────────────────────────────

@pytest.mark.parametrize('bad', [[], [''], [' '], ['시'], ['·'], ['국외연수', '-'], 'abc', None, [3]])
def test_clean_words_rejects_empty_and_one_char(bad):
    with pytest.raises(ValueError):
        RS.clean_words(bad)


def test_clean_words_trims_and_dedupes():
    assert RS.clean_words([' 국외연수 ', '국외 연수', '참가기업']) == ['국외연수', '참가기업']


def test_rule_matches_ignores_spacing_and_case():
    assert RS.rule_matches('2027 교직원 국외 연수 운영', ['국외연수'])
    assert RS.rule_matches('AI·빅데이터 인재양성', ['ai 빅데이터'])
    assert RS.rule_matches('참가기업 모집 공고 (국외연수)', ['국외연수', '참가기업'])
    assert not RS.rule_matches('국외연수 운영', ['국외연수', '참가기업'])        # 모두 들어 있어야 한다
    assert not RS.rule_matches(None, ['국외연수'])


def test_add_rule_validates_reason_and_words(app, make_user):
    u = make_user()
    for reason in ('budget', 'etc', 'like_field', 'eligible', 'nope'):
        with pytest.raises(ValueError):
            RS.add_rule(u.id, reason, ['국외연수'])
    with pytest.raises(ValueError):
        RS.add_rule(u.id, 'license', ['시'])
    assert RS.list_rules(u.id) == []


def test_flags_only_for_on_rules(app, make_user, make_tender):
    u = make_user()
    t = make_tender(title='교직원 국외 연수 운영')
    titles = {t.id: t.title}
    rule = RS.add_rule(u.id, 'license', ['국외연수'])
    assert RS.flags(u.id, titles) == {t.id: [{'reason': 'license', 'label': '업종·등록 요건', 'rule_id': rule.id}]}
    RS.update_rule(u.id, rule.id, status='off')
    assert RS.flags(u.id, titles) == {}
    RS.reject(u.id, 'size', ['교직원'])
    assert RS.flags(u.id, titles) == {}


def test_flags_dedupe_same_reason_and_keep_order(app, make_user, make_tender):
    u = make_user()
    t = make_tender(title='소상공인 국외연수 해외탐방 지원')
    first = RS.add_rule(u.id, 'license', ['국외연수'])
    RS.add_rule(u.id, 'license', ['해외탐방'])
    RS.add_rule(u.id, 'size', ['소상공인'])
    got = RS.flags(u.id, {t.id: t.title})[t.id]
    assert [f['reason'] for f in got] == ['size', 'license']           # 이유마다 하나, 정해진 순서
    assert got[1]['rule_id'] == first.id                               # 같은 이유는 먼저 만든 규칙


def test_flags_are_per_user(app, make_user, make_tender):
    a, b = make_user(), make_user()
    t = make_tender(title='국외연수 운영')
    RS.add_rule(a.id, 'license', ['국외연수'])
    assert RS.flags(b.id, {t.id: t.title}) == {}
    with pytest.raises(LookupError):
        RS.update_rule(b.id, RS.list_rules(a.id)[0]['id'], status='off')


def test_counterexample_listed_when_flagged_tender_bookmarked(app, make_user, make_tender):
    u = make_user()
    RS.add_rule(u.id, 'license', ['국외연수'])
    kept, ok, plain = (make_tender(title=f'국외연수 {x}') for x in ('가', '나', '다'))
    db.session.add(Bookmark(user_id=u.id, tender_id=kept.id)); db.session.commit()
    RS.set_reasons(u.id, ok.id, ['eligible'])
    rule = RS.list_rules(u.id)[0]
    assert {c['id'] for c in rule['counterexamples']} == {kept.id, ok.id}
    assert rule['words'] == ['국외연수'] and rule['status'] == 'on' and rule['label'] == '업종·등록 요건'


def test_rule_survives_evidence_removal(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    ts = _tag(u, make_tender, TRIPS, 'license')
    RS.add_rule(u.id, 'license', ['국외연수'])
    for t in ts:
        RS.set_reasons(u.id, t.id, [])
    assert len(RS.list_rules(u.id)) == 1
    assert RS.flags(u.id, {ts[0].id: ts[0].title}) != {}


def test_rejected_candidate_never_returns_and_is_not_listed(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    _tag(u, make_tender, TRIPS, 'license')
    RS.reject(u.id, 'license', ['국외연수'])
    assert RS.candidates(u.id) == [] and RS.list_rules(u.id) == []


def test_add_rule_revives_same_rule_instead_of_duplicating(app, make_user):
    from database import ReasonRule
    u = make_user()
    r1 = RS.add_rule(u.id, 'license', ['국외연수'])
    RS.update_rule(u.id, r1.id, status='off')
    r2 = RS.add_rule(u.id, 'license', ['국외 연수'])
    assert r2.id == r1.id and r2.status == 'on' and ReasonRule.query.count() == 1


def test_update_rule_words(app, make_user, make_tender):
    u = make_user()
    r = RS.add_rule(u.id, 'license', ['국외연수'])
    RS.update_rule(u.id, r.id, words=['해외연수'])
    t = make_tender(title='해외연수 운영')
    assert RS.flags(u.id, {t.id: t.title}) != {}
    with pytest.raises(ValueError):
        RS.update_rule(u.id, r.id, words=['시'])
    with pytest.raises(ValueError):
        RS.update_rule(u.id, r.id, status='rejected')


def test_attach_flags_fills_every_dict(app, make_user, make_tender):
    u = make_user()
    RS.add_rule(u.id, 'license', ['국외연수'])
    dicts = [{'id': 1, 'title': '국외연수 운영'}, {'id': 2, 'title': '교육 운영'}, {'id': 3, 'title': None}]
    RS.attach_flags(u.id, dicts)
    assert [bool(d['eligibility_flags']) for d in dicts] == [True, False, False]
    assert dicts[0]['eligibility_flags'][0]['label'] == '업종·등록 요건'
