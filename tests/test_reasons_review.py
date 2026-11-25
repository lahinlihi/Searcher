"""5부 전체 검토에서 나온 지적을 고정하는 테스트."""
from datetime import datetime, timedelta

import pytest

import reasons as RS
from database import db, Bookmark, DismissedTender, ReasonRule, TenderReason, User


@pytest.fixture
def me(reasons_app, client, login, make_user, make_prefs, fake_model):
    u = make_user()
    make_prefs(u, interest=['교육'])
    login(u)
    return u


# ── 1. 공백류 낱말로 모든 공고에 걸리는 규칙이 저장되면 안 된다 ───────────────

@pytest.mark.parametrize('bad', [['\t\t'], ['시\n'], ['　　'], [' \n '], ['가\t'], ['국외연수', '\t']])
def test_clean_words_rejects_whitespace_only_and_one_char_after_trim(bad):
    with pytest.raises(ValueError):
        RS.clean_words(bad)


def test_norm_strips_every_kind_of_whitespace():
    assert RS.norm('국외\t연수\n운영　용역') == '국외연수운영용역'
    assert RS.clean_words(['국외\t연수']) == ['국외\t연수'] and RS.rule_matches('국외 연수 운영', ['국외\t연수'])


def test_api_rejects_whitespace_rule_words(me, client, make_tender):
    make_tender(title='교육 운영 용역')
    for words in (['\t\t'], ['　　'], ['시\n']):
        assert client.post('/api/reason-rules', json={'reason': 'size', 'words': words}).status_code == 400
        assert client.post('/api/reason-rules/reject', json={'reason': 'size', 'words': words}).status_code == 400
    assert ReasonRule.query.count() == 0
    assert all(x['eligibility_flags'] == [] for x in client.get('/api/dashboard').get_json()['urgent_tenders'])


# ── 2. 계정을 지우면 그 계정의 이유·규칙도 지워진다 (id 를 물려받은 새 계정에 남지 않게) ──

def test_deleting_user_removes_reasons_and_rules(app, make_user, make_tender):
    u, t = make_user(), make_tender(title='국외연수 운영')
    RS.set_reasons(u.id, t.id, ['license'])
    RS.add_rule(u.id, 'license', ['국외연수'])
    uid = u.id
    db.session.delete(db.session.get(User, uid)); db.session.commit()
    assert TenderReason.query.filter_by(user_id=uid).count() == 0
    assert ReasonRule.query.filter_by(user_id=uid).count() == 0
    assert RS.flags(uid, {t.id: t.title}) == {} and RS.get_reasons(uid, [t.id]) == {}


# ── 4. 제외는 '자격 가능'과 담는 이유 칩을 함부로 지우지 않는다 ───────────────

def test_dismiss_keeps_like_chips_and_eligible_unless_ineligible_reason(me, client, make_tender):
    a, b = make_tender(title='해외탐방 가'), make_tender(title='해외탐방 나')
    for t in (a, b):
        client.put(f'/api/tenders/{t.id}/reasons', json={'reasons': ['eligible', 'like_form', 'field']})
    # 자격과 무관한 이유로 제외 → '자격 가능'(규칙의 반례)과 담는 이유는 남고, 예전 제외 이유(field)만 바뀐다
    assert client.post(f'/api/tenders/{a.id}/dismiss', json={'reasons': ['budget']}).get_json()['reasons'] == ['budget']
    assert RS.get_reasons(me.id, [a.id]) == {a.id: ['budget', 'like_form', 'eligible']}
    # 자격이 안 된다는 이유로 제외 → '자격 가능'은 모순이므로 지운다
    client.post(f'/api/tenders/{b.id}/dismiss', json={'reasons': ['region']})
    assert RS.get_reasons(me.id, [b.id]) == {b.id: ['region', 'like_form']}


def test_counterexample_survives_unrelated_dismiss(me, client, make_tender):
    t = make_tender(title='해외탐방 프로그램')
    RS.add_rule(me.id, 'license', ['해외탐방'])
    client.put(f'/api/tenders/{t.id}/reasons', json={'reasons': ['eligible']})
    client.post(f'/api/tenders/{t.id}/dismiss', json={'reasons': ['budget']})
    assert [c['id'] for c in RS.list_rules(me.id)[0]['counterexamples']] == [t.id]


# ── 5. 근거가 같은 낱말들은 한 후보로 묶는다 (계약서 36.3 의 예: "국외 연수") ──

