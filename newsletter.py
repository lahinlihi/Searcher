# -*- coding: utf-8 -*-
"""
뉴스레터 템플릿 + 발송

설계 근거
  - 전원 동일 1종 발송(2026-09-22 확정). 시사점은 공통으로 1회 생성하므로
    구독자가 늘어도 AI 호출은 하루 1회로 고정된다.
  - 승인된 시사점만 실린다. 검수 화면에서 approved 로 바뀐 것만 대상.
  - 참고 브리핑(2026-09-23 수령) 구조를 차용: 동향 / 시사점 2단,
    출처·날짜 명기, 말미 고지문.

저작권 경계 — 코드로 강제
  관련 기사는 insight/hr_news 의 render_for_newsletter() 가 반환하는
  제목·출처·링크·발행일만 싣는다. 패시지(본문 조각)는 이 모듈로 넘어오지 않는다.

Outlook 호환
  Outlook 은 flexbox·grid·외부 스타일시트를 무시한다. 표 기반 레이아웃과
  인라인 스타일만 쓰고, 폭은 width 속성으로도 함께 지정한다.

사용:
    python newsletter.py --preview               # HTML 파일로 미리보기 저장
    python newsletter.py --test you@example.com  # 테스트 발송
    python newsletter.py --subscribers           # 구독자 목록
"""
import argparse
import html as _html
import json
import os
import re
import secrets
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BASE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))

SETTINGS_PATH = os.path.join(BASE, 'data', 'settings.json')

SMTP_PRESETS = {
    'gmail':   {'server': 'smtp.gmail.com',        'port': 587, 'ssl': False},
    'naver':   {'server': 'smtp.naver.com',        'port': 587, 'ssl': False},
    'daum':    {'server': 'smtp.daum.net',         'port': 465, 'ssl': True},
    'outlook': {'server': 'smtp-mail.outlook.com', 'port': 587, 'ssl': False},
}

# 말미 고지문 — 참고 브리핑이 책임을 한정한 방식.
# 행동 제안을 빼는 대신 자료의 성격을 명시한다.
DISCLAIMER = ('본 자료는 공개된 정부 발표 및 언론 보도를 바탕으로 '
              '경영 참고용으로 정리한 것입니다. 기사 본문은 포함하지 않으며 '
              '제목과 출처만 싣습니다.')


def esc(s):
    return _html.escape(str(s or ''), quote=True)


def _settings():
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _cfg(path, default=None):
    cur = _settings()
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur if cur not in (None, '') else default


# ════════════════════════════════════════════════════════════ 저장소

SCHEMA = """
CREATE TABLE IF NOT EXISTS newsletter_subscribers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    email             TEXT NOT NULL UNIQUE,
    name              TEXT,
    company           TEXT,
    status            TEXT NOT NULL DEFAULT 'active',   -- active / unsubscribed
    consent_at        TEXT,       -- 수신동의 일시
    consent_source    TEXT,       -- 동의 경로 (신청폼/담당자등록 등)
    consent_ip        TEXT,       -- 동의 시점 IP
    unsubscribe_token TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    unsubscribed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_subs_status ON newsletter_subscribers(status);

CREATE TABLE IF NOT EXISTS newsletter_sends (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT NOT NULL,
    kind            TEXT NOT NULL,          -- test / real
    subject         TEXT NOT NULL,
    recipient_count INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    fail_count      INTEGER NOT NULL DEFAULT 0,
    sent_by         TEXT,
    sent_at         TEXT NOT NULL,
    detail          TEXT
);
CREATE INDEX IF NOT EXISTS idx_sends_run ON newsletter_sends(run_date DESC);
"""


