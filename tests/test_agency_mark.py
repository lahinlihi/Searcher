"""발주처 표시(중점 / 후순위) 등록 API 와 예전 값 이전 도구 (제품 계약서 3부 22.4)."""
import sqlite3

import pytest

import relevance as R
from database import db, AgencyWeight


@pytest.fixture
def api(app, client, login, make_user):
    from routes.filters import bp
    app.register_blueprint(bp)
    u = make_user()
    login(u)
    return client, u


def test_post_stores_mark(api):
    client, u = api
    r = client.post('/api/agency-weights', json={'agency_name': '한국콘텐츠진흥원', 'mark': 'key'})
    assert r.status_code == 200 and r.get_json()['mark'] == 'key'
    rows = client.get('/api/agency-weights').get_json()
    assert [(x['agency_name'], x['mark']) for x in rows] == [('한국콘텐츠진흥원', 'key')]
    assert R.load_agency_marks(u.id) == {'한국콘텐츠진흥원': 'key'}


def test_post_same_name_updates_instead_of_duplicating(api):
    client, u = api
    client.post('/api/agency-weights', json={'agency_name': '가나기관', 'mark': 'key'})
    client.post('/api/agency-weights', json={'agency_name': '가나기관', 'mark': 'low'})
    assert R.load_agency_marks(u.id) == {'가나기관': 'low'}
    assert AgencyWeight.query.filter_by(user_id=u.id).count() == 1


@pytest.mark.parametrize('bad', ['good', '', None, 20, ['key']])
def test_post_rejects_bad_mark(api, bad):
    client, u = api
    r = client.post('/api/agency-weights', json={'agency_name': '가나기관', 'mark': bad})
    assert r.status_code == 400 and 'error' in r.get_json()
    assert AgencyWeight.query.filter_by(user_id=u.id).count() == 0


def test_post_requires_name(api):
    client, _ = api
    assert client.post('/api/agency-weights', json={'agency_name': '  ', 'mark': 'key'}).status_code == 400


@pytest.mark.parametrize('name', ['시', ' 구 ', 'A'])
def test_post_rejects_one_character_name(api, name):
    """한 글자 이름은 거의 모든 공고에 걸린다 — 등록을 막는다 (2026-11-25 사용자 결정)."""
    client, u = api
    r = client.post('/api/agency-weights', json={'agency_name': name, 'mark': 'key'})
    assert r.status_code == 400 and '두 글자' in r.get_json()['error']
    assert AgencyWeight.query.filter_by(user_id=u.id).count() == 0


def test_post_accepts_two_character_name(api):
    client, _ = api
    assert client.post('/api/agency-weights', json={'agency_name': '서울', 'mark': 'key'}).status_code == 200


def test_post_survives_non_object_body(api):
    client, _ = api
    assert client.post('/api/agency-weights', json=['가나기관']).status_code == 400


def test_put_updates_mark(api):
    client, u = api
    rid = client.post('/api/agency-weights', json={'agency_name': '가나기관', 'mark': 'key'}).get_json()['id']
    r = client.put(f'/api/agency-weights/{rid}', json={'mark': 'low'})
    assert r.status_code == 200 and r.get_json()['mark'] == 'low'
    assert client.put(f'/api/agency-weights/{rid}', json={'mark': 'x'}).status_code == 400
    assert R.load_agency_marks(u.id) == {'가나기관': 'low'}


def test_put_cannot_touch_other_users_row(api, make_user):
    client, _ = api
    other = make_user()
    row = AgencyWeight(user_id=other.id, agency_name='남의기관', mark='key')
    db.session.add(row); db.session.commit()
    assert client.put(f'/api/agency-weights/{row.id}', json={'mark': 'low'}).status_code == 404


def test_row_without_mark_is_ignored(app, make_user):
    u = make_user()
    db.session.add(AgencyWeight(user_id=u.id, agency_name='예전기관', weight=10.0)); db.session.commit()
    assert R.load_agency_marks(u.id) == {}


# ── 예전 값(0~10) 이전 도구 ──────────────────────────────────────────────────

def test_old_weight_to_mark():
    from tools.agency_mark_migrate import old_to_mark
    assert [old_to_mark(w) for w in (0, 2.5, 5, 7.5, 10, None)] == ['low', 'low', None, 'key', 'key', None]


def _dump(path):
    c = sqlite3.connect(path)
    try:
        return c.execute('SELECT id, agency_name, weight, mark FROM agency_weights ORDER BY id').fetchall()
    finally:
        c.close()


def test_migrate_tool_writes_only_with_apply_and_only_empty_rows(app, make_user, tmp_path, capsys):
    from tools import agency_mark_migrate as tool
    u = make_user()
    db.session.add_all([
        AgencyWeight(user_id=u.id, agency_name='중점기관', weight=10.0),
        AgencyWeight(user_id=u.id, agency_name='후순위기관', weight=0.0),
        AgencyWeight(user_id=u.id, agency_name='보통기관', weight=5.0),
        AgencyWeight(user_id=u.id, agency_name='값없음', weight=None),
        AgencyWeight(user_id=u.id, agency_name='이미정함', weight=10.0, mark='low'),
    ])
    db.session.commit()
    db.session.remove()
    path = str(tmp_path / 'test.db')
    before = _dump(path)

    assert tool.main(['--db', path]) == 0
    assert _dump(path) == before                          # 표만 출력
    out = capsys.readouterr().out
    assert '중점기관' in out and '값없음' in out

    assert tool.main(['--db', path, '--apply']) == 0
    after = {name: mark for _, name, _, mark in _dump(path)}
    assert after == {'중점기관': 'key', '후순위기관': 'low', '보통기관': None, '값없음': None, '이미정함': 'low'}
    assert [(i, n, w) for i, n, w, _ in _dump(path)] == [(i, n, w) for i, n, w, _ in before]   # 예전 값은 그대로

    assert tool.main(['--db', path, '--apply']) == 0      # 두 번 돌려도 같다
    assert {name: mark for _, name, _, mark in _dump(path)} == after
