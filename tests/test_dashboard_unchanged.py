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
    assert DASHBOARD_TOP_N == 24


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
    assert all(len(body[k]) <= 24 for k in ('pre_tenders', 'urgent_tenders', 'recent_tenders'))
    assert 'case_score' not in r.get_data(as_text=True)
