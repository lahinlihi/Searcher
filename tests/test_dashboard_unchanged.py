"""대시보드 구역 조건을 함수로 꺼낸 뒤에도 결과가 같은지."""
from datetime import datetime, timedelta

from database import db, Tender


def _original_sections(now):
    """꺼내기 전 api_dashboard 안에 있던 조건 그대로."""
    seven_days_ago = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    not_private = ~Tender.bid_method.contains('수의계약')
    recent_open = [
        Tender.announced_date >= seven_days_ago, Tender.announced_date <= now,
        Tender.status != '사전규격', Tender.status != '결과공고',
        Tender.deadline_date >= now, not_private,
    ]
    return {
        'pre_tenders': Tender.query.filter(
            Tender.deadline_date >= now, Tender.status == '사전규격',
            db.or_(Tender.source_site.contains('나라장터'), Tender.source_site.contains('g2b'))),
        'urgent_tenders': Tender.query.filter(
            *recent_open,
            db.or_(Tender.source_site.contains('나라장터 API'), Tender.source_site.like('%g2b_api%'))),
        'recent_tenders': Tender.query.filter(
            *recent_open, ~Tender.source_site.contains('나라장터'), ~Tender.source_site.like('%g2b%')),
    }


def _seed(make_tender):
    now = datetime.now()
    d = timedelta(days=1)
    for src in ('나라장터 API (용역)', '나라장터 사전규격 (용역)', '서울특별시 입찰공고', 'g2b_api'):
        for status in ('일반', '사전규격', '결과공고', '재공고'):
            for ann in (now - 2 * d, now - 10 * d, now + d, None):
                for dl in (now + 3 * d, now - d, None):
                    for bm in ('일반경쟁', '수의계약', None):
                        make_tender(source_site=src, status=status, announced_date=ann,
                                    deadline_date=dl, bid_method=bm, title='교육 운영 용역')


def test_dashboard_sections_same(tenders_app, make_tender):
    from routes.tenders import dashboard_section_queries
    _seed(make_tender)
    now = datetime.now()
    new, old = dashboard_section_queries(now), _original_sections(now)
    assert set(new) == set(old)
    for k in old:
        a = sorted(t.id for t in old[k].all())
        b = sorted(t.id for t in new[k].all())
        assert a == b and len(a) > 0, k


def test_dashboard_top_n_constant():
    from routes.tenders import DASHBOARD_TOP_N
    assert DASHBOARD_TOP_N == 15


def test_dashboard_response_keys(tenders_app, client, login, make_user, make_prefs, make_tender):
    u = make_user()
    make_prefs(u, interest=['교육'])
    _seed(make_tender)
    login(u)
    r = client.get('/api/dashboard')
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {'summary', 'pre_tenders', 'urgent_tenders', 'recent_tenders',
                         'include_keywords', 'exclude_keywords'}
    assert all(len(body[k]) <= 15 for k in ('pre_tenders', 'urgent_tenders', 'recent_tenders'))
    assert 'case_score' not in r.get_data(as_text=True)


def _many(make_tender, n=40):
    from datetime import datetime, timedelta
    now = datetime.now()
    return [make_tender(title=f'교육 운영 용역 {i}', announced_date=now - timedelta(hours=1),
                        deadline_date=now + timedelta(days=5)) for i in range(n)]


def _view(user, tender, days_ago=0):
    from datetime import datetime, timedelta
    from database import TenderView
    db.session.add(TenderView(user_id=user.id, tender_id=tender.id,
                              viewed_at=datetime.utcnow() - timedelta(days=days_ago)))
    db.session.commit()


def test_dashboard_fresh_drops_read_tenders_at_once(tenders_app, client, login, make_user, make_prefs, make_tender):
    """fresh=1: 열어 본 공고는 (오늘 본 것도) 바로 15칸에서 빠지고 다음 순위가 올라온다."""
    from database import Tender
    u = make_user(); make_prefs(u, interest=['교육']); _many(make_tender); login(u)
    base = [t['id'] for t in client.get('/api/dashboard').get_json()['urgent_tenders']]
    assert len(base) == 15
    _view(u, db.session.get(Tender, base[0]), days_ago=2)
    _view(u, db.session.get(Tender, base[1]), days_ago=0)
    fresh = [t['id'] for t in client.get('/api/dashboard?fresh=1').get_json()['urgent_tenders']]
    assert len(fresh) == 15
    assert base[0] not in fresh and base[1] not in fresh
    assert fresh[:13] == base[2:] and not set(fresh[13:]) & set(base)
    # 파라미터 없는 응답은 그대로다
    assert [t['id'] for t in client.get('/api/dashboard').get_json()['urgent_tenders']] == base


