from flask import Blueprint, request, jsonify, g, current_app
from database import db, Tender, CrawlLog, TenderMemo, DismissedTender, Filter
from decorators import login_required, admin_required
from scoring import load_user_prefs, load_interest_keywords
from relevance import Scorer
from sqlalchemy import func as sql_func
from config import Config
from datetime import datetime, timedelta
import json
import re
import threading

bp = Blueprint('tenders', __name__)

# 제목 키워드 매칭 시 무시할 구두점/공백 문자
# "AI·빅데이터"(가운뎃점) vs "AI 빅데이터"(공백) vs "AI빅데이터"(붙여쓰기)처럼
# 표기만 다르고 의미는 같은 경우가 실제 공고 제목에 흔한데, 기존에는 완전
# 문자열 부분일치(LIKE)만 써서 표기가 조금만 달라도 검색이 실패했다.
# (실제 사례: "2026년도 AI·빅데이터 기반 소상공인 매출 증대 프로젝트 운영 용역"을
#  "AI 빅데이터"나 "매출증대"로 검색하면 안 나오던 문제)
_TITLE_SEARCH_STRIP_CHARS = [' ', '·', '/', '-', '~', '(', ')', '[', ']']


def _title_contains(keyword):
    """제목과 검색어 양쪽에서 공백·가운뎃점 등 구두점을 제거한 뒤 부분일치 비교하는
    SQLAlchemy 필터 조건을 반환한다."""
    norm_title = Tender.title
    norm_kw = keyword
    for ch in _TITLE_SEARCH_STRIP_CHARS:
        norm_title = sql_func.replace(norm_title, ch, '')
        norm_kw = norm_kw.replace(ch, '')
    return norm_title.contains(norm_kw)


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
            filters.append(_title_contains(title_key))

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


def _apply_interest_filters(query, prefs):
    """
    사용자 관심 설정으로 거른다: 제외 키워드 → 관심 키워드(하나라도 포함) → 금액 범위.
    금액이 비어 있는 공고는 금액 조건을 통과시킨다.
    """
    for keyword in prefs['exclude_keywords']:
        query = query.filter(~_title_contains(keyword))
    if prefs['interest_keywords']:
        query = query.filter(db.or_(*[_title_contains(kw) for kw in prefs['interest_keywords']]))
    budget = prefs['budget_range']
    if budget.get('min'):
        query = query.filter(
            db.or_(Tender.estimated_price == None, Tender.estimated_price >= budget['min']))
    if budget.get('max'):
        query = query.filter(
            db.or_(Tender.estimated_price == None, Tender.estimated_price <= budget['max']))
    return query


def _scored_dict(tender, prefs, result):
    """공고를 화면용 dict 로 바꾸고 적합도를 붙인다. result 는 Scorer.score() 가 그 공고에 낸 값."""
    d = tender.to_dict(interest_keywords=prefs['interest_keywords'])
    d['relevance_score'] = result['total']
    d['business_type'] = result['business_type']
    d['score_breakdown'] = Scorer.breakdown(result)
    if result.get('nearest_case'):
        d['nearest_case'] = result['nearest_case']
    return d


SECTION_NAMES = ('pre_tenders', 'urgent_tenders', 'recent_tenders')
DASHBOARD_TOP_N = 15   # 대시보드 탭마다 보여 주는 건수 — 한 번에 볼 '진짜 중요한 것'만 (쪽 넘기기 없음)


def dashboard_section_conditions(now):
    """대시보드 구역 3개의 조건. {구역: [(설명, 조건, 구역을 가르는 조건인가)]}

    '구역을 가르는 조건'(출처·사전규격 여부)은 공고가 어느 구역 소속인지를 정하고,
    나머지(기간·상태·수의계약)는 그 구역 안에서 거르는 조건이다. 놓친 공고 진단이 이 구분을 쓴다.
    순서는 예전 api_dashboard 의 filter() 인자 순서 그대로다.
    """
    seven_days_ago = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    recent_open = [
        ('공고일이 최근 7일 밖 (또는 공고일 없음)', Tender.announced_date >= seven_days_ago, False),
        ('공고일이 적재 시점보다 뒤', Tender.announced_date <= now, False),
        ('사전규격 아님', Tender.status != '사전규격', True),
        ('결과공고', Tender.status != '결과공고', False),
        ('마감이 지남 (또는 마감일 없음)', Tender.deadline_date >= now, False),
        ('수의계약 (또는 입찰방식 없음)', ~Tender.bid_method.contains('수의계약'), False),
    ]
    return {
        # 사전규격: 나라장터 사전규격 중 마감 전
        'pre_tenders': [
            ('마감이 지남 (또는 마감일 없음)', Tender.deadline_date >= now, False),
            ('사전규격', Tender.status == '사전규격', True),
            ('나라장터', db.or_(Tender.source_site.contains('나라장터'), Tender.source_site.contains('g2b')), True),
        ],
        # 신규공고(나라장터 API)
        'urgent_tenders': recent_open + [
            ('나라장터 API', db.or_(Tender.source_site.contains('나라장터 API'),
                                    Tender.source_site.like('%g2b_api%')), True),
        ],
        # 신규공고(기타 채널): 나라장터 제외
        'recent_tenders': recent_open + [
            ('나라장터 아님', ~Tender.source_site.contains('나라장터'), True),
            ('g2b 아님', ~Tender.source_site.like('%g2b%'), True),
        ],
    }


