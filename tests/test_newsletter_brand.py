"""메일 본문 — 하이서치가 보낸 것임이 보여야 한다 (2026-11-26 사용자 요청).

머리의 "오늘의 입찰동향 · HR뉴스" 글자 대신 HIGH-SEARCH 로고, 색은 사이트와 같은 주황(#FF5B14).
"""
import os

import newsletter as nl


def _html(monkeypatch):
    monkeypatch.setattr(nl, '_cfg', lambda path, default=None: default)
    data = {'run_date': '2026-11-26',
            'sections': [{'category': '정책', 'headline': '머리기사', 'points': ['요점'], 'synthesis': '시사점 본문',
                          'closing': '', 'articles': []}],
            'tenders': {'count': 7, 'items': [{'id': 1}],
                        'sections': [{'key': 'pre', 'label': '사전규격', 'available': 7,
                                      'items': [{'id': 1, 'title': '공고', 'agency': '기관', 'price': 1.0,
                                                 'deadline': '2026-12-01', 'url': 'https://example.com/1'}]}]}}
    return nl.render_html(data, unsubscribe_url='#')


def test_header_shows_the_logo_instead_of_the_old_title(monkeypatch):
    html = _html(monkeypatch)
    assert '<img src="https://ht-search.com/static/img/logo-mail.png"' in html
    assert 'alt="HIGH-SEARCH"' in html                      # 그림을 막아 둔 메일함에서도 이름이 보인다
    assert '오늘의 입찰동향 &middot; HR뉴스' not in html
    assert '2026년 11월 26일 목요일' in html and 'HR 뉴스' in html and '입찰동향' in html


def test_logo_file_exists_and_is_a_png():
    p = os.path.join(os.path.dirname(nl.__file__), 'static', 'img', 'logo-mail.png')
    assert open(p, 'rb').read(8) == b'\x89PNG\r\n\x1a\n'


def test_mail_uses_site_colors_not_the_old_green(monkeypatch):
    html = _html(monkeypatch).upper()
    assert '#FF5B14' in html                                # 사이트의 주황
    for old in ('#0B6E5F', '#EDF5F3', '#F1F7F5'):           # 예전 초록 계열
        assert old not in html, old
