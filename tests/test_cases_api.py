from datetime import datetime, timedelta

import pytest

import case_store
import tender_vectors
from database import db, Bookmark

UTC = timedelta(hours=9)


def _fresh(make_tender, title, **kw):
    now = datetime.now()
    kw.setdefault('announced_date', now - timedelta(hours=1))
    kw.setdefault('deadline_date', now + timedelta(days=10))
    kw.setdefault('created_at', now - UTC)
    return make_tender(title=title, **kw)


def _cases(u, make_tender, n=5, title='공공앱 운영 사례'):
    old = datetime.now() - timedelta(days=60)      # 지난 공고 — 대시보드 구역에는 나오지 않는다
    ts = [make_tender(title=f'{title} {i}', created_at=old, announced_date=old,
                      deadline_date=old + timedelta(days=10)) for i in range(n)]
    for t in ts:
        case_store.add_case(u.id, t.id, 'report')
    return ts


@pytest.fixture
def user(cases_app, client, login, make_user, make_prefs):
    u = make_user()
    make_prefs(u, interest=['교육', '공공앱'])
    login(u)
    return u


def _items(body):
    return [x for k in ('pre_tenders', 'urgent_tenders', 'recent_tenders') for x in body[k]]


# ── 대시보드 ────────────────────────────────────────────────────────────────

def test_dashboard_no_cases_unchanged(user, client, make_tender, fake_model):
    for i in range(5):
        _fresh(make_tender, f'교육 운영 {i}')
    r = client.get('/api/dashboard')
    assert r.status_code == 200
    assert 'case_score' not in r.get_data(as_text=True)
    assert 'case_sort' not in r.get_json()


def test_dashboard_with_cases_adds_fields(user, client, make_tender, fake_model):
    _cases(user, make_tender)
    _fresh(make_tender, '교육 운영 용역'); _fresh(make_tender, '공공앱 유지관리')
    items = _items(client.get('/api/dashboard').get_json())
    assert len(items) == 2
    assert all('case_score' in x and 'nearest_case' in x for x in items)
    by_title = {x['title']: x for x in items}
    assert by_title['공공앱 유지관리']['case_score'] > by_title['교육 운영 용역']['case_score']


def test_dashboard_missing_vectors_computed_on_the_fly(user, client, make_tender, fake_model):
    _cases(user, make_tender)
    _fresh(make_tender, '공공앱 유지관리')
    client.get('/api/dashboard')
    conn = tender_vectors.connect()
    assert conn.execute('SELECT COUNT(*) FROM tender_vecs').fetchone()[0] >= 6


def test_dashboard_without_model_unchanged(user, client, make_tender, monkeypatch, tmp_path):
    import scoring
    monkeypatch.setattr(scoring, '_get_embed_model', lambda block=False: None)
    monkeypatch.setattr(tender_vectors, 'VEC_DB_PATH', str(tmp_path / 'v.db'))
    _cases(user, make_tender)
    _fresh(make_tender, '공공앱 유지관리')
    r = client.get('/api/dashboard')
    assert r.status_code == 200 and 'case_score' not in r.get_data(as_text=True)


def _order(client):
    return [x['title'] for x in client.get('/api/dashboard').get_json()['urgent_tenders']]


def test_sort_on_reorders_only_filtered(user, client, make_tender, fake_model):
    _cases(user, make_tender)
    _fresh(make_tender, '교육 운영 용역')                     # 규칙 점수가 높다 (유형 점수 있음)
    _fresh(make_tender, '공공앱 개선')                        # 사례와 비슷하다 (유형 점수 없음)
    _fresh(make_tender, '건설 공사 감리')                     # 관심 키워드 없음
    before = _order(client)
    assert before[0].startswith('교육')
    case_store.set_sort_enabled(user.id, True)
    after = _order(client)
    assert after[0] == '공공앱 개선'
    assert '건설 공사 감리' not in after and sorted(after) == sorted(before)


def test_dashboard_tells_screen_when_sorted_by_case(user, client, make_tender, fake_model):
    """사례 점수로 정렬했으면 화면이 임베딩 점수로 다시 정렬하지 않도록 알려 준다."""
    _cases(user, make_tender)
    _fresh(make_tender, '공공앱 개선')
    assert 'case_sort' not in client.get('/api/dashboard').get_json()
    case_store.set_sort_enabled(user.id, True)
    assert client.get('/api/dashboard').get_json()['case_sort'] is True