def dashboard_section_queries(now):
    """대시보드 구역 3개의 쿼리 (관심 설정 필터 적용 전)."""
    return {name: Tender.query.filter(*[c for _, c, _ in conds])
            for name, conds in dashboard_section_conditions(now).items()}


@bp.route('/api/dashboard')
@login_required
def api_dashboard():
    """대시보드 데이터 조회"""
    try:
        now = datetime.now()
        # 어제 자정(00:00:00) 기준 — timedelta(1)은 현재 시각 기준이므로 00:00 공고가 탈락하는 버그 방지
        yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        uid = g.user.id if g.user else None
        fresh_only = request.args.get('fresh') == '1'
        prefs = load_user_prefs(uid)
        include_keywords = prefs['interest_keywords']
        scorer = Scorer(uid)
        # 관심없음 처리된 공고
        dismissed = {d.tender_id for d in DismissedTender.query.filter_by(user_id=uid).all()} if uid else set()

        not_private = ~Tender.bid_method.contains('수의계약')

        # ── 상단 요약 숫자 (전체 공고 기준, 관심 설정과 무관) ────────────────────
        summary = {
            # 신규공고: 공고일이 어제~오늘 (수의계약 제외)
            'new_today': Tender.query.filter(
                Tender.announced_date >= yesterday, Tender.announced_date <= now, not_private).count(),
            # 사전규격: 마감일이 지나지 않은 것
            'pre_announcement': Tender.query.filter(
                Tender.status == '사전규격', Tender.deadline_date >= now).count(),
            # 마감 임박: 3일 이내 (수의계약 제외)
            'deadline_soon': Tender.query.filter(
                Tender.deadline_date >= now, Tender.deadline_date <= now + timedelta(days=3),
                not_private).count(),
            'total': Tender.query.count(),
        }

        # ── 목록 3개: 조건만 다르고, 관심 설정 필터와 정렬은 같다 ──────────────
        response_data = {'summary': summary}
        matched = 0
        # fresh=1: 15칸을 '아직 처리 안 한 공고'로 채운다 — 열어 본 공고는 바로, 담은 공고는 다음 날 빠지고 다음 순위가 올라온다
        handled = _handled(uid) if fresh_only else set()
        filtered = {name: [t for t in _apply_interest_filters(query, prefs).all()
                           if t.id not in dismissed and t.id not in handled]
                    for name, query in dashboard_section_queries(now).items()}
        # 적합도(제품 계약서 3부): 구역을 합쳐 한 번에 점수를 낸다 — 좋은 사례 벡터를 한 번만 읽는다
        scores = scorer.score([t for ts in filtered.values() for t in ts])
        for name, tenders in filtered.items():
            matched += len(tenders)
            ordered = scorer.sort(tenders, scores)
            response_data[name] = [_scored_dict(t, prefs, scores[t.id]) for t in ordered[:DASHBOARD_TOP_N]]

        summary['keyword_match'] = matched   # 관심 설정에 걸린 전체 건수 (배지용)
        response_data['include_keywords'] = include_keywords
        response_data['exclude_keywords'] = prefs['exclude_keywords']
        import reasons          # 자격 확인 표시 (5부) — 순서와 점수가 정해진 뒤에 붙인다
        reasons.attach_flags(uid, [d for name in SECTION_NAMES for d in response_data[name]])
        return jsonify(response_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _key_agency_candidates(names, now):
    """등록 이름이 발주기관·수요기관에 들어 있는 진행 중 공고, 수집일이 새로운 순.
    이름의 % 와 _ 는 글자 그대로 찾는다 (autoescape) — 그렇지 않으면 '%' 한 글자가 전 공고를 읽어 온다."""
    name_match = db.or_(*[c.contains(name, autoescape=True)
                          for name in names for c in (Tender.agency, Tender.demand_agency)])
    return (Tender.query
            .filter(name_match,
                    db.or_(Tender.deadline_date == None, Tender.deadline_date >= now),
                    db.or_(Tender.status == None, Tender.status != '결과공고'),
                    db.or_(Tender.is_duplicate == None, Tender.is_duplicate == False))
            .order_by(Tender.created_at.desc(), Tender.id.desc()).all())


@bp.route('/api/dashboard/key-agencies')
@login_required
def api_key_agencies():
    """중점 발주처 탭 (제품 계약서 3부 22.5): "이 발주처의 다른 사업들은 이렇다".

    중점으로 등록한 발주처의 공고 가운데 아직 처리하지 않은 것을 적합도·관심 키워드와 상관없이 모은다.
    적합도는 일 기준 그대로 붙인다(맞지 않는 사업은 낮게 보인다). 수의계약도 넣는다.
    마감이 지난 공고와 결과공고는 뺀다. 적합도 높은 순(같으면 수집일이 새로운 순), 최대 DASHBOARD_TOP_N 건.
    점수가 낮아도 빼지 않는다 — 중점 발주처의 공고는 "무조건" 나온다.
    """
    import relevance
    uid = g.user.id
    try:
        marks = relevance.load_agency_marks(uid)
        keys = sorted(name for name, m in marks.items() if m == relevance.MARK_KEY)
        if not keys:
            return jsonify({'agencies': [], 'items': []})
        skip = _handled(uid) | {d.tender_id for d in DismissedTender.query.filter_by(user_id=uid).all()}
        # 더 긴 이름으로 후순위에 둔 발주처면(예: '서울' 중점, '서울시교육청' 후순위) 중점 발주처가 아니다
        rows = [t for t in _key_agency_candidates(keys, datetime.now())
                if t.id not in skip and relevance.agency_mark(t.agency, t.demand_agency, marks) == relevance.MARK_KEY]
        prefs = load_user_prefs(uid)
        scores = Scorer(uid).score(rows)
        # rows 는 수집일이 새로운 순 — 안정 정렬이라 점수가 같으면 그 순서가 남는다
        picked = sorted(rows, key=lambda t: -scores[t.id]['total'])[:DASHBOARD_TOP_N]
        items = []
        for t in picked:
            d = _scored_dict(t, prefs, scores[t.id])
            d['matched_agency'] = relevance.matched_agency_name(t.agency, t.demand_agency, keys)
            items.append(d)
        import reasons
        reasons.attach_flags(uid, items)
        return jsonify({'agencies': keys, 'items': items})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


RECENT_VIEW_DAYS = 7    # '읽은 공고'에 남겨 두는 기간


def _utc_start_of_local_today():
    """오늘 0시(서버 현지 시각)를 UTC 로. 열람·북마크 시각은 UTC(datetime.utcnow)로 저장된다."""
    now = datetime.now()
    offset = now - datetime.utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0) - offset