def ensure_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def add_subscriber(conn, email, name=None, company=None,
                   consent_source='관리자 등록', consent_ip=None):
    """구독자 등록 — 수신동의 기록을 함께 남긴다(법적 근거)."""
    ensure_schema(conn)
    now = datetime.now(KST).isoformat(timespec='seconds')
    token = secrets.token_urlsafe(24)
    conn.execute(
        """INSERT INTO newsletter_subscribers
           (email, name, company, status, consent_at, consent_source,
            consent_ip, unsubscribe_token, created_at)
           VALUES (?,?,?,'active',?,?,?,?,?)
           ON CONFLICT(email) DO UPDATE SET
             status='active', name=COALESCE(excluded.name, name),
             company=COALESCE(excluded.company, company),
             consent_at=excluded.consent_at,
             consent_source=excluded.consent_source,
             unsubscribed_at=NULL""",
        (email.strip().lower(), name, company, now, consent_source,
         consent_ip, token, now))
    conn.commit()
    return conn.execute('SELECT * FROM newsletter_subscribers WHERE email=?',
                        (email.strip().lower(),)).fetchone()


def unsubscribe(conn, token):
    ensure_schema(conn)
    now = datetime.now(KST).isoformat(timespec='seconds')
    cur = conn.execute(
        "UPDATE newsletter_subscribers SET status='unsubscribed', "
        "unsubscribed_at=? WHERE unsubscribe_token=? AND status='active'",
        (now, token))
    conn.commit()
    return cur.rowcount > 0


def active_subscribers(conn):
    ensure_schema(conn)
    return conn.execute(
        "SELECT * FROM newsletter_subscribers WHERE status='active' "
        "ORDER BY id").fetchall()


# ════════════════════════════════════════════════════════════ 발송 데이터 구성

def build(conn, run_date=None):
    """
    발송 데이터 구성.

    승인된(approved) 시사점만 담는다. 관련 기사는 제목·출처·링크만 싣는다.
    """
    import hr_news
    import insight
    insight.ensure_schema(conn)

    if not run_date:
        row = conn.execute(
            "SELECT run_date FROM daily_insights WHERE status='approved' "
            "ORDER BY run_date DESC LIMIT 1").fetchone()
        if not row:
            return None
        run_date = row['run_date']

    rows = conn.execute(
        "SELECT * FROM daily_insights WHERE run_date=? AND status='approved' "
        "ORDER BY id", (run_date,)).fetchall()
    if not rows:
        return None

    sections = []
    for r in rows:
        d = dict(r)
        points = json.loads(d.get('points') or '[]')
        # 근거 표기 [1,2] 는 내부 검증용 — 발송물에서는 제거한다
        points = [re.sub(r'\s*\[[\d,\s]+\]', '', p).strip() for p in points]
        synthesis = re.sub(r'\s*\[[\d,\s]+\]', '',
                           d.get('synthesis') or '').strip()
        closing = re.sub(r'\s*\[[\d,\s]+\]', '',
                         d.get('closing') or '').strip()

        articles = _articles_for(conn, d['topic'], hr_news, limit=4)
        sections.append({
            'category': d.get('category') or '',
            'headline': d.get('headline') or '',
            'points': [p for p in points if p],
            'synthesis': synthesis,
            'closing': closing,
            'articles': articles,
        })

    # 입찰동향 — 조건 설정기(tender_brief)의 활성 프리셋을 그대로 쓴다.
    # 실패해도 HR뉴스는 나가야 하므로 예외를 삼킨다.
    tenders = None
    try:
        import tender_brief
        tb = tender_brief.build_section(conn)
        if tb['items']:
            tenders = tb
    except Exception as e:
        print(f'[뉴스레터] 입찰동향 섹션 생략: {type(e).__name__}: {e}')

    return {'run_date': run_date, 'sections': sections, 'tenders': tenders}