def test_sort_skipped_when_some_scores_missing(user, client, make_tender, fake_model, monkeypatch):
    """모델이 없어 새 공고의 사례 점수를 못 구하면, 그 요청은 정렬하지 않는다 (새 공고가 맨 뒤로 밀리지 않게)."""
    import scoring
    _cases(user, make_tender)
    _fresh(make_tender, '공공앱 개선')
    client.get('/api/dashboard')                       # 여기까지는 벡터가 저장된다
    case_store.set_sort_enabled(user.id, True)
    monkeypatch.setattr(scoring, '_get_embed_model', lambda block=False: None)
    _fresh(make_tender, '교육 운영 용역')               # 벡터가 없는 새 공고 (규칙 점수가 높다)
    order = _order(client)
    assert order[0] == '교육 운영 용역'


def test_sort_off_restores_order(user, client, make_tender, fake_model):
    _cases(user, make_tender)
    for t in ('교육 운영 AI 교육', '공공앱 유지관리', '교육 과정'):
        _fresh(make_tender, t)
    def snapshot():
        # days_left 는 호출 시각(datetime.now)에 따라 달라질 수 있어 비교에서 뺀다
        body = client.get('/api/dashboard').get_json()
        return {k: [{f: v for f, v in d.items() if f != 'days_left'} for d in body[k]]
                for k in ('pre_tenders', 'urgent_tenders', 'recent_tenders')}
    before = snapshot()
    case_store.set_sort_enabled(user.id, True)
    assert snapshot() != before                       # 켜면 순서가 바뀐다 (사례와 비슷한 '공공앱'이 앞으로)
    case_store.set_sort_enabled(user.id, False)
    assert snapshot() == before


# ── 정렬 설정 ───────────────────────────────────────────────────────────────

def test_sort_setting_rejected_without_eval(user, client):
    r = client.post('/api/cases/sort-setting', json={'enabled': True})
    assert r.status_code == 409 and r.get_json()['reason']
    assert client.get('/api/cases/sort-setting').get_json() == {
        'enabled': False, 'allowed': False, 'reason': r.get_json()['reason']}


def test_sort_setting_allowed_when_case_better(user, client):
    m = lambda med, n=6: {'n': n, 'median': med, 'top100': 0, 'top500': 0}
    case_store.save_eval(user.id, {'filtered': {'current': m(300), 'case': m(40)}})
    assert client.post('/api/cases/sort-setting', json={'enabled': True}).status_code == 200
    assert client.get('/api/cases/sort-setting').get_json()['enabled'] is True
    assert client.post('/api/cases/sort-setting', json={'enabled': False}).status_code == 200


def test_sort_setting_rejected_when_vectors_missing(user, client):
    m = lambda med, n=6: {'n': n, 'median': med, 'top100': 0, 'top500': 0}
    case_store.save_eval(user.id, {'missing_vectors': 120, 'filtered': {'current': m(300), 'case': m(40)}})
    r = client.post('/api/cases/sort-setting', json={'enabled': True})
    assert r.status_code == 409 and '120' in r.get_json()['reason']


def test_sort_setting_rejected_when_case_worse(user, client):
    m = lambda med, n=6: {'n': n, 'median': med, 'top100': 0, 'top500': 0}
    case_store.save_eval(user.id, {'filtered': {'current': m(40), 'case': m(300)}})
    assert client.post('/api/cases/sort-setting', json={'enabled': True}).status_code == 409


# ── 비슷한 공고 구역 ────────────────────────────────────────────────────────

def test_similar_section_only_keywordless(user, client, make_tender, make_prefs, fake_model):
    from database import UserPreference
    UserPreference.query.filter_by(user_id=user.id).delete(); db.session.commit()
    make_prefs(user, interest=['교육'])
    cases = _cases(user, make_tender)
    db.session.add(Bookmark(user_id=user.id, tender_id=_fresh(make_tender, '공공앱 북마크함').id)); db.session.commit()
    _fresh(make_tender, '공공앱 유지관리 용역')
    _fresh(make_tender, '교육 공공앱 운영')        # 관심 키워드 있음 → 기존 구역에 있으니 제외
    _fresh(make_tender, '건설 감리')               # 사례와 다름 → 점수 낮아 제외
    body = client.get('/api/cases/similar').get_json()
    assert body['enabled'] is True and body['cases'] == 6
    titles = [x['title'] for x in body['items']]
    assert titles == ['공공앱 유지관리 용역']
    assert body['items'][0]['nearest_case']['id'] in {c.id for c in cases} | set()
    assert body['items'][0]['case_score'] >= 50