def _handled(uid):
    """이미 처리한 공고 id — 열어 본 공고(바로)와 어제까지 담은 공고. 대시보드 15칸에서 뺀다.
    오늘 담은 공고는 남긴다 (별표를 누르자마자 사라지면 잘못 누른 것처럼 보인다)."""
    if not uid:
        return set()
    from database import Bookmark, TenderView
    seen = {r[0] for r in TenderView.query.filter(TenderView.user_id == uid)
            .with_entities(TenderView.tender_id).all()}
    kept = {r[0] for r in Bookmark.query.filter(Bookmark.user_id == uid, Bookmark.created_at < _utc_start_of_local_today())
            .with_entities(Bookmark.tender_id).all()}
    return seen | kept


@bp.route('/api/viewed/recent')
@login_required
def api_viewed_recent():
    """읽은 공고 — 열어 봤지만 담지도 숨기지도 지우지도 않은, 아직 마감 전인 공고. 최근에 본 순, 최대 15건.

    쌓이지 않게 하는 장치: 마감이 지나면 빠지고, 7일이 지나면 빠지고, 담거나 숨기거나 지우면 빠지고, 15건을 넘지 않는다.
    """
    from database import Bookmark, TenderView
    uid = g.user.id
    try:
        now = datetime.now()
        prefs = load_user_prefs(uid)
        skip = {d.tender_id for d in DismissedTender.query.filter_by(user_id=uid).all()}
        skip |= {r[0] for r in Bookmark.query.filter(Bookmark.user_id == uid).with_entities(Bookmark.tender_id).all()}
        rows = (db.session.query(TenderView, Tender).join(Tender, Tender.id == TenderView.tender_id)
                .filter(TenderView.user_id == uid, TenderView.cleared_at == None,
                        TenderView.viewed_at >= datetime.utcnow() - timedelta(days=RECENT_VIEW_DAYS),
                        db.or_(Tender.deadline_date == None, Tender.deadline_date >= now))
                .order_by(TenderView.viewed_at.desc()).all())
        shown = [(view, tender) for view, tender in rows if tender.id not in skip][:DASHBOARD_TOP_N]
        scores = Scorer(uid).score([tender for _, tender in shown])
        items = []
        for view, tender in shown:
            d = _scored_dict(tender, prefs, scores[tender.id])
            d['viewed_at'] = view.viewed_at.isoformat(timespec='seconds') + 'Z'
            items.append(d)
        import reasons
        reasons.attach_flags(uid, items)
        return jsonify({'items': items, 'days': RECENT_VIEW_DAYS})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/viewed/<int:tender_id>', methods=['DELETE'])
