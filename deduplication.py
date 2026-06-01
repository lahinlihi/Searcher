"""
중복 제거 로직
공고번호 및 제목 기반으로 중복 공고를 제거합니다.
"""

def remove_duplicates(tenders, existing_tender_numbers=None, existing_titles=None):
    """
    중복 공고 제거

    Args:
        tenders (list): 공고 리스트
        existing_tender_numbers (set): 이미 DB에 있는 공고번호 집합
        existing_titles (set): 이미 DB에 있는 공고 제목 집합

    Returns:
        tuple: (unique_tenders, duplicate_tenders)
    """
    if existing_tender_numbers is None:
        existing_tender_numbers = set()
    if existing_titles is None:
        existing_titles = set()

    unique_tenders = []
    duplicate_tenders = []

    seen_numbers = existing_tender_numbers.copy()
    seen_titles = existing_titles.copy()

    for tender in tenders:
        tender_number = tender.get('tender_number')
        title = tender.get('title', '')

        # 1. 공고번호 중복 체크 (O(1))
        if tender_number and tender_number in seen_numbers:
            tender['is_duplicate'] = True
            duplicate_tenders.append(tender)
            continue

        # 2. 제목 정확 일치 중복 체크 (O(1)) — DB 기존 + 현재 배치 모두 포함
        if title and title in seen_titles:
            tender['is_duplicate'] = True
            duplicate_tenders.append(tender)
            continue

        # 중복이 아니면 추가
        tender['is_duplicate'] = False
        unique_tenders.append(tender)

        if tender_number:
            seen_numbers.add(tender_number)
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
        # (사전규격 공고번호 R26BD..., 본 공고 R26BK... — 번호가 달라 number 체크를 통과하므로
        #  title 체크까지 걸리면 본 공고가 저장되지 않는 문제 발생)
        PRE_SPEC_SOURCES = {'나라장터 사전규격 (용역)', '나라장터 사전규격 (물품)',
                            '나라장터 사전규격 (공사)', '나라장터 사전규격 (외자)'}
        existing_titles = set(
            row[0] for row in Tender.query.with_entities(Tender.title)
            .filter(
                Tender.title.isnot(None),
                ~Tender.source_site.in_(PRE_SPEC_SOURCES)
            ).all()
        )

        # 중복 제거 (번호 + 제목 모두 DB 비교)
        unique_tenders, duplicate_tenders = remove_duplicates(
            new_tenders, existing_numbers, existing_titles)

        return unique_tenders, len(duplicate_tenders)
