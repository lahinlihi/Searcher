"""사례로 배우는 점수.

좋은 사례 = 그 사용자의 북마크 ∪ 신고·[좋음]으로 넣은 공고.
사례 점수 = 공고 제목 벡터와 좋은 사례 벡터들의 코사인 유사도 중 상위 3개의 평균 (0~100 으로 표시).
좋은 사례가 5건 미만이면 점수를 내지 않는다 (None) — 화면은 기존 점수만 쓴다.
"""
import numpy as np

import case_store
import tender_vectors
from database import Bookmark, Tender

MIN_CASES = 5
TOP_K = 3


def knn_scores(cand, good, k=TOP_K, exclude=None):
    """cand (n,d), good (m,d) — 둘 다 길이 1로 정규화돼 있어야 한다.
    exclude: 길이 n, 각 후보가 good 의 몇 번째 행과 같은 공고인지 (없으면 -1). 그 칸은 비교에서 뺀다.
    반환: (점수 n개, 가장 비슷한 good 행 번호 n개). 비교할 사례가 없는 후보는 점수 nan, 번호 -1."""
    if len(good) == 0:
        raise ValueError('좋은 사례가 없습니다')
    sims = cand @ good.T
    if exclude is not None:
        for i, j in enumerate(exclude):
            if j >= 0:
                sims[i, j] = -np.inf
    return topk_mean(sims, k), np.where(np.isfinite(sims).any(axis=1), np.argmax(sims, axis=1), -1)


def topk_mean(sims, k=TOP_K):
    """유사도 행렬(후보 × 사례)에서 행마다 상위 k 개의 평균. -inf 칸(비교에서 뺀 사례)은 세지 않는다.
    비교할 사례가 하나도 없는 행은 nan."""
    k = min(k, sims.shape[1])
    top = -np.sort(-sims, axis=1)[:, :k]
    valid = np.isfinite(top)
    counts = valid.sum(axis=1)
    sums = np.where(valid, top, 0).sum(axis=1)
    return np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)


def good_case_ids(user_id):
    bm = {r.tender_id for r in Bookmark.query.filter(Bookmark.user_id == user_id).all()}
    return bm | case_store.case_tender_ids(user_id)


def score_tenders(user_id, tenders, vec_conn=None, encoder=None):
    """{tender.id: {'case_score': 0~100, 'nearest_case': {'id', 'title'}}} 또는 None."""
    gids = good_case_ids(user_id)
    if len(gids) < MIN_CASES or not tenders:
        return None
    good_tenders = Tender.query.filter(Tender.id.in_(gids)).all()
    conn = vec_conn or tender_vectors.connect()
    try:
        vecs = tender_vectors.ensure(conn, good_tenders + [t for t in tenders if t.id not in gids], encoder=encoder)
    finally:
        if vec_conn is None:
            conn.close()
    good = [t for t in good_tenders if t.id in vecs]
    cands = [t for t in tenders if t.id in vecs]
    if len(good) < MIN_CASES or not cands:
        return None
    G = np.stack([vecs[t.id] for t in good])
    C = np.stack([vecs[t.id] for t in cands])
    pos = {t.id: j for j, t in enumerate(good)}
    scores, nearest = knn_scores(C, G, exclude=[pos.get(t.id, -1) for t in cands])
    out = {}
    for t, s, j in zip(cands, scores, nearest):
        if j < 0:
            continue
        g = good[int(j)]
        out[t.id] = {'case_score': round(float(s) * 100, 1), 'nearest_case': {'id': g.id, 'title': g.title}}
    return out
