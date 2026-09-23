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
     → 2026-09-23 참고 브리핑 수령 후 음슴체(~함/~임)로 확정

주의: 후보 2는 생성 AI가 "일부러 덜 좋게 만든 예(시사점 없는 사실 나열)"로
표시했으나 대표는 O를 주었다. "시사점 = 해석 + 촉구" 라는 AI의 전제가 틀렸다.
잘 정리된 사실 자체가 유효한 시사점이다. 프롬프트에 명시해야 한다.

2026-09-23 추가 확정 (참고 브리핑 대조 결과):
  - 문체: 음슴체(~함/~임)
  - 행동: **기회 제시까지만 허용.** 상황·조건·수요를 사실로 제시하는 것은 되고,
    읽는 사람이 무엇을 할지 지시하는 것은 금지. 경계는 주어다
    (주어가 시장·수요·기회면 허용 / 주어가 읽는 사람이고 서술어가 행위면 금지).
  - 목적함수: 행동 유발이 아니라 "이 회사는 이런 수준까지 아는 전문가구나"라는
    인상. 아무나 쓸 수 있는 요약은 실패다.
"""
import json
import os
import re
import time

# ════════════════════════════════════════════════════════════ 하드 제약

# 1) 행동 지시 금지 — 판정에서 완전 분리된 유일한 변수
#
# 허용선(2026-09-23 확정): **기회 제시까지만.**
#   허용: "일본 반도체장비 업계가 지금 가장 좋은 기회가 될 수 있음" (상황 서술)
#   금지: "4분기에 현지 EPC와 접촉할 필요가 있음"                   (독자 행위 지시)
#
# 초기 규칙은 서술체("~해야 합니다")만 잡아 음슴체 행동지시를 전부 놓쳤다.
# 참고 브리핑의 시사점 6개 중 5개가 음슴체 행동지시였는데 0개가 걸렸다.
# 문체를 음슴체로 바꾸면 이 구멍이 그대로 열리므로 아래를 함께 넣는다.
RULE_DIRECTIVE = [
    # 서술체
    (re.compile(r'(?:해야|하여야|하셔야|되어야|돼야)\s*(?:합니다|한다|할)'), '행동 지시'),
    (re.compile(r'(?:하십시오|하시기\s*바랍니다|하세요|합시다|하자)'), '행동 지시'),
    (re.compile(r'(?:필요합니다|필수적입니다|요구됩니다|바람직합니다)'), '행동 지시'),
    (re.compile(r'(?:할|해야\s*할)\s*(?:때입니다|시점입니다)'), '행동 지시'),
    (re.compile(r'(?:권고|권장|당부)(?:합니다|드립니다)'), '행동 지시'),
    (re.compile(r'(?:어떨까요|어떻습니까|보시기\s*바랍니다)'), '행동 지시'),
    # 음슴체 — 참고 브리핑에서 실제로 쓰인 형태들
    (re.compile(r'(?:할|볼|둘|낼|쓸)\s*필요가?\s*있(?:음|다|습니다)'), '행동 지시(음슴체)'),
    (re.compile(r'(?:해야|하여야)\s*(?:함|하는)'), '행동 지시(음슴체)'),
    (re.compile(r'[가-힣]{1,6}(?:할|볼)\s*것(?:임)?\s*(?:[.。]|$)', re.M), '행동 지시(음슴체)'),
    (re.compile(r'(?:하는|해\s*두는)\s*것이\s*(?:좋|바람직|유리)'), '행동 지시(음슴체)'),
    (re.compile(r'(?:권장|권고|요구)됨'), '행동 지시(음슴체)'),
    (re.compile(r'(?:접촉|컨택|타진|문의|상담|신청|등록|참여|도입|점검|검토|'
                r'대비|준비|확인|고려|마련|구축|강화|분석)\s*'
                r'(?:할\s*것|할\s*필요|해야|하는\s*것이|를?\s*권(?:장|고))'),
     '행동 지시(음슴체)'),
]

# 기회·상황 제시는 허용 — 금지 대상이 아님을 명시해 둔다(문서용).
# 예: "~시장이 열림", "~수요가 발생함", "~기회가 될 수 있음", "~여지가 있음",
#     "~대상이 됨", "~가능성이 있음", "~부담이 커짐"

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

# 6) 공허한 서술 — 전문성을 깎는 표현
#
# 목적함수 정의(2026-09-23): 읽는 사람이 바라는 것은 행동이 아니라
# "이 회사는 이런 수준까지 정보를 주는 전문가구나" 라는 인상이며,
# 그것이 이후 상품 신뢰로 이어진다. 금지 사항은 "비전문적으로 보이면서
# 마케팅으로 활용한다는 느낌".
# → 아무나 쓸 수 있는 서술은 전문성을 증명하지 못하므로 경고로 표시한다.
#   차단이 아닌 경고인 이유: 문맥에 따라 정당할 수 있고, 오탐이 유효 항목을
#   죽이는 사례를 이미 겪었다('당사자' 오탐).
RULE_VAGUE = [
    (re.compile(r'(?:관심|우려|기대|논란)(?:이|가)\s*(?:커지|높아지|모이|쏠리)'),
     '측정 불가 서술'),
    (re.compile(r'(?:화제|이슈|주목)(?:가|이)\s*되고\s*있'), '공허한 서술'),
    (re.compile(r'(?:변화|영향)(?:가|이)\s*(?:예상|전망)'), '내용 없는 전망'),
    (re.compile(r'(?:중요한|의미\s*있는|주목할\s*만한)\s*(?:변화|대목|지점)'),
     '수식만 있고 내용 없음'),
    (re.compile(r'(?:다양한|여러|각종)\s*(?:방안|노력|대책|움직임)'), '구체성 없음'),
    (re.compile(r'(?:귀추가?\s*주목|촉각을\s*곤두)'), '상투 표현'),
]

# 5) 음슴체 고정 — 서술형·평서형 종결 금지
#
# 판정 후속 지시(2026-09-22): "이왕이면 ~~합니다도 아니고. 개조식으로."
# 이후 참고 브리핑(2026-09-23)을 받아 음슴체(~함/~임)로 확정했다.
# 개조식은 사실 밀도가 높지만 단문을 잇지 못해 경위·조건을 담기 어렵다.
# 음슴체는 서술체가 아니면서 맥락을 전달할 수 있어 '전문성 증명'에 더 맞다.
RULE_STYLE = [
    (re.compile(r'(?:합니다|입니다|습니다|됩니다|칩니다|립니다)\s*(?:[.。]|$)', re.M),
     '서술체 종결 — 음슴체로'),
    (re.compile(r'(?:이다|한다|된다|있다|없다|했다|였다)\s*(?:[.。]|$)', re.M),
     '평서체 종결 — 음슴체로'),
    (re.compile(r'(?:하였|하겠|할\s*것)(?:습니다|입니다)'), '서술체 — 음슴체로'),
]

HARD_RULES = [('directive', RULE_DIRECTIVE), ('self', RULE_SELF),
              ('tone', RULE_TONE), ('style', RULE_STYLE)]
SOFT_RULES = [('unsourced', RULE_UNSOURCED), ('vague', RULE_VAGUE)]

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

    # 4) 마무리 재료가 마지막 항목의 복사가 아닌가
    #    실측: closing_material 이 points 의 마지막 항목과 동일하게 나온 사례.
    closing = obj.get('closing_material') or ''
    if closing and points:
        cn = re.sub(r'[^가-힣A-Za-z0-9]', '', closing)
        for i, p_ in enumerate(points, 1):
            pn = re.sub(r'[^가-힣A-Za-z0-9]', '', p_)
            if cn and pn and (cn in pn or pn in cn):
                warning.append({'label': f'마무리가 항목{i} 과 중복',
                                'match': closing[:30]})
                break

    # 5) 종합 판단의 근거가 '위에 나열한 사실 항목' 인가  ← 핵심 요건
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

## 읽는 사람의 상태 — 이걸 전제로 써라

수신자는 강한 목적을 갖고 열지 않는다. "보내니까 열고, 우리 회사에 필요한
정보가 있을까" 정도의 상태다. 따라서:

- **첫 줄에서 무엇에 관한 것인지 판별되어야 한다.** 탐색 비용이 높으면 닫는다.
- 기대하는 반응은 행동이 아니라 **"이 회사는 이런 수준까지 아는 전문가구나"**
  라는 인상이다. 그 인상이 이후 신뢰로 이어진다.

그러므로 **아무나 쓸 수 있는 요약은 실패다.** 기사 제목만 봐도 아는 내용을
다시 적지 마라. 전문가가 짚는 것을 짚어라:

  - 숫자의 의미 (형량 구간, 기준 금액, 적용 범위)
  - 적용 대상과 예외
  - 기존과 달라진 점
  - 아직 정해지지 않은 것
  - 실무에서 걸리는 지점

**비전문적으로 보이면서 마케팅에 쓰는 느낌**을 주면 안 된다.
"관심이 커지고 있다", "변화가 예상된다", "주목할 만하다" 같은
누구나 쓸 수 있는 문장은 전문성을 깎는다. 쓰지 마라.

## 형식 — 음슴체로 쓴다

종결은 **~함 / ~임 / ~됨 / 명사형**으로 한다. 서술체·평서체를 쓰지 마라.

  금지: "대법원이 첫 양형기준을 마련했습니다."
  금지: "대법원이 첫 양형기준을 마련했다."
  올바름: "대법원 양형위원회, 중대재해처벌법 시행 이후 첫 양형기준안 심의·의결함"

  금지: "적용 시점은 아직 정해지지 않았습니다."
  올바름: "적용 시점 미정"

음슴체는 단문을 이어 맥락을 전달할 수 있다. 사실을 압축만 하지 말고,
필요하면 두 문장으로 나눠 경위와 조건을 함께 담아라.

  예: "대법원 양형위, 중대산업재해치사 기본영역을 1년6개월~4년으로 권고함.
       법정형 하한 1년보다 높게 설정한 것으로, 선고 사례가 1건뿐이어서
       산업안전보건법상 의무위반치사 기준을 참고해 범위를 잡음."


## 절대 규칙 — 위반하면 발송되지 않는다

1. **기회·상황 제시까지만 한다. 행동을 지시하지 마라.**

   허용: 상황·조건·기회를 사실로 제시하는 것
     "노후 화력의 수명연장 개보수 시장이 열림"
     "일본 반도체장비 업계에 기회가 될 수 있음"
     "정밀감속기·서보모터의 대량 조달 수요가 발생함"
     "설비 발주 시점은 내년 상반기임"

   금지: 읽는 사람이 무엇을 할지 지시하는 것
     "4분기에 현지 EPC와 접촉할 필요가 있음"
     "1차 벤더 등록 요건을 확인할 것"
     "기술이전 요소를 사업계획에 포함해야 함"
     "점검해야 함", "대비할 필요가 있음", "검토가 권장됨"

   경계는 **주어**다. 주어가 시장·수요·기회·조건이면 허용,
   주어가 읽는 사람(기업·귀사·담당자)이고 서술어가 행위면 금지다.
   무엇을 할지는 읽는 사람이 정한다.

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
  "headline": "한 줄 헤드라인 (40자 이내, 명사형 종결, 부호 없음)",
  "mode": "fact" 또는 "interpretation",
  "mode_reason": "왜 그 모드를 택했는지 한 줄",
  "points": ["사실 항목 [재료번호]", "사실 항목 [재료번호]"],
  "synthesis": "위 항목들을 종합한 판단 [1,2,3]  (fact 모드면 null)",
  "closing_material": "마지막 사실 항목이 제시한 판단 재료 한 줄",
  "insufficient": true/false
}}

## 재료를 읽는 법 — 중요

각 항목의 본문은 기사 원문에서 **서로 떨어진 구간을 발췌해 이어붙인 것**이다.
`⁄` 기호가 그 경계다. **경계를 넘어 인접한 두 조각은 이어지는 내용이 아니다.**

실제 사고 사례:
  "중대재해 사망사고 발생 시 ... ⁄ 중대산업재해치상 범죄는 기본 징역 1년~2년 6개월"
  → 앞 조각의 '사망사고' 와 뒤 조각의 '치상 형량' 은 **다른 사안**이다.
    이어 읽어서 사망사고의 형량이 1년~2년 6개월이라고 쓰면 사실 오류다.

따라서:
- 수치·기간·금액은 **그 수치가 들어 있는 조각 안에서** 주어를 확인하고 쓴다.
- 조각 경계를 넘어 주어와 수치를 연결하지 마라.
- 같은 사안에 서로 다른 수치가 보이면, 각각 어느 대상의 것인지 조각 안에서
  확인되는 경우에만 쓴다. 확인되지 않으면 쓰지 마라.

## 재료

{data}
"""


