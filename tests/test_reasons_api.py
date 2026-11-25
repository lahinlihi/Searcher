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


def test_reason_api_requires_login(reasons_app, client, make_tender):
    t = make_tender()
    assert client.get('/api/reasons/options').status_code == 401
    assert client.put(f'/api/tenders/{t.id}/reasons', json={'reasons': ['size']}).status_code == 401
