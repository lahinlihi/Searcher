from flask import Blueprint, request, jsonify, g
from database import db, Tender, Bookmark, TenderMemo, AgencyWeight, UserPreference
from decorators import login_required
from scoring import load_interest_keywords, _score_and_type

bp = Blueprint('bookmarks', __name__)


@bp.route('/api/bookmarks', methods=['GET'])
@login_required
def api_bookmarks():
    """관심공고 목록 조회 (공고 상세 + 적합도 점수 포함)"""
    try:
        uid = g.user.id
        include_keywords = load_interest_keywords(uid)
        _pref = UserPreference.query.filter_by(user_id=uid).first()
        user_type_weights = _pref.get_type_weights() if _pref else {}
        try:
            _aw_rows = AgencyWeight.query.filter_by(user_id=uid).all()
            user_agency_weights = {r.agency_name: r.weight for r in _aw_rows}
        except Exception:
            user_agency_weights = {}
        bookmarks = Bookmark.query.filter_by(user_id=uid).order_by(Bookmark.created_at.desc()).all()

        # memo_count 배치 조회
        from sqlalchemy import func as _sql_func2
        _bm_ids = [b.tender_id for b in bookmarks if b.tender]
        _bm_memo_counts = {}
        if _bm_ids:
            _bm_rows = db.session.query(
                TenderMemo.tender_id, _sql_func2.count(TenderMemo.id).label('cnt')
            ).filter(TenderMemo.tender_id.in_(_bm_ids)).group_by(TenderMemo.tender_id).all()
            _bm_memo_counts = {r[0]: r[1] for r in _bm_rows}

        result = []
        for b in bookmarks:
            tender = b.tender
            if not tender:
                continue
            score, btype, kw_s, t_s, a_s = _score_and_type(tender, include_keywords, user_type_weights, user_agency_weights)
            label_bonus = Bookmark.LABEL_BONUS.get(b.label or '', 0)
            d = tender.to_dict(interest_keywords=include_keywords)
            d['relevance_score'] = min(100.0, round(score + label_bonus, 1))
            d['label_bonus'] = label_bonus
            d['business_type'] = btype
            d['score_breakdown'] = {'keyword': kw_s, 'type': t_s, 'agency': a_s}
            d['bookmark_id'] = b.id
            d['bookmark_label'] = b.label or ''
            d['bookmark_note'] = b.user_note or ''
            d['bookmarked_at'] = b.created_at.isoformat()
            d['memo_count'] = _bm_memo_counts.get(tender.id, 0)
            result.append(d)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/memos/tenders')
@login_required
def api_memo_tenders():
    """메모가 있는 공고 목록 (전체 사용자 공개, 최신 메모순)"""
    try:
        from sqlalchemy import func as _sql_func3
        subq = db.session.query(
            TenderMemo.tender_id,
            _sql_func3.count(TenderMemo.id).label('memo_count'),
            _sql_func3.max(TenderMemo.created_at).label('latest_memo_at')
        ).group_by(TenderMemo.tender_id).subquery()

        rows = db.session.query(Tender, subq.c.memo_count, subq.c.latest_memo_at)\
            .join(subq, Tender.id == subq.c.tender_id)\
            .order_by(subq.c.latest_memo_at.desc())\
            .limit(200).all()

        # 각 공고별 최신 메모 1개 조회
        _mt_ids = [r[0].id for r in rows]
        _latest_memos = {}
        if _mt_ids:
            _all_memos = TenderMemo.query\
                .filter(TenderMemo.tender_id.in_(_mt_ids))\
                .order_by(TenderMemo.tender_id, TenderMemo.created_at.desc()).all()
            _seen = set()
            for m in _all_memos:
                if m.tender_id not in _seen:
                    _latest_memos[m.tender_id] = m.to_dict()
                    _seen.add(m.tender_id)

        data = []
        for tender, memo_count, latest_memo_at in rows:
            d = tender.to_dict()
            d['memo_count'] = memo_count
            d['latest_memo_at'] = (latest_memo_at.isoformat() + 'Z') if latest_memo_at else None
            d['latest_memo'] = _latest_memos.get(tender.id)
            data.append(d)

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/bookmarks/toggle', methods=['POST'])
@login_required
def api_bookmark_toggle():
    """관심공고 토글 (추가/삭제)"""
    try:
        data = request.json or {}
        tender_id = data.get('tender_id')
        if not tender_id:
            return jsonify({'error': 'tender_id 필요'}), 400

        existing = Bookmark.query.filter_by(tender_id=tender_id, user_id=g.user.id).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify({'bookmarked': False})
        else:
            bookmark = Bookmark(tender_id=tender_id, user_id=g.user.id, user_note='')
            db.session.add(bookmark)
            db.session.commit()
            return jsonify({'bookmarked': True, 'bookmark_id': bookmark.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/bookmarks/<int:bookmark_id>/label', methods=['POST'])
@login_required
def api_bookmark_label(bookmark_id):
    """관심공고 라벨 설정"""
    try:
        data = request.json or {}
        label = data.get('label', '')
        valid_labels = [k for k, _ in Bookmark.LABEL_CHOICES] + ['']
        if label not in valid_labels:
            return jsonify({'error': '유효하지 않은 라벨'}), 400
        b = Bookmark.query.get_or_404(bookmark_id)
        b.label = label or None
        db.session.commit()
        return jsonify({'label': b.label, 'label_bonus': Bookmark.LABEL_BONUS.get(b.label or '', 0)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/bookmarks/ids', methods=['GET'])
@login_required
def api_bookmark_ids():
    """북마크된 tender_id 목록"""
    try:
        ids = [b.tender_id for b in Bookmark.query.filter_by(user_id=g.user.id).with_entities(Bookmark.tender_id).all()]
        return jsonify(ids)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
