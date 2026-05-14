from flask import Blueprint, request, jsonify, g
from database import db, Filter, CrawlLog, Tender
from decorators import login_required, admin_required, moderator_required
from datetime import datetime, timedelta
import json

bp = Blueprint('filters', __name__)


@bp.route('/api/filters', methods=['GET', 'POST'])
@login_required
def api_filters():
    """필터 목록 조회 또는 새 필터 생성"""
    if request.method == 'GET':
        filters = Filter.query.filter_by(user_id=g.user.id).all()
        return jsonify([f.to_dict() for f in filters])

    elif request.method == 'POST':
        try:
            data = request.json

            # 기본 필터로 설정하는 경우, 해당 사용자의 다른 필터 기본값 해제
            if data.get('is_default'):
                Filter.query.filter_by(user_id=g.user.id).update({'is_default': False})

            new_filter = Filter(
                user_id=g.user.id,
                name=data['name'],
                is_default=data.get('is_default', False),
                include_keywords=json.dumps(data.get('include_keywords', [])),
                exclude_keywords=json.dumps(data.get('exclude_keywords', [])),
                regions=json.dumps(data.get('regions', [])),
                categories=json.dumps(data.get('categories', [])),
                min_price=data.get('min_price'),
                max_price=data.get('max_price'),
                days_before_deadline=data.get('days_before_deadline'),
                priority_pre_announcement=data.get(
                    'priority_pre_announcement', True),
                sme_only=data.get('sme_only', False)
            )

            db.session.add(new_filter)
            db.session.commit()

            return jsonify(new_filter.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500


@bp.route('/api/filters/<int:filter_id>', methods=['PUT', 'DELETE'])
@login_required
def api_filter_detail(filter_id):
    """필터 수정 또는 삭제 (본인 소유만)"""
    filter_obj = Filter.query.get_or_404(filter_id)
    if filter_obj.user_id != g.user.id:
        return jsonify({'error': '본인 필터만 수정/삭제할 수 있습니다.'}), 403

    if request.method == 'PUT':
        try:
            data = request.json

            # 기본 필터로 설정하는 경우, 다른 필터의 기본값 해제
            if data.get('is_default') and not filter_obj.is_default:
                Filter.query.filter(Filter.id != filter_id).update(
                    {'is_default': False})

            filter_obj.name = data.get('name', filter_obj.name)
            filter_obj.is_default = data.get(
                'is_default', filter_obj.is_default)
            filter_obj.include_keywords = json.dumps(
                data.get('include_keywords', []))
            filter_obj.exclude_keywords = json.dumps(
                data.get('exclude_keywords', []))
            filter_obj.regions = json.dumps(data.get('regions', []))
            filter_obj.categories = json.dumps(data.get('categories', []))
            filter_obj.min_price = data.get('min_price')
            filter_obj.max_price = data.get('max_price')
            filter_obj.days_before_deadline = data.get('days_before_deadline')
            filter_obj.priority_pre_announcement = data.get(
                'priority_pre_announcement', True)
            filter_obj.sme_only = data.get('sme_only', False)

            db.session.commit()
            return jsonify(filter_obj.to_dict())
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500

    elif request.method == 'DELETE':
        try:
            db.session.delete(filter_obj)
            db.session.commit()
            return jsonify({'message': '필터가 삭제되었습니다.'}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500


@bp.route('/api/logs')
@admin_required
def api_logs():
    """크롤링 로그 조회"""
    logs = CrawlLog.query.order_by(CrawlLog.started_at.desc()).limit(20).all()
    return jsonify([log.to_dict() for log in logs])


@bp.route('/api/stats')
@login_required
def api_stats():
    """통계 데이터"""
    try:
        now = datetime.now()

        # 수집 채널별 공고 수 (announced_date 기준, 마감 안 지난 공고만)
        source_stats = db.session.query(
            Tender.source_site,
            db.func.count(Tender.id)
        ).filter(
            Tender.deadline_date >= now
        ).group_by(Tender.source_site)\
         .order_by(db.func.count(Tender.id).desc())\
         .all()

        # 최근 7일간 일별 공고 수 (announced_date 기준)
        seven_days_ago = now - timedelta(days=7)
        daily_stats = db.session.query(
            db.func.date(Tender.announced_date),
            db.func.count(Tender.id)
        ).filter(
            Tender.announced_date >= seven_days_ago,
            Tender.announced_date <= now
        ).group_by(db.func.date(Tender.announced_date))\
         .all()

        return jsonify({
            'source_stats': [{'source': s, 'count': c} for s, c in source_stats],
            'daily_stats': [{'date': str(d), 'count': c} for d, c in daily_stats]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
