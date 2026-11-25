"""놓친 공고 신고·진단, 사례, 채점, 사례 점수 정렬 설정 API (docs/product-contract.md 1차)."""
from datetime import datetime

from flask import Blueprint, jsonify, request, g

import case_eval
import case_scoring
import case_store
import missed_diagnosis
from database import db, Tender, DismissedTender
from decorators import login_required
from relevance import Scorer
from routes.tenders import _apply_interest_filters, _scored_dict, dashboard_section_queries
from scoring import load_user_prefs

bp = Blueprint('cases', __name__)

SIMILAR_LIMIT = 12        # "비슷한 공고" 구역에 보여 줄 최대 건수
SIMILAR_MIN_SCORE = 50.0  # 이 사례 점수 미만은 싣지 않는다 (채점을 보며 조정)
SOURCES = ('report', 'similar')


def _error(e):
    db.session.rollback()
    return jsonify({'error': str(e)}), 500


# ── 놓친 공고 ───────────────────────────────────────────────────────────────

@bp.route('/api/missed/lookup', methods=['POST'])
@login_required
def api_missed_lookup():
    q = (request.get_json(silent=True) or {}).get('q', '')
    try:
        found = missed_diagnosis.find_tender(q)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'candidates': [{
        'id': t.id, 'title': t.title, 'source_site': t.source_site, 'status': t.status,
        'tender_number': t.tender_number,
        'created_at': missed_diagnosis.loaded_at(t).isoformat(timespec='minutes'),
    } for t in found]})


@bp.route('/api/missed/diagnose', methods=['POST'])
@login_required
def api_missed_diagnose():
    body = request.get_json(silent=True) or {}
    q = (body.get('q') or '').strip()
    try:
        tid = body.get('tender_id')
        if tid is None:
            if not q:
                return jsonify({'error': '공고를 고르거나 공고번호·제목을 넣어 주세요'}), 400
            note = (body.get('source_note') or '').strip() or None
            rid = case_store.save_report(g.user.id, q, None, '수집 안 됨', {}, source_note=note)
            return jsonify({'verdict': '수집 안 됨', 'reasons': [], 'report_id': rid})
        tender = db.session.get(Tender, int(tid))
        if tender is None:
            return jsonify({'error': '공고를 찾을 수 없습니다'}), 404
        result = missed_diagnosis.diagnose(tender, g.user.id)
        result['report_id'] = case_store.save_report(
            g.user.id, q or str(tender.id), tender.id, result['verdict'], result)
        result['tender'] = {'id': tender.id, 'title': tender.title, 'source_site': tender.source_site}
        result['is_case'] = tender.id in case_scoring.good_case_ids(g.user.id)
        return jsonify(result)
    except Exception as e:
        return _error(e)


# ── 사례 ────────────────────────────────────────────────────────────────────

@bp.route('/api/cases', methods=['POST'])
@login_required
def api_add_case():
    body = request.get_json(silent=True) or {}
    if body.get('source') not in SOURCES:
        return jsonify({'error': 'source 는 report 또는 similar'}), 400
    try:
        tid = int(body.get('tender_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'tender_id 가 필요합니다'}), 400
    if db.session.get(Tender, tid) is None:
        return jsonify({'error': '공고를 찾을 수 없습니다'}), 404
    try:
        added = case_store.add_case(g.user.id, tid, body['source'])
        return jsonify({'added': added, 'cases': len(case_scoring.good_case_ids(g.user.id))})
    except Exception as e:
        return _error(e)


@bp.route('/api/cases/<int:tender_id>', methods=['DELETE'])
@login_required
def api_remove_case(tender_id):
    try:
        return jsonify({'removed': case_store.remove_case(g.user.id, tender_id)})
    except Exception as e:
        return _error(e)


@bp.route('/api/cases/similar')
@login_required
def api_similar():
    """관심 키워드 필터만 통과하지 못했고 사례와 비슷한 공고 (대시보드의 새 구역)."""
    uid = g.user.id
    try:
        good = case_scoring.good_case_ids(uid)
        if len(good) < case_scoring.MIN_CASES:
            return jsonify({'enabled': False, 'cases': len(good),
                            'min_cases': case_scoring.MIN_CASES, 'items': []})
        prefs = load_user_prefs(uid)
        without_interest = dict(prefs, interest_keywords=[])
        dismissed = {d.tender_id for d in DismissedTender.query.filter_by(user_id=uid).all()}
        now = datetime.now()
        cands, section_of = [], {}
        for name, query in dashboard_section_queries(now).items():
            passing = set()
            if prefs['interest_keywords']:
                passing = {r[0] for r in _apply_interest_filters(query, prefs).with_entities(Tender.id).all()}
            for t in _apply_interest_filters(query, without_interest).all():
                if t.id in passing or t.id in dismissed or t.id in good or t.id in section_of:
                    continue
                section_of[t.id] = name
                cands.append(t)
        scores = case_scoring.score_tenders(uid, cands) or {}
        picked = sorted((t for t in cands if scores.get(t.id, {}).get('case_score', -1) >= SIMILAR_MIN_SCORE),
                        key=lambda t: -scores[t.id]['case_score'])[:SIMILAR_LIMIT]
        items = []
        rel = Scorer(uid).score(picked)
        for t in picked:
            d = _scored_dict(t, prefs, rel[t.id])   # 대시보드 카드와 같은 형태 (적합도·유형 포함)
            d.update(scores[t.id], section=section_of[t.id])
            items.append(d)
        return jsonify({'enabled': True, 'cases': len(good), 'min_cases': case_scoring.MIN_CASES,
                        'items': items})
    except Exception as e:
        return _error(e)


# ── 채점 ────────────────────────────────────────────────────────────────────

@bp.route('/api/cases/eval', methods=['GET', 'POST'])
@login_required
def api_eval():
    try:
        if request.method == 'POST':
            return jsonify(case_eval.evaluate(g.user.id))
        return jsonify({'latest': case_store.latest_eval(g.user.id),
                        'history': case_store.eval_history(g.user.id),
                        'report_counts': case_store.report_counts(g.user.id),
                        'cases': len(case_scoring.good_case_ids(g.user.id)),
                        'min_cases': case_scoring.MIN_CASES})
    except Exception as e:
        return _error(e)


# ── 사례 점수로 정렬 ────────────────────────────────────────────────────────
# 3부부터 사례 점수는 적합도에 항상 절반 섞인다. 켜고 끄는 전환은 없어졌고, 예전 화면이 부르던 주소만 남긴다.

SORT_FIXED = {'enabled': True, 'allowed': True, 'reason': '사례 점수는 적합도에 항상 절반 반영됩니다.'}


@bp.route('/api/cases/sort-setting', methods=['GET', 'POST'])
@login_required
def api_sort_setting():
    return jsonify(SORT_FIXED)
