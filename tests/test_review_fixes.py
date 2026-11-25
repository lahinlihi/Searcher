"""3부 전체 검토에서 나온 지적을 고정하는 테스트."""
import sqlite3
from datetime import datetime

import relevance as R
from database import db, AgencyWeight


# ── 지적 1: 유형 하나를 낮췄다고 다른 공고의 점수가 오르면 안 된다 ──────────────

def test_type_max_never_below_default():
    # 가중치를 주지 않은 유형은 25점을 받는다 — 만점이 그보다 작으면 100점을 넘는 점수가 생긴다
    assert R.type_max({'행사운영': 15}) == 25.0
    assert R.type_max({'행사운영': 15, '교육운영': 35}) == 35.0


def test_lowering_one_type_does_not_raise_other_tenders(app, make_user, make_tender, make_prefs, vec_db):
    import json
    from database import UserPreference
    u = make_user(); make_prefs(u, interest=['교육'])
    t = make_tender(title='AI 교육 운영 용역')
    before = R.Scorer(u.id, vec_conn=vec_db).score([t])[t.id]
    assert before['business_type'] != '행사운영'
    p = UserPreference.query.filter_by(user_id=u.id).first()
    p.type_weights = json.dumps({'행사운영': 15}, ensure_ascii=False)
    db.session.commit()
    assert R.Scorer(u.id, vec_conn=vec_db).score([t])[t.id]['total'] == before['total']


# ── 지적 2: 관심 키워드가 없는 계정은 가감점이 있어도 모든 점수가 0 ─────────────

def test_no_keywords_account_scores_zero_even_with_adjust(app, make_user, make_tender, add_adjust, vec_db):
    u = make_user()
    add_adjust(u, '테스트기관', 20.0)
    r = R.Scorer(u.id, vec_conn=vec_db).score([make_tender(title='AI 교육 운영 용역')])
    r = next(iter(r.values()))
    assert r['total'] == 0.0 and r['agency'] == 0.0      # 상세 화면("관심 키워드를 설정하면…")과 같은 답


# ── 지적 3-1: 중점 발주처 조회 — 등록 이름의 _ 와 % 는 글자 그대로 ──────────────

def test_key_agency_query_escapes_like_wildcards(app, make_tender):
    from routes.tenders import _key_agency_candidates
    make_tender(title='아무 공고', agency='기관')
    hit = make_tender(title='밑줄 공고', agency='기_')
    now = datetime.now()
    assert [t.id for t in _key_agency_candidates(['기_'], now)] == [hit.id]
    assert _key_agency_candidates(['%'], now) == []


# ── 지적 3-2: 이전 도구 — --apply 없이는 쓰지 않고, 비어 있는 행에만 쓴다 ────────

def _dump(path):
    c = sqlite3.connect(path)
    try:
        return c.execute('SELECT id, agency_name, weight, adjust FROM agency_weights ORDER BY id').fetchall()
    finally:
        c.close()


def test_migrate_tool_writes_only_with_apply_and_only_null_rows(app, make_user, tmp_path, capsys):
    from tools import agency_adjust_migrate as tool
    u = make_user()
    db.session.add_all([
        AgencyWeight(user_id=u.id, agency_name='가점기관', weight=10.0),
        AgencyWeight(user_id=u.id, agency_name='감점기관', weight=0.0),
        AgencyWeight(user_id=u.id, agency_name='이미정함', weight=10.0, adjust=-5.0),
    ])
    db.session.commit()
    db.session.remove()
    path = str(tmp_path / 'test.db')
    before = _dump(path)

    assert tool.main(['--db', path]) == 0
    assert _dump(path) == before                          # 표만 출력
    assert '가점기관' in capsys.readouterr().out

    assert tool.main(['--db', path, '--apply']) == 0
    after = {name: adj for _, name, _, adj in _dump(path)}
    assert after == {'가점기관': 20.0, '감점기관': -20.0, '이미정함': -5.0}
    assert [(i, n, w) for i, n, w, _ in _dump(path)] == [(i, n, w) for i, n, w, _ in before]   # 예전 값은 그대로

    assert tool.main(['--db', path, '--apply']) == 0      # 두 번 돌려도 같다
    assert {name: adj for _, name, _, adj in _dump(path)} == after
