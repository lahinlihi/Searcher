from flask import Blueprint, request, jsonify, make_response, current_app, g
from database import db, Tender
from decorators import login_required, admin_required
from excel_exporter import excel_exporter
from settings_manager import settings_manager
from datetime import datetime, timedelta

bp = Blueprint('data', __name__)


@bp.route('/api/data/delete-old', methods=['POST'])
@admin_required
def api_delete_old_tenders():
    """오래된 공고 삭제"""
    try:
        days = request.json.get('days', 30)
        count = current_app.data_manager.delete_old_tenders(days)
        return jsonify({'message': f'{count}건의 공고를 삭제했습니다.', 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/data/clear-tenders', methods=['POST'])
@admin_required
def api_clear_tenders():
    """크롤링 데이터(공고)만 삭제 - 설정, 필터, 북마크 유지"""
    try:
        count = Tender.query.count()
        Tender.query.delete()
        db.session.commit()
        return jsonify({'message': f'크롤링 데이터 {count}건을 삭제했습니다.', 'count': count})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/data/reset', methods=['POST'])
@admin_required
def api_reset_database():
    """데이터베이스 초기화"""
    try:
        keep_filters = request.json.get('keep_filters', True)
        result = current_app.data_manager.reset_database(keep_filters)

        if result:
            return jsonify({
                'message': '데이터베이스가 초기화되었습니다.',
                'result': result
            })
        else:
            return jsonify({'error': '초기화 실패'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/data/stats')
@admin_required
def api_database_stats():
    """데이터베이스 통계"""
    try:
        stats = current_app.data_manager.get_database_stats()
        if stats:
            return jsonify(stats)
        else:
            return jsonify({'error': '통계 조회 실패'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/data/cleanup', methods=['POST'])
@admin_required
def api_cleanup_data():
    """데이터 정리 (중복 제거)"""
    try:
        count = current_app.data_manager.cleanup_duplicates()
        return jsonify(
            {'message': f'{count}건의 중복 공고를 삭제했습니다.', 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/export/csv')
@login_required
def api_export_csv():
    """CSV로 내보내기"""
    try:
        # 필터링된 공고 조회
        include_keywords = request.args.get('include_keywords', '')
        exclude_keywords = request.args.get('exclude_keywords', '')
        status = request.args.get('status', '')

        query = Tender.query

        if include_keywords:
            for keyword in include_keywords.split(','):
                query = query.filter(Tender.title.contains(keyword.strip()))

        if exclude_keywords:
            for keyword in exclude_keywords.split(','):
                query = query.filter(~Tender.title.contains(keyword.strip()))

        if status:
            query = query.filter_by(status=status)

        tenders = query.order_by(
            db.case((Tender.status == '사전규격', 1), else_=2),
            Tender.deadline_date.asc()
        ).all()

        # 딕셔너리로 변환
        tender_dicts = [t.to_dict() for t in tenders]

        # CSV 생성
        csv_content = excel_exporter.export_to_csv(tender_dicts)

        # 응답 생성
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        response.headers['Content-Disposition'] = f'attachment; filename=tenders_{_ts}.csv'

        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/export/excel')
@login_required
def api_export_excel():
    """Excel HTML로 내보내기"""
    try:
        # 공고 조회 (CSV와 동일)
        include_keywords = request.args.get('include_keywords', '')
        status = request.args.get('status', '')

        query = Tender.query

        if include_keywords:
            for keyword in include_keywords.split(','):
                query = query.filter(Tender.title.contains(keyword.strip()))

        if status:
            query = query.filter_by(status=status)

        tenders = query.order_by(
            db.case((Tender.status == '사전규격', 1), else_=2),
            Tender.deadline_date.asc()
        ).all()

        tender_dicts = [t.to_dict() for t in tenders]

        # Excel HTML 생성
        html_content = excel_exporter.export_to_excel_html(tender_dicts)

        response = make_response(html_content)
        response.headers['Content-Type'] = 'application/vnd.ms-excel; charset=utf-8'
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        response.headers['Content-Disposition'] = f'attachment; filename=tenders_{_ts}.xls'

        return response

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/sync/tenders')
def api_sync_tenders():
    """
    팀원 앱이 호출하여 최신 공고 데이터를 가져가는 엔드포인트.
    settings.json 의 sync.token 과 일치하는 요청만 허용.

    Query params:
        token   : 인증 토큰 (필수)
        since   : ISO datetime — 이 시각 이후 생성된 공고만 반환 (선택)
        limit   : 최대 건수 (기본 500, 최대 2000)
    """
    # ── 인증 ──────────────────────────────────────────────────
    expected = settings_manager.get('sync.token', '')
    if not expected:
        return jsonify({'error': 'Sync not enabled on this server'}), 403

    token = request.args.get('token') or request.headers.get('X-Sync-Token', '')
    if token != expected:
        return jsonify({'error': 'Unauthorized'}), 401

    # ── 파라미터 ───────────────────────────────────────────────
    since_str = request.args.get('since')
    try:
        since = datetime.fromisoformat(since_str) if since_str else datetime.now() - timedelta(days=30)
    except ValueError:
        since = datetime.now() - timedelta(days=30)

    limit = min(int(request.args.get('limit', 500)), 2000)

    # ── 쿼리 ───────────────────────────────────────────────────
    tenders = (
        Tender.query
        .filter(Tender.created_at >= since)
        .order_by(Tender.created_at.desc())
        .limit(limit)
        .all()
    )

    return jsonify({
        'count': len(tenders),
        'since': since.isoformat(),
        'synced_at': datetime.now().isoformat(),
        'tenders': [t.to_dict() for t in tenders]
    })
