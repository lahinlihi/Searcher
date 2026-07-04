"""
중복 제거 로직
공고번호 및 제목 기반으로 중복 공고를 제거합니다.
"""

def remove_duplicates(tenders, existing_tender_numbers=None, existing_titles=None, existing_urls=None):
    """
    중복 공고 제거

    Args:
        tenders (list): 공고 리스트
        existing_tender_numbers (set): 이미 DB에 있는 공고번호 집합
        existing_titles (set): 이미 DB에 있는 공고 제목 집합
        existing_urls (set): 이미 DB에 있는 URL 집합

    Returns:
        tuple: (unique_tenders, duplicate_tenders)
    """
    if existing_tender_numbers is None:
        existing_tender_numbers = set()
    if existing_titles is None:
        existing_titles = set()
    if existing_urls is None:
        existing_urls = set()

    unique_tenders = []
    duplicate_tenders = []

    seen_numbers = existing_tender_numbers.copy()
    seen_titles = existing_titles.copy()
    seen_urls = existing_urls.copy()

    for tender in tenders:
        tender_number = tender.get('tender_number')
        title = tender.get('title', '')
        url = tender.get('url', '')

        # 1. 공고번호 중복 체크 (O(1))
        if tender_number and tender_number in seen_numbers:
            tender['is_duplicate'] = True
            duplicate_tenders.append(tender)
            continue

        # 2. URL 중복 체크 — 같은 URL은 동일 공고 (제목이 조금 바뀌어도)
        if url and url in seen_urls:
            tender['is_duplicate'] = True
            duplicate_tenders.append(tender)
            continue

        # 3. 제목 정확 일치 중복 체크 (O(1)) — DB 기존 + 현재 배치 모두 포함
        if title and title in seen_titles:
            tender['is_duplicate'] = True
            duplicate_tenders.append(tender)
            continue

        # 중복이 아니면 추가
        tender['is_duplicate'] = False
        unique_tenders.append(tender)

        if tender_number:
            seen_numbers.add(tender_number)
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)

    return unique_tenders, duplicate_tenders


def merge_duplicates(tenders):
    """
    중복 공고 병합 (같은 공고의 다른 버전)

    Args:
        tenders (list): 공고 리스트

    Returns:
        list: 병합된 공고 리스트
    """
    # 공고번호별로 그룹화
    grouped = {}

    for tender in tenders:
        tender_number = tender.get('tender_number')
        if not tender_number:
            continue

        if tender_number not in grouped:
            grouped[tender_number] = []
        grouped[tender_number].append(tender)

    # 각 그룹에서 최신 공고만 유지
    merged = []
    for tender_number, group in grouped.items():
        if len(group) == 1:
            merged.append(group[0])
        else:
            # 가장 최근에 크롤링된 것 선택
            latest = max(group, key=lambda x: x.get('announced_date', ''))
            merged.append(latest)

    return merged


import re as _re

# NIA [조달입찰공고] 제목에서 실제 사업명 추출
_NIA_PROC_PREFIX = _re.compile(r'^\[조달입찰공고\]\s*')
_NIA_PROC_SUFFIX = _re.compile(r'\s*-\s*(첨부파일\s*(있음|없음)|파일\s*(있음|없음))$')
_G2B_SOURCES = {'나라장터 API (용역)', '나라장터 API (물품)', '나라장터 API (공사)',
                '나라장터 API (외자)', '나라장터 사전규격 (용역)', '나라장터 사전규격 (물품)',
                '나라장터 사전규격 (공사)', '나라장터 사전규격 (외자)'}


def _strip_nia_proc_prefix(title):
    """NIA [조달입찰공고] 제목에서 실제 사업명만 추출"""
    t = _NIA_PROC_PREFIX.sub('', title or '')
    t = _NIA_PROC_SUFFIX.sub('', t)
    return t.strip()


def mark_nia_procurement_duplicates(app):
    """
    NIA [조달입찰공고] 항목 중 나라장터에 동명 공고가 있으면 NIA 항목을 중복으로 표시.
    나라장터 버전이 더 정확하므로 NIA 쪽을 is_duplicate=True 처리.
    """
    from database import db, Tender

    with app.app_context():
        # 나라장터 공고 제목 인덱스 (정규화 제목 → id)
        g2b_tenders = Tender.query.filter(
            Tender.source_site.in_(_G2B_SOURCES),
            Tender.is_duplicate == False,
        ).with_entities(Tender.id, Tender.title).all()
        g2b_title_map = {row[1].strip(): row[0] for row in g2b_tenders if row[1]}

        # NIA [조달입찰공고] 항목 조회
        nia_proc = Tender.query.filter(
            Tender.source_site == '한국지능정보사회진흥원',
            Tender.title.like('[조달입찰공고]%'),
            Tender.is_duplicate == False,
        ).all()

        marked = 0
        for t in nia_proc:
            real_title = _strip_nia_proc_prefix(t.title)
            if real_title in g2b_title_map:
                t.is_duplicate = True
                marked += 1

        if marked:
            db.session.commit()
        return marked


def mark_duplicates_in_db(app, new_tenders):
    """
    DB에 이미 존재하는 공고와 비교하여 중복 표시

    Args:
        app: Flask 앱 인스턴스
        new_tenders (list): 새로운 공고 리스트

    Returns:
        tuple: (unique_tenders, duplicate_count)
    """
    from database import Tender

    with app.app_context():
        # DB에서 모든 공고번호 가져오기
        existing_numbers = set(
            row[0] for row in Tender.query.with_entities(
                Tender.tender_number).filter(Tender.tender_number.isnot(None)).all())

        # DB에서 공고 제목 가져오기 (공고번호 없는 소스 방어)
        # 사전규격 source는 제외: 사전규격과 동명의 본 공고를 중복으로 처리하면 안 됨
        PRE_SPEC_SOURCES = {'나라장터 사전규격 (용역)', '나라장터 사전규격 (물품)',
                            '나라장터 사전규격 (공사)', '나라장터 사전규격 (외자)'}
        existing_titles = set(
            row[0] for row in Tender.query.with_entities(Tender.title)
            .filter(
                Tender.title.isnot(None),
                ~Tender.source_site.in_(PRE_SPEC_SOURCES)
            ).all()
        )

        # DB에서 URL 가져오기 — 같은 URL은 제목이 달라도 동일 공고로 처리
        existing_urls = set(
            row[0] for row in Tender.query.with_entities(Tender.url)
            .filter(Tender.url.isnot(None)).all()
        )

        # 중복 제거 (번호 + URL + 제목 모두 DB 비교)
        unique_tenders, duplicate_tenders = remove_duplicates(
            new_tenders, existing_numbers, existing_titles, existing_urls)

        # 새로 들어온 NIA [조달입찰공고]도 실시간 체크
        # (나라장터 버전이 이미 DB에 있으면 중복 처리)
        g2b_tenders = Tender.query.filter(
            Tender.source_site.in_(_G2B_SOURCES),
            Tender.is_duplicate == False,
        ).with_entities(Tender.title).all()
        g2b_titles = {row[0].strip() for row in g2b_tenders if row[0]}

        final_unique = []
        extra_dups = 0
        for t in unique_tenders:
            if (t.get('source_site') == '한국지능정보사회진흥원'
                    and t.get('title', '').startswith('[조달입찰공고]')):
                real = _strip_nia_proc_prefix(t['title'])
                if real in g2b_titles:
                    t['is_duplicate'] = True
                    extra_dups += 1
                    continue
            final_unique.append(t)

        return final_unique, len(duplicate_tenders) + extra_dups
