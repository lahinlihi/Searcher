from flask import Blueprint, request, jsonify, g, current_app
from database import db, Tender, CrawlLog, TenderMemo, DismissedTender, Filter
from decorators import login_required, admin_required
from scoring import (load_user_prefs, load_interest_keywords,
                     smart_sort_tenders_by_keyword_count,
                     _score_and_type, get_last_workday, compute_embed_sims)
from config import Config
from datetime import datetime, timedelta
import json
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
        # 어제 자정(00:00:00) 기준 — timedelta(1)은 현재 시각 기준이므로 00:00 공고가 탈락하는 버그 방지
        yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        # 월요일이면 금요일부터, 아니면 어제 자정부터
        if now.weekday() == 0:  # 월요일
            start_date = get_last_workday(now)  # 금요일
        else:
            start_date = yesterday

        # 포함/제외 키워드 및 금액 범위 로드 (사용자별, 단일 DB 조회)
        uid = g.user.id if g.user else None
        _uprefs = load_user_prefs(uid)
        include_keywords = _uprefs['interest_keywords']
        exclude_keywords = _uprefs['exclude_keywords']
        budget_range = _uprefs['budget_range']
        user_type_weights = _uprefs['type_weights']
        user_core_keywords = _uprefs.get('core_keywords', [])

        # 관심없음 처리된 공고 ID 목록
        dismissed_ids = [d.tender_id for d in DismissedTender.query.filter_by(user_id=uid).all()] if uid else []

        from database import AgencyWeight
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

        # 4. 총 공고: DB에 누적된 전체 공고 수 (중복 없이)
        total_tenders = Tender.query.count()

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

        # 6. 신규공고(기타 채널): 7일 이내, 나라장터 제외, 수의계약 제외, 마감 안 지난 것
        # (나라장터와 동일한 7일 창 사용 — 기타채널도 주중 공고 누락 방지)
        seven_days_ago_midnight = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        new_query = Tender.query.filter(
            Tender.announced_date >= seven_days_ago_midnight,
            Tender.announced_date <= now,
            Tender.status != '사전규격',
            Tender.status != '결과공고',
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

        seven_days_ago = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)

        # 7. 신규공고(나라장터 API): 최근 7일, 수의계약 제외, 마감 안 지난 것 + 3중 필터
        urgent_query = Tender.query.filter(
            Tender.announced_date >= seven_days_ago,
            Tender.announced_date <= now,
            Tender.status != '사전규격',
            Tender.status != '결과공고',
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

        # 규칙 점수 기반 정렬만 수행 — 임베딩은 /api/embed-scores 에서 on-demand 처리
        sorted_pre_new = smart_sort_tenders_by_keyword_count(
            all_pre_new, include_keywords, user_type_weights, user_agency_weights, user_core_keywords)
        pre_tenders = sorted_pre_new[:24]

        sorted_new = smart_sort_tenders_by_keyword_count(
            all_new, include_keywords, user_type_weights, user_agency_weights, user_core_keywords)
        recent_tenders = sorted_new[:24]

        sorted_urgent = smart_sort_tenders_by_keyword_count(
            all_urgent, include_keywords, user_type_weights, user_agency_weights, user_core_keywords)
        urgent_tenders = sorted_urgent[:24]

        # 전체 필터 적용 후 총 건수 (배지용)
        keyword_match_count = len(all_pre_new) + len(all_urgent) + len(all_new)

        def _td(t):
            d = t.to_dict(interest_keywords=include_keywords)
            r = _score_and_type(t, include_keywords, user_type_weights, user_agency_weights, user_core_keywords)
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


@bp.route('/api/embed-scores', methods=['POST'])
@login_required
def api_embed_scores():
    """화면에 보이는 공고 ID 목록 → 임베딩 혼합 점수 반환 (on-demand lazy 처리)"""
    try:
        tender_ids = (request.json or {}).get('tender_ids', [])
        if not tender_ids:
            return jsonify({'scores': {}})

        uid = g.user.id if g.user else None
        _uprefs = load_user_prefs(uid)
        kws = _uprefs['interest_keywords']
        tw  = _uprefs['type_weights']
        ck  = _uprefs.get('core_keywords', [])

        from database import AgencyWeight
        aw_rows = AgencyWeight.query.filter_by(user_id=uid).all() if uid else []
        aw = {r.agency_name: r.weight for r in aw_rows}

        tenders = Tender.query.filter(Tender.id.in_(tender_ids)).all()
        sims = compute_embed_sims(tenders, kws, ck)

        scores = {}
        for t in tenders:
            s, btype, ks, ts, as_ = _score_and_type(t, kws, tw, aw, ck, embed_sim=sims.get(t.id))
            scores[str(t.id)] = {
                'score': s,
                'keyword': ks,
                'type': ts,
                'agency': as_,
                'business_type': btype,
            }
        return jsonify({'scores': scores})
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

        # 신규 필터 파라미터
        min_price = request.args.get('min_price', type=int)   # 원 단위
        max_price = request.args.get('max_price', type=int)   # 원 단위
        regions   = [r.strip() for r in request.args.get('regions', '').split(',') if r.strip()]
        demand_agency_include = [t.strip() for t in request.args.get('demand_agency_include', '').split(',') if t.strip()]
        demand_agency_exclude = [t.strip() for t in request.args.get('demand_agency_exclude', '').split(',') if t.strip()]

        # 결과공고 표시 여부 (기본: 제외)
        show_result_notices = request.args.get('show_result', '0') == '1'

        # 수의계약은 검색 결과에서 기본 제외
        query = Tender.query.filter(~Tender.bid_method.contains('수의계약'))
        # 결과공고(선정결과·낙찰결과 등)는 기본 제외
        if not show_result_notices:
            query = query.filter(Tender.status != '결과공고')

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
                query = query.filter(Tender.deadline_date >= today)

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

        # ── 금액 범위 필터 ──────────────────────────────────────────────────────
        if min_price is not None:
            query = query.filter(Tender.estimated_price >= min_price)
        if max_price is not None:
            query = query.filter(Tender.estimated_price <= max_price)

        # ── 지역 필터 (광역시도 → 하위 시/군/구 포함) ───────────────────────────
        if regions:
            region_terms = []
            for r in regions:
                region_terms.append(r)
                region_terms.extend(_REGION_ALIASES.get(r, []))
            region_conditions = []
            for term in region_terms:
                region_conditions.append(Tender.title.ilike(f'%{term}%'))
                region_conditions.append(Tender.agency.ilike(f'%{term}%'))
                region_conditions.append(Tender.demand_agency.ilike(f'%{term}%'))
            query = query.filter(db.or_(*region_conditions))

        # ── 수요기관 포함 필터 (OR) ──────────────────────────────────────────────
        if demand_agency_include:
            inc_conditions = []
            for term in demand_agency_include:
                inc_conditions.append(Tender.demand_agency.ilike(f'%{term}%'))
                inc_conditions.append(Tender.agency.ilike(f'%{term}%'))
            query = query.filter(db.or_(*inc_conditions))

        # ── 수요기관 제외 필터 (AND NOT) ─────────────────────────────────────────
        # 주의: demand_agency=NULL 인 일반공고는 NOT ILIKE가 NULL로 평가되어 제외됨
        # → NULL이면 "해당 없음(대학 아님)"으로 간주하여 통과시켜야 함
        for term in demand_agency_exclude:
            query = query.filter(
                db.or_(Tender.demand_agency.is_(None),
                       ~Tender.demand_agency.ilike(f'%{term}%')),
                ~Tender.agency.ilike(f'%{term}%'),
            )

        # 모든 결과 가져오기 (스마트 정렬을 위해)
        all_tenders = query.all()

        # 사용자 설정 단일 조회 (정렬 + 점수 계산 공통)
        uid = g.user.id if g.user else None
        _uprefs = load_user_prefs(uid)
        interest_keywords = _uprefs['interest_keywords']
        user_type_weights = _uprefs['type_weights']
        user_core_keywords2 = _uprefs.get('core_keywords', [])

        # 스마트 정렬 적용 (사용자 관심 키워드 기반)
        from database import AgencyWeight as _AgencyWeight
        try:
            _aw_rows2 = _AgencyWeight.query.filter_by(user_id=uid).all() if uid else []
            user_agency_weights2 = {r.agency_name: r.weight for r in _aw_rows2}
        except Exception:
            user_agency_weights2 = {}

        # 점수/정렬은 항상 필터관리에 저장된 관심 키워드 기준 — 검색창 키워드와 무관
        sort_keywords = interest_keywords

        sorted_tenders = smart_sort_tenders_by_keyword_count(
            all_tenders, sort_keywords, user_type_weights, user_agency_weights2, user_core_keywords2
        )

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

        # memo_count 배치 조회
        from sqlalchemy import func as _sql_func
        _page_ids = [t.id for t in pagination.items]
        _memo_counts = {}
        if _page_ids:
            _mcrows = db.session.query(
                TenderMemo.tender_id, _sql_func.count(TenderMemo.id).label('cnt')
            ).filter(TenderMemo.tender_id.in_(_page_ids)).group_by(TenderMemo.tender_id).all()
            _memo_counts = {r[0]: r[1] for r in _mcrows}

        # 점수 계산용 키워드 (sort_keywords와 동일한 소스에서 이미 파싱됨)
        score_keywords = sort_keywords

        _tenders_data = []
        for t in pagination.items:
            d = t.to_dict(interest_keywords=interest_keywords)
            d['memo_count'] = _memo_counts.get(t.id, 0)
            if score_keywords:
                score, btype, kw_s, t_s, a_s = _score_and_type(
                    t, score_keywords, user_type_weights, user_agency_weights2, user_core_keywords2)
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
            memo = TenderMemo(tender_id=tender_id, user_id=g.user.id, content=content)  # type: ignore[call-arg]
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
            dismissed = DismissedTender(user_id=g.user.id, tender_id=tender_id)  # type: ignore[call-arg]
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


# ── 광역시도 → 하위 시/군/구 매핑 (지역 검색 확장용) ─────────────────────────
_REGION_ALIASES: dict = {
    '서울': ['강남구','강동구','강북구','강서구','관악구','광진구','구로구','금천구',
             '노원구','도봉구','동대문구','동작구','마포구','서대문구','서초구',
             '성동구','성북구','송파구','양천구','영등포구','용산구','은평구',
             '종로구','중구','중랑구'],
    '부산': ['강서구','금정구','기장군','남구','동구','동래구','부산진구','북구',
             '사상구','사하구','서구','수영구','연제구','영도구','해운대구'],
    '대구': ['남구','달서구','달성군','동구','북구','서구','수성구'],
    '인천': ['강화군','계양구','남동구','동구','미추홀구','부평구','서구',
             '연수구','옹진군'],
    '광주': ['광산구','남구','동구','북구','서구'],
    '대전': ['대덕구','동구','서구','유성구'],
    '울산': ['남구','동구','북구','울주군'],
    '세종': [],
    '경기': ['가평군','고양시','과천시','광명시','광주시','구리시','군포시','김포시',
             '남양주시','동두천시','부천시','성남시','수원시','시흥시','안산시',
             '안성시','안양시','양주시','양평군','여주시','연천군','오산시','용인시',
             '의왕시','의정부시','이천시','파주시','평택시','포천시','하남시','화성시'],
    '강원': ['강릉시','고성군','동해시','삼척시','속초시','양구군','양양군','영월군',
             '원주시','인제군','정선군','철원군','춘천시','태백시','평창군','홍천군',
             '화천군','횡성군'],
    '충북': ['괴산군','단양군','보은군','영동군','옥천군','음성군','제천시','증평군',
             '진천군','청주시','충주시'],
    '충남': ['계룡시','공주시','금산군','논산시','당진시','보령시','부여군','서산시',
             '서천군','아산시','예산군','천안시','청양군','태안군','홍성군'],
    '전북': ['고창군','군산시','김제시','남원시','무주군','부안군','순창군','완주군',
             '익산시','임실군','장수군','전주시','정읍시','진안군'],
    '전남': ['강진군','고흥군','곡성군','광양시','구례군','나주시','담양군','목포시',
             '무안군','보성군','순천시','신안군','여수시','영광군','영암군','완도군',
             '장성군','장흥군','진도군','함평군','해남군','화순군'],
    '경북': ['경산시','경주시','고령군','구미시','군위군','김천시','문경시','봉화군',
             '상주시','성주군','안동시','영덕군','영양군','영주시','영천시','예천군',
             '울릉군','울진군','의성군','청도군','청송군','칠곡군','포항시'],
    '경남': ['거제시','거창군','고성군','김해시','남해군','밀양시','사천시','산청군',
             '양산시','의령군','진주시','창녕군','창원시','통영시','하동군','함안군',
             '함양군','합천군'],
    '제주': ['제주시','서귀포시'],
}

_history_cache: dict = {}           # {tender_id: (epoch, result_dict)}
_HISTORY_CACHE_TTL = 3600           # 1시간


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

    # ── 캐시 확인 (1시간 TTL) ────────────────────────────────────────────────
    _force = request.args.get('force', '0') == '1'
    _now_ts = _time.time()
    _cached = _history_cache.get(tender_id)
    if _cached and not _force:
        _ts, _result = _cached
        if _now_ts - _ts < _HISTORY_CACHE_TTL:
            return jsonify({**_result, 'cached': True})

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
    # 상·하반기 / 학기 표현 제거: 매년 동일 사업이 "상반기"/"하반기"로 나뉘어 공고될 때
    # 쿼리에 "하반기"가 포함되면 "상반기" 공고가 조회되지 않으므로 제거
    clean = _re.sub(r'[상하]반기', '', clean)
    clean = _re.sub(r'[1-4]학기', '', clean)
    clean = _re.sub(r'\s+', ' ', clean).strip()

    # ── API 검색어 빌딩 ───────────────────────────────────────────────────────
    # G2B API는 exact substring 검색 → 쿼리에 연도간 변동 단어가 들어가면 매칭 실패
    #
    # Case 1 — 일반어(stopword)가 중간에 낀 경우
    #   "AI바우처 사업 사업화 역량" → "사업" 제거 → "AI바우처 사업화 역량"
    #   (같은 연도의 공고명이 "AI바우처 사업화 역량..."로 되어 있어야 매칭)
    #
    # Case 2 — "·" 복합어로 새 단어가 추가된 경우
    #   "AI·디지털 실생활 역량" → split → "AI 디지털 실생활"
    #   2025년 공고는 "AI 실생활 역량..."이라 매칭 안 됨
    #   → "·" 두 번째 토큰(디지털)을 제외한 보조 쿼리 "AI 실생활 역량"도 병행 실행
    _QUERY_STOPWORDS = {'사업', '용역', '운영', '관리', '지원', '추진', '수행'}
    # "·" 복합어 두 번째 파트 수집 (ex: "AI·디지털" → {'디지털'})
    _dot_extras = set(_re.findall(r'[가-힣A-Za-z0-9]+·([가-힣A-Za-z0-9]+)', clean))

    _search_clean = _re.sub(r'[·/~\-+·]', ' ', clean)
    _search_clean = _re.sub(r'\s+', ' ', _search_clean).strip()
    _clean_words = _search_clean.split()

    def _pick_query(word_list, extra_exclude=None):
        """stopword + optional extra_exclude 제거 후 앞 3단어 조합"""
        exclude = _QUERY_STOPWORDS | (extra_exclude or set())
        mw = [w for w in word_list if w not in exclude]
        if len(mw) >= 3:
            return ' '.join(mw[:3])
        if len(mw) >= 2:
            return ' '.join(mw[:2])
        # 의미어가 부족하면 원본으로 폴백
        return ' '.join(word_list[:3]) if len(word_list) >= 3 else ' '.join(word_list)

    query_nm     = _pick_query(_clean_words)[:60]               # 주 쿼리
    query_nm_alt = _pick_query(_clean_words, _dot_extras)[:60]  # 보조 쿼리 ("·" 추가어 제외)

    # 두 쿼리가 같으면 보조 쿼리 불필요
    _queries = [query_nm] if query_nm_alt == query_nm else [query_nm, query_nm_alt]

    # ── 유사도·기관 매칭 유틸 ─────────────────────────────────────────────────
    import difflib as _difflib

    def _norm_title(s):
        """공고명 정규화: 연도·괄호접두어·차수 등 제거"""
        s = _re.sub(r'\[[^\]]+\]', '', s)
        s = _re.sub(
            r'\(\s*(?:입찰재공고|입찰공고|입찰|재공고|재입찰|긴급|사전규격공개|사전규격'
            r'|일반용역|추가공고|정정공고|공고|변경)\s*\)',
            '', s, flags=_re.IGNORECASE,
        )
        s = _re.sub(r'\d{4}년도?', '', s)
        s = _re.sub(r"'\d{2}년도?", '', s)
        s = _re.sub(r'\(\s*20\d{2}\s*\)', '', s)
        s = _re.sub(r'\b(?:19|20)\d{2}\b', '', s)
        s = _re.sub(r'제\s*\d+\s*회차?', '', s)
        s = _re.sub(r'\d+\s*차년도', '', s)
        s = _re.sub(r'\d+\s*차\b', '', s)
        s = _re.sub(r'^\(?\s*(?:입찰재공고|입찰공고|재공고|재입찰)\s*\)?[\s-]*', '', s)
        return _re.sub(r'\s+', ' ', s).strip()

    def _name_similarity(a, b):
        """정규화된 공고명 간 유사도 (0.0~1.0)"""
        a2, b2 = _norm_title(a), _norm_title(b)
        if not a2 or not b2:
            return 0.0
        return _difflib.SequenceMatcher(None, a2, b2).ratio()

    def _agency_match(tender_ag, tender_demand_ag, item):
        """발주처(수요기관) 매칭.
        API 응답에 기관 정보가 없으면 True (미필터) — false negative 방지.
        개찰결과: ntceInsttNm / 낙찰결과: dminsttNm 사용.
        """
        item_ags = [
            (item.get('ntceInsttNm') or '').strip(),   # 개찰결과 공고기관
            (item.get('demandOrgNm') or '').strip(),   # (일부 API)
            (item.get('dminsttNm')   or '').strip(),   # 낙찰결과 수요기관
        ]
        item_ags = [a for a in item_ags if a]
        if not item_ags:
            return True   # 기관 정보 없음 → 이름 유사도만으로 판단

        def _pair(a, b):
            if not a or not b:
                return False
            a, b = a.strip(), b.strip()
            if a == b:
                return True
            shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
            return len(shorter) >= 4 and shorter in longer

        for item_ag in item_ags:
            if _pair(tender_ag, item_ag) or _pair(tender_demand_ag, item_ag):
                return True
        return False

    _tender_agency        = tender.agency        or ''
    _tender_demand_agency = tender.demand_agency or ''
    _title_norm           = _norm_title(title)   # 현재 공고 정규화명

    # ── 조회 기간: 최근 3년 × 월별 목록 ─────────────────────────────────────
    # G2B API 제약: 1개월 초과 범위(07 오류) → 월별 분할 필수
    # 3년(36개월) × 2 API × 10 workers = 검색당 최대 72 호출
    # (기존 5년 × 40 workers = 120 호출 → 429 재시도 × 3 = 360 호출)
    now = _dt.now()
    periods = []
    for offset in range(36):   # 3년 = 36개월
        y, m = now.year, now.month - offset
        while m <= 0:
            m += 12; y -= 1
        last_day = _cal.monthrange(y, m)[1]
        periods.append((f'{y}{m:02d}010000', f'{y}{m:02d}{last_day:02d}2359'))

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
        """GET 요청 → (items, error_str).
        - 429(할당량 초과): 즉시 포기 — 재시도해도 quota는 회복 안 됨
        - 502/503(일시 오류): 최대 2회 재시도
        """
        for attempt in range(3):
            try:
                r = _req.get(url, params=params, timeout=timeout)
                if r.status_code == 429:
                    return [], '할당량초과(429)'   # 재시도 없이 즉시 반환
                if r.status_code in (502, 503):
                    _time.sleep(2 + attempt * 2)
                    continue
                if r.status_code != 200:
                    return [], f'HTTP {r.status_code}'
                text = r.text.strip()
                if not text or text.startswith('<'):
                    return [], None
                data = r.json()
                # G2B 비표준 오류 응답 처리
                if 'nkoneps.com.response.ResponseError' in data:
                    err_code = data['nkoneps.com.response.ResponseError'].get('header', {}).get('resultCode', '')
                    err_msg  = data['nkoneps.com.response.ResponseError'].get('header', {}).get('resultMsg', '')
                    return [], f'{err_code}:{err_msg}'
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

    # ── 1단계: 개찰결과 + 낙찰결과 — 월별 병렬 조회 ─────────────────────────
    ops = [
        ('openg', RESULT_BASE, 'getOpengResultListInfoServcPPSSrch'),
        ('award', RESULT_BASE, 'getScsbidListSttusServcPPSSrch'),
    ]

    def fetch_period(kind, base, ep, bdt, edt, qnm):
        items, err = _safe_get(
            f'{base}/{ep}',
            {'ServiceKey': service_key, 'type': 'json',
             'inqryDiv': '1', 'inqryBgnDt': bdt, 'inqryEndDt': edt,
             'bidNtceNm': qnm, 'pageNo': '1', 'numOfRows': '100'},
        )
        return kind, items, err

    openg_by_no: dict = {}
    award_by_no: dict = {}
    errors = []

    def _run_query(qnm):
        """월별 병렬 조회 (workers=10, 429 즉시 중단)"""
        _quota_hit = False
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = [
                ex.submit(fetch_period, kind, base, ep, bdt, edt, qnm)
                for kind, base, ep in ops
                for bdt, edt in periods
            ]
            for fut in as_completed(futures):
                kind, items, err = fut.result()
                if err:
                    if '429' in str(err) or '할당량' in str(err):
                        _quota_hit = True
                    errors.append(f'{kind}: {err}')
                    continue
                for item in items:
                    bid_no = item.get('bidNtceNo', '')
                    if not bid_no:
                        continue
                    _dedup_key = (bid_no, item.get('bidNtceOrd', '000'))
                    if kind == 'openg':
                        openg_by_no.setdefault(bid_no, []).append(item)
                    elif kind == 'award':
                        award_by_no.setdefault(bid_no, []).append(item)
        return _quota_hit

    # 주 쿼리 실행
    _quota_exceeded = _run_query(query_nm)

    # 보조 쿼리: 주 쿼리 결과 없고, 할당량 초과 아닐 때만 실행
    if not _quota_exceeded and not (openg_by_no or award_by_no) and len(_queries) > 1:
        errors.clear()
        _run_query(query_nm_alt)

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

    # ── 후처리 필터: 수요기관 일치 + 사업명 유사도 70% 이상 ─────────────────────
    # G2B API는 공고명 키워드 검색이라 관련 없는 결과가 섞일 수 있음
    # → 발주처(수요기관)가 같고, 정규화 공고명 유사도 ≥ 70% 인 것만 유지
    SIMILARITY_THRESHOLD = 0.70
    filtered_items = []
    for _it in final_items:
        _item_nm = _it.get('bidNtceNm', '')
        _sim = _name_similarity(_title_norm, _item_nm)
        _ag  = _agency_match(_tender_agency, _tender_demand_agency, _it)
        if _sim >= SIMILARITY_THRESHOLD and _ag:
            _it['_similarity'] = round(_sim, 2)
            filtered_items.append(_it)
    final_items = filtered_items

    # ── 정렬: 개찰일/공고일 최신순 ──────────────────────────────────────────
    def _sort_key(x):
        return x.get('rlOpengDt') or x.get('opengDt') or x.get('fnlSucsfDate') or x.get('bidNtceDt') or ''

    final_items.sort(key=_sort_key, reverse=True)

    _result_data = {
        'items':          final_items,
        'query':          query_nm,
        'queries':        _queries,
        'original_title': title,
        'errors':         list(set(errors))[:5],
        'pblnc_api_ok':   True,
    }
    _history_cache[tender_id] = (_time.time(), _result_data)

    return jsonify({
        'items':          final_items,
        'query':          query_nm,
        'queries':        _queries,
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
        if scheduler.is_crawling:
            return jsonify({
                'message': '이미 크롤링이 진행 중입니다.',
                'status': 'already_running'
            }), 409

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


def _localhost_only():
    """127.0.0.1에서 온 요청인지 확인. 아니면 403 반환."""
    from flask import request as _req
    remote = _req.remote_addr
    if remote not in ('127.0.0.1', '::1', 'localhost'):
        from flask import abort
        abort(403)


@bp.route('/api/internal/crawl/start', methods=['POST'])
def api_internal_crawl_start():
    """로컬 전용 — 인증 없이 크롤링 시작 (CLI/스크립트용)"""
    _localhost_only()
    scheduler = getattr(current_app, 'crawler_scheduler', None)
    if not scheduler:
        return jsonify({'error': '스케줄러가 초기화되지 않았습니다.'}), 500
    if scheduler.is_crawling:
        return jsonify({'message': '이미 크롤링이 진행 중입니다.', 'status': 'already_running'}), 409

    def run_crawl():
        result = scheduler.run_manual_crawl()
        print(f"[수동 크롤링] 결과: {result}")

    t = threading.Thread(target=run_crawl, daemon=True)
    t.start()
    return jsonify({'message': '크롤링이 시작되었습니다.', 'status': 'started'}), 200


@bp.route('/api/internal/crawl/stop', methods=['POST'])
def api_internal_crawl_stop():
    """로컬 전용 — 인증 없이 크롤링 강제 중지 (CLI/스크립트용)"""
    _localhost_only()
    scheduler = getattr(current_app, 'crawler_scheduler', None)
    if not scheduler:
        return jsonify({'error': '스케줄러가 초기화되지 않았습니다.'}), 500
    if scheduler.stop_crawl():
        return jsonify({'message': '크롤링 중지 요청이 전송되었습니다.', 'status': 'stopping'}), 200
    else:
        return jsonify({'message': '진행 중인 크롤링이 없습니다.', 'status': 'not_running'}), 200


@bp.route('/api/internal/crawl/status')
def api_internal_crawl_status():
    """로컬 전용 — 인증 없이 상태 조회 (CLI/스크립트 검증용)"""
    _localhost_only()
    scheduler = getattr(current_app, 'crawler_scheduler', None)
    is_running = scheduler.is_crawling if scheduler else False
    progress = scheduler.crawl_progress if scheduler else None
    latest_log = CrawlLog.query.order_by(CrawlLog.started_at.desc()).first()
    data = latest_log.to_dict() if latest_log else {}
    data['is_running'] = is_running
    data['progress'] = progress
    return jsonify(data)


@bp.route('/api/crawl/stop', methods=['POST'])
@admin_required
def api_crawl_stop():
    """실행 중인 크롤링 강제 중지"""
    scheduler = getattr(current_app, 'crawler_scheduler', None)
    if not scheduler:
        return jsonify({'error': '스케줄러가 초기화되지 않았습니다.'}), 500
    if scheduler.stop_crawl():
        return jsonify({'message': '크롤링 중지 요청이 전송되었습니다.', 'status': 'stopping'}), 200
    else:
        return jsonify({'message': '진행 중인 크롤링이 없습니다.', 'status': 'not_running'}), 200


@bp.route('/api/crawl/status')
@admin_required
def api_crawl_status():
    """최근 크롤링 상태 조회"""
    try:
        scheduler = getattr(current_app, 'crawler_scheduler', None)
        is_running = scheduler.is_crawling if scheduler else False
        progress = scheduler.crawl_progress if scheduler else None

        latest_log = CrawlLog.query.order_by(
            CrawlLog.started_at.desc()).first()
        if latest_log:
            data = latest_log.to_dict()
            data['is_running'] = is_running
            data['progress'] = progress
            return jsonify(data)
        else:
            return jsonify({'message': '크롤링 기록이 없습니다.', 'is_running': is_running, 'progress': progress}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/crawl/site-stats')
@admin_required
def api_crawl_site_stats():
    """
    사이트별 평균 소요 시간 및 성공률 통계.
    최근 N개 크롤링 로그의 site_results(elapsed_sec 포함)를 집계한다.
    오래된 로그는 elapsed_sec가 없을 수 있으며 해당 기록은 시간 집계에서 제외된다.
    """
    try:
        limit = int(request.args.get('limit', 20))
        logs = CrawlLog.query.filter(
            CrawlLog.site_results.isnot(None)
        ).order_by(CrawlLog.started_at.desc()).limit(limit).all()

        stats = {}  # site_name -> {durations: [], success: 0, fail: 0, timeout: 0}
        for log in logs:
            try:
                site_results = json.loads(log.site_results)
            except Exception:
                continue
            for site_name, r in site_results.items():
                s = stats.setdefault(site_name, {'durations': [], 'success': 0, 'fail': 0})
                if 'elapsed_sec' in r:
                    s['durations'].append(r['elapsed_sec'])
                if r.get('success'):
                    s['success'] += 1
                else:
                    s['fail'] += 1

        result = []
        for site_name, s in stats.items():
            durations = s['durations']
            avg_sec = round(sum(durations) / len(durations), 1) if durations else None
            max_sec = max(durations) if durations else None
            total = s['success'] + s['fail']
            result.append({
                'site': site_name,
                'avg_elapsed_sec': avg_sec,
                'max_elapsed_sec': max_sec,
                'runs_counted': len(durations),
                'success_count': s['success'],
                'fail_count': s['fail'],
                'success_rate': round(s['success'] / total * 100, 1) if total else None,
            })

        # 평균 소요 시간이 긴 순서로 정렬 (느린 사이트를 먼저 보여줌)
        result.sort(key=lambda x: (x['avg_elapsed_sec'] is None, -(x['avg_elapsed_sec'] or 0)))

        return jsonify({'sites': result, 'logs_analyzed': len(logs)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
