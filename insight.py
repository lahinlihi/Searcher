# -*- coding: utf-8 -*-
"""
시사점 사양 + 검사기 (lint)

사양은 추측이 아니라 판정 결과에서 도출했다.
2026-09-22, 실데이터 후보 8개에 대한 대표 판정:

    후보  축                                      판정
    1     B-D-F-H-I  고객사·해석·행동촉구·5문장·보고체   X
    2     B-C-E-G-I  고객사·사실·정보제공·2문장·보고체   O
    3     B-D-F-H-J  고객사·해석·행동촉구·5문장·대화체   X
    4     A-D-F-H-J  자사·해석·행동촉구·5문장·대화체     X
    5     B-D-F-G-J  고객사·해석·행동촉구·2문장·대화체   X
    6     B-C-F-H-I  고객사·사실·행동촉구·5문장·보고체   X
    7     B-D-E-H-I  고객사·해석·정보제공·5문장·보고체   O
    8     B-D-E-G-I  고객사·해석·정보제공·2문장·보고체   O

축별 분해 결과:
  마무리  E(정보제공) 3건 전부 O / F(행동촉구) 5건 전부 X  → 완전 분리. 유일한 결정 변수
  어조    J(대화체) 3건 전부 X                              → 하드 제약
  관점    A(자사 관점) 1건 X                                → 하드 제약
  성격    C·D 가 O·X 양쪽에 분포                            → 결정 변수 아님 (내용에 따라)
  길이    G·H 가 O·X 양쪽에 분포                            → 결정 변수 아님 (내용에 따라)

대표 진술 (원문 요지):
  1) 자사 관점보다 "보고 싶은 정보를 사실적으로 보여준다 / 자료 신뢰성을 높인다"가 핵심
  2) 성격은 내용에 따라 취사선택. 즉시 적용 사안이면 사실, 정책 전망·준비가
     필요하면 해석
  3) 구체적 행동은 우리가 정할 부분이 아니다. 우리는 "행동을 취할 수 있는
     최대한도의 재료를 주는 것"에 가깝다. 행동을 의도하면 불신과 책임이 생긴다
  4) 길이는 상황에 따라. 요약 가능하면 짧게, 분석이 필요하면 길게
  5) 건조한 보고체 고정

주의: 후보 2는 생성 AI가 "일부러 덜 좋게 만든 예(시사점 없는 사실 나열)"로
표시했으나 대표는 O를 주었다. "시사점 = 해석 + 촉구" 라는 AI의 전제가 틀렸다.
잘 정리된 사실 자체가 유효한 시사점이다. 프롬프트에 명시해야 한다.
"""
import re

# ════════════════════════════════════════════════════════════ 하드 제약

# 1) 행동 지시 금지 — 판정에서 완전 분리된 유일한 변수
RULE_DIRECTIVE = [
    (re.compile(r'(?:해야|하여야|하셔야|되어야|돼야)\s*(?:합니다|한다|할)'), '행동 지시'),
    (re.compile(r'(?:하십시오|하시기\s*바랍니다|하세요|합시다|하자)'), '행동 지시'),
    (re.compile(r'(?:필요합니다|필수적입니다|요구됩니다|바람직합니다)'), '행동 지시'),
    (re.compile(r'(?:할|해야\s*할)\s*(?:때입니다|시점입니다)'), '행동 지시'),
    (re.compile(r'(?:점검|검토|분석|대비|준비|고민|확인|마련|구축|강화)'
                r'\s*(?:하시|해\s*보|해야|할\s*필요)'), '행동 지시'),
    (re.compile(r'(?:권고|권장|당부)(?:합니다|드립니다)'), '행동 지시'),
    (re.compile(r'(?:어떨까요|어떻습니까|보시기\s*바랍니다)'), '행동 지시'),
]

# 2) 자사 언급·영업 유도 금지
RULE_SELF = [
    # '당사자', '본사람' 같은 일반 어휘를 자사 언급으로 오탐한 사례가 있었다.
    # 실측: "정책 설계 단계부터 당사자 참여 보장 요구" 가 차단됐다.
    (re.compile(r'(?:저희|우리\s*회사|당사(?!자)|본사(?!람))'), '자사 언급'),
    (re.compile(r'(?:문의|상담|연락)\s*(?:해\s*주|주시|바랍니다|하세요)'), '영업 유도'),
    (re.compile(r'(?:솔루션|서비스|프로그램)을?\s*(?:제공|지원)합니다'), '자사 홍보'),
    (re.compile(r'(?:도와드|지원해\s*드|함께\s*하겠)'), '영업 유도'),
]

