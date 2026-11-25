"""뉴스레터 입찰동향의 A/B/C 분류 — AI 응답 모양이 달라도 죽지 않는다.

2026-11-25 운영 로그: `[HR뉴스] 입찰동향 분류 실패: AttributeError: 'list' object has no attribute 'get'`
(응답이 {"items": [...]} 가 아니라 목록으로 왔다. 그 여파로 그날 메일용 입찰동향이 저장되지 않았다.)
"""
import sqlite3

import pytest

import tender_brief as tb


@pytest.fixture
def conn(monkeypatch):
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    tb.ensure_schema(c)
    monkeypatch.setattr(tb.time, 'sleep', lambda s: None)
    yield c
    c.close()


ROWS = [{'id': 11, 'title': '재직자 교육 참여기업 모집', 'agency': '가기관', 'demand_agency': None, 'source_site': 's'},
        {'id': 12, 'title': '청사 유지보수 용역', 'agency': '나기관', 'demand_agency': None, 'source_site': 's'},
        {'id': 13, 'title': '인사발령 공고', 'agency': '다기관', 'demand_agency': None, 'source_site': 's'}]


def _saved(c):
    return {r['tender_id']: (r['class'], r['hr_related'])
            for r in c.execute('SELECT tender_id, class, hr_related FROM tender_classes')}


def _answer(monkeypatch, out):
    monkeypatch.setattr(tb, '_call', lambda prompt, api_key=None: (out, 'test-model'))


def test_classify_accepts_object_with_items(conn, monkeypatch):
    _answer(monkeypatch, {'items': [{'n': 1, 'class': 'A', 'hr_related': True}, {'n': 2, 'class': 'b'}]})
    assert tb.classify(conn, ROWS, api_key='x', quiet=True) == (2, 1)
    assert _saved(conn) == {11: ('A', 1), 12: ('B', 0)}


def test_classify_accepts_bare_list(conn, monkeypatch):
    """응답이 목록으로 와도 같은 결과여야 한다 (운영에서 난 오류)."""
    _answer(monkeypatch, [{'n': 1, 'class': 'A', 'hr_related': True}, {'n': 3, 'class': 'C', 'hr_related': False}])
    assert tb.classify(conn, ROWS, api_key='x', quiet=True) == (2, 1)
    assert _saved(conn) == {11: ('A', 1), 13: ('C', 0)}


@pytest.mark.parametrize('out', [
    {'items': None}, {'items': 'ABC'}, {'result': []}, 'A', 7, [1, 'x', None],
    [{'n': 9, 'class': 'A'}],            # 범위를 벗어난 번호
    [{'n': 1, 'class': ''}],             # 빈 등급
    [{'n': 1}],                          # 등급 없음
    [{'n': '1', 'class': 'A'}],          # 번호가 숫자가 아님
    [{'n': 1, 'class': 'D'}],
])
def test_classify_skips_unusable_answers_without_crashing(conn, monkeypatch, out):
    _answer(monkeypatch, out)
    assert tb.classify(conn, ROWS, api_key='x', quiet=True) == (0, 1)
    assert _saved(conn) == {}
