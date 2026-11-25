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
GENERIC_LIVE_MAX = 30                          # 진행 중 공고가 이보다 많이 걸리는 낱말은 후보로 올리지 않는다 (겨냥한 규칙이 아니다)
_STRIP_CHARS = (' ', '·', '/', '-', '~', '(', ')', '[', ']')    # routes.tenders._TITLE_SEARCH_STRIP_CHARS 와 같다 (제목 검색과 같은 맞춤)
STOP_WORDS = frozenset('''용역 사업 운영 위탁 지원 공고 입찰 재공고 긴급 모집 추진 계획 관련 사전규격 제안요청서 년 년도 차
    위한 통한 대한 기반 구축 개발 수립 수행 시행 선정 안내 변경 정정 취소 관리 프로그램 과정 제안서 평가 계약 협상 의한 등 및 외
    제출 참여 참가 위탁용역 용역사업 위탁운영 운영용역 지원사업'''.split())
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
    같은 규칙이 이미 있다(켬·끔·거절 모두), 진행 중 공고가 GENERIC_LIVE_MAX 건보다 많이 걸린다. 근거가 많은 순으로 돌려준다.
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
            if len(live) > GENERIC_LIVE_MAX:
                continue        # '위탁용역'처럼 흔한 낱말 (2026-11-25 사본: 근거 3건인데 진행 중 92건에 걸렸다)
            out.append({'reason': reason, 'label': REASONS[reason]['label'], 'words': [word],
                        'evidence': [{'id': tid, 'title': title} for tid, title in evidence],
                        'live_count': len(live),
                        'live_examples': [{'id': t[0], 'title': t[1]} for t in live[:3]]})
    # 근거가 많은 순, 같으면 더 좁게 걸리는(진행 중 건수가 적은) 낱말 먼저
    out.sort(key=lambda c: (-len(c['evidence']), c['live_count'], _ORDER[c['reason']], c['words']))
    return out


# ── 규칙·표시·반례 (5부 36.3, 36.4) ──────────────────────────────────────────

def clean_words(words):
    """규칙의 낱말을 다듬는다. 맞춤한 뒤 두 글자 미만이면 거절한다 — 한 글자는 거의 모든 공고에 걸린다."""
    if not isinstance(words, (list, tuple)) or not words:
        raise ValueError('규칙의 낱말을 하나 이상 넣어 주세요.')
    out, seen = [], set()
    for w in words:
        if not isinstance(w, str) or len(norm(w)) < 2:
            raise ValueError('규칙의 낱말은 두 글자 이상이어야 합니다.')
        if norm(w) not in seen:
            seen.add(norm(w))
            out.append(w.strip())
    return out


def rule_matches(title, words):
    """제목에 낱말이 모두 들어 있으면 참 (공백·가운뎃점·대소문자 무시)."""
    n = norm(title)
    return bool(n) and bool(words) and all(norm(w) in n for w in words)


def _find_rule(user_id, reason, words):
    from database import ReasonRule
    key = _words_key(words)
    for r in ReasonRule.query.filter_by(user_id=user_id, reason=reason).all():
        if _words_key(json.loads(r.words)) == key:
            return r
    return None


def _save_rule(user_id, reason, words, status):
    from database import db, ReasonRule
    if reason not in RULE_REASONS:
        raise ValueError('이 이유로는 규칙을 만들 수 없습니다.')
    words = clean_words(words)
    rule = _find_rule(user_id, reason, words)
    if rule is None:
        rule = ReasonRule(user_id=user_id, reason=reason, words=json.dumps(words, ensure_ascii=False), status=status)
        db.session.add(rule)
    else:
        rule.status = status
    db.session.commit()
    return rule


def add_rule(user_id, reason, words):
    """규칙을 켠다. 같은 규칙이 이미 있으면(꺼 둔 것, 거절한 것 포함) 그것을 다시 켠다."""
    return _save_rule(user_id, reason, words, 'on')


def reject(user_id, reason, words):
    """후보를 거절한다 — 다시 후보로 올리지 않는다."""
    return _save_rule(user_id, reason, words, 'rejected')


