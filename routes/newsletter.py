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


# ════════════════════════════════════════════════════════════ 검증·재작성

@bp.route('/api/newsletter/insight/<int:insight_id>/verify')
@moderator_required
def api_verify(insight_id):
    """
    근거 대조. 기본은 코드 대조만(즉시·무료), ai=1 이면 위치 지목까지.

    AI 호출은 항목 수만큼 일어나므로 화면을 열 때마다 자동으로 부르지 않는다.
    편집자가 필요할 때 누른다.
    """
    import verify as V
    use_ai = request.args.get('ai') == '1'
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM daily_insights WHERE id=?',
                           (insight_id,)).fetchone()
        if row is None:
            return jsonify({'error': '없는 항목입니다.'}), 404
        return jsonify(V.verify(conn, row, use_ai=use_ai))
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        conn.close()


@bp.route('/api/newsletter/insight/<int:insight_id>/rewrite', methods=['POST'])
@moderator_required
def api_rewrite(insight_id):
    """
    다시 쓰기 요청 — 대안을 가져오기만 한다. 저장하지 않는다.

    채택은 편집자가 한다. 자동으로 갈아끼우면 편집자가 사후 확인자가 된다.
    """
    import json as _j
    import verify as V
    data = request.get_json(silent=True) or {}
    idx = int(data.get('index') or 0)
    note = (data.get('note') or '').strip()
    conn = _conn()
    try:
        row = conn.execute('SELECT * FROM daily_insights WHERE id=?',
                           (insight_id,)).fetchone()
        if row is None:
            return jsonify({'error': '없는 항목입니다.'}), 404
        points = _j.loads(row['points'] or '[]')
        if not (1 <= idx <= len(points)):
            return jsonify({'error': '항목 번호가 범위를 벗어났습니다.'}), 400
        material, rebuilt = V.load_material(conn, row)
        if not material:
            return jsonify({'error': '재료가 없어 다시 쓸 수 없습니다.'}), 400
        res = V.rewrite(points[idx - 1], material, note)
        res['material_rebuilt'] = rebuilt
        res['index'] = idx
        return (jsonify(res), 502) if res.get('error') else jsonify(res)
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════ 미리보기·발송

@bp.route('/newsletter/send')
@moderator_required
def send_page():
    """
    발송 전 최종 화면 — 편집실(/newsletter/review)과 분리한다.

    편집하다 실수로 발송 버튼을 누르는 경로를 없애기 위해서다.
    이 화면은 고치는 곳이 아니라 '이대로 내보낼지' 만 정하는 곳이다.
    """
    return render_template('newsletter_send.html')


@bp.route('/api/newsletter/send-status')
@moderator_required
def api_send_status():
    """발송 전 점검 — 무엇이 실릴지, 보낼 수 있는 상태인지."""
    import newsletter as nl
    import insight
    conn = _conn()
    try:
        run_date = request.args.get('date') or None
        data = nl.build(conn, run_date)
        run_date = (data or {}).get('run_date') or run_date
        if not run_date:
            r = conn.execute('SELECT run_date FROM daily_insights '
                             'ORDER BY run_date DESC LIMIT 1').fetchone()
            run_date = r['run_date'] if r else None

        rows = conn.execute(
            'SELECT status, COUNT(*) c FROM daily_insights WHERE run_date=? '
            'GROUP BY status', (run_date,)).fetchall() if run_date else []
        counts = {r['status']: r['c'] for r in rows}

        nl.ensure_schema(conn)
        subs = nl.active_subscribers(conn)
        mail = nl.mail_settings()
        sent = conn.execute(
            "SELECT * FROM newsletter_sends WHERE run_date=? AND kind='real' "
            'ORDER BY id DESC LIMIT 1', (run_date,)).fetchone() if run_date else None

        blockers = []
        if not data:
            blockers.append('승인된 시사점이 없습니다. 편집실에서 먼저 승인하세요.')
        if not subs:
            blockers.append('활성 구독자가 없습니다.')
        if not (mail.get('user') and mail.get('password_set')):
            blockers.append('발송 계정이 설정되지 않았습니다.')

        return jsonify({
            'run_date': run_date,
            'subject': nl.subject_for(data) if data else None,
            'counts': counts,
            'sections': [{'headline': s['headline'],
                          'category': s['category'],
                          'points': len(s['points']),
                          'articles': len(s['articles'])}
                         for s in (data or {}).get('sections', [])],
            'tenders': len(((data or {}).get('tenders') or {}).get('items', [])),
            'tenders_computed_at': ((data or {}).get('tenders') or {}).get('computed_at'),
            'subscribers': [{'email': r['email'], 'name': r['name'],
                             'company': r['company']} for r in subs],
            'mail_user': mail.get('user'),
            'mail_ready': bool(mail.get('user') and mail.get('password_set')),
            'blockers': blockers,
            'already_sent': dict(sent) if sent else None,
            **_send_progress(nl, conn, run_date, subs),
        })
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        conn.close()


