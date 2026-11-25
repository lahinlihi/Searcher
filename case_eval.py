"""채점: 정답 목록(북마크 + 신고 공고)이 후보 중 몇 등에 오는지를 방식별로 잰다.

- 후보: 정답 공고마다 그 공고가 적재된 날 앞뒤 7일 안에 적재된 공고 (결과공고 제외, 마감 여부 무관).
  그 공고가 실제로 화면에서 경쟁하던 공고들이다.
- 현재 방식: 관심 설정 필터를 통과하면 사례를 섞기 전의 적합도(기본 점수 + 발주처 가감점), 못 하면 0점.
- 사례 방식: 그 정답을 뺀 나머지 사례와의 상위 3건 평균 유사도 (자기 자신과 비교하면 늘 1등이라서).
- 숫자 두 가지: all = 전체 후보 중 등수, filtered = 관심 필터를 통과한 후보 중 등수 (정답도 통과한 것만).
  대시보드 정렬 전환은 filtered 로 판정한다 (켜도 관심 필터는 그대로이므로).
- 벡터가 없는 후보는 두 방식 모두에서 뺀다 (같은 후보로 비교하려고). 그 수를 missing_vectors 로 알린다.
"""
from datetime import timedelta
import statistics

import numpy as np

import case_scoring
import case_store
import tender_vectors
from database import Tender
import relevance
from routes.tenders import _apply_interest_filters
from scoring import load_user_prefs, _score_and_type

WINDOW_DAYS = 7


def _metric(ranks):
    return {'n': len(ranks), 'median': float(statistics.median(ranks)) if ranks else None,
            'top100': sum(r <= 100 for r in ranks), 'top500': sum(r <= 500 for r in ranks)}


def _rank(answer_score, cand_scores):
    return 1 + int(np.sum(np.asarray(cand_scores) > answer_score))


def evaluate(user_id, vec_conn=None, encoder=None, save=True):
    prefs = load_user_prefs(user_id)
    core = prefs.get('core_keywords', [])
    tmax = relevance.type_max(prefs['type_weights'])
    adjusts = relevance.load_agency_adjusts(user_id)
    answers = Tender.query.filter(Tender.id.in_(case_scoring.good_case_ids(user_id))).all()

    conn = vec_conn or tender_vectors.connect()
    rule_cache, pass_cache = {}, {}

    def current(t, passed):
        if not passed:
            return 0.0
        if t.id not in rule_cache:
            # "현재 방식" = 사례를 섞기 전의 적합도 (기본 점수 + 발주처 가감점). 사례 방식과 견주려는 것이라 섞지 않는다
            _, _, kw, ty, _ = _score_and_type(t, prefs['interest_keywords'], prefs['type_weights'], None, core)
            rule_cache[t.id] = relevance.combine(
                relevance.base_score(kw, ty, tmax) if (kw or ty) else 0.0, None,
                relevance.agency_adjust(t.agency, t.demand_agency, adjusts))
        return rule_cache[t.id]

    ranks = {'all': {'current': [], 'case': []}, 'filtered': {'current': [], 'case': []}}
    missing = set()
    try:
        avec = tender_vectors.ensure(conn, answers, encoder=encoder)
        answers = [a for a in answers if a.id in avec]
        G = np.stack([avec[a.id] for a in answers]) if answers else None
        col = {a.id: j for j, a in enumerate(answers)}

        for i, a in enumerate(answers):
            if a.created_at is None:
                continue
            window = Tender.query.filter(
                Tender.created_at >= a.created_at - timedelta(days=WINDOW_DAYS),
                Tender.created_at <= a.created_at + timedelta(days=WINDOW_DAYS),
                Tender.status != '결과공고', Tender.id != a.id)
            cands = window.all()
            unknown = [t.id for t in cands if t.id not in pass_cache]
            if unknown:
                passing = {r[0] for r in _apply_interest_filters(window, prefs).with_entities(Tender.id).all()}
                for tid in unknown:
                    pass_cache[tid] = tid in passing
            if a.id not in pass_cache:
                pass_cache[a.id] = _apply_interest_filters(
                    Tender.query.filter(Tender.id == a.id), prefs).count() == 1

            cvec = tender_vectors.load(conn, [t.id for t in cands])
            missing |= {t.id for t in cands if t.id not in cvec}
            cands = [t for t in cands if t.id in cvec]

            a_pass = pass_cache[a.id]
            cur_c = np.array([current(t, pass_cache[t.id]) for t in cands])
            cur_a = current(a, a_pass)
            ranks['all']['current'].append(_rank(cur_a, cur_c))
            cand_pass = np.array([pass_cache[t.id] for t in cands], dtype=bool)
            if a_pass:
                ranks['filtered']['current'].append(_rank(cur_a, cur_c[cand_pass]))

            if len(answers) < 2:
                continue
            # 사례 방식: 이 정답(i열)을 사례에서 빼고, 후보가 다른 정답이면 자기 열도 뺀다
            sims = (np.stack([cvec[t.id] for t in cands]) @ G.T) if cands else np.zeros((0, len(answers)))
            sims[:, i] = -np.inf
            for r, t in enumerate(cands):
                if t.id in col:
                    sims[r, col[t.id]] = -np.inf
            case_c = np.nan_to_num(case_scoring.topk_mean(sims), nan=-1.0) if cands else np.zeros(0)
            a_sims = (G @ G[i]).reshape(1, -1)
            a_sims[0, i] = -np.inf
            case_a = float(case_scoring.topk_mean(a_sims)[0])
            ranks['all']['case'].append(_rank(case_a, case_c))
            if a_pass:
                ranks['filtered']['case'].append(_rank(case_a, case_c[cand_pass]))
    finally:
        if vec_conn is None:
            conn.close()

    result = {
        'answers': len(answers),
        'cases': len(answers),
        'missing_vectors': len(missing),
        'all': {k: _metric(v) for k, v in ranks['all'].items()},
        'filtered': {k: _metric(v) for k, v in ranks['filtered'].items()},
    }
    if save:
        case_store.save_eval(user_id, result)
    return result
