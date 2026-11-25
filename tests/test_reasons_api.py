"""이유 칩·자격 확인 규칙 API (제품 계약서 5부)."""
import pytest

import reasons as RS
from database import db, DismissedTender


@pytest.fixture
def me(reasons_app, client, login, make_user, make_prefs, fake_model):
    u = make_user()
    make_prefs(u, interest=['교육'])
    login(u)
    return u


def _dismissed(u):
    return DismissedTender.query.filter_by(user_id=u.id).count()


# ── 2단계: 제외할 때 이유 필수 ───────────────────────────────────────────────

@pytest.mark.parametrize('body', [None, {}, {'reasons': []}, {'reasons': ['like_field']}, {'reasons': ['eligible']},
                                  {'reasons': ['bogus']}, {'reasons': 'size'}, ['size']])
def test_dismiss_requires_reason(me, client, make_tender, body):
    t = make_tender(title='교육 운영 용역')
    r = client.post(f'/api/tenders/{t.id}/dismiss', json=body) if body is not None else client.post(f'/api/tenders/{t.id}/dismiss')
    assert r.status_code == 400 and '이유' in r.get_json()['error']
    assert _dismissed(me) == 0 and RS.get_reasons(me.id, [t.id]) == {}


def test_dismiss_with_reason_saves_both(me, client, make_tender):
    t = make_tender(title='교육 운영 용역')
    r = client.post(f'/api/tenders/{t.id}/dismiss', json={'reasons': ['region', 'size']})
    assert r.status_code == 200 and r.get_json() == {'dismissed': True, 'reasons': ['region', 'size']}
    assert _dismissed(me) == 1 and RS.get_reasons(me.id, [t.id]) == {t.id: ['size', 'region']}


def test_dismiss_again_updates_reasons(me, client, make_tender):
    t = make_tender()
    client.post(f'/api/tenders/{t.id}/dismiss', json={'reasons': ['region']})
    r = client.post(f'/api/tenders/{t.id}/dismiss', json={'reasons': ['etc']})
    assert r.status_code == 200 and _dismissed(me) == 1
    assert RS.get_reasons(me.id, [t.id]) == {t.id: ['etc']}


def test_undismiss_keeps_reasons(me, client, make_tender):
    t = make_tender()
    client.post(f'/api/tenders/{t.id}/dismiss', json={'reasons': ['license']})
    assert client.delete(f'/api/tenders/{t.id}/dismiss').get_json() == {'dismissed': False}
    assert _dismissed(me) == 0 and RS.get_reasons(me.id, [t.id]) == {t.id: ['license']}   # 검토 기록으로 남는다


def test_legacy_dismissed_without_reason_still_works(me, client, make_tender):
    """이유를 받기 전에 제외한 기록(운영에 60건)은 그대로 유효하다."""
    t = make_tender(title='교육 운영 용역')
    db.session.add(DismissedTender(user_id=me.id, tender_id=t.id)); db.session.commit()
    listed = client.get('/api/dismissed').get_json()
    assert [(x['id'], x['reasons']) for x in listed] == [(t.id, [])]
    assert all(x['id'] != t.id for x in client.get('/api/dashboard').get_json()['urgent_tenders'])
    assert client.delete(f'/api/tenders/{t.id}/dismiss').get_json() == {'dismissed': False}
    assert any(x['id'] == t.id for x in client.get('/api/dashboard').get_json()['urgent_tenders'])


def test_dismissed_list_carries_reasons(me, client, make_tender):
    t = make_tender()
    client.post(f'/api/tenders/{t.id}/dismiss', json={'reasons': ['target']})
    assert client.get('/api/dismissed').get_json()[0]['reasons'] == ['target']


# ── 이유만 남기기 (제외하지 않고) ────────────────────────────────────────────

def test_put_and_get_tender_reasons(me, client, login, make_user, make_tender):
    t = make_tender()
    r = client.put(f'/api/tenders/{t.id}/reasons', json={'reasons': ['like_form', 'eligible']})
    assert r.status_code == 200 and r.get_json() == {'reasons': ['like_form', 'eligible']}
    assert client.get(f'/api/tenders/{t.id}/reasons').get_json() == {'reasons': ['like_form', 'eligible']}
    assert _dismissed(me) == 0
    login(make_user())
    assert client.get(f'/api/tenders/{t.id}/reasons').get_json() == {'reasons': []}      # 남의 이유는 안 보인다