@bp.route('/api/newsletter/tenders/refresh', methods=['POST'])
@moderator_required
def api_tenders_refresh():
    """메일용 입찰동향을 지금 다시 계산해 저장한다."""
    import tender_brief as tb
    conn = _conn()
    try:
        tb.ensure_schema(conn)
        snap = tb.build_section_cached(conn, force=True)
        return jsonify({'items': len(snap['items']),
                        'computed_at': snap['computed_at'],
                        'degraded': bool(snap.get('degraded'))})
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        conn.close()


def _send_progress(nl, conn, run_date, subs):
    """이미 보낸 발행일이면 몇 명이 받았고 몇 명이 남았는지."""
    if not run_date:
        return {'sent_count': 0, 'remaining': None, 'send_in_progress': False}
    st = nl.real_send_state(conn, run_date)
    remaining = None
    if st['count'] and st['trackable']:
        remaining = sum(1 for r in subs if r['email'].lower() not in st['sent'])
    return {'sent_count': len(st['sent']), 'remaining': remaining,
            'send_in_progress': st['in_progress']}


@bp.route('/newsletter/preview')
@moderator_required
def preview_page():
    """메일 미리보기 — 승인된 시사점으로 실제 발송될 HTML 을 그대로 보여준다."""
    import newsletter as nl
    from flask import Response
    conn = _conn()
    try:
        # draft=1 이면 검토 대기분까지 포함해 보여준다. 미리보기 전용이며
        # 발송 경로(send_test/send_all)는 이 인자를 넘기지 않는다.
        draft = request.args.get('draft') == '1'
        st = ('approved', 'pending') if draft else ('approved',)
        data = nl.build(conn, request.args.get('date') or None, statuses=st)
        if not data:
            return Response(
                '<p style="font-family:sans-serif;padding:40px;color:#555">'
                '실을 시사점이 없습니다. 편집실에서 먼저 생성·승인하세요.</p>',
                mimetype='text/html')
        nl.archive_tenders(conn, data, 'preview')       # 미리보기의 '외 N건' 링크도 열리게 (정식 발송분은 덮지 않는다)
        html = nl.render_html(data, unsubscribe_url='#', is_test=True)
        if draft:
            html = html.replace('<body', '<body data-draft="1"', 1)
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
    mode = data.get('mode')
    if mode not in (None, 'resume', 'force'):
        return jsonify({'error': '허용되지 않는 발송 방식입니다.'}), 400
    # 전원 재발송은 다른 확인 문구를 요구한다. 같은 문구면 습관적으로 입력해
    # 중복 발송을 내기 쉽다.
    need = 'RESEND' if mode == 'force' else 'SEND'
    if data.get('confirm') != need:
        return jsonify({'error': '확인 문구가 일치하지 않습니다.'}), 400
    conn = _conn()
    try:
        res = nl.send_all(conn, data.get('date') or None,
                          sent_by=g.user.username if g.user else None,
                          mode=mode)
    finally:
        conn.close()
    if 'error' in res:
        dup = res.get('already_sent') or res.get('in_progress')
        return jsonify(res), (409 if dup else 400)
    return jsonify(res)


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
        try:
            r = nl.add_subscriber(
                conn, email, data.get('name'), data.get('company'),
                consent_source=data.get('consent_source') or '관리자 등록',
                consent_ip=request.headers.get('X-Forwarded-For', request.remote_addr),
                reconsent=bool(data.get('reconsent')))
        except nl.Unsubscribed as e:
            return jsonify({'error': str(e), 'unsubscribed': True}), 409
        return jsonify(dict(r))
    finally:
        conn.close()


@bp.route('/api/newsletter/subscribers/<int:subscriber_id>', methods=['DELETE'])
@moderator_required
def api_subscriber_delete(subscriber_id):
    """잘못 등록한 구독자 삭제. 수신거부한 주소는 기록을 남겨야 해서 지우지 않는다."""
    import newsletter as nl
    conn = _conn()
    try:
        result = nl.remove_subscriber(conn, subscriber_id)
        if result == 'not_found':
            return jsonify({'error': '구독자를 찾을 수 없습니다.'}), 404
        if result == 'unsubscribed':
            return jsonify({'error': '수신거부한 주소는 지울 수 없습니다. 기록을 지우면 같은 주소가 '
                                     '재동의 확인 없이 다시 등록될 수 있습니다.'}), 409
        return jsonify({'deleted': True})
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


