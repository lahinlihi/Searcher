"""3부 전체 검토에서 나온 지적을 고정하는 테스트."""
import relevance as R
from database import db


# ── 유형 하나를 낮췄다고 다른 공고의 점수가 오르면 안 된다 ──────────────────────

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


# ── 관심 키워드가 없는 계정은 모든 점수가 0 ─────────────────────────────────────

def test_no_keywords_account_scores_zero(app, make_user, make_tender, add_mark, vec_db):
    u = make_user()
    add_mark(u, '테스트기관', 'key')
    r = R.Scorer(u.id, vec_conn=vec_db).score([make_tender(title='AI 교육 운영 용역')])
    r = next(iter(r.values()))
    assert r['total'] == 0.0 and r['agency'] == 'key'     # 표시는 점수와 별도라 그대로 붙는다
