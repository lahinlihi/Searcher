"""어느 화면에서나 같은 공고는 같은 적합도 (제품 계약서 3부 23절)."""
from datetime import datetime, timedelta

import numpy as np
import pytest

import relevance as R
import tender_vectors
from database import db, Bookmark


def _axis(i):
    v = np.zeros(tender_vectors.DIM, dtype=np.float32)
    v[i] = 1.0
    return v


@pytest.fixture
def site(app, client, login, make_user, make_prefs, fake_model):
    """화면 API 가 모두 붙은 앱 + 관심 키워드 '교육' 을 가진 로그인 사용자."""
    from routes.pages import bp as pages_bp
    from routes.tenders import bp as tenders_bp
    from routes.cases import bp as cases_bp
    from routes.bookmarks import bp as bookmarks_bp
    for b in (pages_bp, tenders_bp, cases_bp, bookmarks_bp):
        app.register_blueprint(b)
    app.jinja_env.globals['now'] = datetime.now
    app.jinja_env.globals['parse_g2b_dt'] = lambda s: None
    app.jinja_env.filters['safe_url'] = lambda u: u or '#'
    app.jinja_env.filters['format_price'] = lambda p: f'{p}원' if p else '미정'
    u = make_user()
    make_prefs(u, interest=['교육'])
    login(u)
    return client, u


def _store(pairs):
    conn = tender_vectors.connect()
    try:
        tender_vectors.store(conn, [t.id for t, _ in pairs], [v for _, v in pairs])
    finally:
        conn.close()


def _five_cases(u, make_tender):
    """담은 공고 5건 (마감이 지나 대시보드에는 안 나온다). 벡터는 모두 0번 축."""
    old = datetime.now() - timedelta(days=60)
    goods = [make_tender(title=f'교육 사례 {i}', announced_date=old, deadline_date=old + timedelta(days=5))
             for i in range(5)]
    for g_ in goods:
        db.session.add(Bookmark(user_id=u.id, tender_id=g_.id))
    db.session.commit()
    _store([(g_, _axis(0)) for g_ in goods])
    return goods


def test_same_tender_same_score_everywhere(site, make_tender, add_mark):
    client, u = site
    _five_cases(u, make_tender)
    add_mark(u, '테스트기관', 'key')
    x = make_tender(title='AI 교육 운영 용역')
    _store([(x, _axis(0))])
    db.session.add(Bookmark(user_id=u.id, tender_id=x.id)); db.session.commit()

    want = R.Scorer(u.id).score([x])[x.id]
    assert want['case'] == 100.0 and want['agency'] == 'key' and 0 < want['total'] < 100

    dash = client.get('/api/dashboard').get_json()
    d = next(i for i in dash['urgent_tenders'] if i['id'] == x.id)
    assert d['relevance_score'] == want['total']
    assert d['score_breakdown'] == {'keyword': want['keyword'], 'type': want['type'], 'case': 100.0,
                                    'agency': 'key', 'base': want['base']}
    assert d['nearest_case']['title'].startswith('교육 사례')

    found = client.get('/api/tenders?keyword=교육').get_json()['tenders']
    assert next(i for i in found if i['id'] == x.id)['relevance_score'] == want['total']

    bm = client.get('/api/bookmarks').get_json()
    assert next(i for i in bm if i['id'] == x.id)['relevance_score'] == want['total']

    emb = client.post('/api/embed-scores', json={'tender_ids': [x.id]}).get_json()['scores'][str(x.id)]
    assert emb['score'] == want['total'] and emb['case'] == 100.0 and emb['agency'] == 'key'

    html = client.get(f'/tender/{x.id}').get_data(as_text=True)
    assert f">{want['total']:.1f}<" in html and '중점 발주처' in html


def test_dashboard_has_no_case_sort_flag(site, make_tender):
    client, u = site
    _five_cases(u, make_tender)
    make_tender(title='AI 교육 운영 용역')
    assert 'case_sort' not in client.get('/api/dashboard').get_json()


def test_dashboard_orders_by_total_with_cases_mixed(site, make_tender):
    client, u = site
    _five_cases(u, make_tender)
    now = datetime.now()
    near = make_tender(title='AI 교육 운영 용역', announced_date=now - timedelta(days=2))
    far = make_tender(title='AI 교육 운영 용역', announced_date=now, tender_number='FAR00001')
    _store([(near, _axis(0)), (far, _axis(1))])
    ids = [i['id'] for i in client.get('/api/dashboard').get_json()['urgent_tenders']]
    assert ids.index(near.id) < ids.index(far.id)      # 닮은 공고가 더 새 공고보다 위