def _articles_for(conn, topic, hr_news, limit=4):
    """
    토픽 관련 기사 — 제목·출처·링크·날짜만.

    hr_news.render_for_newsletter() 를 거치므로 패시지는 반환되지 않는다.
    """
    terms = [t for t in re.split(r'\s+', topic or '') if len(t) >= 2]
    if not terms:
        return []
    where = ' OR '.join(['title LIKE ?'] * len(terms))
    rows = conn.execute(
        f"""SELECT title, source, original_link, pub_date, tier
            FROM hr_news
            WHERE is_noise=0 AND ({where})
            ORDER BY tier ASC, pub_date DESC LIMIT ?""",
        [f'%{t}%' for t in terms] + [limit]).fetchall()
    return [hr_news.render_for_newsletter(dict(r)) for r in rows]


# ════════════════════════════════════════════════════════════ 템플릿

_BRAND = '#0B6E5F'
_INK = '#17212B'
_SUB = '#5B6874'
_LINE = '#DDE3E8'


def _section_html(i, s):
    points = ''.join(
        f'<tr><td valign="top" width="14" style="padding:3px 6px 3px 0;'
        f'color:{_SUB};font-size:13px;line-height:1.7;">·</td>'
        f'<td style="padding:3px 0;color:{_INK};font-size:13.5px;'
        f'line-height:1.75;">{esc(p)}</td></tr>'
        for p in s['points'])

    synth = ''
    if s['synthesis']:
        synth = (
            f'<tr><td style="padding:12px 0 0;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td style="background:#F1F7F5;border-left:3px solid {_BRAND};'
            f'padding:11px 14px;color:{_INK};font-size:13.5px;line-height:1.75;">'
            f'<strong style="color:{_BRAND};">시사점</strong><br>{esc(s["synthesis"])}'
            f'</td></tr></table></td></tr>')

    closing = ''
    if s['closing']:
        closing = (
            f'<tr><td style="padding:10px 0 0;color:{_SUB};font-size:12.5px;'
            f'line-height:1.7;">{esc(s["closing"])}</td></tr>')

    arts = ''
    if s['articles']:
        rows = ''.join(
            f'<tr><td style="padding:2px 0;font-size:12px;line-height:1.65;">'
            f'<a href="{esc(a["link"])}" style="color:{_INK};text-decoration:none;">'
            f'{esc(a["title"])}</a> '
            f'<span style="color:#8C99A5;">{esc(a["source"])}'
            f'{" · " + esc((a["pub_date"] or "")[:10]) if a.get("pub_date") else ""}</span>'
            f'</td></tr>'
            for a in s['articles'])
        arts = (
            f'<tr><td style="padding:12px 0 0;">'
            f'<div style="color:{_SUB};font-size:11px;font-weight:bold;'
            f'letter-spacing:0.06em;padding-bottom:5px;">관련 기사</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{rows}</table></td></tr>')

    return f'''
<tr><td style="padding:20px 24px;border-top:1px solid {_LINE};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td style="padding-bottom:4px;">
      <span style="display:inline-block;background:#EDF5F3;color:{_BRAND};
        font-size:11px;font-weight:bold;padding:2px 7px;border-radius:3px;">
        {esc(s['category'])}</span>
    </td></tr>
    <tr><td style="padding:2px 0 10px;color:{_INK};font-size:16px;
      font-weight:bold;line-height:1.45;">{i}. {esc(s['headline'])}</td></tr>
    <tr><td>
      <div style="color:{_SUB};font-size:11px;font-weight:bold;
        letter-spacing:0.06em;padding-bottom:5px;">동향</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        {points}
      </table>
    </td></tr>
    {synth}
    {closing}
    {arts}
  </table>
</td></tr>'''


