"""
품질 문제가 있는 사이트 비활성화 및 데이터 삭제
"""

from database import db, Tender
from app import app
import json

# 비활성화할 사이트 목록
SITES_TO_DISABLE = [
    'hrdkorea',
    'khidi',
    'kocca',
    'kosac',
    'moe',
    'mss',
    'nipa',
    'semas',
    'seoul-city'
]

# 비활성화 사유
DISABLE_REASONS = {
    'hrdkorea': '실제 공고 URL 추출 불가, 공고번호 자동생성',
    'khidi': '실제 공고 URL 추출 불가, 공고번호 자동생성',
    'kocca': '제목 및 URL 추출 불가',
    'kosac': '실제 공고 URL 추출 불가, 공고번호 자동생성',
    'moe': '실제 공고 URL 추출 불가, 공고번호 자동생성',
    'mss': '실제 공고 URL 추출 불가, 공고번호 자동생성',
    'nipa': '실제 공고 URL 추출 불가, 공고번호 자동생성',
    'semas': '실제 공고 URL 추출 불가, 공고번호 자동생성',
    'seoul-city': '제목 및 URL 추출 불가'
}

def disable_sites():
    """설정 파일에서 사이트 비활성화"""

    # 설정 파일 로드
    with open('data/settings.json', 'r', encoding='utf-8') as f:
        settings = json.load(f)

    sites_config = settings['crawl']['sites_config']

    print("=" * 60)
    print("사이트 비활성화 작업")
    print("=" * 60)

    disabled_count = 0

    for site_id in SITES_TO_DISABLE:
        if site_id in sites_config:
            site_name = sites_config[site_id].get('name', site_id)
            sites_config[site_id]['enabled'] = False
            sites_config[site_id]['disabled_reason'] = DISABLE_REASONS.get(site_id, '데이터 품질 문제')

            print(f"[비활성화] {site_name}")
            print(f"  사유: {DISABLE_REASONS.get(site_id, '데이터 품질 문제')}")
            disabled_count += 1

    # sites 섹션도 동일하게 업데이트
    if 'sites' in settings['crawl']:
        for site_id in SITES_TO_DISABLE:
            if site_id in settings['crawl']['sites']:
                settings['crawl']['sites'][site_id]['enabled'] = False
                settings['crawl']['sites'][site_id]['disabled_reason'] = DISABLE_REASONS.get(site_id, '데이터 품질 문제')

    # 설정 파일 저장
    with open('data/settings.json', 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

    print(f"\n총 {disabled_count}개 사이트 비활성화 완료")
    return disabled_count

def delete_data():
    """비활성화된 사이트의 기존 데이터 삭제"""

    with app.app_context():
        # 설정 파일에서 사이트명 가져오기
        with open('data/settings.json', 'r', encoding='utf-8') as f:
            settings = json.load(f)

        sites_config = settings['crawl']['sites_config']

        print("\n" + "=" * 60)
        print("기존 데이터 삭제 작업")
        print("=" * 60)

        total_deleted = 0

        for site_id in SITES_TO_DISABLE:
            if site_id in sites_config:
                site_name = sites_config[site_id].get('name', site_id)

                # 해당 사이트 공고 삭제
                tenders = Tender.query.filter(
                    Tender.source_site.contains(site_name)
                ).all()

                count = len(tenders)
                for t in tenders:
                    db.session.delete(t)

                if count > 0:
                    print(f"{site_name}: {count}건 삭제")
                    total_deleted += count

        db.session.commit()
        print(f"\n총 {total_deleted}건 삭제 완료")
        return total_deleted

if __name__ == '__main__':
    print("품질 문제가 있는 사이트를 비활성화하고 데이터를 삭제합니다.\n")

    # 1. 설정에서 비활성화
    disabled_count = disable_sites()

    # 2. 기존 데이터 삭제
    deleted_count = delete_data()

    print("\n" + "=" * 60)
    print("작업 완료")
    print("=" * 60)
    print(f"비활성화: {disabled_count}개 사이트")
    print(f"삭제: {deleted_count}건 공고")
    print("\n이제 정상 작동하는 사이트만 크롤링됩니다:")
    print("  - 나라장터 API (용역)")
    print("  - 나라장터 사전규격 (용역)")
    print("  - 성동구")