def test_dashboard_without_cases_orders_by_base_then_date(site, make_tender):
    client, u = site
    now = datetime.now()
    old = make_tender(title='AI 교육 운영 용역', announced_date=now - timedelta(days=2))
    new = make_tender(title='AI 교육 운영 용역', announced_date=now, tender_number='NEW00001')
    items = client.get('/api/dashboard').get_json()['urgent_tenders']
    assert [i['id'] for i in items] == [new.id, old.id]
    assert items[0]['score_breakdown']['case'] is None and items[0]['score_breakdown']['agency'] is None
    assert 'nearest_case' not in items[0]


def test_bookmark_label_bonus_capped(site, make_tender, monkeypatch):
    client, u = site
    _five_cases(u, make_tender)
    x = make_tender(title='AI 교육 운영 용역')
    _store([(x, _axis(0))])
    label = next(iter(Bookmark.LABEL_BONUS))
    bonus = 60                                   # 어떤 점수에 더해도 100 을 넘는 보너스로 자르기를 확인한다
    monkeypatch.setitem(Bookmark.LABEL_BONUS, label, bonus)
    db.session.add(Bookmark(user_id=u.id, tender_id=x.id, label=label)); db.session.commit()
    total = R.Scorer(u.id).score([x])[x.id]['total']
    assert total < 100 < total + bonus, total
    item = next(i for i in client.get('/api/bookmarks').get_json() if i['id'] == x.id)
    assert item['relevance_score'] == 100.0 and item['label_bonus'] == bonus


def test_search_without_interest_keywords_scores_zero(app, client, login, make_user, make_tender, make_prefs,
                                                      fake_model):
    from routes.tenders import bp
    app.register_blueprint(bp)
    u = make_user(); make_prefs(u)   # 빈 설정 행 (설정 행이 없으면 data/settings.json 의 키워드로 떨어진다)
    login(u)
    t = make_tender(title='AI 교육 운영 용역')
    item = next(i for i in client.get('/api/tenders').get_json()['tenders'] if i['id'] == t.id)
    assert item['relevance_score'] == 0


def test_low_agency_keeps_score_and_goes_to_bottom(site, make_tender, add_mark):
    """후순위 발주처: 점수는 그대로, 목록에서는 더 약한 공고보다도 아래. 검색에서도 사라지지 않는다."""
    client, u = site
    strong = make_tender(title='교육 운영 용역', agency='후순위기관')                      # 유형이 잡힌다
    weak = make_tender(title='교육 자료', agency='다른기관', tender_number='WEAK0001')     # 유형 없음 → 더 낮다
    get = lambda: client.get('/api/dashboard').get_json()['urgent_tenders']
    before = get()
    assert [i['id'] for i in before] == [strong.id, weak.id]
    add_mark(u, '후순위기관', 'low')
    after = get()
    assert [i['id'] for i in after] == [weak.id, strong.id]
    assert after[1]['relevance_score'] == before[0]['relevance_score']
    assert after[1]['score_breakdown']['agency'] == 'low'
    found = [i['id'] for i in client.get('/api/tenders?keyword=교육').get_json()['tenders']]
    assert found.index(weak.id) < found.index(strong.id)


def test_low_agency_drops_out_of_dashboard_top_n_when_enough_others(site, make_tender, add_mark):
    from routes.tenders import DASHBOARD_TOP_N
    client, u = site
    add_mark(u, '후순위기관', 'low')
    low = make_tender(title='교육 운영 용역', agency='후순위기관')
    for i in range(DASHBOARD_TOP_N):
        make_tender(title=f'교육 자료 {i}', agency='다른기관')
    ids = [i['id'] for i in client.get('/api/dashboard').get_json()['urgent_tenders']]
    assert len(ids) == DASHBOARD_TOP_N and low.id not in ids


def test_brief_scores_use_new_scale():
    import scoring
    import tender_brief
    row = {'id': 1, 'title': 'AI 교육 운영 용역', 'agency': '테스트기관', 'demand_agency': None,
           'status': '일반', 'estimated_price': None, 'announced_date': None}
    cfg = {'include_keywords': ['교육'], 'core_keywords': [], 'type_weights': {}}
    _, btype, kw, ty, _ = scoring._score_and_type(tender_brief._Row(row), ['교육'], {}, None, [])
    want = round(R.base_score(kw, ty, 25.0), 1)
    assert tender_brief.score_rows([row], cfg) == {1: (want, btype)}
    # 예전 설정에 발주처 값이 남아 있어도 점수는 같다 (발주처는 적합도에 들어가지 않는다)
    cfg['agency_weights'] = {'테스트기관': 0}
    assert tender_brief.score_rows([row], cfg) == {1: (want, btype)}
