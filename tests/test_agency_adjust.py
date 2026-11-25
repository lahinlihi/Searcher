"""발주처 가감점 등록 API 와 예전 값 이전 표 (제품 계약서 3부 22.4)."""
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


def test_post_stores_adjust(api):
    client, u = api
    r = client.post('/api/agency-weights', json={'agency_name': '한국콘텐츠진흥원', 'adjust': 20})
    assert r.status_code == 200 and r.get_json()['adjust'] == 20.0
    rows = client.get('/api/agency-weights').get_json()
    assert [(x['agency_name'], x['adjust']) for x in rows] == [('한국콘텐츠진흥원', 20.0)]
    assert R.load_agency_adjusts(u.id) == {'한국콘텐츠진흥원': 20.0}


def test_post_same_name_updates_instead_of_duplicating(api):
    client, u = api
    client.post('/api/agency-weights', json={'agency_name': '가나기관', 'adjust': 10})
    client.post('/api/agency-weights', json={'agency_name': '가나기관', 'adjust': -30})
    assert R.load_agency_adjusts(u.id) == {'가나기관': -30.0}
    assert AgencyWeight.query.filter_by(user_id=u.id).count() == 1


@pytest.mark.parametrize('bad', [31, -31, 'abc', None, float('nan')])
def test_post_rejects_bad_adjust(api, bad):
    client, u = api
    r = client.post('/api/agency-weights', json={'agency_name': '가나기관', 'adjust': bad})
    assert r.status_code == 400 and 'error' in r.get_json()
    assert AgencyWeight.query.filter_by(user_id=u.id).count() == 0


def test_post_requires_name(api):
    client, _ = api
    assert client.post('/api/agency-weights', json={'agency_name': '  ', 'adjust': 10}).status_code == 400


def test_put_updates_adjust(api):
    client, u = api
    rid = client.post('/api/agency-weights', json={'agency_name': '가나기관', 'adjust': 10}).get_json()['id']
    r = client.put(f'/api/agency-weights/{rid}', json={'adjust': -15})
    assert r.status_code == 200 and r.get_json()['adjust'] == -15.0
    assert client.put(f'/api/agency-weights/{rid}', json={'adjust': 99}).status_code == 400
    assert R.load_agency_adjusts(u.id) == {'가나기관': -15.0}


def test_put_cannot_touch_other_users_row(api, make_user):
    client, _ = api
    other = make_user()
    row = AgencyWeight(user_id=other.id, agency_name='남의기관', adjust=5.0)
    db.session.add(row); db.session.commit()
    assert client.put(f'/api/agency-weights/{row.id}', json={'adjust': 30}).status_code == 404


def test_null_adjust_is_ignored(app, make_user):
    u = make_user()
    db.session.add(AgencyWeight(user_id=u.id, agency_name='예전기관', weight=10.0)); db.session.commit()
    assert R.load_agency_adjusts(u.id) == {}


def test_migration_table():
    from tools.agency_adjust_migrate import old_to_new
    assert [old_to_new(w) for w in (0, 2.5, 5, 7.5, 10)] == [-20.0, -10.0, 0.0, 10.0, 20.0]
    assert old_to_new(None) == 0.0
