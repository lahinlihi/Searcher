from datetime import datetime, timedelta

import pytest

from database import db, DismissedTender
import missed_diagnosis as md

UTC = timedelta(hours=9)


def _fresh(make_tender, title, **kw):
    """방금 적재된 공고. created_at 은 실제 DB 처럼 UTC 로 둔다."""
    now = datetime.now()
    kw.setdefault('announced_date', now - timedelta(hours=1))
    kw.setdefault('deadline_date', now + timedelta(days=10))
    kw.setdefault('created_at', now - UTC)
    return make_tender(title=title, **kw)


def test_find_tender_blank_and_limit(tenders_app, make_tender):
    with pytest.raises(ValueError):
        md.find_tender('   ')
    for i in range(30):
        make_tender(title=f'교육 용역 {i}')
    assert len(md.find_tender('용역')) == 20


def test_find_tender_by_number_and_url(tenders_app, make_tender):
    t = make_tender(title='무관한 제목', tender_number='R26BK01234567', url='https://example.test/a?b=1')
    assert [x.id for x in md.find_tender('R26BK01234567')] == [t.id]
    assert [x.id for x in md.find_tender('https://example.test/a?b=1')] == [t.id]


def test_find_tender_ignores_spacing(tenders_app, make_tender):
    t = make_tender(title='AI·빅데이터 기반 교육 운영')
    assert t.id in [x.id for x in md.find_tender('AI 빅데이터')]


def test_diagnose_no_interest_keyword(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = _fresh(make_tender, '2027년 공공앱 운영관리 용역')
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '걸러짐'
    assert '관심 키워드 없음' in r['reasons']


def test_diagnose_excluded_keyword(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육'], exclude=['청소'])
    t = _fresh(make_tender, '교육 시설 청소 용역')
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '걸러짐'
    assert "제외 키워드 '청소'" in r['reasons']


def test_diagnose_budget(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육'], budget_max=10_000_000)
    t = _fresh(make_tender, '교육 운영 용역', estimated_price=500_000_000)
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '걸러짐' and '금액 범위 밖' in r['reasons']


def test_diagnose_dismissed(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = _fresh(make_tender, '교육 운영 용역')
    db.session.add(DismissedTender(user_id=u.id, tender_id=t.id)); db.session.commit()
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '걸러짐' and '직접 제외함' in r['reasons']


def test_diagnose_duplicate(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = _fresh(make_tender, '교육 운영 용역', is_duplicate=True)
    assert md.diagnose(t, u.id)['verdict'] == '묶임'


def test_diagnose_result_notice(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = _fresh(make_tender, '교육 운영 용역 결과', status='결과공고')
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '걸러짐'
    assert any('결과공고' in x for x in r['reasons'])


def test_diagnose_private_contract(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = _fresh(make_tender, '교육 운영 용역', bid_method='수의계약')
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '걸러짐' and any('수의계약' in x for x in r['reasons'])


def test_diagnose_low_rank(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육', '운영', 'AI', '컨설팅'])
    for i in range(30):
        _fresh(make_tender, f'AI 교육 운영 컨설팅 {i}')
    t = _fresh(make_tender, '교육과정 위탁')
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '순위 낮음'
    assert r['section'] == 'urgent_tenders'
    assert r['rank'] > 24 and r['pool'] == 31
    assert set(r['breakdown']) == {'keyword', 'type', 'case', 'agency', 'base'}
    assert r['breakdown']['agency'] is None and r['score'] == r['breakdown']['base']


def test_diagnose_in_range(tenders_app, make_user, make_prefs, make_tender):
    u = make_user(); make_prefs(u, interest=['교육'])
    t = _fresh(make_tender, '교육 운영 용역')
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '표시 범위 안' and r['rank'] == 1


def test_diagnose_uses_load_time_not_now(tenders_app, make_user, make_prefs, make_tender):
    """지금은 마감이 지났어도, 적재 시점에 마감 전이었으면 기간 때문에 걸러진 것이 아니다."""
    u = make_user(); make_prefs(u, interest=['교육'])
    loaded = datetime.now() - timedelta(days=30)
    t = make_tender(title='교육 운영 용역', announced_date=loaded - timedelta(hours=2),
                    deadline_date=loaded + timedelta(days=5), created_at=loaded - UTC)
    r = md.diagnose(t, u.id)
    assert r['verdict'] == '표시 범위 안'
    assert r['as_of'].startswith(loaded.strftime('%Y-%m-%dT%H'))