@bp.route('/newsletter/tenders/<run_date>')
def tenders_list_page(run_date):
    """메일의 '외 N건' 이 여는 페이지 — 그 구분의 전체 목록. 로그인 없이 접근한다.

    메일을 보낸 날 보관해 둔 목록을 그대로 보여 준다. 공공 공고의 제목·기관·금액·마감뿐이다.
    7일이 지나면 지워지고, 그 뒤에는 안내만 한다.
    """
    import re
    from datetime import datetime
    from html import escape
    from flask import Response
    import tender_brief as tb

    def page(body, status=200):
        return Response(
            '<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow"><title>입찰동향 전체 목록</title>'
            '<style>body{margin:0;background:#EEF1F3;font-family:"Malgun Gothic","Apple SD Gothic Neo",sans-serif;color:#17212B}'
            '.wrap{max-width:720px;margin:0 auto;padding:24px 16px 48px}.card{background:#fff;border:1px solid #DDE3E8;border-radius:6px;padding:20px 22px}'
            'h1{font-size:18px;margin:0 0 4px}.sub{font-size:12.5px;color:#5E6B77;line-height:1.6}'
            '.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:16px 0 6px}.tabs a{font-size:13px;padding:8px 12px;min-height:20px;border:1px solid #DDE3E8;border-radius:18px;'
            'text-decoration:none;color:#17212B;background:#fff}.tabs a.on{background:#17212B;color:#fff;border-color:#17212B;font-weight:bold}'
            '.row{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #EEF1F3}.row:last-child{border-bottom:0}'
            '.n{flex:0 0 26px;text-align:right;font-size:12px;color:#8C99A5;padding-top:2px}.t{font-size:14px;line-height:1.55}'
            '.t a{color:#17212B;text-decoration:none}.t a:hover{text-decoration:underline}.m{font-size:12px;color:#8C99A5;padding-top:2px}'
            '</style></head><body><div class="wrap">' + body + '</div></body></html>',
            status=status, mimetype='text/html')

    gone = page('<div class="card"><h1>목록을 볼 수 없습니다</h1><p class="sub">이 날짜의 입찰동향 목록이 없거나 '
                f'보관 기간({tb.ARCHIVE_DAYS}일)이 지났습니다.</p></div>', 404)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', run_date or ''):
        return gone
    try:
        d = datetime.strptime(run_date, '%Y-%m-%d')
    except ValueError:
        return gone
    conn = _conn()
    try:
        data = tb.archived_brief(conn, run_date)
    finally:
        conn.close()
    secs = [x for x in ((data or {}).get('sections') or []) if x.get('items')]
    if not secs:
        return gone

    want = request.args.get('section') or ''
    cur = next((x for x in secs if x.get('key') == want), secs[0])
    tabs = ''.join(
        f'<a class="{"on" if x is cur else ""}" href="?section={escape(str(x.get("key") or ""))}">'
        f'{escape(str(x.get("label") or ""))} {len(x["items"])}건</a>' for x in secs)

    def row(i, it):
        title = escape(str(it.get('title') or ''))
        url = str(it.get('url') or '')
        if url.lower().startswith(('http://', 'https://')):       # 공고 원문 주소만 링크로 (javascript: 등은 버린다)
            title = f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{title}</a>'
        meta = [escape(str(it.get('agency') or ''))]
        meta.append(f'{it["price"]}억' if it.get('price') else '금액 미공개')
        if it.get('deadline'):
            meta.append('마감 ' + escape(str(it['deadline'])))
        return (f'<div class="row"><div class="n">{i}</div><div><div class="t">{title}</div>'
                f'<div class="m">{" · ".join(m for m in meta if m)}</div></div></div>')

    week = '월화수목금토일'[d.weekday()]
    body = (f'<div class="card"><h1>입찰동향 전체 목록</h1>'
            f'<div class="sub">{d.year}년 {d.month}월 {d.day}일 {week}요일 브리핑에 실린 조건 그대로의 목록입니다. '
            f'관심 분야 적합도가 높은 순이며, 그 뒤 마감된 공고가 있을 수 있습니다. 이 페이지는 {tb.ARCHIVE_DAYS}일 동안 열립니다.</div>'
            f'<div class="tabs">{tabs}</div>'
            + ''.join(row(i, it) for i, it in enumerate(cur['items'], 1)) + '</div>')
    return page(body)


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


