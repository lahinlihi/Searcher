# -*- coding: utf-8 -*-
"""
발송 전 검증 · 재작성 지원

왜 필요한가
  시사점은 AI 가 쓴다. 재료(기사 본문 조각)에 없는 수치나 기관이 섞여 들어가면
  그대로 고객사에 나간다. 사람이 재료 전수를 읽어 대조하면 한 건당 18분이 걸렸다.
  그래서 기계가 먼저 좁히고 사람은 좁혀진 곳만 본다.

세 겹으로 나눈 이유 — 확실한 것부터 쌓는다
  1층 코드 대조    AI 를 쓰지 않는다. 항목 속 수치·기관명이 인용한 재료 안에
                   문자열로 존재하는지만 본다. 틀릴 수 없다. 대신 '숫자는 맞는데
                   엉뚱한 사건에 붙은 경우' 는 잡지 못한다.
  2층 AI 위치 지목 판단을 시키지 않는다. "이 문장이 재료 어디서 나왔는지
                   원문 그대로 옮겨라" 만 시킨다. 그리고 그 인용이 재료에 실제로
                   있는지는 다시 코드가 대조한다(quote_verified). 지어낸 인용은
                   여기서 걸러진다. 2026-09-23 실측 4건 중 지어낸 인용 0건.
  3층 전체 재료    접어 둔다. 1·2층이 뭔가를 표시했을 때만 펼쳐 본다.

주어 불일치
  가장 위험한 오류는 '없는 수치' 가 아니라 '맞는 수치를 엉뚱한 대상에 붙이는 것'
  이었다. 실측 사례: 치상(1년~2년6개월) 형량을 치사 사건에 귀속. 코드로는 잡히지
  않으므로 AI 에게 주어 비교만 따로 시킨다.

재작성
  AI 가 쓴 것을 자동으로 갈아끼우지 않는다. 대안을 가져오기만 하고 채택은
  편집자가 한다. 자동 교체는 편집자를 사후 확인자로 만든다.
"""
import json
import re

CITE = re.compile(r'\[([\d,\s]+)\]')
# 수치는 단위가 붙은 것만 대조한다.
# 단위 없는 맨 숫자('6학년'의 6 같은 것)까지 대조하면 오탐이 쏟아진다.
NUM = re.compile(r'(\d+(?:[,.]\d+)?)\s*'
                 r'(년|개월|월|주|일|시간|분|시|억|만원|원|%|건|명|차|배|조|학년|개|호)')

# 기관명은 접미사 한 글자로 잡으면 '근무시간'의 '근무시', '영업시간'의 '영업시'
# 까지 기관으로 오인한다(실측). 부처·청은 목록으로 한정하고, 나머지는
# 두 글자 이상 접미사만 쓴다.
_MINISTRY = ('고용노동|기획재정|교육|과학기술정보통신|외교|통일|법무|국방|행정안전|'
             '문화체육관광|농림축산식품|산업통상자원|보건복지|환경|여성가족|'
             '국토교통|해양수산|중소벤처기업')
ORG = re.compile(
    r'(?:' + _MINISTRY + r')부'
    r'|[가-힣]{2,10}(?:위원회|노동조합|노총|공단|협회|연구원|진흥원|법원|'
    r'노동청|경찰청|국세청|관세청|조달청|통계청|기상청|산림청|특허청|'
    r'병무청|소방청|인권위|권익위)')

QUOTE_PREFIX = 40   # AI 인용을 재료와 대조할 때 비교하는 앞부분 길이


def strip_cite(t):
    """근거 표기 [2,3] 제거. 수치 대조보다 먼저 해야 한다.

    초기 구현에서 [3] 의 '3' 을 문장 속 수치로 오인해 허위 경고가 2건 났다.
    """
    return CITE.sub('', t or '').strip()


def cited_numbers(t):
    out = []
    for m in CITE.finditer(t or ''):
        out += [int(x) for x in m.group(1).split(',') if x.strip().isdigit()]
    return sorted(set(out))


def _norm(s):
    return re.sub(r'[\s,·‧]', '', s or '')


# ════════════════════════════════════════════════════════════ 재료

def load_material(conn, row):
    """저장된 재료를 읽는다. 없으면 토픽으로 재구성한다.

    material 컬럼은 뒤늦게 추가했다. 그 전에 생성된 시사점은 재료가 없으므로
    hr_news 에서 같은 토픽의 기사로 다시 만든다. 번호가 원래와 달라질 수 있어
    rebuilt=True 로 표시하고 화면에서 그 사실을 알린다.
    """
    raw = row['material'] if 'material' in row.keys() else None
    if raw:
        try:
            mat = json.loads(raw)
            if mat:
                return mat, False
        except Exception:
            pass
    return _rebuild_material(conn, row['topic']), True


