"""메일의 '외 N건' — 누르면 그 구분의 전체 목록이 열린다 (2026-11-26 사용자 요청).

- 누구나 볼 수 있다 (로그인 없음).
- 메일을 보낸 날 그대로의 목록이다 — 보낼 때 보관해 둔 것을 보여 준다.
- 일주일만 보관한다 (자료가 쌓이지 않게).
"""
import sqlite3
from datetime import datetime, timedelta

import pytest

import newsletter as nl
import tender_brief as tb


def _item(i, sec, title=None, url='https://example.com/t'):
    return {'id': i, 'title': title or f'{sec} 공고 {i}', 'agency': f'기관{i}', 'price': 1.5, 'deadline': '2026-12-01',
            'url': f'{url}{i}', 'class': None, 'hr_related': False, 'status': '일반', 'section': sec, 'score': 90 - i, 'type': '기타'}


def _brief(n_pre=13, n_normal=12, n_support=5):
    """구분별 전체 목록(all)과 그중 메일에 싣는 것(items)."""
    secs = []
    for key, label, n, limit in (('pre', '사전규격', n_pre, 10), ('normal', '일반공고', n_normal, 10), ('support', '지원사업', n_support, 5)):
        every = [_item(i, key) for i in range(1, n + 1)]
        secs.append({'key': key, 'label': label, 'limit': limit, 'days': 7, 'available': n, 'items': every[:limit], 'all': every})
    return {'count': n_pre + n_normal + n_support, 'items': [it for s in secs for it in s['items']], 'sections': secs}


@pytest.fixture
def conn():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    yield c
    c.close()


# ── 보관 ─────────────────────────────────────────────────────────────────────

def test_archive_keeps_full_lists_per_section(conn):
    tb.archive_brief(conn, '2026-11-26', _brief(), kind='real')
    got = tb.archived_brief(conn, '2026-11-26')
    assert [(s['key'], s['label'], len(s['items'])) for s in got['sections']] == [('pre', '사전규격', 13), ('normal', '일반공고', 12), ('support', '지원사업', 5)]
    assert got['sections'][0]['items'][12]['title'] == 'pre 공고 13'
    assert tb.archived_brief(conn, '2026-11-25') is None


def test_real_send_archive_is_never_overwritten(conn):
    """정식 발송 때의 목록이 그날의 목록이다. 그 뒤의 테스트 발송·미리보기·재발송이 바꾸지 못한다."""
    tb.archive_brief(conn, '2026-11-26', _brief(n_pre=11), kind='preview')
    tb.archive_brief(conn, '2026-11-26', _brief(n_pre=13), kind='real')          # 정식 발송이 미리보기 것을 덮는다
    for kind in ('preview', 'test', 'real'):
        tb.archive_brief(conn, '2026-11-26', _brief(n_pre=20), kind=kind)
    assert len(tb.archived_brief(conn, '2026-11-26')['sections'][0]['items']) == 13


def test_archive_is_kept_for_one_week_only(conn):
    now = datetime(2026, 11, 26, 9, 0, tzinfo=tb.KST)
    tb.archive_brief(conn, '2026-11-18', _brief(), kind='real', now=now - timedelta(days=8))
    tb.archive_brief(conn, '2026-11-20', _brief(), kind='real', now=now - timedelta(days=6))
    tb.archive_brief(conn, '2026-11-26', _brief(), kind='real', now=now)          # 저장할 때 오래된 것을 지운다
    assert [r[0] for r in conn.execute('SELECT run_date FROM brief_archives ORDER BY run_date')] == ['2026-11-20', '2026-11-26']
    # 지우는 작업이 아직 돌지 않았어도, 일주일이 지난 것은 보여 주지 않는다
    assert tb.archived_brief(conn, '2026-11-20', now=now + timedelta(days=2)) is None
    assert tb.archived_brief(conn, '2026-11-26', now=now + timedelta(days=2)) is not None
    assert tb.ARCHIVE_DAYS == 7