# ════════════════════════════════════════════════════════════ 입찰동향 조건

@bp.route('/newsletter/brief')
@moderator_required
def brief_page():
    """입찰동향 발송 조건 설정 화면"""
    return render_template('brief_settings.html')


@bp.route('/api/brief/preset', methods=['GET', 'PUT'])
@moderator_required
def api_brief_preset():
    """발송 조건 프리셋 조회·저장. 저장 시 변경 이력을 남긴다."""
    import tender_brief as tb
    from flask import g
    conn = tb.connect()
    try:
        if request.method == 'GET':
            return jsonify(tb.get_preset(conn))
        data = request.get_json(silent=True) or {}
        for key in ('include_keywords', 'exclude_keywords', 'classes'):
            if key in data and not isinstance(data[key], list):
                return jsonify({'error': f'{key} 는 배열이어야 합니다.'}), 400
        p = tb.save_preset(conn, data,
                           changed_by=g.user.username if g.user else None)
        return jsonify(p)
    finally:
        conn.close()


@bp.route('/api/brief/preview', methods=['POST'])
@moderator_required
def api_brief_preview():
    """
    즉시 미리보기 — 조건을 저장하지 않고 결과만 본다.

    "조건을 바꾸면 지금 몇 건이 걸리는지" 가 이 화면의 핵심이므로
    저장 전에도 확인할 수 있어야 한다.
    """
    import tender_brief as tb
    data = request.get_json(silent=True) or {}
    days = int(data.get('days') or 3)
    conn = tb.connect()
    try:
        preset = {**tb.get_preset(conn), **{k: v for k, v in data.items()
                                            if k in tb.DEFAULT_PRESET}}
        return jsonify(tb.preview(conn, preset, days=days))
    finally:
        conn.close()


@bp.route('/api/brief/classify', methods=['POST'])
@moderator_required
def api_brief_classify():
    """미분류 후보를 분류한다. 건수에 따라 수십 초 걸릴 수 있다."""
    import tender_brief as tb
    data = request.get_json(silent=True) or {}
    days = int(data.get('days') or 3)
    conn = tb.connect()
    try:
        preset = {**tb.get_preset(conn), **{k: v for k, v in data.items()
                                            if k in tb.DEFAULT_PRESET}}
        rows = tb.candidates(conn, preset, days=days)
        saved, calls = tb.classify(conn, rows, quiet=True)
        pv = tb.preview(conn, preset, days=days)
        return jsonify({'classified': saved, 'api_calls': calls, 'preview': pv})
    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        conn.close()


@bp.route('/api/brief/history')
@moderator_required
def api_brief_history():
    import tender_brief as tb
    conn = tb.connect()
    try:
        return jsonify(tb.preset_history(conn))
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════ 메일 계정 설정

@bp.route('/newsletter/settings')
@moderator_required
def mail_settings_page():
    """발송 계정·구독자 관리 화면"""
    return render_template('newsletter_settings.html')


@bp.route('/api/newsletter/mail-settings', methods=['GET', 'PUT'])
@moderator_required
def api_mail_settings():
    """
    메일 설정 조회·저장.

    비밀번호는 조회 시 반환하지 않는다(설정 여부만). 저장 시 빈 값이면
    기존 비밀번호를 유지한다.
    """
    import newsletter as nl
    if request.method == 'GET':
        return jsonify(nl.mail_settings())
    data = request.get_json(silent=True) or {}
    allowed = {'service', 'user', 'password', 'from_name', 'base_url'}
    patch = {k: v for k, v in data.items() if k in allowed}
    if 'user' in patch and patch['user'] and '@' not in patch['user']:
        return jsonify({'error': '올바른 이메일 주소가 아닙니다.'}), 400
    try:
        return jsonify(nl.update_mail_settings(patch))
    except Exception as e:
        return jsonify({'error': f'저장 실패: {type(e).__name__}: {e}'}), 500


@bp.route('/api/newsletter/test-connection', methods=['POST'])
@moderator_required
def api_test_connection():
    """
    SMTP 연결 시험 — 로그인만 하고 끊는다. 메일은 보내지 않는다.

    저장 전에 확인할 수 있도록 전달받은 값으로도 시험한다.
    """
    import newsletter as nl
    data = request.get_json(silent=True) or {}
    res = nl.test_connection(data.get('user') or None,
                             data.get('password') or None,
                             data.get('service') or None)
    return (jsonify(res), 400) if not res['ok'] else jsonify(res)
