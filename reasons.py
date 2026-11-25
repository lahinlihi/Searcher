"""이유 칩과 자격 확인 규칙 (제품 계약서 5부).

공고를 제외하거나 검토하면서 남긴 "왜"를 받아 두고, 같은 이유가 쌓이면 규칙 후보를 뽑아 사용자에게 확인받는다.
확인받은 규칙에 걸리는 공고에는 "자격 확인 필요" 표시만 붙인다 — 적합도와 목록 순서는 바꾸지 않는다.
이유도 규칙도 계정별이다. 모든 함수가 user_id 를 받는다.
"""
import json
import re

# 코드 → 문구·묶음. 순서가 화면의 순서다.
REASONS = {
    'size':        {'label': '규모 제한',           'group': 'ineligible'},
    'region':      {'label': '지역 제한',           'group': 'ineligible'},
    'license':     {'label': '업종·등록 요건',      'group': 'ineligible'},
    'record':      {'label': '실적 요건',           'group': 'ineligible'},
    'target':      {'label': '대상이 다름',         'group': 'ineligible'},
    'field':       {'label': '사업영역이 다름',     'group': 'other'},
    'budget':      {'label': '금액·기간이 안 맞음', 'group': 'other'},
    'cancelled':   {'label': '공고 취소·변경',      'group': 'other'},
    'etc':         {'label': '기타',                'group': 'other'},
    'like_field':  {'label': '분야가 맞음',         'group': 'like'},
    'like_form':   {'label': '해 본 수행 형태',     'group': 'like'},
    'like_agency': {'label': '발주처 때문에',       'group': 'like'},
    'eligible':    {'label': '자격 가능',           'group': 'eligible'},
}
_ORDER = {code: i for i, code in enumerate(REASONS)}
DISMISS_GROUPS = ('ineligible', 'other')      # 제외할 때 받을 수 있는 이유


RULE_REASONS = tuple(c for c, v in REASONS.items() if v['group'] == 'ineligible') + ('field',)   # 규칙을 만들 수 있는 이유
MIN_EVIDENCE = 3                               # 같은 이유를 준 공고가 이만큼 모여야 규칙 후보가 된다
_STRIP_CHARS = (' ', '·', '/', '-', '~', '(', ')', '[', ']')    # routes.tenders._TITLE_SEARCH_STRIP_CHARS 와 같다 (제목 검색과 같은 맞춤)
STOP_WORDS = frozenset('''용역 사업 운영 위탁 지원 공고 입찰 재공고 긴급 모집 추진 계획 관련 사전규격 제안요청서 년 년도 차
    위한 통한 대한 기반 구축 개발 수립 수행 시행 선정 안내 변경 정정 취소 관리 프로그램 과정 제안서 평가 계약 협상 의한 등 및 외
    제출 참여 참가'''.split())
_NUMBERISH = re.compile(r'^(제)?\d+(년|년도|차|단계|회|기|호|급|개월|일|억|만원|건)?$')


def norm(text):
    """제목 검색과 같은 맞춤: 공백·가운뎃점 등을 지우고 소문자로."""
    s = (text or '').lower()
    for ch in _STRIP_CHARS:
        s = s.replace(ch, '')
    return s


def title_words(title):
    """제목에서 규칙의 낱말이 될 만한 것을 뽑는다: 두 글자 이상, 숫자·연도·흔한 말 제외, 소문자."""
    out = set()
    for w in re.findall(r'[0-9A-Za-z가-힣]+', title or ''):
        w = w.lower()
        if len(w) < 2 or _NUMBERISH.match(w) or w in STOP_WORDS:
            continue
        out.add(w)
    return out


def options():
    return [{'code': c, 'label': v['label'], 'group': v['group']} for c, v in REASONS.items()]


def clean(codes, groups=None):
    """이유 코드 목록을 검사한다. 중복은 빼고 순서는 지킨다. 잘못되면 ValueError."""
    if not isinstance(codes, (list, tuple)):
        raise ValueError('이유는 목록이어야 합니다.')
    out = []
    for c in codes:
        if not isinstance(c, str) or c not in REASONS:
            raise ValueError(f'모르는 이유입니다: {c!r}')
        if groups is not None and REASONS[c]['group'] not in groups:
            raise ValueError(f"여기서는 쓸 수 없는 이유입니다: {REASONS[c]['label']}")
        if c not in out:
            out.append(c)
    return out


def set_reasons(user_id, tender_id, codes, commit=True):
    """그 계정·그 공고의 이유를 codes 로 통째로 바꾼다 (빈 목록이면 모두 지운다)."""
    from database import db, TenderReason
    codes = clean(codes)
    TenderReason.query.filter_by(user_id=user_id, tender_id=tender_id).delete()
    for c in codes:
        db.session.add(TenderReason(user_id=user_id, tender_id=tender_id, reason=c))
    if commit:
        db.session.commit()
    return codes


