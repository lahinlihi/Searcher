from flask import Blueprint, render_template, request, jsonify, g
from database import Tender
from decorators import login_required, admin_required, moderator_required
from datetime import datetime
import json

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

    return render_template('detail.html', tender=tender, days_left=days_left,
                           is_expired=is_expired, extra=extra)