def test_words_sharing_the_same_evidence_become_one_candidate(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    for title in ('공무원 국외 연수 운영', '교직원 국외 연수 위탁', '청년 국외 연수 지원'):
        RS.set_reasons(u.id, make_tender(title=title).id, ['license'])
    cands = RS.candidates(u.id)
    assert [(c['reason'], c['words'], len(c['evidence'])) for c in cands] == [('license', ['국외', '연수'], 3)]
    rule = RS.add_rule(u.id, 'license', cands[0]['words'])
    assert RS.candidates(u.id) == []                                  # 켠 규칙은 다시 후보로 안 나온다
    assert RS.rule_matches('임직원 국외연수 대행', ['국외', '연수'])
    assert not RS.rule_matches('국외 전시회 참가', ['국외', '연수'])    # 낱말이 모두 있어야 걸린다
    assert RS.rule_dict(rule)['words'] == ['국외', '연수']


def test_words_with_different_evidence_stay_separate(app, make_user, make_tender, make_prefs):
    u = make_user(); make_prefs(u, interest=['교육'])
    for title in ('가나 국외연수 다라', '마바 국외연수 탐방', '사아 국외연수 탐방', '자차 해외출장 탐방'):
        RS.set_reasons(u.id, make_tender(title=title).id, ['license'])
    got = {tuple(c['words']): len(c['evidence']) for c in RS.candidates(u.id)}
    assert got == {('국외연수',): 3, ('탐방',): 3}


# ── 6. 정밀도 도구: 공고가 들어온 날로 나누고, 자격을 모르는 공고는 분모에서 뺀다 ──

def test_eval_tool_splits_by_tender_date_and_ignores_unknown_verdicts(app, make_user, make_tender, tmp_path, capsys):
    from tools import reason_rule_eval as tool
    u = make_user()
    old, new = datetime(2026, 5, 1), datetime(2026, 9, 1)
    for title in ('가 국외연수', '나 국외연수', '다 국외연수'):
        RS.set_reasons(u.id, make_tender(title=title, created_at=old).id, ['license'])       # 학습 (예전 공고)
    RS.set_reasons(u.id, make_tender(title='라 국외연수', created_at=new).id, ['license'])   # 시험: 못 하는 공고
    RS.set_reasons(u.id, make_tender(title='마 국외연수', created_at=new).id, ['eligible'])  # 시험: 할 수 있는 공고
    RS.set_reasons(u.id, make_tender(title='바 국외연수', created_at=new).id, ['budget'])    # 자격을 모른다 → 분모에서 뺀다
    uid = u.id
    db.session.remove()
    # 이유 칩은 모두 오늘 한자리에서 붙였다 — 칩을 붙인 날로 나누면 학습 자료가 비어 버린다
    assert tool.main(['--user', str(uid), '--db', str(tmp_path / 'test.db'), '--split', '2026-07-01']) == 0
    out = capsys.readouterr().out
    assert '잡은 공고 2건 중 못 하는 공고 1건' in out and '정밀도 0.5' in out


def test_eval_tool_default_split_uses_tender_dates(app, make_user, make_tender, tmp_path, capsys):
    from tools import reason_rule_eval as tool
    u = make_user()
    base = datetime(2026, 5, 1)
    for i in range(6):
        RS.set_reasons(u.id, make_tender(title=f'{i}번 국외연수', created_at=base + timedelta(days=30 * i)).id, ['license'])
    uid = u.id
    db.session.remove()
    assert tool.main(['--user', str(uid), '--db', str(tmp_path / 'test.db')]) == 0
    out = capsys.readouterr().out
    assert '규칙을 만든 이유 3건' in out and '대어 본 공고 3건' in out and '정밀도 1.0' in out


# ── 7. 규칙 후보를 낼 때 진행 중 공고를 낱말마다 다시 훑지 않는다 ─────────────

def test_candidates_query_count_does_not_grow_with_words(app, make_user, make_tender, make_prefs):
    from sqlalchemy import event
    u = make_user(); make_prefs(u, interest=['교육'])
    words = [f'낱말{chr(0xAC00 + i)}{chr(0xAC00 + i)}' for i in range(12)]
    for k in range(3):
        for w in words:                                    # 낱말마다 근거 집합이 다르게: 12개 후보
            RS.set_reasons(u.id, make_tender(title=f'{w} 공고{k}{w[-1]}').id, ['license'])
    counts = []
    listen = lambda *a: counts.append(1)
    event.listen(db.engine, 'before_cursor_execute', listen)
    try:
        cands = RS.candidates(u.id)
    finally:
        event.remove(db.engine, 'before_cursor_execute', listen)
    assert len(cands) == 12
    assert len(counts) <= 12, len(counts)                   # 예전: 낱말마다 3건씩 (12개면 36건 + α)


# ── 8. 대시보드의 브라우저 캐시는 계정마다 따로 ───────────────────────────────

def test_dashboard_cache_key_is_per_user(app, client, login, make_user):
    from routes.pages import bp as pages_bp
    app.register_blueprint(pages_bp)
    app.jinja_env.globals['now'] = datetime.now
    u = make_user(); login(u)
    html = client.get('/').get_data(as_text=True)
    assert f'const HS_USER_ID = {u.id};' in html
    js = open('static/js/dashboard.js', encoding='utf-8').read()
    assert "const _DASH_CACHE_KEY = 'dashboard_cache_v5_u' + HS_USER_ID;" in js
    assert "localStorage.removeItem(k)" in js and "'dashboard_cache_v4'" in js      # 계정 구분 없던 예전 캐시는 지운다