@login_required
def api_viewed_clear(tender_id):
    """읽은 공고 목록에서 지운다. 열람 기록은 남겨 15칸으로 돌아오지 않게 한다."""
    from database import TenderView
    try:
        view = TenderView.query.filter_by(user_id=g.user.id, tender_id=tender_id).first()
        if view is None:
            return jsonify({'cleared': False})
        view.cleared_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'cleared': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@bp.route('/api/viewed/ids')
@login_required
def api_viewed_ids():
    """내가 상세 화면을 열어 본 공고 id 목록 (대시보드가 '안 본 공고'를 앞에 두는 데 쓴다)."""
    from database import TenderView
    rows = TenderView.query.filter_by(user_id=g.user.id).with_entities(TenderView.tender_id).all()
    return jsonify(sorted(r[0] for r in rows))


@bp.route('/api/embed-scores', methods=['POST'])
@login_required
def api_embed_scores():
    """화면에 보이는 공고 ID 목록 → 적합도. 목록 API 와 같은 점수다 (3부부터 임베딩 혼합으로 숫자를 바꾸지 않는다).
    예전 화면 코드가 부르던 주소라 남겨 둔다."""
    try:
        tender_ids = (request.json or {}).get('tender_ids', [])
        if not tender_ids:
            return jsonify({'scores': {}})

        uid = g.user.id if g.user else None
        tenders = Tender.query.filter(Tender.id.in_(tender_ids)).all()
        scores = {}
        for tid, r in Scorer(uid).score(tenders).items():
            scores[str(tid)] = {
                'score': r['total'],
                'keyword': r['keyword'],
                'type': r['type'],
                'case': r['case'],
                'agency': r['agency'],
                'base': r['base'],
                'business_type': r['business_type'],
            }
        return jsonify({'scores': scores})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ════════════════════════════════════════════════════════════ 검색 (/api/tenders)

def _csv_arg(name):
    """쉼표로 구분된 요청 파라미터 → 빈 값을 뺀 목록"""
    return [v.strip() for v in request.args.get(name, '').split(',') if v.strip()]


def _keyword_expression(expr):
    """
    검색창 키워드 식을 조건으로 바꾼다. 쉼표는 OR, + 는 AND.
    예: "AI+교육, 시스템" → (AI AND 교육) OR 시스템.  조건이 없으면 None.
    """
    or_conditions = []
    for group in expr.split(','):
        and_keywords = [k.strip() for k in group.split('+') if k.strip()]
        if and_keywords:
            or_conditions.append(db.and_(*[_title_contains(k) for k in and_keywords]))
    return db.or_(*or_conditions) if or_conditions else None