def _tenders_html(tb):
    """입찰동향 — 공고 제목·기관·금액·마감. 공공 공고이므로 저작권 제약이 없다."""
    if not tb or not tb.get('items'):
        return ''
    rows = ''.join(
        f'<tr><td valign="top" width="16" style="padding:5px 6px 5px 0;'
        f'color:{_SUB};font-size:12px;">{i}</td>'
        f'<td style="padding:5px 0;">'
        f'<div style="color:{_INK};font-size:13px;line-height:1.55;">'
        + (f'<a href="{esc(it["url"])}" style="color:{_INK};text-decoration:none;">'
           f'{esc(it["title"])}</a>' if it.get('url') else esc(it['title']))
        + f'</div>'
        f'<div style="color:#8C99A5;font-size:11.5px;padding-top:2px;">'
        f'{esc(it["agency"])}'
        + (f' &middot; {it["price"]}억' if it.get('price') else ' &middot; 금액 미공개')
        + (f' &middot; 마감 {esc(it["deadline"])}' if it.get('deadline') else '')
        + f'</div></td></tr>'
        for i, it in enumerate(tb['items'], 1))
    more = ''
    if tb['count'] > len(tb['items']):
        more = (f'<tr><td colspan="2" style="padding:8px 0 0;color:{_SUB};'
                f'font-size:11.5px;">외 {tb["count"] - len(tb["items"])}건</td></tr>')
    return f"""
<tr><td style="padding:20px 24px;border-top:1px solid {_LINE};">
  <div style="color:{_BRAND};font-size:11.5px;font-weight:bold;
    letter-spacing:0.08em;padding-bottom:3px;">오늘의 입찰동향</div>
  <div style="color:{_SUB};font-size:11.5px;padding-bottom:10px;">
    기업이 직접 신청할 수 있는 지원사업 {tb['count']}건</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    {rows}{more}
  </table>
</td></tr>"""


def render_html(data, unsubscribe_url=None, is_test=False, consent_at=None):
    """메일 HTML 생성 — 표 기반, 인라인 스타일 (Outlook 호환)"""
    d = datetime.strptime(data['run_date'], '%Y-%m-%d')
    week = '월화수목금토일'[d.weekday()]
    date_label = f"{d.year}년 {d.month}월 {d.day}일 {week}요일"

    sections = ''.join(_section_html(i, s)
                       for i, s in enumerate(data['sections'], 1))
    tenders_block = _tenders_html(data.get('tenders'))

    test_banner = ''
    if is_test:
        test_banner = (
            '<tr><td style="background:#7A2E14;color:#ffffff;padding:9px 24px;'
            'font-size:12.5px;line-height:1.6;">'
            '<strong>테스트 발송</strong> — 실제 구독자에게는 발송되지 않았습니다.'
            '</td></tr>')

    unsub = ''
    if unsubscribe_url:
        unsub = (f' &middot; <a href="{esc(unsubscribe_url)}" '
                 f'style="color:{_SUB};text-decoration:underline;">수신거부</a>')
    consent = ''
    if consent_at:
        consent = f' &middot; 수신동의 {esc(consent_at[:10])}'

    return f'''<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>오늘의 입찰동향 · HR뉴스 {esc(data['run_date'])}</title>
</head>
<body style="margin:0;padding:0;background:#EEF1F3;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background:#EEF1F3;">
<tr><td align="center" style="padding:20px 10px;">

<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
       style="width:600px;max-width:600px;background:#ffffff;
              border:1px solid {_LINE};border-radius:4px;
              font-family:'Malgun Gothic','맑은 고딕',Arial,sans-serif;">

  {test_banner}

  <tr><td style="background:#EDF5F3;padding:18px 24px;border-bottom:1px solid {_LINE};">
    <div style="color:{_BRAND};font-size:11.5px;font-weight:bold;
      letter-spacing:0.08em;">{esc(date_label)}</div>
    <div style="color:{_INK};font-size:19px;font-weight:bold;padding-top:5px;">
      오늘의 입찰동향 &middot; HR뉴스</div>
    <div style="color:{_SUB};font-size:12.5px;padding-top:3px;">
      기업 인사담당자를 위한 일일 브리핑</div>
  </td></tr>

  {sections}
  {tenders_block}

  <tr><td style="background:#F7F9FA;padding:16px 24px;border-top:1px solid {_LINE};">
    <div style="color:{_SUB};font-size:11.5px;line-height:1.75;">
      {esc(DISCLAIMER)}
    </div>
    <div style="color:#8C99A5;font-size:11px;line-height:1.7;padding-top:8px;">
      이 메일은 수신을 신청하신 분께 발송됩니다{consent}{unsub}
    </div>
  </td></tr>

</table>
</td></tr></table>
</body></html>'''


