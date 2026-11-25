"""중점 발주처 칸 (제품 계약서 3부 22.5): 가점을 준 발주처의 아직 안 본 공고를 적합도와 상관없이 모은다."""
from datetime import datetime, timedelta

import pytest

from database import db, Bookmark, DismissedTender, TenderView


@pytest.fixture
def api(tenders_app, client, login, make_user, make_prefs, fake_model):
    u = make_user()
    make_prefs(u, interest=['교육'])
    login(u)

    def get():
        r = client.get('/api/dashboard/key-agencies')
        assert r.status_code == 200, r.get_data(as_text=True)
        return r.get_json()
    return u, get


def _ids(body):
    return [i['id'] for i in body['items']]


def test_lists_new_tenders_of_plus_agencies(api, make_tender, add_adjust):
    u, get = api
    add_adjust(u, '한국콘텐츠진흥원', 20.0)
    hit = make_tender(title='청사 보안 용역', agency='한국콘텐츠진흥원 본원')        # 관심 키워드에 안 걸린다
    make_tender(title='교육 운영 용역', agency='다른기관')
    body = get()
    assert body['agencies'] == ['한국콘텐츠진흥원'] and _ids(body) == [hit.id]
    item = body['items'][0]
    assert item['matched_agency'] == '한국콘텐츠진흥원' and item['score_breakdown']['agency'] == 20.0
    assert 'relevance_score' in item and 'business_type' in item


def test_matches_demand_agency_too(api, make_tender, add_adjust):
    u, get = api
    add_adjust(u, '서울경제진흥원', 10.0)
    hit = make_tender(title='홍보물 제작', agency='조달청', demand_agency='서울경제진흥원')
    assert _ids(get()) == [hit.id]


def test_excludes_minus_and_zero_agencies(api, make_tender, add_adjust):
    u, get = api
    add_adjust(u, '꺼리는기관', -30.0)
    add_adjust(u, '그냥기관', 0.0)
    make_tender(title='교육 운영', agency='꺼리는기관')
    make_tender(title='교육 운영', agency='그냥기관')
    assert get() == {'agencies': [], 'items': []}


def test_longer_minus_name_wins_over_shorter_plus_name(api, make_tender, add_adjust):
    """'서울' 에 가점, '서울시교육청' 에 감점이면 교육청 공고는 감점 발주처다 — 중점 칸에 넣지 않는다."""
    u, get = api
    add_adjust(u, '서울', 10.0)
    add_adjust(u, '서울시교육청', -30.0)
    keep = make_tender(title='홍보물 제작', agency='서울특별시')
    make_tender(title='홍보물 제작', agency='서울시교육청')
    assert _ids(get()) == [keep.id]


def test_excludes_viewed_bookmarked_dismissed(api, make_tender, add_adjust):
    u, get = api
    add_adjust(u, '중점기관', 20.0)
    viewed, kept, hidden, fresh = [make_tender(title=f'용역 {i}', agency='중점기관') for i in range(4)]
    db.session.add(TenderView(user_id=u.id, tender_id=viewed.id, viewed_at=datetime.utcnow()))
    db.session.add(Bookmark(user_id=u.id, tender_id=kept.id, created_at=datetime.utcnow() - timedelta(days=2)))
    db.session.add(DismissedTender(user_id=u.id, tender_id=hidden.id))
    db.session.commit()
    assert _ids(get()) == [fresh.id]


def test_excludes_expired_and_result_notices(api, make_tender, add_adjust):
    u, get = api
    add_adjust(u, '중점기관', 20.0)
    now = datetime.now()
    make_tender(title='지난 용역', agency='중점기관', deadline_date=now - timedelta(days=1))
    make_tender(title='선정 결과', agency='중점기관', status='결과공고')
    make_tender(title='중복 수집', agency='중점기관', is_duplicate=True)
    live = make_tender(title='진행 용역', agency='중점기관')
    assert _ids(get()) == [live.id]


def test_keeps_tender_without_deadline_and_private_contract(api, make_tender, add_adjust):
    u, get = api
    add_adjust(u, '중점기관', 20.0)
    a = make_tender(title='마감일 없는 공고', agency='중점기관', deadline_date=None,
                    created_at=datetime.utcnow() - timedelta(hours=2))
    b = make_tender(title='수의계약 공고', agency='중점기관', bid_method='수의계약',
                    created_at=datetime.utcnow() - timedelta(hours=1))
    assert _ids(get()) == [b.id, a.id]


def test_newest_collected_first_and_limit_15(api, make_tender, add_adjust):
    u, get = api
    add_adjust(u, '중점기관', 20.0)
    base = datetime.utcnow() - timedelta(days=2)
    ts = [make_tender(title=f'용역 {i}', agency='중점기관', created_at=base + timedelta(hours=i)) for i in range(18)]
    assert _ids(get()) == [t.id for t in reversed(ts)][:15]


def test_no_plus_agencies_returns_empty(api, make_tender):
    _, get = api
    make_tender(title='교육 운영', agency='아무기관')
    assert get() == {'agencies': [], 'items': []}


def test_like_wildcards_in_agency_name_are_literal(api, make_tender, add_adjust):
    """등록 이름의 % 나 _ 가 모든 공고에 걸리면 안 된다."""
    u, get = api
    add_adjust(u, '%', 20.0)
    make_tender(title='아무 공고', agency='아무기관')
    assert get()['items'] == []
