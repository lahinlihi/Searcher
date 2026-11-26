"""뉴스레터 구독자 삭제 — 잘못 넣은 주소를 지울 수 있어야 한다 (2026-11-26 사용자: "지우는 법이 없네")."""
import sqlite3

import pytest

import newsletter as nl


@pytest.fixture
def conn():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    nl.ensure_schema(c)
    yield c
    c.close()


def _emails(c):
    return [r['email'] for r in c.execute('SELECT email FROM newsletter_subscribers ORDER BY id')]


def test_remove_deletes_only_that_subscriber(conn):
    a = nl.add_subscriber(conn, 'a@example.com')
    nl.add_subscriber(conn, 'b@example.com')
    assert nl.remove_subscriber(conn, a['id']) == 'deleted'
    assert _emails(conn) == ['b@example.com']
    assert [r['email'] for r in nl.active_subscribers(conn)] == ['b@example.com']


def test_remove_unknown_id(conn):
    nl.add_subscriber(conn, 'a@example.com')
    assert nl.remove_subscriber(conn, 9999) == 'not_found'
    assert _emails(conn) == ['a@example.com']


def test_remove_refuses_unsubscribed_address(conn):
    """수신거부한 주소는 지우지 않는다 — 기록을 지우면 같은 주소를 재동의 확인 없이 다시 등록할 수 있게 된다."""
    a = nl.add_subscriber(conn, 'a@example.com')
    assert nl.unsubscribe(conn, a['unsubscribe_token'])
    assert nl.remove_subscriber(conn, a['id']) == 'unsubscribed'
    assert _emails(conn) == ['a@example.com']
    with pytest.raises(nl.Unsubscribed):
        nl.add_subscriber(conn, 'a@example.com')


def test_deleted_address_can_be_added_again(conn):
    a = nl.add_subscriber(conn, 'a@example.com')
    nl.remove_subscriber(conn, a['id'])
    again = nl.add_subscriber(conn, 'a@example.com')
    assert again['status'] == 'active' and again['id'] != a['id']


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def api(app, client, login, make_user, monkeypatch, tmp_path):
    import hr_news
    monkeypatch.setattr(hr_news, 'DB_PATH', str(tmp_path / 'news.db'))      # 운영 DB 를 건드리지 않게
    from routes.newsletter import bp
    app.register_blueprint(bp)
    return client, login, make_user


def test_api_delete_subscriber(api):
    client, login, make_user = api
    login(make_user(role='moderator'))
    sid = client.post('/api/newsletter/subscribers', json={'email': 'wrong@example.com'}).get_json()['id']
    client.post('/api/newsletter/subscribers', json={'email': 'keep@example.com'})
    r = client.delete(f'/api/newsletter/subscribers/{sid}')
    assert r.status_code == 200 and r.get_json() == {'deleted': True}
    assert [s['email'] for s in client.get('/api/newsletter/subscribers').get_json()] == ['keep@example.com']
    assert client.delete(f'/api/newsletter/subscribers/{sid}').status_code == 404


def test_api_delete_refuses_unsubscribed(api):
    client, login, make_user = api
    login(make_user(role='moderator'))
    sub = client.post('/api/newsletter/subscribers', json={'email': 'gone@example.com'}).get_json()
    assert client.get(f"/newsletter/unsubscribe/{sub['unsubscribe_token']}").status_code == 200
    r = client.delete(f"/api/newsletter/subscribers/{sub['id']}")
    assert r.status_code == 409 and '수신거부' in r.get_json()['error']
    assert len(client.get('/api/newsletter/subscribers').get_json()) == 1


def test_api_delete_requires_moderator(api):
    client, login, make_user = api
    login(make_user(role='moderator'))
    sid = client.post('/api/newsletter/subscribers', json={'email': 'a@example.com'}).get_json()['id']
    login(make_user(role='user'))
    assert client.delete(f'/api/newsletter/subscribers/{sid}').status_code in (401, 403)
    login(make_user(role='moderator'))
    assert len(client.get('/api/newsletter/subscribers').get_json()) == 1
