from flask import Blueprint, request, jsonify, g, current_app
from database import db, Tender, CrawlLog, TenderMemo, DismissedTender, Filter, UserPreference
from decorators import login_required, admin_required
from scoring import (load_interest_keywords, load_exclude_keywords, load_budget_range,
                     smart_sort_tenders, smart_sort_tenders_by_keyword_count,
                     calculate_relevance_score, _score_and_type, get_last_workday)
from config import Config
from datetime import datetime, timedelta
import json
import re
import threading

bp = Blueprint('tenders', __name__)


@bp.route('/api/tender/<int:tender_id>/related')
@login_required
def api_tender_related(tender_id):
    """
    연관 공고 검색.
    우선순위:
      1) 사업번호(business_number) 기반 — G2B 사전규격↔입찰공고 정확 연계
      2) 채널 + 수요기관 + 제목 핵심어 기반 (폴백)
    """
    import re as _re2

    tender = Tender.query.get_or_404(tender_id)

    # ── 1. 채널 패밀리 결정 ──────────────────────────────────────
    if tender.source_site and tender.source_site.startswith('나라장터'):
        site_filter = Tender.source_site.like('나라장터%')
    else:
        site_filter = Tender.source_site == tender.source_site

    # ── 2-A. 사업번호 기반 검색 (G2B 우선) ──────────────────────
    biz_results = []
    if tender.business_number:
        biz_results = Tender.query.filter(
            Tender.id != tender_id,
            Tender.business_number == tender.business_number,
            site_filter,
        ).order_by(
            db.case((Tender.status != tender.status, 0), else_=1),
            Tender.announced_date.desc()
        ).limit(8).all()

    # ── 2-B. 폴백: 수요기관 + 제목 핵심어 ──────────────────────
    title_results = []
    if not biz_results:
        search_agency = tender.demand_agency or tender.agency
        agency_filter = db.or_(
            Tender.demand_agency == search_agency,
            db.and_(Tender.demand_agency == None, Tender.agency == search_agency),
            Tender.agency == search_agency,
        ) if search_agency else None

        raw = tender.title or ''
        raw = _re2.sub(r'\[[^\]]+\]', '', raw)
        raw = _re2.sub(r'\d{4}년도?', '', raw)
        raw = _re2.sub(r"'\d{2}년도?", '', raw)
        raw = _re2.sub(r'제\s*\d+\s*회차?', '', raw)
        raw = _re2.sub(r'\d+\s*차년도', '', raw)
        raw = _re2.sub(r'\d+\s*차\b', '', raw)
        raw = _re2.sub(r'^\(?\s*(재공고|재입찰)\s*\)?[\s-]*', '', raw)
        raw = _re2.sub(r'\s+', ' ', raw).strip()
        title_key = raw[:20] if len(raw) > 20 else raw

        filters = [Tender.id != tender_id, site_filter]
        if agency_filter is not None:
            filters.append(agency_filter)
        if title_key:
            filters.append(Tender.title.contains(title_key))

        title_results = Tender.query.filter(*filters).order_by(
            db.case((Tender.status != tender.status, 0), else_=1),
            Tender.announced_date.desc()
        ).limit(8).all()

    related = biz_results or title_results

    result = []
    for t in related:
        dl = None
        if t.deadline_date:
            dl = (t.deadline_date - datetime.now()).days
        result.append({
            'id': t.id,
            'title': t.title,
            'status': t.status,
            'source_site': t.source_site,
            'deadline_date': t.deadline_date.strftime('%Y-%m-%d') if t.deadline_date else None,
            'days_left': dl,
            'business_number': t.business_number,
        })
    return jsonify(result)