# ════════════════════════════════════════════════════════════ 생성기

MODELS = ('gemini-3.5-flash', 'gemini-3.1-flash-lite', 'gemini-2.5-flash')

# 실측 근거: 503 UNAVAILABLE 이 하루에 두 번 발생했고 두 번 다 폴백으로 살아났다.
# 매일 정시 생성에서는 한 모델 실패가 그날 발행 누락이 되므로 체인을 고정한다.
_RETRY_ROUNDS = 3
_ROUND_WAIT = 15


def _api_key():
    import json as _j
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'data', 'settings.json')
    with open(path, encoding='utf-8') as f:
        k = _j.load(f).get('gemini_api_key')
    if not k:
        raise RuntimeError('settings.json 에 gemini_api_key 가 없습니다.')
    return k


def _call(prompt, api_key=None, timeout_ms=150_000):
    """모델 체인 × 라운드로 호출. (결과dict, 모델명) 또는 (None, None)."""
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key or _api_key(),
                          http_options=types.HttpOptions(timeout=timeout_ms))
    last = ''
    for rnd in range(_RETRY_ROUNDS):
        for model in MODELS:
            try:
                r = client.models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type='application/json'))
                return json.loads(r.text), model
            except Exception as e:
                last = f'{model}: {str(e)[:90]}'
                time.sleep(3)
        if rnd < _RETRY_ROUNDS - 1:
            time.sleep(_ROUND_WAIT)
    print(f'  [시사점] 전 모델 실패 — {last}')
    return None, None


