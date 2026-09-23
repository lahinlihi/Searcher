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


# ════════════════════════════════════════════════════════════ 미리보기·발송

@bp.route('/newsletter/preview')
@moderator_required
def preview_page():
    """메일 미리보기 — 승인된 시사점으로 실제 발송될 HTML 을 그대로 보여준다."""
    import newsletter as nl
    from flask import Response
    conn = _conn()
    try:
        data = nl.build(conn, request.args.get('date') or None)
        if not data:
            return Response(
                '<p style="font-family:sans-serif;padding:40px;color:#555">'
                '승인된 시사점이 없습니다. 검수 화면에서 먼저 승인하세요.</p>',
                mimetype='text/html')
        html = nl.render_html(data, unsubscribe_url='#', is_test=True)
        return Response(html, mimetype='text/html')
    finally:
        conn.close()


@bp.route('/api/newsletter/send-test', methods=['POST'])
@moderator_required
def api_send_test():
    """테스트 발송 — 지정한 주소로만. 구독자에게 나가지 않는다."""
    import newsletter as nl
    from flask import g
    data = request.get_json(silent=True) or {}
    to = (data.get('to') or (g.user.email if g.user else '') or '').strip()
    if not to or '@' not in to:
        return jsonify({'error': '받을 이메일 주소가 필요합니다.'}), 400
    conn = _conn()
    try:
        res = nl.send_test(conn, to, data.get('date') or None,
                           sent_by=g.user.username if g.user else None)
    finally:
        conn.close()
    return (jsonify(res), 400) if 'error' in res else jsonify(res)


@bp.route('/api/newsletter/send', methods=['POST'])
@moderator_required
def api_send():
    """
    실제 발송 — 승인된 시사점만, 활성 구독자 전체.

    확인 문구를 요구한다. 실수로 눌러 나가는 일을 막기 위한 장치로,
    '승인 없이 나가는 경로를 만들지 않는다'는 요구사항의 연장이다.
    """
    import newsletter as nl
    from flask import g
    data = request.get_json(silent=True) or {}
    if data.get('confirm') != 'SEND':
        return jsonify({'error': '확인 문구가 일치하지 않습니다.'}), 400
    conn = _conn()
    try:
        res = nl.send_all(conn, data.get('date') or None,
                          sent_by=g.user.username if g.user else None)
    finally:
        conn.close()
    return (jsonify(res), 400) if 'error' in res else jsonify(res)


@bp.route('/api/newsletter/subscribers', methods=['GET', 'POST'])
@moderator_required
def api_subscribers():
    """구독자 조회·등록. 등록 시 수신동의 기록(일시·경로·IP)을 남긴다."""
    import newsletter as nl
    conn = _conn()
    try:
        if request.method == 'GET':
            nl.ensure_schema(conn)
            rows = conn.execute(
                'SELECT id,email,name,company,status,consent_at,consent_source '
                'FROM newsletter_subscribers ORDER BY id').fetchall()
            return jsonify([dict(r) for r in rows])

        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip()
        if '@' not in email:
            return jsonify({'error': '올바른 이메일 주소가 아닙니다.'}), 400
        r = nl.add_subscriber(
            conn, email, data.get('name'), data.get('company'),
            consent_source=data.get('consent_source') or '관리자 등록',
            consent_ip=request.headers.get('X-Forwarded-For', request.remote_addr))
        return jsonify(dict(r))
    finally:
        conn.close()


@bp.route('/api/newsletter/history')
@moderator_required
def api_history():
    import newsletter as nl
    conn = _conn()
    try:
        return jsonify(nl.send_history(conn))
    finally:
        conn.close()


@bp.route('/newsletter/unsubscribe/<token>')
def unsubscribe_page(token):
    """수신거부 — 로그인 없이 접근. 메일 하단 링크가 여기로 온다."""
    import newsletter as nl
    from flask import Response
    conn = _conn()
    try:
        done = nl.unsubscribe(conn, token)
    finally:
        conn.close()
    msg = ('수신이 해지되었습니다. 앞으로 뉴스레터가 발송되지 않습니다.'
           if done else '이미 해지되었거나 유효하지 않은 링크입니다.')
    return Response(
        f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>수신거부</title></head>'
        f'<body style="margin:0;background:#EEF1F3;font-family:Malgun Gothic,sans-serif">'
        f'<div style="max-width:440px;margin:60px auto;background:#fff;'
        f'border:1px solid #DDE3E8;border-radius:6px;padding:32px;text-align:center">'
        f'<div style="font-size:16px;color:#17212B;line-height:1.7">{msg}</div>'
        f'</div></body></html>', mimetype='text/html')