def _apply_preset(query, filter_id):
    """저장된 필터(Filter)의 조건을 적용한다. 포함 키워드는 모두 포함(AND)."""
    preset = Filter.query.get(filter_id) if filter_id else None
    if not preset:
        return query
    for keyword in (json.loads(preset.include_keywords) if preset.include_keywords else []):
        query = query.filter(_title_contains(keyword))
    for keyword in (json.loads(preset.exclude_keywords) if preset.exclude_keywords else []):
        query = query.filter(~_title_contains(keyword))
    if preset.min_price:
        query = query.filter(Tender.estimated_price >= preset.min_price)
    if preset.max_price:
        query = query.filter(Tender.estimated_price <= preset.max_price)
    if preset.days_before_deadline:
        query = query.filter(
            Tender.deadline_date <= datetime.now() + timedelta(days=preset.days_before_deadline))
    return query


def _apply_date_range(query, column, date_from, date_to):
    """YYYY-MM-DD 문자열 범위를 적용한다. 끝 날짜는 그날 23:59:59 까지. 형식이 틀리면 무시."""
    if date_from:
        try:
            query = query.filter(column >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            end = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(column <= end)
        except ValueError:
            pass
    return query


def _apply_agency_and_region(query, regions, agency_include, agency_exclude):
    """지역(제목·기관명에서 찾음)과 수요기관 포함/제외 조건"""
    if regions:
        # 광역시도를 고르면 하위 시/군/구 이름도 함께 찾는다
        terms = []
        for r in regions:
            terms.append(r)
            terms.extend(_REGION_ALIASES.get(r, []))
        conditions = []
        for term in terms:
            conditions.append(Tender.title.ilike(f'%{term}%'))
            conditions.append(Tender.agency.ilike(f'%{term}%'))
            conditions.append(Tender.demand_agency.ilike(f'%{term}%'))
        query = query.filter(db.or_(*conditions))

    if agency_include:      # 하나라도 포함
        conditions = []
        for term in agency_include:
            conditions.append(Tender.demand_agency.ilike(f'%{term}%'))
            conditions.append(Tender.agency.ilike(f'%{term}%'))
        query = query.filter(db.or_(*conditions))

    # 제외: demand_agency 가 NULL 이면 NOT ILIKE 가 NULL 로 평가돼 공고가 통째로 빠진다.
    # → NULL 은 "해당 없음"으로 보고 통과시킨다
    for term in agency_exclude:
        query = query.filter(
            db.or_(Tender.demand_agency.is_(None),
                   ~Tender.demand_agency.ilike(f'%{term}%')),
            ~Tender.agency.ilike(f'%{term}%'),
        )
    return query


_REVISION_PREFIX = re.compile(
    r'^[\s\(（\[「『【]*(?:수정공고|재공고|재입찰|정정공고|취소공고)[\s\)）\]」』】,·\s]*', re.IGNORECASE)


def _dedupe_same_project(tenders):
    """
    같은 사업의 수정공고·재공고를 하나로 줄인다. 정렬된 목록에서 먼저 나온 것을 대표로 남긴다.
    상태(사전규격/일반)가 다르면 제목이 같아도 따로 보여준다.
    """
    seen = set()
    result = []
    for tender in tenders:
        title = re.sub(r'[「」『』【】\[\]]', '', _REVISION_PREFIX.sub('', tender.title)).strip()
        key = (title, tender.status)
        if key not in seen:
            seen.add(key)
            result.append(tender)
    return result


@bp.route('/api/tenders')
@login_required
def api_tenders():
    """공고 목록 조회 (필터링, 페이징)"""
    try:
        args = request.args
        page = args.get('page', 1, type=int)
        per_page = args.get('per_page', Config.ITEMS_PER_PAGE, type=int)

        # 수의계약은 항상 제외, 결과공고(선정결과·낙찰결과 등)는 show_result=1 일 때만 포함
        query = Tender.query.filter(~Tender.bid_method.contains('수의계약'))
        if args.get('show_result', '0') != '1':
            query = query.filter(Tender.status != '결과공고')

        # ── 키워드 ──────────────────────────────────────────────────────────
        query = _apply_preset(query, args.get('filter_id', type=int))
        keyword_condition = _keyword_expression(args.get('include_keywords', ''))
        if keyword_condition is not None:
            query = query.filter(keyword_condition)
        for keyword in _csv_arg('exclude_keywords'):
            query = query.filter(~_title_contains(keyword))

        if args.get('status', ''):
            query = query.filter_by(status=args.get('status'))

        # ── 날짜 ────────────────────────────────────────────────────────────
        date_args = {k: args.get(k, '') for k in (
            'announced_date_from', 'announced_date_to', 'deadline_date_from', 'deadline_date_to')}
        # 날짜를 하나도 지정하지 않으면 마감 전 공고만 보여준다 (include_expired=1 이면 마감된 것도)
        if not any(date_args.values()) and args.get('include_expired', '0') != '1':
            query = query.filter(Tender.deadline_date >= datetime.now())
        query = _apply_date_range(query, Tender.announced_date,
                                  date_args['announced_date_from'], date_args['announced_date_to'])
        query = _apply_date_range(query, Tender.deadline_date,
                                  date_args['deadline_date_from'], date_args['deadline_date_to'])

        # ── 금액 (원 단위) · 지역 · 수요기관 ─────────────────────────────────
        min_price = args.get('min_price', type=int)
        max_price = args.get('max_price', type=int)
        if min_price is not None:
            query = query.filter(Tender.estimated_price >= min_price)
        if max_price is not None:
            query = query.filter(Tender.estimated_price <= max_price)
        query = _apply_agency_and_region(
            query, _csv_arg('regions'), _csv_arg('demand_agency_include'), _csv_arg('demand_agency_exclude'))

        # ── 정렬 · 중복 제거 · 페이징 ────────────────────────────────────────
        # 점수/정렬은 항상 필터관리에 저장된 관심 키워드 기준 — 검색창 키워드와 무관.
        # 점수를 파이썬에서 계산하므로 조건에 맞는 공고를 전부 읽어 온 뒤 정렬한다.
        uid = g.user.id if g.user else None
        prefs = load_user_prefs(uid)
        interest_keywords = prefs['interest_keywords']
        scorer = Scorer(uid)
        found = query.all()
        scores = scorer.score(found)

        tenders = _dedupe_same_project(scorer.sort(found, scores))

        total = len(tenders)
        page_items = tenders[(page - 1) * per_page:page * per_page]

        memo_counts = {}
        if page_items:
            memo_counts = dict(db.session.query(
                TenderMemo.tender_id, sql_func.count(TenderMemo.id)
            ).filter(TenderMemo.tender_id.in_([t.id for t in page_items])
                     ).group_by(TenderMemo.tender_id).all())

        result = []
        for t in page_items:
            d = _scored_dict(t, prefs, scores[t.id])     # 관심 키워드가 없으면 Scorer 가 0점을 낸다
            d['memo_count'] = memo_counts.get(t.id, 0)
            result.append(d)

        import reasons
        reasons.attach_flags(uid, result)
        return jsonify({
            'tenders': result,
            'total': total,
            'pages': (total + per_page - 1) // per_page,
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
    """공고 관심없음 처리 / 취소.

    제외할 때는 이유를 꼭 받는다 (제품 계약서 5부 36.2): body {"reasons": [코드...]}, 자격·기타 묶음에서 하나 이상.
    이유가 없으면 제외하지 않는다. 이미 제외한 공고면 이유만 새 값으로 바꾼다.
    담는 이유 칩과 '자격 가능'은 남긴다 ('자격이 안 됨'을 골랐을 때만 '자격 가능'을 지운다).
    복원(DELETE)해도 이유는 남긴다 — 검토 기록이다."""
    import reasons
    try:
        existing = DismissedTender.query.filter_by(
            user_id=g.user.id, tender_id=tender_id).first()

        if request.method == 'POST':
            body = request.get_json(silent=True)
            try:
                codes = reasons.clean(body.get('reasons') if isinstance(body, dict) else None,
                                      groups=reasons.DISMISS_GROUPS)
                if not codes:
                    raise ValueError('이유 없음')
            except ValueError:
                return jsonify({'error': '제외하는 이유를 하나 이상 골라 주세요.'}), 400
            if not existing:
                db.session.add(DismissedTender(user_id=g.user.id, tender_id=tender_id))  # type: ignore[call-arg]
            reasons.set_dismiss_reasons(g.user.id, tender_id, codes, commit=False)
            db.session.commit()            # 제외와 이유를 한 번에 — 하나만 저장되는 일이 없게
            return jsonify({'dismissed': True, 'reasons': codes})

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
        import reasons
        why = reasons.get_reasons(g.user.id, [d.tender_id for d in dismissed])
        result = []
        for d in dismissed:
            tender = d.tender
            if not tender:
                continue
            td = tender.to_dict(interest_keywords=include_keywords)
            td['dismissed_at'] = d.created_at.isoformat()
            td['dismissed_id'] = d.id
            td['reasons'] = why.get(d.tender_id, [])      # 이유를 받기 전에 제외한 기록은 빈 목록
            td['reason_labels'] = [reasons.REASONS[c]['label'] for c in td['reasons']]
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