# 3) 건조한 보고체 고정 — 대화체 금지
RULE_TONE = [
    (re.compile(r'[!?]'), '대화체(감탄·의문 부호)'),
    (re.compile(r'(?:죠|지요|네요|군요|는데요|거든요|답니다)\s*[.\s]'), '대화체 종결'),
    (re.compile(r'(?:요즘|혹시|한번|미리미리|많이\s*들으셨)'), '대화체 어휘'),
    (re.compile(r'(?:이신가요|하시죠|보셨죠|아시나요)'), '대화체 의문'),
]

# 4) 근거 없는 배경 서술 탐지 보조
#    실측: "2016년부터 생활임금제를 시행해 온 성남시" 가 재료에 근거 없이 등장했다.
#    연도·횟수·순위 같은 단정은 재료 대조가 필요하다는 신호로 표시한다.
RULE_UNSOURCED = [
    (re.compile(r'\d{4}년(?:부터|에|까지)'), '연도 단정 — 재료 대조 필요'),
    (re.compile(r'(?:최초|처음으로|유일|최대|최고)(?!\s*징역)'), '최상급 단정 — 재료 대조 필요'),
    (re.compile(r'(?:\d+년\s*연속|\d+번째|\d+회째)'), '횟수 단정 — 재료 대조 필요'),
]

# 5) 개조식 고정 — 서술형 종결 금지
#
# 판정 후속 지시(2026-09-22): "기업에게 행동을 유도하지 말고, 정보만 제공하는
# 말투로써 정리해야 함. 이왕이면 ~~합니다도 아니고. 개조식으로 표현하는 것이 좋음."
# → #7 도 X 로 확정(검사기 8/8 일치). 나아가 서술체 자체를 배제한다.
#   개조식은 해석을 줄이고 사실 밀도를 높여 '신뢰성' 기준에 부합한다.
RULE_STYLE = [
    (re.compile(r'(?:합니다|입니다|습니다|됩니다|칩니다|립니다)\s*(?:[.。]|$)', re.M),
     '서술체 종결 — 개조식으로'),
    (re.compile(r'(?:이다|한다|된다|있다|없다|했다|였다)\s*(?:[.。]|$)', re.M),
     '평서체 종결 — 개조식으로'),
    (re.compile(r'(?:하였|하겠|할\s*것)(?:습니다|입니다)'), '서술체 — 개조식으로'),
]

HARD_RULES = [('directive', RULE_DIRECTIVE), ('self', RULE_SELF),
              ('tone', RULE_TONE), ('style', RULE_STYLE)]
SOFT_RULES = [('unsourced', RULE_UNSOURCED)]

# 개조식 권장 종결 — 명사형 또는 명사구
OUTLINE_ENDING = re.compile(
    r'(?:[가-힣]{1,}(?:함|됨|임|음|짐|옴|김)|'          # 명사형 어미
    r'[가-힣A-Za-z0-9)\]%원건명곳년월일차호배]|'        # 명사·수량 종결
    r'미정|예정|불가|가능|무관|해당|제외|포함)$')


def is_outline(line):
    """한 줄이 개조식인가 (명사형·명사구 종결)"""
    s = (line or '').strip().rstrip('.·,')
    return bool(s) and bool(OUTLINE_ENDING.search(s))


def lint(text, groups=None):
    """
    시사점 문장 검사.

    groups: 검사할 하드 규칙군 이름 목록. None 이면 전체.
            ('directive', 'self', 'tone', 'style')
            판정 재현 검증과 개조식 검증을 분리해 보기 위한 인자.

    반환: {'blocking': [...], 'warning': [...], 'by_group': {군: [...]}}
    """
    text = text or ''
    blocking, warning, by_group = [], [], {}
    for name, rules in HARD_RULES:
        if groups is not None and name not in groups:
            continue
        hits = []
        for pat, label in rules:
            m = pat.search(text)
            if m:
                hit = {'label': label, 'match': m.group(0).strip()}
                hits.append(hit)
                blocking.append(hit)
        if hits:
            by_group[name] = hits
    for _, rules in SOFT_RULES:
        for pat, label in rules:
            m = pat.search(text)
            if m:
                warning.append({'label': label, 'match': m.group(0).strip()})
    return {'blocking': blocking, 'warning': warning, 'by_group': by_group}


def passes(text, groups=None):
    return not lint(text, groups)['blocking']


# ════════════════════════════════════════════════════════════ 추론 구조 검증

# 지시(2026-09-22): "모든 해석은 사실에 기반해야 함.
#   A하고 B했고 C를 했으므로 이를 종합적으로 봤을때 D이다.
#   (그러므로 E를 해야 한다는 읽는 사람이 판단하는 몫)"
#
# → 해석(종합 판단)은 반드시 앞서 나열한 사실 항목에서 도출되어야 한다.
#   종합 판단이 인용한 번호가 사실 항목 목록 안에 실제로 존재하는지 대조하면
#   근거 없는 해석을 구조적으로 막을 수 있다. E(행동)는 쓰지 않는다.