@bp.route('/api/dashboard')
@login_required
def api_dashboard():
    """대시보드 데이터 조회"""
    try:
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        # 월요일이면 금요일부터, 아니면 1일전부터
        if now.weekday() == 0:  # 월요일
            start_date = get_last_workday(now)  # 금요일
        else:
            start_date = yesterday

        # 포함/제외 키워드 및 금액 범위 로드 (사용자별)
        uid = g.user.id if g.user else None
        include_keywords = load_interest_keywords(uid)
        exclude_keywords = load_exclude_keywords(uid)
        budget_range = load_budget_range(uid)

        # 관심없음 처리된 공고 ID 목록
        dismissed_ids = [d.tender_id for d in DismissedTender.query.filter_by(user_id=uid).all()] if uid else []

        # 사용자 사업유형 가중치 로드
        from database import AgencyWeight
        _pref = UserPreference.query.filter_by(user_id=uid).first() if uid else None
        user_type_weights = _pref.get_type_weights() if _pref else {}

        # 기관별 가중치 로드 {기관명: 점수}
        try:
            _aw_rows = AgencyWeight.query.filter_by(user_id=uid).all() if uid else []
            user_agency_weights = {r.agency_name: r.weight for r in _aw_rows}
        except Exception:
            user_agency_weights = {}

        # 공통 필터 준비
        kw_filter = db.or_(*[Tender.title.contains(kw) for kw in include_keywords]) if include_keywords else None
        br_min = budget_range.get('min')
        br_max = budget_range.get('max')

        # 1. 신규공고: announced_date 기준 1일전~당일 (수의계약 제외)
        new_today = Tender.query.filter(
            Tender.announced_date >= yesterday,
            Tender.announced_date <= now,
            ~Tender.bid_method.contains('수의계약')
        ).count()

        # 2. 사전규격: 마감일이 지나지 않은 모든 공고
        pre_announcement = Tender.query.filter(
            Tender.status == '사전규격',
            Tender.deadline_date >= now
        ).count()

        # 3. 마감 임박 (3일 이내): 수의계약 제외, 마감일 안 지난 공고
        deadline_soon = Tender.query.filter(
            Tender.deadline_date >= now,
            Tender.deadline_date <= now + timedelta(days=3),
            ~Tender.bid_method.contains('수의계약')
        ).count()

        # 4. 총 공고: 수의계약 제외, 마감일 안 지난 공고
        total_tenders = Tender.query.filter(
            Tender.deadline_date >= now,
            ~Tender.bid_method.contains('수의계약')
        ).count()

        # 5. 사전규격: 나라장터 사전규격 중 마감 안 지난 것, 키워드 매칭 순, 20개
        pre_new_query = Tender.query.filter(
            Tender.deadline_date >= now,
            Tender.status == '사전규격',
            db.or_(
                Tender.source_site.contains('나라장터'),
                Tender.source_site.contains('g2b')
            )
        )
        # 제외 키워드 + 관심 키워드 + 금액 범위 필터
        for keyword in exclude_keywords:
            pre_new_query = pre_new_query.filter(~Tender.title.contains(keyword))
        if kw_filter is not None:
            pre_new_query = pre_new_query.filter(kw_filter)
        if br_min:
            pre_new_query = pre_new_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price >= br_min))
        if br_max:
            pre_new_query = pre_new_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price <= br_max))

        all_pre_new = pre_new_query.all()
        if dismissed_ids:
            all_pre_new = [t for t in all_pre_new if t.id not in dismissed_ids]
        sorted_pre_new = smart_sort_tenders_by_keyword_count(
            all_pre_new, include_keywords, user_type_weights, user_agency_weights)
        pre_tenders = sorted_pre_new[:20]

        # 6. 신규공고(기타 채널): 금~오늘, 나라장터 제외, 수의계약 제외, 마감 안 지난 것
        new_query = Tender.query.filter(
            Tender.announced_date >= start_date,
            Tender.announced_date <= now,
            Tender.status != '사전규격',
            Tender.deadline_date >= now,           # 마감일 지난 공고 제외
            ~Tender.bid_method.contains('수의계약'),  # 수의계약 제외
            ~Tender.source_site.contains('나라장터'),
            ~Tender.source_site.like('%g2b%')
        )
        # 제외 키워드 + 관심 키워드 + 금액 범위 필터
        for keyword in exclude_keywords:
            new_query = new_query.filter(~Tender.title.contains(keyword))
        if kw_filter is not None:
            new_query = new_query.filter(kw_filter)
        if br_min:
            new_query = new_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price >= br_min))
        if br_max:
            new_query = new_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price <= br_max))

        all_new = new_query.all()
        if dismissed_ids:
            all_new = [t for t in all_new if t.id not in dismissed_ids]
        sorted_new = smart_sort_tenders_by_keyword_count(
            all_new, include_keywords, user_type_weights, user_agency_weights)
        recent_tenders = sorted_new[:20]

        seven_days_ago = now - timedelta(days=7)

        # 7. 신규공고(나라장터 API): 최근 7일, 수의계약 제외, 마감 안 지난 것 + 3중 필터
        urgent_query = Tender.query.filter(
            Tender.announced_date >= seven_days_ago,
            Tender.announced_date <= now,
            Tender.status != '사전규격',
            Tender.deadline_date >= now,
            ~Tender.bid_method.contains('수의계약'),
            db.or_(
                Tender.source_site.contains('나라장터 API'),
                Tender.source_site.like('%g2b_api%')
            )
        )
        for keyword in exclude_keywords:
            urgent_query = urgent_query.filter(~Tender.title.contains(keyword))
        if kw_filter is not None:
            urgent_query = urgent_query.filter(kw_filter)
        if br_min:
            urgent_query = urgent_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price >= br_min))
        if br_max:
            urgent_query = urgent_query.filter(
                db.or_(Tender.estimated_price == None, Tender.estimated_price <= br_max))

        all_urgent = urgent_query.all()
        if dismissed_ids:
            all_urgent = [t for t in all_urgent if t.id not in dismissed_ids]
        sorted_urgent = smart_sort_tenders_by_keyword_count(all_urgent, include_keywords, user_type_weights, user_agency_weights)
        urgent_tenders = sorted_urgent[:20]

        # 전체 필터 적용 후 총 건수 (배지용)
        keyword_match_count = len(all_pre_new) + len(all_urgent) + len(all_new)

        def _td(t):
            d = t.to_dict(interest_keywords=include_keywords)
            r = _score_and_type(t, include_keywords, user_type_weights, user_agency_weights)
            d['relevance_score'] = r[0]
            d['business_type'] = r[1]
            d['score_breakdown'] = {'keyword': r[2], 'type': r[3], 'agency': r[4]}
            return d

        response_data = {
            'summary': {
                'new_today': new_today,
                'pre_announcement': pre_announcement,
                'deadline_soon': deadline_soon,
                'total': total_tenders,
                'keyword_match': keyword_match_count},
            'pre_tenders':    [_td(t) for t in pre_tenders],
            'urgent_tenders': [_td(t) for t in urgent_tenders],
            'recent_tenders': [_td(t) for t in recent_tenders],
            'include_keywords': include_keywords,
            'exclude_keywords': exclude_keywords}

        return jsonify(response_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/tenders')
@login_required
def api_tenders():
    """공고 목록 조회 (필터링, 페이징)"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get(
            'per_page', Config.ITEMS_PER_PAGE, type=int)

        # 필터 파라미터
        filter_id = request.args.get('filter_id', type=int)
        include_keywords = request.args.get('include_keywords', '')
        exclude_keywords = request.args.get('exclude_keywords', '')
        status = request.args.get('status', '')
        # keyword_logic는 현재 사용하지 않음 (하드코딩된 로직 사용)
        # keyword_logic = request.args.get('keyword_logic', 'OR')

        # 날짜 필터 파라미터
        announced_date_from = request.args.get('announced_date_from', '')
        announced_date_to = request.args.get('announced_date_to', '')
        deadline_date_from = request.args.get('deadline_date_from', '')
        deadline_date_to = request.args.get('deadline_date_to', '')
        include_expired = request.args.get('include_expired', '0') == '1'

        # 수의계약은 검색 결과에서 기본 제외
        query = Tender.query.filter(~Tender.bid_method.contains('수의계약'))

        # 필터 적용
        if filter_id:
            filter_preset = Filter.query.get(filter_id)
            if filter_preset:
                # 키워드 필터링
                include_kw = json.loads(
                    filter_preset.include_keywords) if filter_preset.include_keywords else []
                exclude_kw = json.loads(
                    filter_preset.exclude_keywords) if filter_preset.exclude_keywords else []

                for keyword in include_kw:
                    query = query.filter(Tender.title.contains(keyword))

                for keyword in exclude_kw:
                    query = query.filter(~Tender.title.contains(keyword))

                # 가격 필터
                if filter_preset.min_price:
                    query = query.filter(
                        Tender.estimated_price >= filter_preset.min_price)
                if filter_preset.max_price:
                    query = query.filter(
                        Tender.estimated_price <= filter_preset.max_price)

                # 마감일 필터
                if filter_preset.days_before_deadline:
                    deadline = datetime.now() + timedelta(days=filter_preset.days_before_deadline)
                    query = query.filter(Tender.deadline_date <= deadline)

        # 직접 키워드 필터 (특수문자로 AND/OR 구분)
        # 예: "AI+교육, 시스템" → (AI AND 교육) OR 시스템
        if include_keywords:
            # 쉼표로 split → OR 그룹들
            or_groups = [g.strip()
                         for g in include_keywords.split(',') if g.strip()]

            if or_groups:
                or_conditions = []

                for group in or_groups:
                    # + 기호로 split → AND 키워드들
                    and_keywords = [k.strip()
                                    for k in group.split('+') if k.strip()]

                    if len(and_keywords) == 1:
                        # 단일 키워드: 그냥 포함 조건
                        or_conditions.append(
                            Tender.title.contains(
                                and_keywords[0]))
                    else:
                        # 여러 키워드: 모두 포함해야 함 (AND)
                        and_conditions = [
                            Tender.title.contains(k) for k in and_keywords]
                        or_conditions.append(db.and_(*and_conditions))

                # 모든 OR 조건들을 OR로 묶음
                if len(or_conditions) == 1:
                    query = query.filter(or_conditions[0])
                else:
                    query = query.filter(db.or_(*or_conditions))

        if exclude_keywords:
            # 제외 키워드는 각각 제외 (하나라도 포함되면 제외)
            for keyword in exclude_keywords.split(','):
                if keyword.strip():
                    query = query.filter(
                        ~Tender.title.contains(
                            keyword.strip()))

        # 상태 필터
        if status:
            query = query.filter_by(status=status)

        # 기본 날짜 범위 설정 (마감일 기준 오늘부터 1달)
        # 사용자가 날짜 필터를 하나도 지정하지 않은 경우에만 적용
        # include_expired=True이면 기본 날짜 필터를 적용하지 않음 (마감된 공고 포함)
        if not (
                announced_date_from or announced_date_to or deadline_date_from or deadline_date_to):
            if not include_expired:
                today = datetime.now()
                one_month_later = today + timedelta(days=30)
                query = query.filter(Tender.deadline_date >= today)
                query = query.filter(Tender.deadline_date <= one_month_later)

        # 날짜 필터 적용
        if announced_date_from:
            try:
                from_date = datetime.strptime(announced_date_from, '%Y-%m-%d')
                query = query.filter(Tender.announced_date >= from_date)
            except ValueError:
                pass

        if announced_date_to:
            try:
                to_date = datetime.strptime(announced_date_to, '%Y-%m-%d')
                # 해당 날짜의 끝까지 포함
                to_date = to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(Tender.announced_date <= to_date)
            except ValueError:
                pass

        if deadline_date_from:
            try:
                from_date = datetime.strptime(deadline_date_from, '%Y-%m-%d')
                query = query.filter(Tender.deadline_date >= from_date)
            except ValueError:
                pass

        if deadline_date_to:
            try:
                to_date = datetime.strptime(deadline_date_to, '%Y-%m-%d')
                # 해당 날짜의 끝까지 포함
                to_date = to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(Tender.deadline_date <= to_date)
            except ValueError:
                pass

        # 모든 결과 가져오기 (스마트 정렬을 위해)
        all_tenders = query.all()

        # 스마트 정렬 적용
        sorted_tenders = smart_sort_tenders(all_tenders)

        # 동일 사업명 중복 제거 — smart_sort 이후 첫 번째(최신) 공고만 대표로 유지
        import re as _re

        def _norm_title(t):
            """(수정공고)·(재공고) 등 접두어와 「」 괄호를 제거한 정규화 제목"""
            t = _re.sub(
                r'^[\s\(（\[「『【]*(?:수정공고|재공고|재입찰|정정공고|취소공고)[\s\)）\]」』】,·\s]*',
                '', t, flags=_re.IGNORECASE,
            )
            t = _re.sub(r'[「」『』【】\[\]]', '', t)
            return t.strip()

        seen_titles: dict = {}
        deduped: list = []
        for tender in sorted_tenders:
            # 상태(사전규격/일반)를 키에 포함 — 같은 제목이어도 상태가 다르면 별도 표시
            key = (_norm_title(tender.title), tender.status)
            if key not in seen_titles:
                seen_titles[key] = True
                deduped.append(tender)
        sorted_tenders = deduped

        # 수동 페이징
        total = len(sorted_tenders)
        start = (page - 1) * per_page
        end = start + per_page
        items = sorted_tenders[start:end]

        # 페이징 객체와 유사한 구조 생성
        class ManualPagination:
            def __init__(self, items, page, per_page, total):
                self.items = items
                self.page = page
                self.per_page = per_page
                self.total = total
                self.pages = (total + per_page - 1) // per_page
                self.has_prev = page > 1
                self.has_next = page < self.pages

        pagination = ManualPagination(items, page, per_page, total)

        # 관심 키워드 로드 (사용자별)
        interest_keywords = load_interest_keywords(g.user.id if g.user else None)

        # memo_count 배치 조회
        from sqlalchemy import func as _sql_func
        _page_ids = [t.id for t in pagination.items]
        _memo_counts = {}
        if _page_ids:
            _mcrows = db.session.query(
                TenderMemo.tender_id, _sql_func.count(TenderMemo.id).label('cnt')
            ).filter(TenderMemo.tender_id.in_(_page_ids)).group_by(TenderMemo.tender_id).all()
            _memo_counts = {r[0]: r[1] for r in _mcrows}

        # 사용자 사업유형 가중치 + 기관별 가중치 로드 (점수 계산용)
        uid = g.user.id if g.user else None
        from database import AgencyWeight as _AgencyWeight
        _pref = UserPreference.query.filter_by(user_id=uid).first() if uid else None
        user_type_weights = _pref.get_type_weights() if _pref else {}
        try:
            _aw_rows2 = _AgencyWeight.query.filter_by(user_id=uid).all() if uid else []
            user_agency_weights2 = {r.agency_name: r.weight for r in _aw_rows2}
        except Exception:
            user_agency_weights2 = {}

        # 검색 키워드를 flat list로 파싱 (점수 계산용)
        # "AI+교육, 시스템" → ['AI', '교육', '시스템']
        score_keywords = []
        kw_source = include_keywords or ', '.join(interest_keywords)
        for group in kw_source.split(','):
            for kw in group.split('+'):
                kw = kw.strip()
                if kw:
                    score_keywords.append(kw)

        _tenders_data = []
        for t in pagination.items:
            d = t.to_dict(interest_keywords=interest_keywords)
            d['memo_count'] = _memo_counts.get(t.id, 0)
            if score_keywords:
                score, btype, kw_s, t_s, a_s = _score_and_type(t, score_keywords, user_type_weights, user_agency_weights2)
            else:
                score, btype, kw_s, t_s, a_s = 0, '기타', 0.0, 0.0, 0.0
            d['relevance_score'] = score
            d['business_type'] = btype
            d['score_breakdown'] = {'keyword': kw_s, 'type': t_s, 'agency': a_s}
            _tenders_data.append(d)

        return jsonify({
            'tenders': _tenders_data,
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page,
            'interest_keywords': interest_keywords
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/tenders/<int:tender_id>/memos', methods=['GET', 'POST'])
@login_required
def api_tender_memos(tender_id):
    """공고 공유 메모 조회/작성"""
    if request.method == 'GET':
        try:
            memos = TenderMemo.query.filter_by(tender_id=tender_id)\
                .order_by(TenderMemo.created_at.asc()).all()
            return jsonify([m.to_dict() for m in memos])
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    elif request.method == 'POST':
        try:
            content = (request.json or {}).get('content', '').strip()
            if not content:
                return jsonify({'error': '내용을 입력하세요.'}), 400
            if len(content) > 1000:
                return jsonify({'error': '메모는 1000자 이내로 작성하세요.'}), 400
            memo = TenderMemo(tender_id=tender_id, user_id=g.user.id, content=content)
            db.session.add(memo)
            db.session.commit()
            return jsonify(memo.to_dict()), 201
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500


@bp.route('/api/tenders/<int:tender_id>/memos/<int:memo_id>', methods=['PUT', 'DELETE'])
@login_required
def api_tender_memo_edit_delete(tender_id, memo_id):
    """공고 공유 메모 수정/삭제 (본인 또는 admin)"""
    try:
        memo = TenderMemo.query.filter_by(id=memo_id, tender_id=tender_id).first_or_404()

        if request.method == 'PUT':
            # 수정: 본인 또는 admin
            if memo.user_id != g.user.id and g.user.role != 'admin':
                return jsonify({'error': '본인 메모만 수정할 수 있습니다.'}), 403
            content = (request.json or {}).get('content', '').strip()
            if not content:
                return jsonify({'error': '내용을 입력하세요.'}), 400
            if len(content) > 1000:
                return jsonify({'error': '메모는 1000자 이내로 작성하세요.'}), 400
            memo.content = content
            memo.updated_at = datetime.utcnow()
            db.session.commit()
            return jsonify(memo.to_dict())

        else:  # DELETE
            # 삭제: 본인 또는 admin
            if memo.user_id != g.user.id and g.user.role != 'admin':
                return jsonify({'error': '본인 메모만 삭제할 수 있습니다.'}), 403
            db.session.delete(memo)
            db.session.commit()
            return jsonify({'message': '삭제되었습니다.'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/tenders/<int:tender_id>/dismiss', methods=['POST', 'DELETE'])
@login_required
def api_dismiss_tender(tender_id):
    """공고 관심없음 처리 / 취소"""
    try:
        existing = DismissedTender.query.filter_by(
            user_id=g.user.id, tender_id=tender_id).first()

        if request.method == 'POST':
            if existing:
                return jsonify({'dismissed': True})  # 이미 처리됨
            dismissed = DismissedTender(user_id=g.user.id, tender_id=tender_id)
            db.session.add(dismissed)
            db.session.commit()
            return jsonify({'dismissed': True})

        else:  # DELETE — 관심없음 취소
            if existing:
                db.session.delete(existing)
                db.session.commit()
            return jsonify({'dismissed': False})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/dismissed', methods=['GET'])
@login_required
def api_dismissed_list():
    """관심없음 공고 목록 조회"""
    try:
        include_keywords = load_interest_keywords(g.user.id)
        dismissed = DismissedTender.query.filter_by(
            user_id=g.user.id).order_by(DismissedTender.created_at.desc()).all()
        result = []
        for d in dismissed:
            tender = d.tender
            if not tender:
                continue
            td = tender.to_dict(interest_keywords=include_keywords)
            td['dismissed_at'] = d.created_at.isoformat()
            td['dismissed_id'] = d.id
            result.append(td)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/dismissed/ids', methods=['GET'])
@login_required
def api_dismissed_ids():
    """관심없음 처리된 tender_id 목록"""
    try:
        ids = [d.tender_id for d in DismissedTender.query.filter_by(
            user_id=g.user.id).with_entities(DismissedTender.tender_id).all()]
        return jsonify(ids)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/tenders/<int:tender_id>/history')
@login_required
def api_tender_history(tender_id):
    """공고 수행이력 조회

    조회 흐름:
    1단계. 개찰결과 + 낙찰결과 (최근 2년, 공고명 유사검색) — 순차 소량 요청
    2단계. 유찰/상세정보없음 건에 대해 계약현황 확인

    최종 상태:
    - 낙찰     : 낙찰결과 또는 개찰결과에서 낙찰 확인
    - 단독응찰  : 개찰결과 유찰, 참가 1건
    - 무응찰   : 개찰결과 유찰, 참가 0건
    - 계약     : 낙찰/개찰 없으나 계약현황에서 확인
    - 상세없음  : 공고는 검색됐으나 개찰/낙찰/계약 데이터 없음
    """
    import requests as _req
    import re as _re
    import time as _time
    from datetime import datetime as _dt
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import calendar as _cal
    from urllib.parse import unquote as _unquote
    from settings_manager import settings_manager

    tender = Tender.query.get_or_404(tender_id)

    _raw_key = settings_manager.get('crawl.sites.g2b_api.service_key', '')
    if not _raw_key:
        return jsonify({'error': 'API 키가 설정되지 않았습니다.'}), 500
    service_key = _unquote(_raw_key)  # 이중 인코딩 방지

    # ── 공고명 정제: 메타정보 제거 ────────────────────────────────────────────
    title = tender.title or ''
    clean = title
    clean = _re.sub(r'\[[^\]]+\]', '', clean)
    clean = _re.sub(
        r'\(\s*(?:입찰재공고|입찰공고|입찰|재공고|재입찰|긴급|사전규격공개|사전규격'
        r'|일반용역|추가공고|정정공고|공고|변경)\s*\)',
        '', clean, flags=_re.IGNORECASE,
    )
    clean = _re.sub(r'\d{4}년도?', '', clean)
    clean = _re.sub(r"'\d{2}년도?", '', clean)
    clean = _re.sub(r'\(\s*20\d{2}\s*\)', '', clean)
    clean = _re.sub(r'\b(?:19|20)\d{2}\b', '', clean)   # 단독 연도 숫자 제거 (2026 등)
    clean = _re.sub(r'제\s*\d+\s*회차?', '', clean)
    clean = _re.sub(r'\d+\s*차년도', '', clean)
    clean = _re.sub(r'\d+\s*차\b', '', clean)
    clean = _re.sub(r'^\(?\s*(?:입찰재공고|입찰공고|재공고|재입찰)\s*\)?[\s-]*', '', clean)
    clean = _re.sub(r'\s+', ' ', clean).strip()
    query_nm = clean[:60] if len(clean) > 60 else clean

    # ── 조회 기간: 최근 5년 × 월별, max_workers=20으로 완전 병렬 ──────────────
    # G2B API는 월 단위 범위만 안정적으로 지원 → 월별 유지, workers 대폭 증가
    # 2 ops × 60개월 = 120 호출 / 20 workers = 6 라운드 ≈ 10~15초
    now = _dt.now()
    months = []
    for offset in range(60):   # 5년 = 60개월
        y, m = now.year, now.month - offset
        while m <= 0:
            m += 12; y -= 1
        months.append((y, m))

    RESULT_BASE = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService'
    CNTRCT_BASE = 'https://apis.data.go.kr/1230000/ao/CntrctInfoService'

    # ── 공통 파서 ─────────────────────────────────────────────────────────────
    def _parse_items(data):
        body = data.get('response', {}).get('body', {})
        raw  = body.get('items')
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            inner = raw.get('item', [])
            return [inner] if isinstance(inner, dict) else (inner or [])
        return []

    def _safe_get(url, params, timeout=25):
        """GET 요청 → (items, error_str). 429/502/503 시 최대 3회 재시도."""
        for attempt in range(3):
            try:
                r = _req.get(url, params=params, timeout=timeout)
                if r.status_code in (429, 502, 503):
                    _time.sleep(2 + attempt * 2)
                    continue
                if r.status_code != 200:
                    return [], f'HTTP {r.status_code}'
                text = r.text.strip()
                if not text or text.startswith('<'):
                    return [], None   # 빈 응답 or HTML → 데이터 없음
                data = r.json()
                hdr  = data.get('response', {}).get('header', {})
                code = str(hdr.get('resultCode', '') or '')
                msg  = str(hdr.get('resultMsg',  '') or '')
                if code and code not in ('00', '000'):
                    return [], f'{code}:{msg}'
                return _parse_items(data), None
            except Exception as e:
                if attempt < 2:
                    _time.sleep(1)
                    continue
                return [], str(e)
        return [], '재시도 초과'

    # ── 1단계: 개찰결과 + 낙찰결과 — 월별 병렬 조회 (max_workers=20) ──────────
    ops = [
        ('openg', RESULT_BASE, 'getOpengResultListInfoServcPPSSrch'),
        ('award', RESULT_BASE, 'getScsbidListSttusServcPPSSrch'),
    ]

    def fetch_month(kind, base, ep, year, month):
        last_day = _cal.monthrange(year, month)[1]
        bdt = f'{year}{month:02d}010000'
        edt = f'{year}{month:02d}{last_day:02d}2359'
        items, err = _safe_get(
            f'{base}/{ep}',
            {'ServiceKey': service_key, 'type': 'json',
             'inqryDiv': '1', 'inqryBgnDt': bdt, 'inqryEndDt': edt,
             'bidNtceNm': query_nm, 'pageNo': '1', 'numOfRows': '100'},
        )
        return kind, items, err

    openg_by_no = {}
    award_by_no = {}
    errors = []

    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = [
            ex.submit(fetch_month, kind, base, ep, y, m)
            for kind, base, ep in ops
            for y, m in months
        ]
        for fut in as_completed(futures):
            kind, items, err = fut.result()
            if err:
                errors.append(f'{kind}: {err}')
                continue
            for item in items:
                bid_no = item.get('bidNtceNo', '')
                if not bid_no:
                    continue
                if kind == 'openg':
                    openg_by_no.setdefault(bid_no, []).append(item)
                elif kind == 'award':
                    award_by_no.setdefault(bid_no, []).append(item)

    # 모든 공고번호 통합
    all_bid_nos = set(openg_by_no) | set(award_by_no)

    # ── 2단계: 공고별 상태 결정 ──────────────────────────────────────────────
    def _parse_openg_corp(corp_raw):
        if not corp_raw:
            return {}
        parts = corp_raw.split('^')
        return {
            'name':   (parts[0] if len(parts) > 0 else '').strip(),
            'amount': int(parts[3]) if len(parts) > 3 and parts[3].strip().isdigit() else 0,
            'rate':   (parts[4] if len(parts) > 4 else '').strip(),
        }

    def _winner_from_openg(ol):
        for rec in ol:
            if rec.get('sucsfBidYn') == 'Y':
                b = _parse_openg_corp(rec.get('opengCorpInfo', ''))
                if b.get('name'):
                    return b['name']
        for rec in ol:
            nm = rec.get('bidwinnrNm', '')
            if nm:
                return nm
        if ol:
            b = _parse_openg_corp(ol[0].get('opengCorpInfo', ''))
            return b.get('name', '')
        return ''

    final_items = []
    needs_contract_check = []

    for bid_no in all_bid_nos:
        award_list = award_by_no.get(bid_no, [])
        openg_list = openg_by_no.get(bid_no, [])

        # 낙찰결과 대표 레코드
        award = next((r for r in award_list if r.get('bidwinnrNm')), None)
        if award is None and award_list:
            award = award_list[0]

        openg = openg_list[0] if openg_list else None

        # 공고 URL / 추정가격은 결과 레코드에서 추출
        base_rec = award or openg or {}
        _ann_url     = base_rec.get('bidNtceUrl') or base_rec.get('bidNtceDtlUrl') or ''
        _presmptPrce = base_rec.get('presmptPrce', '') or base_rec.get('asignBdgtAmt', '')
        _openg_corp  = openg.get('opengCorpInfo', '') if openg else ''
        _prtcpt_cnt  = int(openg.get('prtcptCnum') or 0) if openg else 0

        if award:
            item = dict(award)
            item['_status']      = '낙찰'
            item['_presmptPrce'] = _presmptPrce
            _actual_winner  = award.get('bidwinnrNm', '') or _winner_from_openg(openg_list)
            _openg_1st      = _winner_from_openg(openg_list)   # 개찰 시 1순위(sucsfBidYn=Y)
            item['_winner_nm']   = _actual_winner
            item['_prtcpt_cnt']  = _prtcpt_cnt
            # 개찰 1순위와 실제 낙찰자가 다를 때 (적격심사 탈락 후 차순위 낙찰)
            if _openg_1st and _actual_winner and _openg_1st != _actual_winner:
                item['_openg_candidate'] = _openg_1st
            if not item.get('bidNtceUrl'):
                item['bidNtceUrl'] = _ann_url
            final_items.append(item)

        elif openg:
            progrs = openg.get('progrsDivCdNm', '')
            if progrs == '유찰':
                item = dict(openg)
                item['_status']     = 'fail'
                item['_fail_type']  = (
                    'no_bidder'   if _prtcpt_cnt == 0 else
                    'sole_bidder' if _prtcpt_cnt == 1 else
                    'unknown'
                )
                item['_presmptPrce'] = _presmptPrce
                item['_prtcpt_cnt']  = _prtcpt_cnt
                if not item.get('bidNtceUrl'):
                    item['bidNtceUrl'] = _ann_url
                needs_contract_check.append(item)
                final_items.append(item)
            else:
                item = dict(openg)
                item['_status']      = '낙찰'
                item['_presmptPrce'] = _presmptPrce
                item['_winner_nm']   = _winner_from_openg(openg_list)
                item['_prtcpt_cnt']  = _prtcpt_cnt
                if not item.get('bidNtceUrl'):
                    item['bidNtceUrl'] = _ann_url
                final_items.append(item)

        else:
            # 공고번호는 있는데 openg/award 모두 없는 경우 → 상세없음
            item = dict(base_rec)
            item['bidNtceNo']    = bid_no
            item['_status']      = '상세없음'
            item['_presmptPrce'] = _presmptPrce
            item['_prtcpt_cnt']  = 0
            needs_contract_check.append(item)
            final_items.append(item)

    # ── 3단계: 계약현황 확인 (유찰·상세없음 대상) ─────────────────────────────
    _today_str = datetime.now().strftime('%Y%m%d')

    def _parse_corp_list(corp_raw):
        if not corp_raw:
            return ''
        try:
            parts = corp_raw.strip('[]').split('^')
            return parts[3] if len(parts) > 3 else ''
        except Exception:
            return ''

    def _names_match(bid_nm, cntrct_nm):
        stopwords = {'및', '의', '을', '를', '이', '가', '에', '에서', '으로', '로',
                     '용역', '사업', '위탁', '운영', '관리', '지원', '추진', '수행'}
        def kw(nm):
            return {w for w in nm.split() if len(w) >= 2 and w not in stopwords}
        b, c = kw(bid_nm), kw(cntrct_nm)
        if not b or not c:
            return False
        common = len(b & c)
        # 고유명사 1개라도 일치하면 매칭 (짧은 공고명 대응)
        return common >= 1 if len(b) <= 2 else common >= min(2, len(b))

    _NM_PREFIX = _re.compile(
        r'^\s*[\(\[（【]?\s*(입찰공고|재공고|입찰재공고|재입찰|긴급공고|수정공고)\s*[\)\]）】]?\s*'
    )

    def fetch_contract(item):
        ntce_nm = item.get('bidNtceNm', '')
        if not ntce_nm:
            return item, None
        clean_nm  = _NM_PREFIX.sub('', ntce_nm).strip()
        words     = clean_nm.split()
        search_kw = ' '.join(words[:4]) if len(words) >= 4 else clean_nm
        if len(search_kw) < 4:
            return item, None
        raw_dt = (item.get('bidNtceDt') or item.get('opengDt') or item.get('rlOpengDt') or '')
        search_from = _re.sub(r'[^0-9]', '', raw_dt)[:8] if raw_dt else ''
        if not search_from or search_from > _today_str:
            # 날짜 없는 경우 최근 3년치 전체 검색
            search_from = str(now.year - 3) + '0101'
        try:
            # 낙찰 후 계약까지 최대 2년 소요 가능 → 2년 범위로 확장
            search_to = min(str(int(search_from[:4]) + 2) + search_from[4:], _today_str)
        except Exception:
            search_to = _today_str
        cntrct_items, _ = _safe_get(
            f'{CNTRCT_BASE}/getCntrctInfoListServcPPSSrch',
            {'ServiceKey': service_key, 'type': 'json',
             'inqryDiv': '1', 'inqryBgnDate': search_from, 'inqryEndDate': search_to,
             'cntrctNm': search_kw, 'pageNo': '1', 'numOfRows': '10'},
            timeout=20,
        )
        for r0 in cntrct_items:
            c_nm = r0.get('cntrctNm', '')
            if not _names_match(ntce_nm, c_nm):
                continue
            winner = _parse_corp_list(r0.get('corpList', ''))
            amount = r0.get('thtmCntrctAmt', '') or r0.get('totCntrctAmt', '')
            if winner or amount:
                return item, {
                    'winner': winner, 'amount': amount,
                    'date': r0.get('cntrctDate', ''),
                }
        return item, None

    if needs_contract_check:
        with ThreadPoolExecutor(max_workers=3) as ex2:
            for fut in as_completed([ex2.submit(fetch_contract, it) for it in needs_contract_check]):
                item, contract = fut.result()
                if contract:
                    item['_status']            = '계약'
                    item['_followup_contract'] = contract

    # ── 정렬: 개찰일/공고일 최신순 ──────────────────────────────────────────
    def _sort_key(x):
        return x.get('rlOpengDt') or x.get('opengDt') or x.get('fnlSucsfDate') or x.get('bidNtceDt') or ''

    final_items.sort(key=_sort_key, reverse=True)

    return jsonify({
        'items':          final_items,
        'query':          query_nm,
        'original_title': title,
        'errors':         list(set(errors))[:5],
        'pblnc_api_ok':   True,
    })


@bp.route('/api/history/bidders')
@login_required
def api_history_bidders():
    """특정 입찰 공고의 투찰업체 상세 목록 조회
    나라장터 낙찰정보서비스 — getOpnBidResultList (개찰결과목록조회)
    """
    import requests as _req
    from urllib.parse import unquote as _unquote
    from settings_manager import settings_manager

    bid_no  = request.args.get('bid_no', '').strip()
    bid_seq = request.args.get('bid_seq', '000').strip().zfill(3)
    if not bid_no:
        return jsonify({'error': '입찰번호가 필요합니다.'}), 400

    service_key = settings_manager.get('crawl.sites.g2b_api.service_key', '')
    if not service_key:
        return jsonify({'error': 'API 키가 설정되지 않았습니다.'}), 500

    # 서비스 키 이중 인코딩 방지 (requests가 한 번만 인코딩하도록 unquote)
    decoded_key = _unquote(service_key)

    def _parse_items(data):
        body = data.get('response', {}).get('body', {})
        total = body.get('totalCount', 0)
        raw = body.get('items')
        if isinstance(raw, list):
            return raw, total
        if isinstance(raw, dict):
            inner = raw.get('item', [])
            items = [inner] if isinstance(inner, dict) else (inner if isinstance(inner, list) else [])
            return items, total
        return [], 0

    def _try_endpoint(url):
        params = {
            'ServiceKey': decoded_key,
            'type': 'json',
            'bidNtceNo': bid_no,
            'bidNtceOrd': bid_seq,
            'pageNo': '1',
            'numOfRows': '200',
        }
        r = _req.get(url, params=params, timeout=15)
        data = r.json()
        # 에러 코드 확인
        hdr = data.get('response', {}).get('header', {})
        code = str(hdr.get('resultCode', '') or data.get('resultCode', ''))
        msg  = hdr.get('resultMsg', '') or data.get('resultMsg', '')
        if code and code != '00':
            return None, code, msg
        items, total = _parse_items(data)
        return items, '00', msg

    # 기존에 사용 중인 ScsbidInfoService의 getOpnBidResultList 오퍼레이션
    ENDPOINTS = [
        'http://apis.data.go.kr/1230000/as/ScsbidInfoService/getOpnBidResultList',
        'http://apis.data.go.kr/1230000/BidResultService/getOpnBidResultList',
    ]

    try:
        items = None
        last_code, last_msg = '', ''
        for url in ENDPOINTS:
            items, last_code, last_msg = _try_endpoint(url)
            if items is not None:
                break

        if items is None:
            return jsonify({'error': f'API 오류 ({last_code}): {last_msg}'}), 502

        bidders = []
        winner_nm = ''
        for it in items:
            name = (it.get('corpNm') or it.get('bidcorpNm') or
                    it.get('corNm') or '').strip()
            if not name:
                continue
            rank_raw = (it.get('rnk') or it.get('bidprcRank') or
                        it.get('rank') or '')
            biz_no = (it.get('bizno') or it.get('corpRegNo') or
                      it.get('brno') or '').strip()
            amt_raw = (it.get('bidprcAmt') or it.get('bidAmt') or
                       it.get('bidprcPrice') or 0)
            try:
                amt = int(str(amt_raw).replace(',', ''))
            except (ValueError, TypeError):
                amt = 0
            rate = str(it.get('bidprcRate') or it.get('bidRate') or '').strip()
            is_win = str(it.get('sucsfBidYn') or it.get('bidwinnrYn') or '').upper() == 'Y'

            if is_win and not winner_nm:
                winner_nm = name

            bidders.append({
                'name': name,
                'rank': rank_raw,
                'bizNo': biz_no,
                'amount': amt,
                'rate': rate,
                'is_winner': is_win,
            })

        # 순위 기준 정렬
        def _rank_key(b):
            try:
                return int(b['rank'])
            except (ValueError, TypeError):
                return 9999
        bidders.sort(key=_rank_key)

        return jsonify({
            'bidders':   bidders,
            'winner_nm': winner_nm,
            'count':     len(bidders),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/search', methods=['POST'])
@admin_required
def api_search():
    """즉시 검색 시작 (크롤링)"""
    scheduler = getattr(current_app, 'crawler_scheduler', None)
    if not scheduler:
        return jsonify({'error': '스케줄러가 초기화되지 않았습니다.'}), 500

    try:
        # 백그라운드에서 크롤링 실행
        def run_crawl():
            result = scheduler.run_manual_crawl()
            print(f"[수동 크롤링] 결과: {result}")

        thread = threading.Thread(target=run_crawl)
        thread.daemon = True
        thread.start()

        return jsonify({
            'message': '크롤링이 시작되었습니다. 잠시 후 결과를 확인하세요.',
            'status': 'started'
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/crawl/status')
@admin_required
def api_crawl_status():
    """최근 크롤링 상태 조회"""
    try:
        latest_log = CrawlLog.query.order_by(
            CrawlLog.started_at.desc()).first()
        if latest_log:
            return jsonify(latest_log.to_dict())
        else:
            return jsonify({'message': '크롤링 기록이 없습니다.'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
