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