def _rebuild_material(conn, topic, limit=8):
    import hr_news as _h
    terms = [t for t in re.split(r'\s+', topic or '') if len(t) >= 2]
    if not terms:
        return []
    stems = _h.stems(terms)
    where = ' OR '.join(['title LIKE ?'] * len(stems))
    rows = conn.execute(
        f'SELECT title, source, tier, passages, queries FROM hr_news '
        f'WHERE is_noise=0 AND ({where}) ORDER BY tier, id LIMIT 40',
        [f'%{s}%' for s in stems]).fetchall()
    out = []
    for r in rows:
        body = _h.analysis_material(dict(r), topic=topic, max_chars=600)
        if body:
            out.append({'n': len(out) + 1, 'source': r['source'],
                        'title': r['title'], 'body': body})
        if len(out) >= limit:
            break
    return out


def material_text(material, only=None):
    sel = [m for m in material if only is None or m['n'] in only]
    return '\n'.join(f"[{m['n']}] ({m['source']}) {m['title']}\n{m['body']}"
                     for m in sel)


# ════════════════════════════════════════════════════════════ 1층 — 코드 대조

def code_checks(point, material):
    """수치·기관명이 인용한 재료 안에 있는지. AI 를 쓰지 않는다."""
    by_n = {m['n']: m for m in material}
    cited = cited_numbers(point)
    clean = strip_cite(point)

    pool = _norm(' '.join(by_n[n]['body'] + by_n[n]['title']
                          for n in cited if n in by_n))
    seen, nums = set(), []
    for v, unit in NUM.findall(clean):
        tok = f'{v}{unit}'
        if tok not in seen:
            seen.add(tok)
            nums.append(tok)
    orgs = sorted({x for x in ORG.findall(clean)})

    miss_num = []
    for x in nums:
        key = _norm(x)
        core = re.match(r'[\d.]+', key)
        if key not in pool and (not core or core.group(0) not in pool):
            miss_num.append(x)
    miss_org = [x for x in orgs if _norm(x) not in pool]

    return {'cited': cited, 'numbers': nums, 'orgs': orgs,
            'missing_numbers': miss_num, 'missing_orgs': miss_org,
            'ok': not miss_num and not miss_org,
            'no_citation': not cited}


# ════════════════════════════════════════════════════════════ 2층 — AI 위치 지목

LOCATE_PROMPT = """아래 '항목'이 '재료'의 어느 문장에서 나왔는지 찾아라.

절대 규칙
1. 재료에 **실제로 있는 문장을 그대로** 옮겨라. 요약·축약·수정 금지.
2. 찾지 못하면 found=false 로 답하라. **절대 지어내지 마라.**
   지어낸 인용은 자동 대조에서 걸러지고, 그것이 가장 나쁜 결과다.
3. 항목의 **주어**와 찾은 문장의 **주어**가 다르면 subject_mismatch=true 로
   표시하고 무엇이 다른지 한 줄로 적어라.
   예: 항목은 '사망사고' 인데 재료 문장은 '중대산업재해치상' 을 말하는 경우.

JSON으로만 답하라:
{{
  "checks": [
    {{
      "claim": "항목에서 확인이 필요한 부분(수치·대상 등)",
      "material_n": 재료번호,
      "quote": "재료 원문 그대로",
      "found": true,
      "subject_mismatch": false,
      "note": "주어가 다르면 그 이유, 아니면 빈 문자열"
    }}
  ]
}}

항목:
{point}

재료:
{material}
"""


def locate(point, material, api_key=None):
    """AI 가 지목한 위치를 코드가 대조한다.

    AI 의 답을 그대로 믿지 않는다. quote 가 재료 안에 실제로 있을 때만
    quote_verified=True 가 된다.
    """
    import insight as _i
    by_n = {m['n']: m for m in material}
    cited = cited_numbers(point)
    sub = material_text(material, only=set(cited) or None)
    if not sub:
        return []
    obj, _model = _i._call(
        LOCATE_PROMPT.format(point=strip_cite(point), material=sub[:9000]),
        api_key)
    if not obj:
        return []

    out = []
    for c in obj.get('checks', []) or []:
        q = (c.get('quote') or '').strip()
        n = c.get('material_n')
        m = by_n.get(n) or {}
        body = _norm((m.get('body') or '') + (m.get('title') or ''))
        c['quote_verified'] = bool(q) and _norm(q)[:QUOTE_PREFIX] in body
        c['material_n'] = n
        out.append(c)
    return out


# ════════════════════════════════════════════════════════════ 통합

