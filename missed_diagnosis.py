"""놓친 공고 진단: 그 공고가 대시보드 어디에서 빠졌는지 답한다.

판정은 그 공고가 처음 적재된 시점의 대시보드를 기준으로 한다. 지난 공고를 지금 기준으로 보면
전부 '마감이 지남'으로 나와 쓸모가 없기 때문이다. 조건은 대시보드가 실제로 쓰는 SQLAlchemy 조건
(routes.tenders)을 그 공고 하나에 하나씩 적용해 본다 — 조건을 따로 다시 짜면 대시보드와 어긋난다.
"""
from datetime import datetime, timedelta

from database import Tender, DismissedTender
from relevance import Scorer
from routes.tenders import (DASHBOARD_TOP_N, _apply_interest_filters, _title_contains,
                            dashboard_section_conditions, dashboard_section_queries)
from scoring import load_user_prefs

VERDICTS = ('수집 안 됨', '묶임', '걸러짐', '순위 낮음', '표시 범위 안')

# tenders.created_at 은 UTC 로 저장된다 (database.py 의 default=datetime.utcnow).
# 대시보드는 서버 현지 시각(한국)으로 판단하므로 9시간을 더해 맞춘다.
CREATED_AT_TO_LOCAL = timedelta(hours=9)

SECTION_LABELS = {'pre_tenders': '사전규격', 'urgent_tenders': '신규공고(나라장터)',
                  'recent_tenders': '신규공고(기타 채널)'}


def find_tender(q, limit=20):
    """공고번호 → 주소 → 제목 부분 일치 순으로 찾는다."""
    q = (q or '').strip()
    if not q:
        raise ValueError('찾을 공고번호·주소·제목을 넣어 주세요')
    for col in (Tender.tender_number, Tender.url):
        hit = Tender.query.filter(col == q).order_by(Tender.created_at.desc()).limit(limit).all()
        if hit:
            return hit
    return Tender.query.filter(_title_contains(q)).order_by(Tender.created_at.desc()).limit(limit).all()


def loaded_at(tender):
    return tender.created_at + CREATED_AT_TO_LOCAL if tender.created_at else datetime.now()


def _passes(tender, *conds):
    return Tender.query.filter(Tender.id == tender.id, *conds).count() == 1


def _interest_reasons(tender, prefs):
    base = Tender.query.filter(Tender.id == tender.id)
    empty = {'interest_keywords': [], 'exclude_keywords': [], 'budget_range': {}}
    reasons = []
    for kw in prefs['exclude_keywords']:
        if _apply_interest_filters(base, dict(empty, exclude_keywords=[kw])).count() == 0:
            reasons.append(f"제외 키워드 '{kw}'")
    if prefs['interest_keywords'] and \
            _apply_interest_filters(base, dict(empty, interest_keywords=prefs['interest_keywords'])).count() == 0:
        reasons.append('관심 키워드 없음')
    if prefs['budget_range'] and \
            _apply_interest_filters(base, dict(empty, budget_range=prefs['budget_range'])).count() == 0:
        reasons.append('금액 범위 밖')
    return reasons


def diagnose(tender, user_id):
    as_of = loaded_at(tender)
    result = {'verdict': None, 'reasons': [], 'section': None, 'as_of': as_of.isoformat(timespec='minutes'),
              'rank': None, 'pool': None, 'score': None, 'breakdown': None}

    if tender.is_duplicate:
        result.update(verdict='묶임', reasons=['수집 때 다른 공고와 중복으로 표시됨'])
        return result

    conds = dashboard_section_conditions(as_of)
    section = next((name for name, cs in conds.items()
                    if _passes(tender, *[c for _, c, family in cs if family])), None)
    reasons = []
    if section is None:
        reasons.append('대시보드 구역에 해당하지 않는 출처·상태')
    else:
        result['section'] = section
        reasons += [label for label, c, family in conds[section] if not family and not _passes(tender, c)]

    prefs = load_user_prefs(user_id)
    reasons += _interest_reasons(tender, prefs)
    dismissed = {d.tender_id for d in DismissedTender.query.filter_by(user_id=user_id).all()}
    if tender.id in dismissed:
        reasons.append('직접 제외함')

    if reasons:
        result.update(verdict='걸러짐', reasons=reasons)
        return result

    pool = [t for t in _apply_interest_filters(dashboard_section_queries(as_of)[section], prefs).all()
            if t.id not in dismissed]
    scorer = Scorer(user_id)
    scores = scorer.score(pool)
    ranked = scorer.sort(pool, scores)
    rank = next(i for i, t in enumerate(ranked, 1) if t.id == tender.id)
    result.update(verdict='순위 낮음' if rank > DASHBOARD_TOP_N else '표시 범위 안',
                  rank=rank, pool=len(ranked), score=scores[tender.id]['total'],
                  breakdown=Scorer.breakdown(scores[tender.id]))
    return result
