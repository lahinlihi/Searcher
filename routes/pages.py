from flask import Blueprint, render_template, g
from database import db, Tender, UserPreference, AgencyWeight, TenderView
from decorators import login_required, admin_required, moderator_required
from datetime import datetime
from scoring import load_interest_keywords

bp = Blueprint('pages', __name__)


@bp.route('/test')
def test():
    return 'Server is working!'


@bp.route('/')
@login_required
def index():
    """메인 대시보드"""
    return render_template('dashboard.html')


@bp.route('/cases')
@login_required
def cases_page():
    """놓친 공고 신고 · 채점 · 사례 점수 정렬"""
    return render_template('cases.html')


@bp.route('/search')
@login_required
def search_page():
    """검색 페이지"""
    return render_template('search.html')


@bp.route('/filters')
@login_required
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


@bp.route('/review-tenders')
@login_required
def review_tenders_page():
    """검토공고 페이지"""
    return render_template('review_tenders.html')


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
    nearest_case, type_max, agency_mark = None, 25.0, None
    if interest_keywords:
        from relevance import Scorer
        _scorer = Scorer(uid)
        _r = _scorer.score([tender])[tender.id]
        relevance_score, business_type = _r['total'], _r['business_type']
        score_breakdown = Scorer.breakdown(_r)
        nearest_case, type_max, agency_mark = _r['nearest_case'], _scorer.tmax, _r['agency']
    else:
        relevance_score, business_type = None, '기타'
        score_breakdown = None

    # 열람 기록 저장 (upsert)
    if uid:
        try:
            view = TenderView.query.filter_by(user_id=uid, tender_id=tender_id).first()
            if view:
                view.viewed_at = datetime.utcnow()
                view.cleared_at = None      # 다시 열어 봤으면 '읽은 공고'에 다시 나온다
            else:
                db.session.add(TenderView(user_id=uid, tender_id=tender_id, viewed_at=datetime.utcnow()))
            db.session.commit()
        except Exception:
            db.session.rollback()

    import reasons
    eligibility_flags = reasons.flags(uid, {tender.id: tender.title}).get(tender.id, []) if uid else []

    return render_template('detail.html', tender=tender, days_left=days_left,
                           is_expired=is_expired, extra=extra,
                           relevance_score=relevance_score, business_type=business_type,
                           score_breakdown=score_breakdown,
                           nearest_case=nearest_case, type_max=type_max, agency_mark=agency_mark,
                           eligibility_flags=eligibility_flags)