def verify(conn, row, use_ai=True, api_key=None):
    """시사점 1건 전체 검증. 항목별 1회 호출이 아니라 항목 수만큼 호출한다.

    항목을 한 번에 묶어 보내면 AI 가 항목 경계를 흐리게 섞는 일이 있어
    항목별로 나눈다. 대신 인용된 재료만 보내 토큰을 줄인다.
    """
    material, rebuilt = load_material(conn, row)
    points = json.loads(row['points'] or '[]')

    # 재구성 재료는 대조 근거로 쓸 수 없다.
    # 날짜가 지나면 hr_news 에서 뽑히는 기사도, 패시지도 생성 당시와 달라진다.
    # 실측(id=23): 본문에 분명히 있던 '30분' 이 재구성 재료에서 사라져
    #   항목 5건 중 3건이 허위 경고로 떴다. 그래서 경고를 올리지 않고
    #   '대조 불가' 로 표시한다. 없는 근거로 겁주는 것보다 모른다고 하는 편이 낫다.
    usable = bool(material) and not rebuilt

    items = []
    for i, p in enumerate(points, 1):
        code = code_checks(p, material) if usable else None
        ai = locate(p, material, api_key) if (use_ai and usable) else []
        flags = []
        if not usable:
            flags = []
        else:
            if code['no_citation']:
                flags.append('근거 표기 없음')
            if code['missing_numbers']:
                flags.append('재료에 없는 수치: ' + ', '.join(code['missing_numbers']))
            if code['missing_orgs']:
                flags.append('재료에 없는 기관: ' + ', '.join(code['missing_orgs']))
            if any(c.get('subject_mismatch') for c in ai):
                flags.append('주어 확인 필요')
            if any(not c.get('quote_verified') for c in ai):
                flags.append('AI 인용이 재료와 불일치')
        items.append({'i': i, 'raw': p, 'text': strip_cite(p),
                      'cited': cited_numbers(p),
                      'code': code, 'ai': ai, 'flags': flags,
                      'level': 'none' if not usable
                               else ('warn' if flags else 'pass')})

    return {'id': row['id'], 'material': material, 'material_rebuilt': rebuilt,
            'verifiable': usable, 'items': items,
            'flagged': sum(1 for x in items if x['flags']),
            'ai_used': use_ai and usable}


# ════════════════════════════════════════════════════════════ 재작성

REWRITE_PROMPT = """너는 기자다. 편집자가 아래 문장을 돌려보냈다.
서로 다른 접근의 대안 2개를 써라.

편집자 지시: {note}

지켜야 할 규칙
- 음슴체(~함, ~임, ~됨)로 끝낸다. '~합니다' '~이다' 금지.
- 읽는 사람에게 행동을 지시하지 않는다. 기회·시장·수요를 사실로 제시하는 데서
  멈춘다. (예: '대비가 필요함' 금지 / '관련 수요가 늘어남' 허용)
- 자사·당사·우리 회사를 언급하지 않는다.
- **재료에 없는 사실을 보태지 마라.** 수치·기관·날짜는 재료에 있는 것만 쓴다.
- 근거 표기 {cites} 를 문장 끝에 그대로 유지한다.

JSON으로만 답하라:
{{
  "alternatives": [
    {{"approach": "이 안이 무엇을 달리했는지 한 줄", "text": "고쳐 쓴 문장 {cites}"}}
  ]
}}

현재 문장:
{current}

재료:
{material}
"""


def rewrite(point, material, note='', api_key=None):
    """대안을 가져온다. 교체하지 않는다.

    각 대안은 생성 때와 같은 검사(lint)를 거친다. 검사에 걸린 대안도
    버리지 않고 걸린 사실과 함께 보여준다 — 편집자가 손봐서 쓸 수 있다.
    """
    import insight as _i
    cited = cited_numbers(point)
    cites = '[' + ','.join(str(n) for n in cited) + ']' if cited else ''
    obj, model = _i._call(REWRITE_PROMPT.format(
        note=note.strip() or '(지시 없음 — 더 분명하게 다시 써라)',
        cites=cites or '(없음)',
        current=strip_cite(point),
        material=material_text(material, only=set(cited) or None)[:9000],
    ), api_key)
    if not obj:
        return {'error': 'AI 호출 실패', 'alternatives': []}

    alts = []
    for a in (obj.get('alternatives') or [])[:3]:
        text = (a.get('text') or '').strip()
        if not text:
            continue
        if cites and cites not in text and not CITE.search(text):
            text = f'{text} {cites}'
        lint = _i.lint(strip_cite(text))
        code = code_checks(text, material)
        alts.append({
            'approach': a.get('approach') or '',
            'text': text,
            'lint_ok': not lint['blocking'],
            'lint': lint,
            'code': code,
            'ok': not lint['blocking'] and code['ok'],
        })
    return {'current': point, 'note': note, 'model': model,
            'alternatives': alts}