# 검사 실패 시 재생성용 지시. 규칙을 다시 설명하지 않고 위반 사실만 돌려준다.
RETRY_NOTE = """
## 이전 출력이 검사에서 차단됐다. 아래를 고쳐 다시 작성하라.

{violations}

규칙은 위와 동일하다. 같은 재료로 다시 써라.
"""


def build_material(conn, topic_query, cluster_rows, limit=8, max_chars=600):
    """토픽 클러스터에서 생성 입력 재료 구성. (번호, 출처, 제목, 본문) 목록."""
    import hr_news as _h
    links = [r['original_link'] for r in cluster_rows]
    if not links:
        return []
    rows = conn.execute(
        'SELECT title, source, tier, passages, queries FROM hr_news '
        'WHERE is_noise=0 AND original_link IN ({})'.format(
            ','.join('?' * len(links))), links).fetchall()
    out = []
    for r in sorted(rows, key=lambda x: x['tier'])[:limit]:
        m = _h.analysis_material(dict(r), topic=topic_query, max_chars=max_chars)
        if m:
            out.append((len(out) + 1, r['source'], r['title'], m))
    return out


def format_material(material):
    return '\n'.join(f'{n}. [{src}] {title}\n   {body}'
                     for n, src, title, body in material)


def generate(material, api_key=None, max_attempts=2):
    """
    시사점 1건 생성 + 검사 + 검사 실패 시 재생성.

    반환: {'obj','lint','model','attempts','ok'}  또는 생성 실패 시 None
    """
    if not material:
        return None
    base = PROMPT.format(data=format_material(material)[:9000])
    prompt = base
    result = None
    for attempt in range(1, max_attempts + 1):
        obj, model = _call(prompt, api_key)
        if obj is None:
            return None
        v = validate_insight(obj, material_count=len(material))
        result = {'obj': obj, 'lint': v, 'model': model,
                  'attempts': attempt, 'ok': v['ok']}
        if v['ok']:
            return result
        if attempt < max_attempts:
            viol = '\n'.join(f"- {b['label']}: \"{b['match']}\""
                             for b in v['blocking'][:8])
            prompt = base + RETRY_NOTE.format(violations=viol)
    return result