def test_similar_section_disabled_below_min(user, client, make_tender, fake_model):
    _cases(user, make_tender, n=4)
    body = client.get('/api/cases/similar').get_json()
    assert body == {'enabled': False, 'cases': 4, 'min_cases': 5, 'items': []}


def test_dismiss_hides_from_similar(user, client, make_tender, make_prefs, fake_model):
    from database import UserPreference
    UserPreference.query.filter_by(user_id=user.id).delete(); db.session.commit()
    make_prefs(user, interest=['교육'])
    _cases(user, make_tender)
    t = _fresh(make_tender, '공공앱 유지관리 용역')
    assert len(client.get('/api/cases/similar').get_json()['items']) == 1
    client.post(f'/api/tenders/{t.id}/dismiss')
    assert client.get('/api/cases/similar').get_json()['items'] == []


def test_add_and_remove_case(user, client, make_tender):
    t = make_tender()
    r = client.post('/api/cases', json={'tender_id': t.id, 'source': 'similar'}).get_json()
    assert r == {'added': True, 'cases': 1}
    assert client.post('/api/cases', json={'tender_id': t.id, 'source': 'similar'}).get_json()['added'] is False
    assert client.delete(f'/api/cases/{t.id}').get_json() == {'removed': True}


def test_add_case_rejects_bad_input(user, client):
    assert client.post('/api/cases', json={'tender_id': 999999, 'source': 'report'}).status_code == 404
    assert client.post('/api/cases', json={'tender_id': 1, 'source': 'x'}).status_code == 400


# ── 놓친 공고 ───────────────────────────────────────────────────────────────

def test_missed_lookup(user, client, make_tender):
    t = make_tender(title='2026년도 IT역량교육과정 위탁운영')
    assert client.post('/api/missed/lookup', json={'q': '  '}).status_code == 400
    c = client.post('/api/missed/lookup', json={'q': 'IT역량교육과정'}).get_json()['candidates']
    assert [x['id'] for x in c] == [t.id]


def test_missed_diagnose_records_report(user, client, make_tender):
    t = _fresh(make_tender, '2027년 모바일 서비스 운영관리 용역')
    r = client.post('/api/missed/diagnose', json={'tender_id': t.id, 'q': '모바일'}).get_json()
    assert r['verdict'] == '걸러짐' and '관심 키워드 없음' in r['reasons'] and r['report_id']
    assert case_store.report_counts(user.id) == {'걸러짐': 1}


def test_missed_not_found_records_report(user, client):
    r = client.post('/api/missed/diagnose', json={'q': 'R26BK99999999', 'source_note': '기관 홈페이지'}).get_json()
    assert r['verdict'] == '수집 안 됨' and r['report_id']
    assert client.get('/api/cases/eval').get_json()['report_counts'] == {'수집 안 됨': 1}


def test_eval_endpoint(user, client, make_tender, fake_model):
    _cases(user, make_tender, n=6)
    r = client.post('/api/cases/eval').get_json()
    assert r['answers'] == 6
    got = client.get('/api/cases/eval').get_json()
    assert got['latest']['metrics'] == r and len(got['history']) == 1


def test_requires_login(cases_app, client):
    assert client.get('/api/cases/similar').status_code == 401


# ── 수집 직후 벡터 저장 ─────────────────────────────────────────────────────

def test_crawl_hook_failure_does_not_fail_crawl(monkeypatch):
    import scheduler

    def boom(**kw):
        raise RuntimeError('모델 없음')
    monkeypatch.setattr(tender_vectors, 'encode_missing', boom)
    assert scheduler._store_new_vectors() is None


def test_crawl_hook_reports_count(monkeypatch):
    import scheduler
    monkeypatch.setattr(tender_vectors, 'encode_missing', lambda **kw: 7)
    assert scheduler._store_new_vectors() == 7


def test_cases_page_renders(cases_app, client, login, make_user):
    from routes.pages import bp as pages_bp
    cases_app.register_blueprint(pages_bp)
    login(make_user())
    r = client.get('/cases')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for text in ('놓친 공고 신고', '채점', '사례 점수로 정렬', 'js/cases.js'):
        assert text in html


def test_similar_items_have_rule_score(user, client, make_tender, make_prefs, fake_model):
    from database import UserPreference
    UserPreference.query.filter_by(user_id=user.id).delete(); db.session.commit()
    make_prefs(user, interest=['교육'])
    _cases(user, make_tender)
    _fresh(make_tender, '공공앱 유지관리 용역')
    item = client.get('/api/cases/similar').get_json()['items'][0]
    assert 'relevance_score' in item and item['business_type'] == '유지관리'
