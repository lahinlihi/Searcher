# -*- coding: utf-8 -*-
"""
입찰동향 — 발송 조건 설정 + A/B/C 분류

설계 근거 (실측, 2026-09-22)
  - 하루 수집 612건 중 기업이 직접 신청 가능한 지원사업(A)은 약 5%.
    나머지 90%(B)는 발주기관이 용역업체를 찾는 입찰이라 수요기업에 무관하다.
    무작위 40건 AI 분류 후 전수 육안검토 결과 오분류 0건.
  - 키워드만으로는 A/B 를 가를 수 없다. "모집공고" 가 주택건설 감리자 모집을
    전부 끌어왔고, 키워드로 좁히면 하루 2.6건까지 줄어 발행이 불가능했다.
    분류기를 쓰면 A 가 하루 30건 확보된다.

이 모듈은 tenders 테이블과 database.py 를 건드리지 않는다.
분류 결과는 tender_classes 에 따로 쌓고 tender_id 로 조인한다.
(운영 중인 스코어링·대시보드에 영향을 주지 않기 위함)

사용:
    python tender_brief.py --preview          # 현재 프리셋으로 미리보기
    python tender_brief.py --classify         # 미분류 후보 분류
    python tender_brief.py --preset           # 프리셋 확인
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, 'data', 'tenders.db')
KST = timezone(timedelta(hours=9))

MODELS = ('gemini-3.5-flash', 'gemini-3.1-flash-lite', 'gemini-2.5-flash')

CLASS_LABEL = {
    'A': '기업이 직접 신청 가능한 지원사업',
    'B': '발주기관이 용역업체를 찾는 입찰',
    'C': '행정공시·취소·기타',
}

DEFAULT_PRESET = {
    'name': '기본',
    'include_keywords': ['일자리', '채용', '직무', '역량', '교육', '훈련',
                         '컨설팅', '인재', '진로', '소상공인', '디지털', 'AI'],
    'exclude_keywords': ['건설', '감리', '폐기물', '안전점검', '철거',
                         '상수도', '하수', '도로', '토목', '조경', '측량',
                         '준공', '포장', '전기공사'],
    'classes': ['A'],          # 포함할 분류. 빈 배열이면 분류 무시
    'min_price': None,
    'max_price': None,
    'days_ahead': 30,          # 마감이 N일 이내인 것만
    'limit': 8,                # 메일에 실을 최대 건수
}


# ════════════════════════════════════════════════════════════ 저장소

SCHEMA = """
CREATE TABLE IF NOT EXISTS tender_classes (
    tender_id   INTEGER PRIMARY KEY,
    class       TEXT NOT NULL,          -- A / B / C
    hr_related  INTEGER NOT NULL DEFAULT 0,
    model       TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tc_class ON tender_classes(class);

CREATE TABLE IF NOT EXISTS brief_presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    config      TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 0,
    updated_by  TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS brief_preset_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id   INTEGER NOT NULL,
    config      TEXT NOT NULL,
    changed_by  TEXT,
    changed_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bph_preset ON brief_preset_history(preset_id, id DESC);
"""


def connect():
    import hr_news
    conn = hr_news.connect()          # WAL·row_factory 설정 재사용
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def ensure_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


# ════════════════════════════════════════════════════════════ 프리셋

def get_preset(conn):
    ensure_schema(conn)
    row = conn.execute(
        'SELECT * FROM brief_presets WHERE is_active=1 ORDER BY id LIMIT 1'
    ).fetchone()
    if row is None:
        now = datetime.now(KST).isoformat(timespec='seconds')
        conn.execute(
            'INSERT INTO brief_presets (name, config, is_active, updated_at) '
            'VALUES (?,?,1,?)',
            (DEFAULT_PRESET['name'],
             json.dumps(DEFAULT_PRESET, ensure_ascii=False), now))
        conn.commit()
        row = conn.execute(
            'SELECT * FROM brief_presets WHERE is_active=1 LIMIT 1').fetchone()
    cfg = json.loads(row['config'])
    return {'id': row['id'], 'name': row['name'],
            'updated_by': row['updated_by'], 'updated_at': row['updated_at'],
            **{**DEFAULT_PRESET, **cfg}}


def save_preset(conn, config, changed_by=None):
    """프리셋 저장 + 변경 이력 기록 (누가 언제 무엇을 바꿨는지)"""
    ensure_schema(conn)
    cur = get_preset(conn)
    merged = {**DEFAULT_PRESET, **{k: v for k, v in config.items()
                                   if k in DEFAULT_PRESET}}
    now = datetime.now(KST).isoformat(timespec='seconds')
    conn.execute(
        'INSERT INTO brief_preset_history (preset_id, config, changed_by, changed_at) '
        'VALUES (?,?,?,?)',
        (cur['id'], json.dumps(merged, ensure_ascii=False), changed_by, now))
    conn.execute(
        'UPDATE brief_presets SET config=?, updated_by=?, updated_at=? WHERE id=?',
        (json.dumps(merged, ensure_ascii=False), changed_by, now, cur['id']))
    conn.commit()
    return get_preset(conn)


def preset_history(conn, limit=20):
    ensure_schema(conn)
    rows = conn.execute(
        'SELECT * FROM brief_preset_history ORDER BY id DESC LIMIT ?',
        (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d['config'] = json.loads(d['config'])
        out.append(d)
    return out


# ════════════════════════════════════════════════════════════ 후보 조회

def _where(preset, days):
    """키워드·금액·마감 조건을 SQL 로 변환. (절, 파라미터) 반환."""
    cond = ["date(created_at) >= date('now', ?)"]
    params = [f'-{int(days)} day']

    inc = [k.strip() for k in (preset.get('include_keywords') or []) if k.strip()]
    if inc:
        cond.append('(' + ' OR '.join(['title LIKE ?'] * len(inc)) + ')')
        params += [f'%{k}%' for k in inc]

    exc = [k.strip() for k in (preset.get('exclude_keywords') or []) if k.strip()]
    for k in exc:
        cond.append('title NOT LIKE ?')
        params.append(f'%{k}%')

    if preset.get('min_price'):
        cond.append('(estimated_price IS NULL OR estimated_price >= ?)')
        params.append(int(preset['min_price']))
    if preset.get('max_price'):
        cond.append('(estimated_price IS NULL OR estimated_price <= ?)')
        params.append(int(preset['max_price']))

    if preset.get('days_ahead'):
        cond.append("(deadline_date IS NULL OR date(deadline_date) "
                    "BETWEEN date('now') AND date('now', ?))")
        params.append(f"+{int(preset['days_ahead'])} day")

    return ' AND '.join(cond), params


def candidates(conn, preset, days=3, limit=400):
    """분류 이전의 키워드 통과 후보"""
    where, params = _where(preset, days)
    return conn.execute(
        f"""SELECT id, title, agency, demand_agency, source_site,
                   estimated_price, deadline_date, url
            FROM tenders
            WHERE {where}
            ORDER BY COALESCE(estimated_price, 0) DESC
            LIMIT ?""", params + [limit]).fetchall()


# ════════════════════════════════════════════════════════════ A/B/C 분류

PROMPT = """너는 HR·인재양성 전문기업의 뉴스레터 편집자다.
우리는 일반 기업의 CEO·인사담당자에게 뉴스레터를 보낸다.

아래 공공 공고 목록을 3가지로 분류하라.

A = 기업이 직접 수혜자로 신청·참여할 수 있는 지원사업
    (바우처, 컨설팅 지원, 인력양성 참여기업 모집, 보조금, 판로지원,
     교육훈련 참여기업 모집 등)
B = 발주기관이 용역업체를 찾는 입찰
    (감리, 설계, 유지보수, 연구용역, 운영대행, 폐기물처리, 시설공사 등.
     수주하려면 전문 수행사여야 하는 것)
C = 둘 다 아님
    (행정공시, 인사발령, 포상, 부동산, 취소공고, 기부금품 모집 등)

각 항목에 hr_related 도 판정하라.
채용·교육·훈련·인사·노무·일자리와 직접 관련되면 true.

JSON만: {{"items":[{{"n":1,"class":"A","hr_related":true}}]}}

목록:
{data}
"""


def _api_key():
    with open(os.path.join(BASE, 'data', 'settings.json'), encoding='utf-8') as f:
        k = json.load(f).get('gemini_api_key')
    if not k:
        raise RuntimeError('settings.json 에 gemini_api_key 가 없습니다.')
    return k


def _call(prompt, api_key=None):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key or _api_key(),
                          http_options=types.HttpOptions(timeout=120_000))
    last = ''
    for rnd in range(2):
        for model in MODELS:
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type='application/json'))
                return json.loads(r.text), model
            except Exception as e:
                last = f'{model}: {str(e)[:80]}'
                time.sleep(2)
        time.sleep(10)
    print(f'  [분류] 전 모델 실패 — {last}')
    return None, None


def classify(conn, rows, batch=40, api_key=None, quiet=False):
    """
    미분류 공고를 배치로 분류해 tender_classes 에 저장.

    실측: 40건 배치가 24.4초, 입력 1,688 / 출력 923 토큰.
    배치를 키우면 정확도가 떨어질 수 있어 40건을 유지한다.
    """
    ensure_schema(conn)
    done = {r['tender_id'] for r in conn.execute(
        'SELECT tender_id FROM tender_classes')}
    todo = [r for r in rows if r['id'] not in done]
    if not todo:
        return 0, 0

    now = datetime.now(KST).isoformat(timespec='seconds')
    saved, calls = 0, 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        lines = [f"{j}. [{r['demand_agency'] or r['agency'] or r['source_site']}] "
                 f"{(r['title'] or '')[:95]}"
                 for j, r in enumerate(chunk, 1)]
        out, model = _call(PROMPT.format(data='\n'.join(lines)), api_key)
        calls += 1
        if not out:
            continue
        for it in out.get('items', []):
            n = it.get('n')
            cls = str(it.get('class', '')).upper()[:1]
            if not isinstance(n, int) or not (1 <= n <= len(chunk)) or cls not in 'ABC':
                continue
            conn.execute(
                'INSERT OR REPLACE INTO tender_classes '
                '(tender_id, class, hr_related, model, created_at) VALUES (?,?,?,?,?)',
                (chunk[n - 1]['id'], cls, int(bool(it.get('hr_related'))),
                 model, now))
            saved += 1
        conn.commit()
        if not quiet:
            print(f'  배치 {i // batch + 1}: {len(chunk)}건 → 저장 {saved} ({model})')
        time.sleep(0.5)
    return saved, calls


# ════════════════════════════════════════════════════════════ 미리보기

def preview(conn, preset=None, days=3, classify_missing=False, api_key=None):
    """
    조건 → 건수·목록.

    '지금 몇 건이 걸리는지' 를 바로 보여주는 것이 이 화면의 핵심이므로
    분류는 기본적으로 이미 저장된 것만 쓴다(빠른 응답).
    classify_missing=True 면 미분류분을 그 자리에서 분류한다(느림).
    """
    preset = preset or get_preset(conn)
    ensure_schema(conn)
    rows = candidates(conn, preset, days=days)

    if classify_missing and rows:
        classify(conn, rows, api_key=api_key, quiet=True)

    cls_map = {}
    if rows:
        ids = [r['id'] for r in rows]
        q = ','.join('?' * len(ids))
        for c in conn.execute(
                f'SELECT tender_id, class, hr_related FROM tender_classes '
                f'WHERE tender_id IN ({q})', ids):
            cls_map[c['tender_id']] = (c['class'], c['hr_related'])

    wanted = set(preset.get('classes') or [])
    items, counts = [], {'A': 0, 'B': 0, 'C': 0, '미분류': 0}
    for r in rows:
        cls, hr = cls_map.get(r['id'], (None, 0))
        counts['미분류' if cls is None else cls] += 1
        if wanted and cls not in wanted:
            continue
        p = r['estimated_price']
        items.append({
            'id': r['id'],
            'title': r['title'],
            'agency': r['demand_agency'] or r['agency'] or r['source_site'],
            'price': round(p / 1e8, 1) if p and p > 0 else None,
            'deadline': (r['deadline_date'] or '')[:10],
            'url': r['url'],
            'class': cls,
            'hr_related': bool(hr),
        })

    total_raw = conn.execute(
        "SELECT COUNT(*) FROM tenders WHERE date(created_at) >= date('now', ?)",
        (f'-{int(days)} day',)).fetchone()[0]

    return {
        'days': days,
        'total_collected': total_raw,
        'passed_keywords': len(rows),
        'class_counts': counts,
        'selected': len(items),
        'limit': preset.get('limit') or 8,
        'items': items[:preset.get('limit') or 8],
        'items_all': len(items),
    }


def build_section(conn, preset=None, days=3):
    """뉴스레터용 데이터 — 미리보기와 같은 조건, 메일에 실을 형태로"""
    pv = preview(conn, preset, days=days)
    return {'count': pv['items_all'], 'items': pv['items']}


# ════════════════════════════════════════════════════════════ CLI

def main():
    ap = argparse.ArgumentParser(description='입찰동향 조건 설정기')
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--classify', action='store_true', help='미분류 후보 분류')
    ap.add_argument('--preset', action='store_true')
    ap.add_argument('--days', type=int, default=3)
    args = ap.parse_args()

    conn = connect()
    try:
        if args.preset:
            p = get_preset(conn)
            print(json.dumps(p, ensure_ascii=False, indent=2))
            return
        if args.classify:
            p = get_preset(conn)
            rows = candidates(conn, p, days=args.days)
            print(f'후보 {len(rows)}건 — 미분류분 분류 시작')
            saved, calls = classify(conn, rows)
            print(f'분류 저장 {saved}건 / API {calls}회')
            return

        pv = preview(conn, days=args.days)
        print('=' * 70)
        print(f"최근 {pv['days']}일 수집 {pv['total_collected']:,}건")
        print(f"  → 키워드 통과 {pv['passed_keywords']}건")
        print(f"  → 분류 {pv['class_counts']}")
        print(f"  → 조건 부합 {pv['items_all']}건 (메일 게재 상위 {pv['limit']}건)")
        print('=' * 70)
        for i, it in enumerate(pv['items'], 1):
            price = f"{it['price']}억" if it['price'] else '미공개'
            hr = ' [HR]' if it['hr_related'] else ''
            print(f"{i:2d}. [{it['class'] or '?'}]{hr} {it['title'][:62]}")
            print(f"     {it['agency'][:28]} · {price} · 마감 {it['deadline'] or '미정'}")
    finally:
        conn.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