def generate_daily(conn, days=3, top_n=3, api_key=None, quiet=False):
    """오늘의 토픽 상위 N개에 대해 시사점 생성."""
    import hr_news as _h
    topics, total = _h.rank_topics(conn, days=days, top_n=max(top_n * 3, 10))
    targets = [t for t in topics if not t['metrics']['excluded']][:top_n]
    out = []
    for t in targets:
        material = build_material(conn, t['query'], t['cluster']['rows'])
        if not material:
            continue
        if not quiet:
            print(f"  ◆ {t['query']}  (재료 {len(material)}건)")
        res = generate(material, api_key)
        if res is None:
            if not quiet:
                print('    생성 실패 — 건너뜀')
            continue
        res['topic'] = t['query']
        res['category'] = t['metrics']['category']
        res['headline_src'] = t['rep']['title']
        res['material'] = material
        out.append(res)
        if not quiet:
            o, v = res['obj'], res['lint']
            print(f"    {res['model']} | {o.get('mode')} | 시도 {res['attempts']} | "
                  f"{'통과' if v['ok'] else '차단 ' + str(len(v['blocking']))}"
                  f" / 경고 {len(v['warning'])}")
    return out, total


# ════════════════════════════════════════════════════════════ 저장

INSIGHT_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_insights (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date     TEXT NOT NULL,
    topic        TEXT NOT NULL,
    category     TEXT,
    headline     TEXT NOT NULL,
    mode         TEXT,
    points       TEXT NOT NULL DEFAULT '[]',
    synthesis    TEXT,
    closing      TEXT,
    model        TEXT,
    attempts     INTEGER,
    lint_ok      INTEGER NOT NULL DEFAULT 0,
    lint_detail  TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/skipped
    created_at   TEXT NOT NULL,
    UNIQUE(run_date, topic)
);
CREATE INDEX IF NOT EXISTS idx_insights_run ON daily_insights(run_date DESC);
CREATE INDEX IF NOT EXISTS idx_insights_status ON daily_insights(status);
"""


def ensure_schema(conn):
    conn.executescript(INSIGHT_SCHEMA)
    conn.commit()


def save_daily(conn, results, run_date=None):
    """생성 결과 저장. 같은 날짜·토픽은 덮어쓴다."""
    from datetime import datetime, timedelta, timezone as _tz
    kst = _tz(timedelta(hours=9))
    now = datetime.now(kst)
    run_date = run_date or now.strftime('%Y-%m-%d')
    ensure_schema(conn)
    saved = 0
    for r in results:
        o, v = r['obj'], r['lint']
        conn.execute(
            """INSERT INTO daily_insights
               (run_date, topic, category, headline, mode, points, synthesis,
                closing, model, attempts, lint_ok, lint_detail, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(run_date, topic) DO UPDATE SET
                 headline=excluded.headline, mode=excluded.mode,
                 points=excluded.points, synthesis=excluded.synthesis,
                 closing=excluded.closing, model=excluded.model,
                 attempts=excluded.attempts, lint_ok=excluded.lint_ok,
                 lint_detail=excluded.lint_detail""",
            (run_date, r['topic'], r.get('category'), o.get('headline'),
             o.get('mode'), json.dumps(o.get('points') or [], ensure_ascii=False),
             o.get('synthesis'), o.get('closing_material'), r.get('model'),
             r.get('attempts'), int(v['ok']),
             json.dumps({'blocking': v['blocking'], 'warning': v['warning']},
                        ensure_ascii=False),
             'pending', now.isoformat(timespec='seconds')))
        saved += 1
    conn.commit()
    return saved, run_date


def _cmd_daily(days, top_n):
    import hr_news as _h
    conn = _h.connect()
    try:
        print('=' * 74)
        print(f'시사점 생성 — 최근 {days}일 상위 {top_n}개 토픽')
        print('=' * 74)
        results, total = generate_daily(conn, days=days, top_n=top_n)
        saved, run_date = save_daily(conn, results)
        print(f'  DB 저장 {saved}건 (run_date={run_date}, status=pending)')
    finally:
        conn.close()
    print()
    for r in results:
        o, v = r['obj'], r['lint']
        print('─' * 74)
        print(f"[{r['category']}] {r['topic']}")
        print(f"  {o.get('headline')}")
        for i, pt in enumerate(o.get('points') or [], 1):
            print(f"    {i}. {pt}")
        if o.get('synthesis'):
            print(f"  종합: {o['synthesis']}")
        print(f"  마무리: {o.get('closing_material','')}")
        if not v['ok']:
            for b in v['blocking'][:4]:
                print(f"    ✖ {b['label']}  \"{b['match']}\"")
        for w in v['warning'][:3]:
            print(f"    ! {w['label']}  \"{w['match']}\"")
    print('─' * 74)
    ok = sum(1 for r in results if r['ok'])
    print(f'생성 {len(results)}건 / 검사 통과 {ok}건')
    return results


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    if '--daily' in sys.argv:
        def _arg(name, default):
            return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
        _cmd_daily(_arg('--days', 3), _arg('--top', 3))
        sys.exit(0)

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