def get_reasons(user_id, tender_ids):
    """{공고 id: [이유 코드]} — 이유가 있는 공고만. 코드는 REASONS 의 순서."""
    from database import TenderReason
    ids = [int(i) for i in tender_ids]
    out = {}
    for k in range(0, len(ids), 900):
        rows = TenderReason.query.filter(TenderReason.user_id == user_id,
                                         TenderReason.tender_id.in_(ids[k:k + 900])).all()
        for r in rows:
            if r.reason in REASONS:
                out.setdefault(r.tender_id, []).append(r.reason)
    return {tid: sorted(cs, key=_ORDER.get) for tid, cs in out.items()}


# ── 규칙 후보 (5부 36.3) ─────────────────────────────────────────────────────

def _words_key(words):
    return tuple(sorted(norm(w) for w in words))


def _counter_titles(user_id):
    """반례가 되는 공고 제목(맞춤한 것): 그 계정이 담았거나 '자격 가능'으로 남긴 공고."""
    from database import Bookmark, Tender, TenderReason
    ids = {r[0] for r in Bookmark.query.filter(Bookmark.user_id == user_id).with_entities(Bookmark.tender_id).all()}
    ids |= {r[0] for r in TenderReason.query.filter(TenderReason.user_id == user_id, TenderReason.reason == 'eligible')
            .with_entities(TenderReason.tender_id).all()}
    if not ids:
        return {}
    ids = list(ids)
    out = {}
    for k in range(0, len(ids), 900):
        for t in Tender.query.filter(Tender.id.in_(ids[k:k + 900])).with_entities(Tender.id, Tender.title).all():
            out[t[0]] = (t[1] or '', norm(t[1]))
    return out


def _live_matches(words, now):
    """대시보드 구역(관심 설정 적용 전)의 진행 중 공고 가운데 제목에 낱말이 모두 든 것. 새로 들어온 순."""
    from database import Tender
    from routes.tenders import dashboard_section_queries, _title_contains
    seen = {}
    for q in dashboard_section_queries(now).values():
        for w in words:
            q = q.filter(_title_contains(w))
        for t in q.with_entities(Tender.id, Tender.title, Tender.created_at).all():
            seen[t[0]] = t
    return sorted(seen.values(), key=lambda t: (t[2] is None, t[2]), reverse=True)


def candidates(user_id, now=None):
    """규칙 후보. 같은 이유를 준 공고 MIN_EVIDENCE 건 이상의 제목에 공통으로 든 낱말.

    버리는 경우: 반례가 있다(담았거나 '자격 가능'으로 남긴 공고에 그 낱말이 있다), 관심 키워드와 겹친다,
    같은 규칙이 이미 있다(켬·끔·거절 모두). 근거가 많은 순으로 돌려준다.
    """
    from datetime import datetime
    import scoring
    from database import Tender, TenderReason, ReasonRule
    now = now or datetime.now()
    rows = (TenderReason.query.join(Tender, Tender.id == TenderReason.tender_id)
            .filter(TenderReason.user_id == user_id, TenderReason.reason.in_(RULE_REASONS))
            .with_entities(TenderReason.reason, Tender.id, Tender.title).all())
    if not rows:
        return []
    by_reason = {}
    for reason, tid, title in rows:
        by_reason.setdefault(reason, []).append((tid, title or '', norm(title)))

    counter = [n for _, n in _counter_titles(user_id).values()]
    interest = [norm(k) for k in scoring.load_user_prefs(user_id)['interest_keywords'] if norm(k)]
    known = {(r.reason, _words_key(json.loads(r.words))) for r in ReasonRule.query.filter_by(user_id=user_id).all()}

    out = []
    for reason in RULE_REASONS:
        docs = by_reason.get(reason, [])
        if len(docs) < MIN_EVIDENCE:
            continue
        vocab = set()
        for _, title, _ in docs:
            vocab |= title_words(title)
        for word in sorted(vocab):
            w = norm(word)
            evidence = [(tid, title) for tid, title, n in docs if w in n]
            if len(evidence) < MIN_EVIDENCE:
                continue
            if any(w in c for c in counter):
                continue
            if any(k in w or w in k for k in interest):
                continue
            if (reason, (w,)) in known:
                continue
            live = _live_matches([word], now)
            out.append({'reason': reason, 'label': REASONS[reason]['label'], 'words': [word],
                        'evidence': [{'id': tid, 'title': title} for tid, title in evidence],
                        'live_count': len(live),
                        'live_examples': [{'id': t[0], 'title': t[1]} for t in live[:3]]})
    out.sort(key=lambda c: (-len(c['evidence']), _ORDER[c['reason']], c['words']))
    return out
