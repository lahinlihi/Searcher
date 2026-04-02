"""
원격 서버에서 공고 데이터를 받아와 로컬 DB에 저장하는 모듈.
팀원 인스턴스에서 사용 — 크롤링 대신 중앙 서버 API를 호출한다.

settings.json 설정 예시:
  "sync": {
    "enabled": true,
    "server_url": "https://your-tunnel.trycloudflare.com",
    "token": "your-shared-token",
    "interval_minutes": 60
  }
"""

import requests
import json
from datetime import datetime, timedelta
from database import db, Tender


class RemoteSync:
    """중앙 서버에서 공고 데이터를 동기화"""

    def __init__(self, server_url: str, token: str):
        self.server_url = server_url.rstrip('/')
        self.token = token
        self.last_synced_at: datetime | None = None

    def sync(self, days_back: int = 30) -> dict:
        """
        중앙 서버에서 공고를 가져와 로컬 DB에 upsert.

        Args:
            days_back: last_synced_at 이 없을 때 최초 동기화 범위 (기본 30일)

        Returns:
            {'new': int, 'updated': int, 'errors': list}
        """
        since = self.last_synced_at or (datetime.now() - timedelta(days=days_back))
        url = f"{self.server_url}/api/sync/tenders"
        params = {
            'token': self.token,
            'since': since.isoformat(),
            'limit': 2000
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            return {'new': 0, 'updated': 0, 'errors': [f"서버 연결 실패: {url}"]}
        except requests.exceptions.Timeout:
            return {'new': 0, 'updated': 0, 'errors': ["서버 응답 시간 초과"]}
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 401:
                return {'new': 0, 'updated': 0, 'errors': ["인증 실패: 토큰을 확인하세요"]}
            if resp.status_code == 403:
                return {'new': 0, 'updated': 0, 'errors': ["서버에서 Sync가 비활성화됨"]}
            return {'new': 0, 'updated': 0, 'errors': [str(e)]}

        data = resp.json()
        tenders_data = data.get('tenders', [])
        print(f"[RemoteSync] 서버에서 {len(tenders_data)}건 수신 (since {since.date()})")

        new_count = 0
        updated_count = 0
        errors = []

        for item in tenders_data:
            try:
                result = self._upsert_tender(item)
                if result == 'new':
                    new_count += 1
                elif result == 'updated':
                    updated_count += 1
            except Exception as e:
                errors.append(f"upsert 오류 ({item.get('tender_number', '?')}): {e}")

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            errors.append(f"DB commit 오류: {e}")

        self.last_synced_at = datetime.now()
        print(f"[RemoteSync] 완료 — 신규: {new_count}건, 업데이트: {updated_count}건")
        return {'new': new_count, 'updated': updated_count, 'errors': errors}

    def _upsert_tender(self, item: dict) -> str:
        """공고 1건 upsert. 'new' 또는 'updated' 반환."""
        tender_number = item.get('tender_number')
        if not tender_number:
            return 'skip'

        def _parse_dt(s):
            return datetime.fromisoformat(s) if s else None

        existing = Tender.query.filter_by(tender_number=tender_number).first()

        if existing:
            # 이미 있으면 주요 필드만 업데이트
            existing.title          = item.get('title', existing.title)
            existing.agency         = item.get('agency', existing.agency)
            existing.demand_agency  = item.get('demand_agency', existing.demand_agency)
            existing.deadline_date  = _parse_dt(item.get('deadline_date')) or existing.deadline_date
            existing.opening_date   = _parse_dt(item.get('opening_date')) or existing.opening_date
            existing.estimated_price = item.get('estimated_price') or existing.estimated_price
            existing.status         = item.get('status', existing.status)
            existing.url            = item.get('url', existing.url)
            return 'updated'
        else:
            tender = Tender(
                title          = item.get('title', ''),
                agency         = item.get('agency', ''),
                demand_agency  = item.get('demand_agency'),
                tender_number  = tender_number,
                announced_date = _parse_dt(item.get('announced_date')),
                deadline_date  = _parse_dt(item.get('deadline_date')),
                opening_date   = _parse_dt(item.get('opening_date')),
                estimated_price = item.get('estimated_price'),
                bid_method     = item.get('bid_method'),
                status         = item.get('status', '일반'),
                is_sme_only    = item.get('is_sme_only', False),
                source_site    = item.get('source_site', '원격'),
                url            = item.get('url'),
                is_duplicate   = item.get('is_duplicate', False),
            )
            db.session.add(tender)
            return 'new'