def update_rule(user_id, rule_id, words=None, status=None):
    from database import db, ReasonRule
    rule = ReasonRule.query.filter_by(id=rule_id, user_id=user_id).first()
    if rule is None or rule.status == 'rejected':
        raise LookupError('규칙을 찾을 수 없습니다.')
    if words is None and status is None:
        raise ValueError('바꿀 내용이 없습니다.')
    if status is not None and status not in ('on', 'off'):
        raise ValueError("상태는 on 또는 off 여야 합니다.")
    if words is not None:
        rule.words = json.dumps(clean_words(words), ensure_ascii=False)
    if status is not None:
        rule.status = status
    db.session.commit()
    return rule


def rule_dict(rule, counter=None):
    words = json.loads(rule.words)
    d = {'id': rule.id, 'reason': rule.reason, 'label': REASONS[rule.reason]['label'], 'words': words, 'status': rule.status}
    if counter is not None:
        d['counterexamples'] = [{'id': tid, 'title': title} for tid, (title, n) in sorted(counter.items())
                                if all(norm(w) in n for w in words)]
    return d


def list_rules(user_id):
    """켜 둔·꺼 둔 규칙 (거절한 후보는 빼고). 반례 = 규칙에 걸리는데 담았거나 '자격 가능'으로 남긴 공고."""
    from database import ReasonRule
    rules = (ReasonRule.query.filter(ReasonRule.user_id == user_id, ReasonRule.status.in_(('on', 'off')))
             .order_by(ReasonRule.id).all())
    if not rules:
        return []
    counter = _counter_titles(user_id)
    return [rule_dict(r, counter) for r in rules]


def _on_rules(user_id):
    from database import ReasonRule
    if user_id is None:
        return []
    rules = ReasonRule.query.filter_by(user_id=user_id, status='on').order_by(ReasonRule.id).all()
    return [(r.id, r.reason, [norm(w) for w in json.loads(r.words)]) for r in rules if r.reason in REASONS]


def flags(user_id, titles):
    """{공고 id: [{'reason', 'label', 'rule_id'}]} — 켜 둔 규칙에 걸린 공고만. 같은 이유는 먼저 만든 규칙 하나만."""
    rules = _on_rules(user_id)
    if not rules:
        return {}
    out = {}
    for tid, title in titles.items():
        n = norm(title)
        if not n:
            continue
        hit = {}
        for rid, reason, words in rules:
            if reason not in hit and words and all(w in n for w in words):
                hit[reason] = rid
        if hit:
            out[tid] = [{'reason': r, 'label': REASONS[r]['label'], 'rule_id': hit[r]} for r in sorted(hit, key=_ORDER.get)]
    return out


def attach_flags(user_id, dicts):
    """공고 dict 목록의 각 항목에 eligibility_flags 를 넣는다 (걸린 것이 없으면 빈 목록).
    표시만 붙인다 — 적합도와 순서는 건드리지 않는다."""
    dicts = [d for d in dicts if isinstance(d, dict)]
    found = flags(user_id, {d.get('id'): d.get('title') for d in dicts}) if dicts else {}
    for d in dicts:
        d['eligibility_flags'] = found.get(d.get('id'), [])


# ── 예전 메모 되짚기 (5부 36.5) ──────────────────────────────────────────────
MEMO_HINTS = ('불가', '만 가능', '만가능', '미달', '미충족', '상이', '맞지 않', '대상')


def memo_backlog(user_id, limit=50):
    """내가 쓴 메모 가운데 검토 결과로 보이는 것(MEMO_HINTS)이면서, 그 공고에 내 이유가 아직 없는 것. 최신순.
    칩은 사용자가 고른다 — 여기서는 붙일 만한 메모를 찾아 줄 뿐이다."""
    from database import db, Tender, TenderMemo, TenderReason
    done = {r[0] for r in TenderReason.query.filter(TenderReason.user_id == user_id)
            .with_entities(TenderReason.tender_id).distinct().all()}
    hint = db.or_(*[TenderMemo.content.contains(h) for h in MEMO_HINTS])
    rows = (db.session.query(TenderMemo, Tender.title).join(Tender, Tender.id == TenderMemo.tender_id)
            .filter(TenderMemo.user_id == user_id, hint).order_by(TenderMemo.created_at.desc()).all())
    out, seen = [], set()
    for memo, title in rows:
        if memo.tender_id in done or memo.tender_id in seen:
            continue
        seen.add(memo.tender_id)
        out.append({'tender_id': memo.tender_id, 'title': title or '',
                    'memo': ' '.join((memo.content or '').split())[:120],
                    'created_at': memo.created_at.isoformat() if memo.created_at else None})
        if len(out) >= limit:
            break
    return out
