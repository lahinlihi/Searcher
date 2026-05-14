from flask import Blueprint, render_template, g
from database import Tender, UserPreference, AgencyWeight
from decorators import login_required, admin_required, moderator_required
from datetime import datetime
from scoring import load_interest_keywords, _score_and_type

bp = Blueprint('pages', __name__)


@bp.route('/test')
def test():
    return 'Server is working!'


@bp.route('/')
@login_required
def index():
    """메인 대시보드"""
    return render_template('dashboard.html')


@bp.route('/search')
@login_required
def search_page():
    """검색 페이지"""
    return render_template('search.html')


@bp.route('/filters')
@moderator_required
def filters_page():
    """필터 관리 페이지"""
    return render_template('filters.html')


@bp.route('/settings')
@admin_required
def settings_page():
    """설정 페이지"""
    return render_template('settings.html')


@bp.route('/bookmarks')
@login_required
def bookmarks_page():
    """관심공고 페이지"""
    return render_template('bookmarks.html')


@bp.route('/logs')
@admin_required
def logs_page():
    """로그 페이지"""
    return render_template('logs.html')


@bp.route('/tender/<int:tender_id>')
@login_required
def tender_detail(tender_id):
    """공고 상세 페이지"""
    import json as _json
    tender = Tender.query.get_or_404(tender_id)

    # 마감까지 남은 일수 계산
    days_left = 0
    if tender.deadline_date:
        delta = tender.deadline_date - datetime.now()
        days_left = delta.days

    # 마감일이 지났으면 is_expired=True (사전규격 포함)
    is_expired = days_left < 0

    # extra_data 파싱 (G2B 추가 필드)
    extra = {}
    if tender.extra_data:
        try:
            extra = _json.loads(tender.extra_data)
        except Exception:
            pass

    # 매칭 점수 계산
    uid = g.user.id if g.user else None
    interest_keywords = load_interest_keywords(uid)
    _pref = UserPreference.query.filter_by(user_id=uid).first() if uid else None
    user_type_weights = _pref.get_type_weights() if _pref else {}
    try:
        _aw_rows = AgencyWeight.query.filter_by(user_id=uid).all() if uid else []
        user_agency_weights = {r.agency_name: r.weight for r in _aw_rows}
    except Exception:
        user_agency_weights = {}
    if interest_keywords:
        relevance_score, business_type, kw_s, t_s, a_s = _score_and_type(
            tender, interest_keywords, user_type_weights, user_agency_weights)
        score_breakdown = {'keyword': kw_s, 'type': t_s, 'agency': a_s}
    else:
        relevance_score, business_type = None, '기타'
        score_breakdown = None

    return render_template('detail.html', tender=tender, days_left=days_left,
                           is_expired=is_expired, extra=extra,
                           relevance_score=relevance_score, business_type=business_type,
                           score_breakdown=score_breakdown)
