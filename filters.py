"""
필터링 로직
크롤링된 공고를 필터 조건에 따라 필터링합니다.
"""

from datetime import datetime, timedelta
import json


def apply_filter(tenders, filter_preset):
    """
    필터 프리셋을 공고 리스트에 적용

    Args:
        tenders (list): 공고 리스트
        filter_preset (Filter): 필터 프리셋 객체

    Returns:
        list: 필터링된 공고 리스트
    """
    filtered = []

    # 필터 조건 파싱
    include_keywords = json.loads(
        filter_preset.include_keywords) if filter_preset.include_keywords else []
    exclude_keywords = json.loads(
        filter_preset.exclude_keywords) if filter_preset.exclude_keywords else []

    for tender in tenders:
        # 포함 키워드 체크
        if include_keywords:
            if not any(kw.lower() in tender['title'].lower()
                       for kw in include_keywords):
                continue

        # 제외 키워드 체크
        if exclude_keywords:
            if any(kw.lower() in tender['title'].lower()
                   for kw in exclude_keywords):
                continue

        # 가격 범위 체크
        if filter_preset.min_price and tender.get('estimated_price'):
            if tender['estimated_price'] < filter_preset.min_price:
                continue

        if filter_preset.max_price and tender.get('estimated_price'):
            if tender['estimated_price'] > filter_preset.max_price:
                continue

        # 마감일 체크
        if filter_preset.days_before_deadline and tender.get('deadline_date'):
            deadline = tender['deadline_date']
            if isinstance(deadline, str):
                deadline = datetime.fromisoformat(deadline)

            max_deadline = datetime.now() + timedelta(days=filter_preset.days_before_deadline)
            if deadline > max_deadline:
                continue

        # 중소기업 전용 필터
        if filter_preset.sme_only and not tender.get('is_sme_only'):
            continue

        filtered.append(tender)

    # 사전규격 우선 정렬
    if filter_preset.priority_pre_announcement:
        filtered.sort(key=lambda x: (
            0 if x.get('status') == '사전규격' else 1,
            x.get('deadline_date', datetime.max)
        ))

    return filtered


def filter_by_keywords(tenders, include_keywords=None, exclude_keywords=None):
    """
    키워드로 공고 필터링

    Args:
        tenders (list): 공고 리스트
        include_keywords (list): 포함할 키워드
        exclude_keywords (list): 제외할 키워드

    Returns:
        list: 필터링된 공고 리스트
    """
    filtered = []

    for tender in tenders:
        title = tender.get('title', '').lower()

        # 포함 키워드
        if include_keywords:
            if not any(kw.lower() in title for kw in include_keywords):
                continue

        # 제외 키워드
        if exclude_keywords:
            if any(kw.lower() in title for kw in exclude_keywords):
                continue

        filtered.append(tender)

    return filtered


def filter_by_price_range(tenders, min_price=None, max_price=None):
    """
    가격 범위로 공고 필터링

    Args:
        tenders (list): 공고 리스트
        min_price (int): 최소 가격
        max_price (int): 최대 가격

    Returns:
        list: 필터링된 공고 리스트
    """
    filtered = []

    for tender in tenders:
        price = tender.get('estimated_price')
        if not price:
            continue

        if min_price and price < min_price:
            continue

        if max_price and price > max_price:
            continue

        filtered.append(tender)

    return filtered


def filter_by_deadline(tenders, days_before_deadline):
    """
    마감일로 공고 필터링

    Args:
        tenders (list): 공고 리스트
        days_before_deadline (int): 마감까지 남은 일수

    Returns:
        list: 필터링된 공고 리스트
    """
    filtered = []
    max_deadline = datetime.now() + timedelta(days=days_before_deadline)

    for tender in tenders:
        deadline = tender.get('deadline_date')
        if not deadline:
            continue

        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)

        if deadline <= max_deadline:
            filtered.append(tender)

    return filtered


def filter_by_status(tenders, status):
    """
    상태로 공고 필터링

    Args:
        tenders (list): 공고 리스트
        status (str): 상태 ('사전규격' 또는 '일반')

    Returns:
        list: 필터링된 공고 리스트
    """
    return [t for t in tenders if t.get('status') == status]


def filter_by_agency(tenders, agencies):
    """
    발주기관으로 공고 필터링

    Args:
        tenders (list): 공고 리스트
        agencies (list): 발주기관 리스트

    Returns:
        list: 필터링된 공고 리스트
    """
    return [t for t in tenders if t.get('agency') in agencies]


def sort_tenders(tenders, priority_pre_announcement=True, sort_by='deadline'):
    """
    공고 정렬

    Args:
        tenders (list): 공고 리스트
        priority_pre_announcement (bool): 사전규격 우선 여부
        sort_by (str): 정렬 기준 ('deadline', 'price', 'announced_date')

    Returns:
        list: 정렬된 공고 리스트
    """
    if sort_by == 'deadline':
        def key_func(x): return (
            0 if (
                priority_pre_announcement and x.get('status') == '사전규격') else 1, x.get(
                'deadline_date', datetime.max))
    elif sort_by == 'price':
        def key_func(x): return (0 if (priority_pre_announcement and x.get(
            'status') == '사전규격') else 1, -(x.get('estimated_price', 0)))
    elif sort_by == 'announced_date':
        def key_func(x): return (
            0 if (
                priority_pre_announcement and x.get('status') == '사전규격') else 1, -(
                x.get(
                    'announced_date', datetime.min).timestamp() if isinstance(
                    x.get('announced_date'), datetime) else 0))
    else:
        def key_func(x): return x.get('deadline_date', datetime.max)

    return sorted(tenders, key=key_func)
