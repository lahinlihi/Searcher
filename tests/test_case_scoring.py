import numpy as np
import pytest

import case_scoring as cs
import case_store
import tender_vectors as tv
from database import db, Bookmark


class AxisEncoder:
    """제목 첫 글자로 축을 고르는 가짜 인코더: 같은 첫 글자면 거의 같은 벡터."""
    AXES = {'가': 0, '나': 1, '다': 2, '라': 3}

    def encode(self, titles, **kw):
        out = np.zeros((len(titles), tv.DIM), dtype=np.float32)
        for i, t in enumerate(titles):
            out[i, self.AXES.get(t[:1], 10)] = 1.0
            out[i, 20 + (abs(hash(t)) % 50)] = 0.05     # 같은 축 안에서 조금씩 다르게
        return out


def test_knn_scores_top3_mean():
    good = np.eye(4, dtype=np.float32)
    cand = np.array([[1, 1, 1, 0]], np.float32) / np.sqrt(3)
    s, idx = cs.knn_scores(cand, good)
    assert np.isclose(s[0], 1 / np.sqrt(3))
    assert idx[0] in (0, 1, 2)


def test_knn_scores_fewer_than_k():
    good = np.eye(2, 4, dtype=np.float32)
    cand = np.array([[1, 0, 0, 0]], np.float32)
    s, idx = cs.knn_scores(cand, good)
    assert np.isclose(s[0], 0.5) and idx[0] == 0


def test_knn_scores_empty_good():
    with pytest.raises(ValueError):
        cs.knn_scores(np.ones((1, 4), np.float32), np.zeros((0, 4), np.float32))


def _bookmark(user, tender):
    db.session.add(Bookmark(user_id=user.id, tender_id=tender.id))
    db.session.commit()


def test_good_case_ids_union_no_double_count(app, make_user, make_tender):
    u, a, b = make_user(), make_tender(), make_tender()
    _bookmark(u, a)
    case_store.add_case(u.id, a.id, 'report')
    case_store.add_case(u.id, b.id, 'report')
    assert cs.good_case_ids(u.id) == {a.id, b.id}


def test_good_case_ids_ignores_other_users_bookmarks(app, make_user, make_tender):
    u, other, a = make_user(), make_user(), make_tender()
    _bookmark(other, a)
    assert cs.good_case_ids(u.id) == set()


def _cases(u, make_tender, n, prefix='가'):
    ts = [make_tender(title=f'{prefix} 사례 {i}') for i in range(n)]
    for t in ts:
        case_store.add_case(u.id, t.id, 'report')
    return ts


def test_score_tenders_none_below_min_cases(app, make_user, make_tender, tmp_path):
    u = make_user()
    _cases(u, make_tender, 4)
    cand = make_tender(title='가 후보')
    assert cs.score_tenders(u.id, [cand], vec_conn=tv.connect(str(tmp_path / 'v.db')),
                            encoder=AxisEncoder()) is None


def test_score_tenders_similar_scores_higher(app, make_user, make_tender, tmp_path):
    u = make_user()
    cases = _cases(u, make_tender, 5)
    near, far = make_tender(title='가 비슷한 후보'), make_tender(title='나 다른 후보')
    r = cs.score_tenders(u.id, [near, far], vec_conn=tv.connect(str(tmp_path / 'v.db')), encoder=AxisEncoder())
    assert r[near.id]['case_score'] > r[far.id]['case_score']
    assert 0 <= r[far.id]['case_score'] <= 100
    assert r[near.id]['nearest_case']['id'] in {c.id for c in cases}
    assert r[near.id]['nearest_case']['title'].startswith('가 사례')


def test_score_tenders_excludes_self(app, make_user, make_tender, tmp_path):
    u = make_user()
    cases = _cases(u, make_tender, 5)
    r = cs.score_tenders(u.id, [cases[0]], vec_conn=tv.connect(str(tmp_path / 'v.db')), encoder=AxisEncoder())
    assert r[cases[0].id]['nearest_case']['id'] != cases[0].id


def test_score_tenders_none_without_model(app, make_user, make_tender, tmp_path, monkeypatch):
    import scoring
    monkeypatch.setattr(scoring, '_get_embed_model', lambda block=False: None)
    u = make_user()
    _cases(u, make_tender, 5)
    assert cs.score_tenders(u.id, [make_tender(title='가 후보')], vec_conn=tv.connect(str(tmp_path / 'v.db'))) is None
