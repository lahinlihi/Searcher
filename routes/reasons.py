"""이유 칩과 자격 확인 규칙 API (docs/product-contract.md 5부). 모두 로그인한 계정 자신의 자료만 다룬다."""
from flask import Blueprint, jsonify, request, g

import reasons
from database import db, Tender
from decorators import login_required

bp = Blueprint('reasons', __name__)


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _error(e):
    db.session.rollback()
    return jsonify({'error': str(e)}), 500


@bp.route('/api/reasons/options')
@login_required
def api_reason_options():
    return jsonify({'options': reasons.options(), 'dismiss_groups': list(reasons.DISMISS_GROUPS)})


@bp.route('/api/tenders/<int:tender_id>/reasons', methods=['GET', 'PUT'])
@login_required
def api_tender_reasons(tender_id):
    """이 공고에 내가 남긴 이유. PUT 은 통째로 바꾼다 (제외하지 않고 검토 결과만 남길 때)."""
    try:
        if db.session.get(Tender, tender_id) is None:
            return jsonify({'error': '공고를 찾을 수 없습니다'}), 404
        if request.method == 'PUT':
            body = _body()
            try:
                codes = reasons.clean(body.get('reasons') if body else None)
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            reasons.set_reasons(g.user.id, tender_id, codes)
            return jsonify({'reasons': codes})
        return jsonify({'reasons': reasons.get_reasons(g.user.id, [tender_id]).get(tender_id, [])})
    except Exception as e:
        return _error(e)


# ── 자격 확인 규칙 ───────────────────────────────────────────────────────────

@bp.route('/api/reason-rules', methods=['GET', 'POST'])
@login_required
def api_reason_rules():
    """GET: 내 규칙과 규칙 후보. POST: 후보를 규칙으로 켠다 (사용자가 [표시하기]를 눌렀을 때만)."""
    try:
        if request.method == 'POST':
            body = _body() or {}
            try:
                rule = reasons.add_rule(g.user.id, body.get('reason'), body.get('words'))
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
            return jsonify(reasons.rule_dict(rule))
        return jsonify({'rules': reasons.list_rules(g.user.id), 'candidates': reasons.candidates(g.user.id)})
    except Exception as e:
        return _error(e)


@bp.route('/api/reason-rules/reject', methods=['POST'])
@login_required
def api_reason_rule_reject():
    try:
        body = _body() or {}
        try:
            reasons.reject(g.user.id, body.get('reason'), body.get('words'))
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        return jsonify({'rejected': True})
    except Exception as e:
        return _error(e)


@bp.route('/api/reason-rules/<int:rule_id>', methods=['PUT'])
@login_required
def api_reason_rule_update(rule_id):
    try:
        body = _body() or {}
        try:
            rule = reasons.update_rule(g.user.id, rule_id, words=body.get('words'), status=body.get('status'))
        except LookupError as e:
            return jsonify({'error': str(e)}), 404
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        return jsonify(reasons.rule_dict(rule))
    except Exception as e:
        return _error(e)