def test_dashboard_fresh_drops_tenders_bookmarked_before_today(tenders_app, client, login, make_user, make_prefs, make_tender):
    from datetime import datetime, timedelta
    from database import Bookmark
    u = make_user(); make_prefs(u, interest=['교육']); _many(make_tender); login(u)
    base = [t['id'] for t in client.get('/api/dashboard').get_json()['urgent_tenders']]
    db.session.add(Bookmark(user_id=u.id, tender_id=base[0], created_at=datetime.utcnow() - timedelta(days=3)))
    db.session.add(Bookmark(user_id=u.id, tender_id=base[1], created_at=datetime.utcnow()))
    db.session.commit()
    fresh = [t['id'] for t in client.get('/api/dashboard?fresh=1').get_json()['urgent_tenders']]
    assert base[0] not in fresh and base[1] in fresh and len(fresh) == 15


def test_viewed_recent(tenders_app, client, login, make_user, make_prefs, make_tender):
    """읽은 공고: 최근에 본 순, 마감 전·7일 안·담지 않았고 숨기지 않은 것만, 최대 15건."""
    from datetime import datetime, timedelta
    from database import Bookmark, DismissedTender
    u = make_user(); make_prefs(u, interest=['교육']); login(u)
    now = datetime.now()
    ok1 = make_tender(title='교육 A'); ok2 = make_tender(title='교육 B')
    expired = make_tender(title='교육 마감', deadline_date=now - timedelta(days=1))
    old = make_tender(title='교육 오래전'); marked = make_tender(title='교육 담음'); hidden = make_tender(title='교육 숨김')
    _view(u, ok1, days_ago=3); _view(u, ok2, days_ago=1); _view(u, expired, 1); _view(u, old, days_ago=8)
    _view(u, marked, 1); _view(u, hidden, 1)
    db.session.add(Bookmark(user_id=u.id, tender_id=marked.id)); db.session.add(DismissedTender(user_id=u.id, tender_id=hidden.id))
    db.session.commit()
    body = client.get('/api/viewed/recent').get_json()
    assert body['days'] == 7
    assert [t['id'] for t in body['items']] == [ok2.id, ok1.id]
    assert body['items'][0]['viewed_at'].endswith('Z') and 'relevance_score' in body['items'][0]
    for t in _many(make_tender, 35):
        _view(u, t, 0)
    assert len(client.get('/api/viewed/recent').get_json()['items']) == 15


def test_clear_read_tender(tenders_app, client, login, make_user, make_prefs, make_tender):
    """읽은 공고에서 지우면 읽은 공고 목록에서 빠지고, 대시보드 목록으로 돌아오지도 않는다. 다시 열어 보면 다시 나온다."""
    from database import TenderView
    u = make_user(); make_prefs(u, interest=['교육']); login(u)
    ts = _many(make_tender, 5)
    _view(u, ts[0], 0)
    assert client.delete(f'/api/viewed/{ts[0].id}').get_json() == {'cleared': True}
    assert client.get('/api/viewed/recent').get_json()['items'] == []
    assert ts[0].id not in [t['id'] for t in client.get('/api/dashboard?fresh=1').get_json()['urgent_tenders']]
    assert ts[0].id in client.get('/api/viewed/ids').get_json()
    assert client.delete('/api/viewed/999999').get_json() == {'cleared': False}
    # 다른 사람의 열람 기록은 건드리지 못한다
    other = make_user()
    db.session.add(TenderView(user_id=other.id, tender_id=ts[1].id)); db.session.commit()
    assert client.delete(f'/api/viewed/{ts[1].id}').get_json() == {'cleared': False}


def test_viewed_ids(tenders_app, client, login, make_user, make_tender):
    from database import TenderView
    u, other = make_user(), make_user()
    a, b = make_tender(), make_tender()
    db.session.add(TenderView(user_id=u.id, tender_id=a.id))
    db.session.add(TenderView(user_id=other.id, tender_id=b.id))
    db.session.commit()
    login(u)
    assert client.get('/api/viewed/ids').get_json() == [a.id]