def test_put_rejects_unknown_and_missing_tender(me, client, make_tender):
    t = make_tender()
    assert client.put(f'/api/tenders/{t.id}/reasons', json={'reasons': ['bogus']}).status_code == 400
    assert client.put(f'/api/tenders/{t.id}/reasons', json=['size']).status_code == 400
    assert client.put('/api/tenders/999999/reasons', json={'reasons': ['size']}).status_code == 404
    assert client.get('/api/tenders/999999/reasons').status_code == 404


def test_options_endpoint(me, client):
    body = client.get('/api/reasons/options').get_json()
    assert [o['code'] for o in body['options']] == list(RS.REASONS)
    assert body['dismiss_groups'] == ['ineligible', 'other']


# ── 4단계: 규칙 API 와 목록의 표시 ───────────────────────────────────────────

def _urgent(client):
    return client.get('/api/dashboard').get_json()['urgent_tenders']


def test_flags_do_not_change_score_or_order(me, client, make_tender):
    for i, title in enumerate(['교육 국외연수 운영 용역', '교육 운영 용역', '교육 자료 국외연수']):
        make_tender(title=title, tender_number=f'F{i:07d}')
    before = _urgent(client)
    assert all(x['eligibility_flags'] == [] for x in before)
    r = client.post('/api/reason-rules', json={'reason': 'license', 'words': ['국외연수']})
    assert r.status_code == 200 and r.get_json()['status'] == 'on'
    after = _urgent(client)
    assert [(x['id'], x['relevance_score']) for x in after] == [(x['id'], x['relevance_score']) for x in before]
    assert [bool(x['eligibility_flags']) for x in after] == ['국외연수' in x['title'] for x in after]
    assert sum(bool(x['eligibility_flags']) for x in after) == 2


def test_api_rules_crud_and_isolation(me, client, login, make_user, make_tender):
    t = make_tender(title='교육 국외연수 운영')
    rid = client.post('/api/reason-rules', json={'reason': 'license', 'words': ['국외연수']}).get_json()['id']
    body = client.get('/api/reason-rules').get_json()
    assert [r['id'] for r in body['rules']] == [rid] and body['candidates'] == []
    assert client.put(f'/api/reason-rules/{rid}', json={'status': 'off'}).get_json()['status'] == 'off'
    assert all(x['eligibility_flags'] == [] for x in _urgent(client))
    assert client.put(f'/api/reason-rules/{rid}', json={'status': 'on', 'words': ['국외']}).get_json()['words'] == ['국외']
    for bad in ({'status': 'rejected'}, {'words': ['시']}, {'words': []}, {}):
        assert client.put(f'/api/reason-rules/{rid}', json=bad).status_code == 400, bad
    for bad in ({'reason': 'etc', 'words': ['국외연수']}, {'reason': 'license', 'words': ['시']}, {'reason': 'license'}, ['x']):
        assert client.post('/api/reason-rules', json=bad).status_code == 400, bad
    login(make_user())
    assert client.get('/api/reason-rules').get_json()['rules'] == []
    assert client.put(f'/api/reason-rules/{rid}', json={'status': 'off'}).status_code == 404
    assert all(x['eligibility_flags'] == [] for x in client.get('/api/tenders').get_json()['tenders'])


def test_api_candidates_and_reject(me, client, make_tender):
    for title in ('6급 핵심인재 국외연수', '담당교원 국외연수', '우수강사 국외연수'):
        t = make_tender(title=title)
        client.put(f'/api/tenders/{t.id}/reasons', json={'reasons': ['license']})
    cands = client.get('/api/reason-rules').get_json()['candidates']
    assert [(c['reason'], c['words'], len(c['evidence'])) for c in cands] == [('license', ['국외연수'], 3)]
    assert client.post('/api/reason-rules/reject', json={'reason': 'license', 'words': ['국외연수']}).get_json() == {'rejected': True}
    body = client.get('/api/reason-rules').get_json()
    assert body['candidates'] == [] and body['rules'] == []


