from flask import Blueprint, request, jsonify, g, current_app
from database import db, Tender, TenderAnalysis
from decorators import login_required
from settings_manager import settings_manager
from datetime import datetime
import json
import threading

bp = Blueprint('analysis', __name__)

# 분석 진행 중인 tender_id 추적 (중복 실행 방지)
_analysis_in_progress = set()
_analysis_lock = threading.Lock()


def _run_analysis_background(tender_id, tender_url, tender_title, source_site, api_key, model_priority='quality', _app=None):
    """백그라운드 스레드에서 분석 실행 후 DB 저장"""
    import traceback as _tb
    import time as _time

    def _dbg(msg):
        """디버그 로그를 파일에 기록 (서버 콘솔 대신)"""
        try:
            ts = _time.strftime('%H:%M:%S')
            with open('analysis_debug.log', 'a', encoding='utf-8') as f:
                f.write(f'[{ts}] tender={tender_id} {msg}\n')
        except Exception:
            pass

    _dbg(f'시작 url={tender_url[:80] if tender_url else "-"} priority={model_priority}')

    # 백그라운드 스레드에서 app_context 진입 실패 시에도 반드시 cleanup 실행
    try:
        # Flask 공식 패턴: 백그라운드 스레드에는 app 객체를 직접 전달해서 context 생성
        with _app.app_context():
            try:
                from document_analyzer import analyze_tender as _analyze
                _dbg('analyze_tender 호출 시작')
                result = _analyze(
                    tender_url=tender_url,
                    tender_title=tender_title,
                    api_key=api_key,
                    source_site=source_site,
                    model_priority=model_priority,
                )
                _dbg(f'analyze_tender 완료: error={result.get("error")} text_len={result.get("text_length")} files={result.get("files_found")}')
                secs = result.get('gemini_sections')
                if isinstance(secs, dict):
                    _dbg(f'gemini_sections: model={secs.get("_model")} gs_error={secs.get("error")}')
                model = secs.get('_model') if isinstance(secs, dict) else None
                payload = dict(
                    files_found=json.dumps(result.get('files_found', []), ensure_ascii=False),
                    text_length=result.get('text_length', 0),
                    rule_extract=json.dumps(result.get('rule_extract', {}), ensure_ascii=False),
                    gemini_sections=json.dumps(secs, ensure_ascii=False),
                    model_used=model,
                    error=result.get('error'),
                    updated_at=datetime.utcnow(),
                )
                existing = TenderAnalysis.query.filter_by(tender_id=tender_id).first()
                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                else:
                    db.session.add(TenderAnalysis(tender_id=tender_id, **payload))
                db.session.commit()
                _dbg('DB 저장 완료')
            except Exception as e:
                _dbg(f'예외 발생: {type(e).__name__}: {e}\n{_tb.format_exc()}')
    except Exception as e:
        _dbg(f'app_context 오류: {type(e).__name__}: {e}\n{_tb.format_exc()}')
    finally:
        with _analysis_lock:
            _analysis_in_progress.discard(tender_id)
        _dbg('종료 (finally)')


@bp.route('/api/tender/<int:tender_id>/analyze')
@login_required
def api_analyze_tender(tender_id):
    """
    공고 첨부파일(RFP) AI 분석.
    - 캐시 있음 → 즉시 반환
    - 캐시 없음 → 백그라운드 분석 시작 후 {"status":"processing"} 즉시 반환
    - 클라이언트는 2초마다 폴링해서 완료 확인
    """
    try:
        tender = Tender.query.get_or_404(tender_id)
        force = request.args.get('force', '0') == '1'

        # ── 캐시 조회 ──────────────────────────────────────────────────────
        if not force:
            cached = TenderAnalysis.query.filter_by(tender_id=tender_id).first()
            if cached:
                return jsonify(cached.to_dict())

        # ── 이미 분석 중이면 즉시 processing 반환 ─────────────────────────
        with _analysis_lock:
            already_running = tender_id in _analysis_in_progress
            if not already_running:
                _analysis_in_progress.add(tender_id)

        if already_running:
            return jsonify({'status': 'processing', 'message': '분석이 진행 중입니다. 잠시 후 다시 확인합니다.'})

        # ── Gemini API 키 및 모델 우선순위 로드 ──────────────────────────
        api_key = settings_manager.get('gemini_api_key', '').strip() or None
        model_priority = settings_manager.get('gemini_model_priority', 'quality')

        # ── 백그라운드 스레드에서 분석 시작 ──────────────────────────────
        # Flask 공식 패턴: current_app 프록시 대신 실제 app 객체를 전달
        _app = current_app._get_current_object()
        t = threading.Thread(
            target=_run_analysis_background,
            args=(tender_id, tender.url, tender.title, tender.source_site or '', api_key, model_priority),
            kwargs={'_app': _app},
            daemon=True,
        )
        t.start()

        return jsonify({'status': 'processing', 'message': '분석을 시작했습니다. 자동으로 결과를 불러옵니다…'})

    except Exception as e:
        with _analysis_lock:
            _analysis_in_progress.discard(tender_id)
        return jsonify({'error': str(e)}), 500