def subject_for(data):
    n = len(data['sections'])
    first = data['sections'][0]['headline'] if n else ''
    d = datetime.strptime(data['run_date'], '%Y-%m-%d')
    head = first[:28] + ('…' if len(first) > 28 else '')
    return f'[오늘의 브리핑] {d.month}/{d.day} {head}'


# ════════════════════════════════════════════════════════════ 발송

def smtp_config():
    """settings.json 의 newsletter.smtp 우선, 없으면 email 설정 폴백."""
    svc = _cfg('newsletter.smtp.service') or _cfg('email.service') or 'gmail'
    preset = SMTP_PRESETS.get(svc, SMTP_PRESETS['gmail'])
    return {
        'service': svc,
        'server': _cfg('newsletter.smtp.server') or preset['server'],
        'port': int(_cfg('newsletter.smtp.port') or preset['port']),
        'ssl': bool(_cfg('newsletter.smtp.ssl', preset['ssl'])),
        'user': _cfg('newsletter.smtp.user') or _cfg('email.sender'),
        'password': _cfg('newsletter.smtp.password') or _cfg('email.password'),
        'from_name': _cfg('newsletter.from_name') or '오늘의 HR뉴스',
        'base_url': (_cfg('newsletter.base_url') or 'https://ht-search.com').rstrip('/'),
    }


def _send_one(cfg, to_email, subject, html):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{cfg['from_name']} <{cfg['user']}>"
    msg['To'] = to_email
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    if cfg['ssl']:
        with smtplib.SMTP_SSL(cfg['server'], cfg['port'], timeout=30) as s:
            s.login(cfg['user'], cfg['password'])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg['server'], cfg['port'], timeout=30) as s:
            s.starttls()
            s.login(cfg['user'], cfg['password'])
            s.send_message(msg)


