"""모든 화면이 새 공통 틀(상단 막대·디자인 규칙)로 오류 없이 열리는지, 메뉴가 권한대로 보이는지."""
import pytest

PAGES = ['/', '/search', '/bookmarks', '/cases', '/review-tenders', '/filters', '/me',
         '/newsletter/review', '/newsletter/send', '/newsletter/brief', '/newsletter/settings',
         '/admin/users', '/settings', '/logs']


@pytest.fixture
def full_app(app):
    from routes.pages import bp as pages_bp
    from routes.tenders import bp as tenders_bp
    from routes.cases import bp as cases_bp
    from routes.bookmarks import bp as bookmarks_bp
    from routes.auth import bp as auth_bp
    from routes.admin import bp as admin_bp
    from routes.filters import bp as filters_bp
    from routes.newsletter import bp as newsletter_bp
    for b in (pages_bp, tenders_bp, cases_bp, bookmarks_bp, auth_bp, admin_bp, filters_bp, newsletter_bp):
        app.register_blueprint(b)
    # app.py 가 등록하는 템플릿 전역·필터의 시험용 대역 (app.py 를 임포트하면 운영 DB·스케줄러가 붙는다)
    from datetime import datetime
    app.jinja_env.globals['now'] = datetime.now
    app.jinja_env.globals['parse_g2b_dt'] = lambda s: None
    app.jinja_env.filters['safe_url'] = lambda u: u or '#'
    app.jinja_env.filters['format_price'] = lambda p: f'{p}원' if p else '미정'
    return app


def _get(client, login, user, path):
    login(user)
    r = client.get(path)
    return r.status_code, r.get_data(as_text=True)


@pytest.mark.parametrize('path', PAGES)
def test_page_renders_with_new_shell(full_app, client, login, make_user, path):
    code, html = _get(client, login, make_user(role='admin'), path)
    assert code == 200, path
    assert 'class="hs-topbar' in html
    assert 'css/hs-theme.css' in html
    assert 'IBM+Plex+Sans+KR' in html


def test_tender_detail_renders_with_new_shell(full_app, client, login, make_user, make_tender):
    t = make_tender(title='교육 운영 용역')
    code, html = _get(client, login, make_user(role='admin'), f'/tender/{t.id}')
    assert code == 200 and 'class="hs-topbar' in html


def test_login_page_renders(full_app, client):
    r = client.get('/login')
    assert r.status_code == 200 and 'css/hs-theme.css' in r.get_data(as_text=True)


def _menu_links(html):
    import re
    start = html.index('class="hs-topbar')
    end = html.index('</header>', start)
    return set(re.findall(r'href="(/[^"#?]*)"', html[start:end]))


def test_nav_admin_items_by_role(full_app, client, login, make_user):
    base = {'/', '/search', '/bookmarks', '/cases', '/review-tenders'}
    _, html = _get(client, login, make_user(role='user'), '/')
    links = _menu_links(html)
    assert base <= links
    assert not ({'/admin/users', '/settings', '/logs'} & links)

    _, html = _get(client, login, make_user(role='moderator'), '/')
    links = _menu_links(html)
    assert '/admin/users' in links and '/newsletter/review' in links
    assert not ({'/settings', '/logs'} & links)

    _, html = _get(client, login, make_user(role='admin'), '/')
    assert {'/admin/users', '/settings', '/logs', '/filters'} <= _menu_links(html)


def test_detail_shows_new_score_parts(full_app, client, login, make_user, make_prefs, make_tender, add_adjust, fake_model):
    """상세 화면의 점수 구성: 키워드·유형 / (사례가 있으면) 닮음 / (가감점이 있으면) 발주처. 예전 '기관 10점' 막대는 없다."""
    u = make_user(); make_prefs(u, interest=['교육'])
    add_adjust(u, '테스트기관', -30.0)
    t = make_tender(title='AI 교육 운영 용역')
    _, html = _get(client, login, u, f'/tender/{t.id}')
    side = html[html.index('나와 맞는 정도'):]
    side = side[:side.index('</aside>')]
    assert '키워드·유형' in side and '발주처 −30' in side
    assert '>기관<' not in side and '담은 공고와 닮음' not in side      # 담은 공고가 5건 미만이라 닮음 줄은 없다

    plain = make_tender(title='AI 교육 운영 용역', agency='다른기관')
    _, html = _get(client, login, u, f'/tender/{plain.id}')
    assert '발주처 −30' not in html and '발주처 +' not in html


def test_cases_page_has_no_sort_switch(full_app, client, login, make_user):
    _, html = _get(client, login, make_user(role='admin'), '/cases')
    assert 'id="sort-toggle"' not in html
    assert '사례 점수는 적합도에 항상 절반 반영됩니다' in html


def test_filters_page_has_adjust_input(full_app, client, login, make_user):
    _, html = _get(client, login, make_user(role='admin'), '/filters')
    assert 'id="agency-adjust-input"' in html and 'agency-weight-selector' not in html


def test_existing_badge_ids_kept(full_app, client, login, make_user):
    _, html = _get(client, login, make_user(role='admin'), '/')
    for i in ('id="memo-badge"', 'id="nl-badge"', 'id="nav-search-input"'):
        assert i in html, i