CITE = re.compile(r'\[([\d,\s]+)\]')


def cited_numbers(text):
    out = set()
    for m in CITE.finditer(text or ''):
        for part in m.group(1).split(','):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
    return out


def validate_insight(obj, material_count=None):
    """
    시사점 객체 전체 검증.

    obj = {
      'headline': str,
      'mode': 'fact' | 'interpretation',
      'points': [str, ...],        # 사실 항목. 각각 [n] 근거 표기
      'synthesis': str | None,     # 종합 판단. 근거는 points 번호 (1-based)
    }
    material_count: 재료 항목 총 개수. 주어지면 points 의 근거 범위를 검사.

    반환: {'blocking': [...], 'warning': [...], 'ok': bool}
    """
    blocking, warning = [], []
    points = obj.get('points') or []
    synthesis = obj.get('synthesis') or ''
    headline = obj.get('headline') or ''

    if not points:
        blocking.append({'label': '사실 항목 없음', 'match': ''})

    # 1) 문체·지시·자사언급 — 헤드라인과 모든 항목
    for label, text in ([('헤드라인', headline)] +
                        [(f'항목{i}', p) for i, p in enumerate(points, 1)] +
                        ([('종합', synthesis)] if synthesis else [])):
        r = lint(text)
        for b in r['blocking']:
            blocking.append({'label': f"{label}: {b['label']}", 'match': b['match']})
        for w in r['warning']:
            warning.append({'label': f"{label}: {w['label']}", 'match': w['match']})

    # 2) 개조식 종결 확인
    for i, p in enumerate(points, 1):
        if not is_outline(re.sub(r'\[[\d,\s]+\]', '', p)):
            warning.append({'label': f'항목{i}: 개조식 종결 아님', 'match': p[-18:]})

    # 3) 사실 항목의 근거가 재료 범위 안인가
    if material_count:
        for i, p in enumerate(points, 1):
            nums = cited_numbers(p)
            if not nums:
                blocking.append({'label': f'항목{i}: 근거 표기 없음', 'match': p[:28]})
            bad = [n for n in nums if not (1 <= n <= material_count)]
            if bad:
                blocking.append({'label': f'항목{i}: 근거 범위 이탈',
                                 'match': str(bad)})

    # 4) 종합 판단의 근거가 '위에 나열한 사실 항목' 인가  ← 핵심 요건
    if synthesis:
        nums = cited_numbers(synthesis)
        if not nums:
            blocking.append({'label': '종합: 근거 항목 표기 없음',
                             'match': synthesis[:28]})
        bad = [n for n in nums if not (1 <= n <= len(points))]
        if bad:
            blocking.append({
                'label': f'종합: 사실 항목 {len(points)}개를 벗어난 근거 인용',
                'match': str(bad)})
    elif obj.get('mode') == 'interpretation':
        blocking.append({'label': "mode=interpretation 인데 종합 판단 없음",
                         'match': ''})

    return {'blocking': blocking, 'warning': warning, 'ok': not blocking}


# ════════════════════════════════════════════════════════════ 프롬프트

