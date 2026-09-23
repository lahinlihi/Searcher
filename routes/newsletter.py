# -*- coding: utf-8 -*-
"""
뉴스레터 검수 — 시사점 확인·수정·승인

요구사항(2026-09-22 확정):
  "'메일을 보내기 위한 관리자 페이지'가 필요하고, '이런 내용으로 메일을
   보내겠습니다.' 모니터링을 할 수 있어야해. 내가 최종 검토 후 완료하면 나가는거야"

따라서 이 화면은 승인 게이트다. 승인 없이 발송되는 경로를 만들지 않으며,
그 짝으로 검사에 걸린 항목이 승인되는 경로도 만들지 않는다(insight.set_status).

시사점 데이터는 insight 모듈이 raw sqlite3 로 자체 관리하므로
SQLAlchemy 세션이 아니라 자체 커넥션을 연다.
"""
from flask import Blueprint, render_template, request, jsonify

from decorators import login_required, moderator_required

bp = Blueprint('newsletter', __name__)


def _conn():
    import hr_news
    import insight
    conn = hr_news.connect()
    insight.ensure_schema(conn)
    return conn


@bp.route('/newsletter/review')
@moderator_required
def review_page():
    """검수 화면"""
    return render_template('newsletter_review.html')


@bp.route('/api/newsletter/runs')
@moderator_required
def api_runs():
    """검수 대상 날짜 목록"""
    import insight
    conn = _conn()
    try:
        return jsonify(insight.list_runs(conn))
    finally:
        conn.close()


@bp.route('/api/newsletter/run')
@moderator_required
def api_run():
    """특정 날짜의 시사점 목록. ?date=YYYY-MM-DD (생략 시 최신)"""
    import insight
    conn = _conn()
    try:
        run_date, rows = insight.get_run(conn, request.args.get('date') or None)
        return jsonify({'run_date': run_date, 'items': rows})
    finally:
        conn.close()


@bp.route('/api/newsletter/insight/<int:insight_id>', methods=['PUT'])
@moderator_required
def api_update(insight_id):
    """
    시사점 편집. 편집 결과는 즉시 재검사된다.

    points 는 배열 전체를 받는다. 항목 개별 제외는 클라이언트가 해당 항목을
    빼고 배열을 보내는 방식으로 처리한다.
    """
    import insight
    data = request.get_json(silent=True) or {}
    points = data.get('points')
    if points is not None and not isinstance(points, list):
        return jsonify({'error': 'points 는 배열이어야 합니다.'}), 400

    conn = _conn()
    try:
        res = insight.update_insight(
            conn, insight_id,
            headline=data.get('headline'),
            points=points,
            synthesis=data.get('synthesis'),
            closing=data.get('closing'))
        if res is None:
            return jsonify({'error': '해당 시사점을 찾을 수 없습니다.'}), 404
        return jsonify(res)
    finally:
        conn.close()


@bp.route('/api/newsletter/insight/<int:insight_id>/status', methods=['POST'])
@moderator_required
def api_status(insight_id):
    """상태 전이 — pending / approved / skipped"""
    import insight
    status = (request.get_json(silent=True) or {}).get('status', '')
    conn = _conn()
    try:
        res = insight.set_status(conn, insight_id, status)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    finally:
        conn.close()
    if res is None:
        return jsonify({'error': '해당 시사점을 찾을 수 없습니다.'}), 404
    if 'error' in res:
        return jsonify(res), 409
    return jsonify(res)


@bp.route('/api/newsletter/generate', methods=['POST'])
@moderator_required
def api_generate():
    """
    수동 생성 — 스케줄(07:30)을 기다리지 않고 지금 돌린다.

    수집은 하지 않고 이미 수집된 기사로 토픽 선정·시사점 생성만 한다.
    수집까지 필요하면 스케줄러 잡이나 hr_news CLI 를 쓴다.
    """
    import insight
    data = request.get_json(silent=True) or {}
    days = int(data.get('days') or 3)
    top_n = int(data.get('top_n') or 3)
    conn = _conn()
    try:
        results, _ = insight.generate_daily(conn, days=days, top_n=top_n,
                                            quiet=True)
        saved, run_date = insight.save_daily(conn, results)
        return jsonify({
            'saved': saved,
            'run_date': run_date,
            'ok': sum(1 for r in results if r['ok']),
            'blocked': sum(1 for r in results if not r['ok']),
        })
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        conn.close()