def test_archive_without_full_lists_falls_back_to_shown_items(conn):
    old = _brief()
    for s in old['sections']:
        del s['all']                                  # 이 기능 전에 저장된 목록
    tb.archive_brief(conn, '2026-11-26', old, kind='real')
    assert len(tb.archived_brief(conn, '2026-11-26')['sections'][0]['items']) == 10


# ── 메일의 링크 ──────────────────────────────────────────────────────────────

def test_mail_more_count_is_a_link_to_that_section():
    html = nl._tenders_html(_brief(), more_url='https://ht-search.com/newsletter/tenders/2026-11-26')
    assert '<a href="https://ht-search.com/newsletter/tenders/2026-11-26?section=pre"' in html
    assert '<a href="https://ht-search.com/newsletter/tenders/2026-11-26?section=normal"' in html
    assert '외 3건' in html and '외 2건' in html
    assert 'section=support' not in html              # 지원사업은 5건이 전부라 '외'가 없다
    assert 'pre 공고 13' not in html                  # 전체 목록은 메일에 싣지 않는다


def test_mail_without_more_url_keeps_plain_text():
    html = nl._tenders_html(_brief())
    assert '외 3건' in html and '/newsletter/tenders/' not in html


# ── 공개 페이지 ──────────────────────────────────────────────────────────────

@pytest.fixture
def site(app, client, monkeypatch, tmp_path):
    import hr_news
    monkeypatch.setattr(hr_news, 'DB_PATH', str(tmp_path / 'news.db'))      # 운영 DB 를 건드리지 않게
    from routes.newsletter import bp
    app.register_blueprint(bp)
    c = hr_news.connect()
    yield client, c
    c.close()


def test_public_page_shows_full_list_without_login(site):
    client, c = site
    tb.archive_brief(c, '2026-11-26', _brief(), kind='real')
    r = client.get('/newsletter/tenders/2026-11-26?section=pre')
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'pre 공고 1<' in html and 'pre 공고 13<' in html and html.count('class="row"') == 13
    assert 'normal 공고 1<' not in html               # 고른 구분만
    assert '사전규격' in html and '일반공고' in html and '지원사업' in html      # 다른 구분으로 가는 탭
    assert '2026년 11월 26일' in html and 'noindex' in html
    assert 'https://example.com/t13' in html


def test_public_page_defaults_to_first_section_and_ignores_unknown_section(site):
    client, c = site
    tb.archive_brief(c, '2026-11-26', _brief(), kind='real')
    for q in ('', '?section=nope', '?section='):
        html = client.get('/newsletter/tenders/2026-11-26' + q).get_data(as_text=True)
        assert 'pre 공고 13<' in html, q


def test_public_page_for_missing_or_expired_date(site):
    client, c = site
    r = client.get('/newsletter/tenders/2026-11-26')
    assert r.status_code == 404 and '보관 기간' in r.get_data(as_text=True)
    old = datetime.now(tb.KST) - timedelta(days=8)
    tb.archive_brief(c, old.strftime('%Y-%m-%d'), _brief(), kind='real', now=old)
    r = client.get('/newsletter/tenders/' + old.strftime('%Y-%m-%d'))
    assert r.status_code == 404 and '보관 기간' in r.get_data(as_text=True)
    for bad in ('/newsletter/tenders/abc', '/newsletter/tenders/2026-13-99', "/newsletter/tenders/2026-11-26'--"):
        assert client.get(bad).status_code == 404, bad


def test_public_page_escapes_titles_and_drops_unsafe_links(site):
    client, c = site
    b = _brief(n_pre=2)
    b['sections'][0]['all'][0].update(title='<script>alert(1)</script>', url='javascript:alert(1)')
    b['sections'][0]['all'][1].update(agency='<b>기관</b>', url=None)
    tb.archive_brief(c, '2026-11-26', b, kind='real')
    html = client.get('/newsletter/tenders/2026-11-26').get_data(as_text=True)
    assert '<script>alert' not in html and '&lt;script&gt;' in html
    assert 'javascript:' not in html and '<b>기관</b>' not in html