def test_every_list_api_carries_flags(me, client, make_tender, make_prefs):
    from datetime import datetime
    from database import AgencyWeight, Bookmark, TenderView
    client.post('/api/reason-rules', json={'reason': 'license', 'words': ['국외연수']})
    t = make_tender(title='교육 국외연수 운영', agency='중점기관')
    seen = make_tender(title='교육 국외연수 과정', agency='중점기관', tender_number='SEEN0001')
    kept = make_tender(title='교육 국외연수 캠프', tender_number='KEPT0001')
    db.session.add_all([AgencyWeight(user_id=me.id, agency_name='중점기관', mark='key'),
                        TenderView(user_id=me.id, tender_id=seen.id, viewed_at=datetime.utcnow()),
                        Bookmark(user_id=me.id, tender_id=kept.id)])
    db.session.commit()
    flagged = lambda items, tid: next(x for x in items if x['id'] == tid)['eligibility_flags'][0]['reason']
    assert flagged(_urgent(client), t.id) == 'license'
    assert flagged(client.get('/api/dashboard/key-agencies').get_json()['items'], t.id) == 'license'
    assert flagged(client.get('/api/tenders?keyword=국외연수').get_json()['tenders'], t.id) == 'license'
    assert flagged(client.get('/api/viewed/recent').get_json()['items'], seen.id) == 'license'


def test_bookmark_and_similar_lists_carry_flags(reasons_app, client, login, make_user, make_prefs, make_tender, fake_model):
    from routes.bookmarks import bp as bookmarks_bp
    from routes.cases import bp as cases_bp
    from database import Bookmark
    reasons_app.register_blueprint(bookmarks_bp); reasons_app.register_blueprint(cases_bp)
    u = make_user(); make_prefs(u, interest=['교육']); login(u)
    client.post('/api/reason-rules', json={'reason': 'license', 'words': ['국외연수']})
    kept = make_tender(title='교육 국외연수 캠프')
    db.session.add(Bookmark(user_id=u.id, tender_id=kept.id)); db.session.commit()
    assert client.get('/api/bookmarks').get_json()[0]['eligibility_flags'][0]['reason'] == 'license'
    sim = client.get('/api/cases/similar').get_json()
    assert sim['enabled'] is False and sim['items'] == []          # 꺼져 있어도 오류 없이 응답한다


# ── 6단계: 예전 메모 되짚기 ──────────────────────────────────────────────────

def test_memo_backlog_lists_only_my_hinted_memos_without_reasons(me, client, login, make_user, make_tender):
    from database import TenderMemo
    other = make_user()
    a = make_tender(title='국외연수 운영')
    b = make_tender(title='교육 운영')
    c = make_tender(title='남이 검토한 공고')
    d = make_tender(title='소상공인 지원')
    db.session.add_all([
        TenderMemo(tender_id=a.id, user_id=me.id, content='참가자격 불가 : 여행업 등록 업체만 가능'),
        TenderMemo(tender_id=b.id, user_id=me.id, content='검토 중입니다'),
        TenderMemo(tender_id=c.id, user_id=other.id, content='참가자격 불가 : 지역 제한'),
        TenderMemo(tender_id=d.id, user_id=me.id, content='소기업만 가능\n' + '가' * 300),
    ])
    db.session.commit()
    items = client.get('/api/reasons/memo-backlog').get_json()['items']
    assert {i['tender_id'] for i in items} == {a.id, d.id}
    one = next(i for i in items if i['tender_id'] == a.id)
    assert one['title'] == '국외연수 운영' and one['memo'].startswith('참가자격 불가')
    assert all(len(i['memo']) <= 120 for i in items)
    client.put(f'/api/tenders/{a.id}/reasons', json={'reasons': ['license']})       # 이유를 붙이면 목록에서 빠진다
    assert {i['tender_id'] for i in client.get('/api/reasons/memo-backlog').get_json()['items']} == {d.id}


def test_reason_api_requires_login(reasons_app, client, make_tender):
    t = make_tender()
    assert client.get('/api/reasons/options').status_code == 401
    assert client.put(f'/api/tenders/{t.id}/reasons', json={'reasons': ['size']}).status_code == 401
