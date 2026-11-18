"""
나라장터 과거 수행이력 화면용 API

조회 로직은 g2b_history.py 에 있다. 여기서는 요청을 받아 넘기고, 결과를 캐시하고,
동시에 한 건만 조회되도록 막는 일만 한다.
"""

import threading
import time
from urllib.parse import unquote

from flask import Blueprint, request, jsonify

import g2b_history
from database import Tender
from decorators import login_required
from settings_manager import settings_manager

bp = Blueprint('history', __name__)

_cache: dict = {}                   # {tender_id: (epoch, result_dict)}
CACHE_TTL = 3600                    # 1시간
# '다시 조회'(force)도 이 시간 안에는 캐시를 돌려준다. 조회 한 번이 나라장터 API 를
# 최대 216회 부르므로, 버튼을 연달아 누르면 키가 차단된다.
FORCE_MIN_INTERVAL = 300
CACHE_MAX = 500                     # 이보다 많아지면 만료된 항목을 비운다
# 이력 조회는 한 번에 하나만. 두 사람이 동시에 누르면 호출이 그대로 두 배가 된다.
_lock = threading.Lock()


def _service_key():
    """나라장터 API 키. 설정에는 URL 인코딩된 값이 들어 있어 한 번 풀어서 쓴다 (이중 인코딩 방지)."""
    raw = settings_manager.get('crawl.sites.g2b_api.service_key', '')
    return unquote(raw) if raw else ''


def _cached(tender_id, force):
    hit = _cache.get(tender_id)
    if not hit:
        return None
    saved_at, result = hit
    if time.time() - saved_at < (FORCE_MIN_INTERVAL if force else CACHE_TTL):
        return jsonify({**result, 'cached': True})
    return None


@bp.route('/api/tenders/<int:tender_id>/history')
@login_required
def api_tender_history(tender_id):
    """공고 수행이력 조회 — 상태 구분과 조회 흐름은 g2b_history.lookup 참고"""
    force = request.args.get('force', '0') == '1'

    hit = _cached(tender_id, force)
    if hit is not None:
        return hit

    tender = Tender.query.get_or_404(tender_id)

    # 앞선 조회가 끝나기를 기다렸다가, 그 사이 같은 공고가 조회됐으면 그 결과를 쓴다.
    with _lock:
        hit = _cached(tender_id, force)
        if hit is not None:
            return hit

        service_key = _service_key()
        if not service_key:
            return jsonify({'error': 'API 키가 설정되지 않았습니다.'}), 500

        result = g2b_history.lookup(tender.title, tender.agency, tender.demand_agency, service_key)

        if len(_cache) >= CACHE_MAX:
            cutoff = time.time() - CACHE_TTL
            for key in [k for k, (ts, _) in _cache.items() if ts < cutoff]:
                _cache.pop(key, None)
        _cache[tender_id] = (time.time(), result)
        return jsonify(result)


@bp.route('/api/history/bidders')
@login_required
def api_history_bidders():
    """특정 입찰 공고의 투찰업체 상세 목록"""
    bid_no = request.args.get('bid_no', '').strip()
    bid_seq = request.args.get('bid_seq', '000').strip().zfill(3)
    if not bid_no:
        return jsonify({'error': '입찰번호가 필요합니다.'}), 400

    service_key = _service_key()
    if not service_key:
        return jsonify({'error': 'API 키가 설정되지 않았습니다.'}), 500

    try:
        return jsonify(g2b_history.fetch_bidders(service_key, bid_no, bid_seq))
    except g2b_history.G2BApiError as e:
        return jsonify({'error': str(e)}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500