PROMPT = """너는 HR·인재양성 전문기업이 고객사에 보내는 일일 뉴스레터의 편집자다.
수신자는 일반 기업의 CEO와 인사담당자다.

## 이 일의 목적

고객사가 보고 싶어 할 정보를 **사실적으로 정리해 보여주고, 자료의 신뢰성을
높이는 것**이다. 설득하거나 유도하는 글이 아니다.
읽는 사람이 스스로 판단할 재료를 최대한 정확하게 주는 것이 전부다.

## 형식 — 개조식으로 쓴다

각 항목은 **명사형으로 끝낸다.** 서술체로 쓰지 마라.

  금지: "대법원이 첫 양형기준을 마련했습니다."
  금지: "대법원이 첫 양형기준을 마련했다."
  올바름: "대법원 양형위원회, 중대재해처벌법 첫 양형기준 마련"

  금지: "적용 시점은 아직 정해지지 않았습니다."
  올바름: "적용 시점 미정"

종결 예시: ~마련 / ~확정 / ~미정 / ~예정 / ~신설 / ~함 / ~됨 / ~임 /
숫자·단위 종결(1만2900원, 27건, 5인 이상) / 명사 종결

## 절대 규칙 — 위반하면 발송되지 않는다

1. **행동을 지시하거나 유도하지 마라.**
   "~해야 합니다", "~하십시오", "점검할 필요가 있습니다", "대비해야 합니다",
   "분석할 필요가 있습니다", "~할 때입니다" 전부 금지.
   주어가 '귀사'든 '기업들'이든 마찬가지로 금지다.
   무엇을 할지는 읽는 사람이 정한다. 행동을 의도하는 순간 불신이 생기고
   우리에게 책임이 생긴다.

2. **우리 회사를 언급하지 마라.** 자사 서비스·역량 소개, 문의 유도 전부 금지.

3. **느낌표·물음표, "~죠", "~네요", "요즘", "혹시" 금지.**

4. **재료에 없는 사실을 만들지 마라.** 특히 연도, 시행 시점, "최초/유일",
   횟수는 재료에 명시된 것만 쓴다. 근거가 없으면 아예 쓰지 마라.

5. **각 항목 끝에 근거 항목 번호를 [n] 형식으로 표기하라.**

## 내용에 따라 결정할 것

- **사실 중심(fact) vs 해석 포함(interpretation)**
  이미 확정되어 즉시 적용되는 사안이면 사실만 정확히 정리한다.
  정책 방향에 따라 달라질 사안이면 전망을 항목으로 넣는다.
  **잘 정리된 사실만으로도 충분하다. 억지로 해석을 붙이지 마라.**

- **항목 수**: 요약이 가능하면 2~3개. 상세한 사안이면 5~6개.
  분량을 채우려고 늘리지 마라.

## 해석의 구조 — 반드시 이 순서로

해석은 사실에서 도출되어야 한다. 사실을 먼저 나열하고, 그것들을 종합해
판단을 내린다. **그 판단으로부터 무엇을 할지는 읽는 사람의 몫이므로 쓰지 않는다.**

    points    : 사실 A [재료번호]
                사실 B [재료번호]
                사실 C [재료번호]
    synthesis : A·B·C 를 종합하면 D        ← 근거는 위 항목 번호 [1,2,3]
    (행동 E)  : 쓰지 않는다

`synthesis` 의 근거 번호는 **재료 번호가 아니라 위 points 의 순번**(1부터)이다.
points 에 없는 내용을 종합 판단에 끌어오지 마라. 검사기가 대조해서 걸러낸다.

사실만으로 충분한 사안(mode=fact)이면 `synthesis` 를 null 로 둔다.
억지로 종합하지 마라.

## 마지막 항목

마지막 사실 항목은 **판단 재료**로 닫는다. 적용 대상, 시행 시점, 금액 기준,
예외 요건, 확정 여부 같은 사실을 제시한다.

  나쁜 예: "안전보건 시스템 점검 필요"
  좋은 예: "적용 대상 상시근로자 5인 이상 사업장, 시행 시점 미정 [4]"

## 출력

JSON으로만 답하라:
{{
  "headline": "한 줄 헤드라인 (40자 이내, 개조식, 부호 없음)",
  "mode": "fact" 또는 "interpretation",
  "mode_reason": "왜 그 모드를 택했는지 한 줄",
  "points": ["사실 항목 [재료번호]", "사실 항목 [재료번호]"],
  "synthesis": "위 항목들을 종합한 판단 [1,2,3]  (fact 모드면 null)",
  "closing_material": "마지막 사실 항목이 제시한 판단 재료 한 줄",
  "insufficient": true/false
}}

## 재료

{data}
"""


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    # 판정된 후보 8개로 사양 검사기를 역검증한다.
    # O 판정(2,7,8)은 통과해야 하고 X 판정(1,3,4,5,6)은 걸려야 한다.
    import io, json, os
    D = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    path = os.environ.get('CANDIDATES_JSON', '')
    if not path or not os.path.exists(path):
        print('CANDIDATES_JSON 환경변수에 candidates.json 경로를 지정하세요.')
        sys.exit(0)

    RATING = {1: 'X', 2: 'O', 3: 'X', 4: 'X', 5: 'X', 6: 'X', 7: 'O', 8: 'O'}
    cands = json.load(io.open(path, encoding='utf-8'))['candidates']

    print('=' * 74)
    print('사양 검사기 역검증 — 대표 판정과 일치하는가')
    print('=' * 74)
    ok = 0
    for c in cands:
        no = c['no']
        text = f"{c.get('headline','')} {c.get('body','')}"
        r = lint(text)
        verdict = 'O' if not r['blocking'] else 'X'
        rated = RATING.get(no, '?')
        match = '일치' if verdict == rated else '불일치'
        if verdict == rated:
            ok += 1
        print(f"\n[{no}] {c.get('axes')}  대표 {rated} / 검사기 {verdict}  → {match}")
        for b in r['blocking'][:3]:
            print(f"    차단: {b['label']}  \"{b['match']}\"")
        for w in r['warning'][:2]:
            print(f"    경고: {w['label']}  \"{w['match']}\"")
    print()
    print('=' * 74)
    print(f'일치 {ok}/{len(cands)}')