def _log_send(conn, run_date, kind, subject, total, ok, fail, sent_by, detail):
    ensure_schema(conn)
    conn.execute(
        """INSERT INTO newsletter_sends
           (run_date, kind, subject, recipient_count, success_count,
            fail_count, sent_by, sent_at, detail)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (run_date, kind, subject, total, ok, fail, sent_by,
         datetime.now(KST).isoformat(timespec='seconds'),
         json.dumps(detail, ensure_ascii=False)))
    conn.commit()


def send_test(conn, to_email, run_date=None, sent_by=None):
    """테스트 발송 — 실제 구독자에게 나가지 않는다."""
    data = build(conn, run_date)
    if not data:
        return {'error': '승인된 시사점이 없습니다. 검수 화면에서 먼저 승인하세요.'}
    cfg = smtp_config()
    if not (cfg['user'] and cfg['password']):
        return {'error': 'SMTP 설정이 없습니다. settings.json 의 newsletter.smtp 를 채우세요.'}

    subject = '[테스트] ' + subject_for(data)
    html = render_html(data, is_test=True)
    try:
        _send_one(cfg, to_email, subject, html)
    except Exception as e:
        _log_send(conn, data['run_date'], 'test', subject, 1, 0, 1, sent_by,
                  {'error': f'{type(e).__name__}: {e}'})
        return {'error': f'발송 실패: {type(e).__name__}: {e}'}
    _log_send(conn, data['run_date'], 'test', subject, 1, 1, 0, sent_by,
              {'to': to_email})
    return {'ok': True, 'to': to_email, 'subject': subject,
            'sections': len(data['sections'])}


def send_all(conn, run_date=None, sent_by=None):
    """구독자 전체 발송 — 수신거부 링크를 개인별로 넣는다."""
    data = build(conn, run_date)
    if not data:
        return {'error': '승인된 시사점이 없습니다. 검수 화면에서 먼저 승인하세요.'}
    subs = active_subscribers(conn)
    if not subs:
        return {'error': '활성 구독자가 없습니다.'}
    cfg = smtp_config()
    if not (cfg['user'] and cfg['password']):
        return {'error': 'SMTP 설정이 없습니다. settings.json 의 newsletter.smtp 를 채우세요.'}

    subject = subject_for(data)
    ok, fail, errors = 0, 0, []
    for s in subs:
        url = f"{cfg['base_url']}/newsletter/unsubscribe/{s['unsubscribe_token']}"
        html = render_html(data, unsubscribe_url=url,
                           consent_at=s['consent_at'])
        try:
            _send_one(cfg, s['email'], subject, html)
            ok += 1
        except Exception as e:
            fail += 1
            errors.append({'email': s['email'], 'error': f'{type(e).__name__}: {e}'})
    _log_send(conn, data['run_date'], 'real', subject, len(subs), ok, fail,
              sent_by, {'errors': errors[:20]})
    return {'ok': True, 'run_date': data['run_date'], 'subject': subject,
            'total': len(subs), 'success': ok, 'fail': fail, 'errors': errors[:5]}


def send_history(conn, limit=20):
    ensure_schema(conn)
    return [dict(r) for r in conn.execute(
        'SELECT * FROM newsletter_sends ORDER BY id DESC LIMIT ?', (limit,))]


# ════════════════════════════════════════════════════════════ CLI

def main():
    ap = argparse.ArgumentParser(description='뉴스레터 템플릿·발송')
    ap.add_argument('--preview', action='store_true', help='HTML 미리보기 저장')
    ap.add_argument('--test', metavar='EMAIL', help='테스트 발송')
    ap.add_argument('--send', action='store_true', help='구독자 전체 발송')
    ap.add_argument('--subscribers', action='store_true', help='구독자 목록')
    ap.add_argument('--add', metavar='EMAIL', help='구독자 추가')
    ap.add_argument('--name', default=None)
    ap.add_argument('--company', default=None)
    ap.add_argument('--date', default=None, help='발행일 YYYY-MM-DD')
    ap.add_argument('--out', default='newsletter_preview.html')
    args = ap.parse_args()

    import hr_news
    conn = hr_news.connect()
    ensure_schema(conn)
    try:
        if args.add:
            r = add_subscriber(conn, args.add, args.name, args.company)
            print(f'등록: {r["email"]} (동의 {r["consent_at"]})')
            return
        if args.subscribers:
            rows = conn.execute(
                'SELECT * FROM newsletter_subscribers ORDER BY id').fetchall()
            print(f'구독자 {len(rows)}명')
            for r in rows:
                print(f'  [{r["status"]}] {r["email"]:<34} {r["name"] or "":<10} '
                      f'동의 {(r["consent_at"] or "")[:10]}')
            return

        data = build(conn, args.date)
        if not data:
            print('승인된 시사점이 없습니다. 검수 화면에서 승인하세요.')
            return

        if args.preview:
            html = render_html(data, unsubscribe_url='#', is_test=True,
                               consent_at='2026-09-01')
            path = os.path.join(BASE, args.out)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f'미리보기 저장: {path} ({len(html):,} bytes)')
            print(f'  발행일 {data["run_date"]} / 섹션 {len(data["sections"])}개')
            print(f'  제목: {subject_for(data)}')
            return
        if args.test:
            print(send_test(conn, args.test, args.date, sent_by='cli'))
            return
        if args.send:
            print(send_all(conn, args.date, sent_by='cli'))
            return
        ap.print_help()
    finally:
        conn.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
