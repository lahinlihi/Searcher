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


def _room_tabs(html):
    """화면 위 '방' 탭: (묶음 이름, [(주소, 이름, 지금 방인가)])"""
    import re
    if 'class="hs-rooms"' not in html:
        return None, []
    part = html[html.index('class="hs-rooms"'):]
    part = part[:part.index('</nav>')]
    name = re.search(r'aria-label="([^"]+)"', part).group(1)
    tabs = [(m.group(2), re.sub(r'<[^>]+>|\s+', '', m.group(3)), 'active' in m.group(1))
            for m in re.finditer(r'<a class="(hs-tab[^"]*)" href="([^"]+)"[^>]*>(.*?)</a>', part, re.S)]
    return name, tabs


NEWSLETTER = ['/newsletter/review', '/newsletter/brief', '/newsletter/settings', '/newsletter/send']
OPS = ['/admin/users', '/settings', '/logs']


def test_nav_has_one_entry_per_hub(full_app, client, login, make_user):
    """관리 메뉴에서 고르는 것은 '편집실' 하나, '운영' 하나다. 그 안의 방은 메뉴에 늘어놓지 않는다."""
    base = {'/', '/search', '/bookmarks', '/cases', '/review-tenders'}
    inner = {'/newsletter/brief', '/newsletter/settings', '/newsletter/send', '/settings', '/logs'}

    _, html = _get(client, login, make_user(role='user'), '/')
    links = _menu_links(html)
    assert base <= links and '/newsletter/review' in links and '/filters' in links
    assert not (({'/admin/users'} | inner) & links)

    _, html = _get(client, login, make_user(role='moderator'), '/')
    links = _menu_links(html)
    assert {'/admin/users', '/newsletter/review', '/filters'} <= links and not (inner & links)

    _, html = _get(client, login, make_user(role='admin'), '/')
    links = _menu_links(html)
    assert {'/admin/users', '/newsletter/review', '/filters'} <= links and not (inner & links)
    head = html[html.index('class="hs-topbar'):html.index('</header>')]
    assert head.count('>편집실<') == 2 and head.count('>운영<') == 2          # 넓은 화면 메뉴 + 휴대폰 메뉴에 하나씩


@pytest.mark.parametrize('path', NEWSLETTER)
def test_newsletter_rooms_are_tabs_in_one_hub(full_app, client, login, make_user, path):
    """편집실 안의 방 네 개: 편집실 → 입찰동향 조건 → 발송 설정 → 발송. 어느 방에서나 같은 탭이 보인다."""
    _, html = _get(client, login, make_user(role='admin'), path)
    name, tabs = _room_tabs(html)
    assert name == '편집실'
    assert [(href, label) for href, label, _ in tabs] == [
        ('/newsletter/review', '1편집실'), ('/newsletter/brief', '2입찰동향조건'),
        ('/newsletter/settings', '3발송설정'), ('/newsletter/send', '4발송')]
    assert [href for href, _, on in tabs if on] == [path]
    head = html[html.index('class="hs-topbar'):html.index('</header>')]
    assert 'href="/newsletter/review" class="active"' in head               # 메뉴의 '편집실'이 켜져 있다


@pytest.mark.parametrize('path', OPS)
def test_ops_rooms_are_tabs_in_one_hub(full_app, client, login, make_user, path):
    _, html = _get(client, login, make_user(role='admin'), path)
    name, tabs = _room_tabs(html)
    assert name == '운영'
    assert [(href, label) for href, label, _ in tabs] == [('/admin/users', '회원관리'), ('/settings', '설정'), ('/logs', '로그')]
    assert [href for href, _, on in tabs if on] == [path]
    head = html[html.index('class="hs-topbar'):html.index('</header>')]
    assert 'href="/admin/users" class="active"' in head


def test_ops_tabs_show_only_rooms_the_role_can_open(full_app, client, login, make_user):
    _, html = _get(client, login, make_user(role='moderator'), '/admin/users')
    name, tabs = _room_tabs(html)
    assert name == '운영' and [href for href, _, _ in tabs] == ['/admin/users']      # 설정·로그는 Admin 만


