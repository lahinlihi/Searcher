"""이유 칩과 자격 확인 규칙 (제품 계약서 5부)."""
from datetime import datetime, timedelta

import pytest

import reasons as RS
from database import db, Bookmark


# ── 1단계: 이유 저장 ─────────────────────────────────────────────────────────

def test_options_cover_every_code_once():
    codes = [o['code'] for o in RS.options()]
    assert codes == list(RS.REASONS) and len(set(codes)) == 13
    assert {o['group'] for o in RS.options()} == {'ineligible', 'other', 'like', 'eligible'}
    assert RS.REASONS['license']['label'] == '업종·등록 요건' and RS.REASONS['eligible']['label'] == '자격 가능'


def test_clean():
    assert RS.clean(['size', 'region', 'size']) == ['size', 'region']
    assert RS.clean([]) == []
    for bad in (['nope'], 'size', None, [1], [['size']]):
        with pytest.raises(ValueError):
            RS.clean(bad)
    with pytest.raises(ValueError):
        RS.clean(['like_field'], groups=RS.DISMISS_GROUPS)
    assert RS.clean(['etc', 'license'], groups=RS.DISMISS_GROUPS) == ['etc', 'license']


def test_set_replaces_and_is_per_user(app, make_user, make_tender):
    a, b, t = make_user(), make_user(), make_tender()
    assert RS.set_reasons(a.id, t.id, ['size', 'region']) == ['size', 'region']
    RS.set_reasons(b.id, t.id, ['field'])
    assert RS.set_reasons(a.id, t.id, ['license']) == ['license']        # 통째로 바뀐다
    assert RS.get_reasons(a.id, [t.id]) == {t.id: ['license']}
    assert RS.get_reasons(b.id, [t.id]) == {t.id: ['field']}             # 남의 것은 그대로
    RS.set_reasons(a.id, t.id, [])
    assert RS.get_reasons(a.id, [t.id]) == {}


def test_get_reasons_returns_canonical_order(app, make_user, make_tender):
    u, t = make_user(), make_tender()
    RS.set_reasons(u.id, t.id, ['etc', 'size'])
    assert RS.get_reasons(u.id, [t.id]) == {t.id: ['size', 'etc']}
    assert RS.get_reasons(u.id, []) == {}


def test_set_rejects_unknown_code_without_changing_anything(app, make_user, make_tender):
    u, t = make_user(), make_tender()
    RS.set_reasons(u.id, t.id, ['size'])
    with pytest.raises(ValueError):
        RS.set_reasons(u.id, t.id, ['size', 'bogus'])
    assert RS.get_reasons(u.id, [t.id]) == {t.id: ['size']}