def test_pages_outside_hubs_have_no_room_tabs(full_app, client, login, make_user):
    u = make_user(role='admin')
    for path in ('/', '/search', '/bookmarks', '/filters', '/cases', '/me'):
        _, html = _get(client, login, u, path)
        assert _room_tabs(html) == (None, []), path


def test_detail_shows_score_parts_and_agency_mark_separately(full_app, client, login, make_user, make_prefs,
                                                           make_tender, add_mark, fake_model):
    """상세 화면: 점수 구성은 키워드·유형 / (사례가 있으면) 닮음. 발주처는 점수 밖의 표시로 따로 나온다."""
    u = make_user(); make_prefs(u, interest=['교육'])
    add_mark(u, '후순위기관', 'low')
    add_mark(u, '중점기관', 'key')

    def side(t):
        _, html = _get(client, login, u, f'/tender/{t.id}')
        part = html[html.index('나와 맞는 정도'):]
        return part[:part.index('</aside>')]

    low = side(make_tender(title='AI 교육 운영 용역', agency='후순위기관'))
    assert '키워드·유형' in low and '후순위 발주처' in low and '중점 발주처' not in low
    assert '>기관<' not in low and '담은 공고와 닮음' not in low       # 담은 공고가 5건 미만이라 닮음 줄은 없다
    assert '발주처 +' not in low and '발주처 −' not in low            # 점수에 더하거나 빼는 숫자는 없다

    key = side(make_tender(title='AI 교육 운영 용역', agency='중점기관'))
    assert '중점 발주처' in key and '후순위 발주처' not in key

    plain = side(make_tender(title='AI 교육 운영 용역', agency='다른기관'))
    assert '중점 발주처' not in plain and '후순위 발주처' not in plain


def test_detail_has_reason_chips_and_flag_line(full_app, client, login, make_user, make_prefs, make_tender, fake_model):
    """상세 화면: 메모 옆에 이유 칩 자리가 있고, 켜 둔 규칙에 걸린 공고에는 '자격 확인 필요' 줄이 나온다."""
    import reasons as RS
    from routes.reasons import bp as reasons_bp
    full_app.register_blueprint(reasons_bp)
    u = make_user(); make_prefs(u, interest=['교육'])
    RS.add_rule(u.id, 'license', ['국외연수'])
    _, html = _get(client, login, u, f"/tender/{make_tender(title='교육 국외연수 운영').id}")
    assert 'id="reason-chips"' in html and '나에게만 보이고' in html
    assert '자격 확인 필요: 업종·등록 요건' in html
    _, html = _get(client, login, u, f"/tender/{make_tender(title='교육 운영 용역').id}")
    assert 'id="reason-chips"' in html and '자격 확인 필요:' not in html      # 안내 문구에는 이 말이 있고, 표시 줄은 없다


def test_filters_page_has_reason_rules_section(full_app, client, login, make_user):
    _, html = _get(client, login, make_user(role='admin'), '/filters')
    for i in ('id="reason-rules"', 'id="reason-candidates"', 'id="reason-rule-list"', 'id="reason-memo-backlog"'):
        assert i in html, i
    assert '표시만 붙고 점수와 순서는 바뀌지 않습니다' in html and '내 화면에만 적용' in html


def test_cases_page_has_no_sort_switch(full_app, client, login, make_user):
    _, html = _get(client, login, make_user(role='admin'), '/cases')
    assert 'id="sort-toggle"' not in html
    assert '사례 점수는 적합도에 항상 절반 반영됩니다' in html


def test_filters_page_has_mark_choice(full_app, client, login, make_user):
    _, html = _get(client, login, make_user(role='admin'), '/filters')
    assert 'id="agency-mark-key"' in html and 'id="agency-mark-low"' in html
    assert 'agency-adjust-input' not in html and 'agency-weight-selector' not in html


def test_existing_badge_ids_kept(full_app, client, login, make_user):
    _, html = _get(client, login, make_user(role='admin'), '/')
    for i in ('id="memo-badge"', 'id="nl-badge"', 'id="nav-search-input"'):
        assert i in html, i
