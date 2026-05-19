import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from app import app
from database import db, Tender, AgencyWeight
from scoring import _score_and_type, load_user_prefs
from settings_manager import settings_manager
from google import genai
from google.genai import types
from datetime import datetime

with app.app_context():
    prefs = load_user_prefs(1)
    kws = prefs['interest_keywords']
    tw = prefs['type_weights']
    ck = prefs['core_keywords']
    aw_rows = AgencyWeight.query.filter_by(user_id=1).all()
    aw = {r.agency_name: r.weight for r in aw_rows}

    now = datetime.now()
    all_t = Tender.query.filter(
        Tender.deadline_date >= now,
        ~Tender.bid_method.contains('수의계약')
    ).limit(300).all()

    scored = []
    for t in all_t:
        s, btype, ks, ts, as_ = _score_and_type(t, kws, tw, aw, ck)
        if s > 0:
            scored.append((s, ks, ts, as_, btype, t))
    scored.sort(key=lambda x: -x[0])

    total = len(scored)
    samples = scored[:4] + scored[total//2:total//2+3] + scored[-3:]
    samples = samples[:10]

    # Gemini API
    api_key = settings_manager.get('gemini_api_key', '')
    client = genai.Client(api_key=api_key)

    company_profile = (
        "우리 회사 프로필:\n"
        "- 업종: 교육훈련 전문기업 (IT/디지털/AI 분야 교육, 중소기업·소상공인·청년·장년 대상)\n"
        "- 주요 사업: 교육과정 운영·위탁, 교육콘텐츠 개발, 디지털전환(AX) 교육, 역량강화 프로그램\n"
        "- 관심 키워드: " + ', '.join(kws) + "\n"
        "- 수주 가능 사업 유형: 교육운영, 콘텐츠개발, 사업운영, 행사운영, 컨설팅\n"
        "- 불필요 유형: 시설물 공사, 통신망 구축, 의료장비, 단순 IT 유지보수\n\n"
        "채점 기준 (합계 100점):\n"
        "- 사업 핵심 관련성 (0~50): 우리 회사가 실제로 수행 가능한 사업인가\n"
        "- 분야 일치도 (0~30): 관심 분야(교육/IT/AI/청년/장년/소상공인 등)와 일치하는가\n"
        "- 수주 가능성 (0~20): 공고 규모·조건상 중소 교육기업이 참여 가능한가\n"
    )

    tender_list = ''
    for i, (s, ks, ts, as_, btype, t) in enumerate(samples, 1):
        tender_list += f'{i}. 제목: {t.title}\n   발주처: {t.agency}\n\n'

    prompt = (
        company_profile + "\n"
        "아래 10개 입찰공고에 대해 각각 100점 만점으로 채점하세요.\n"
        "각 공고의 채점 결과를 JSON 배열로만 반환하세요. 다른 텍스트 없이 JSON만 반환합니다.\n\n"
        "형식:\n"
        '[{"rank": 1, "score": 85, "reason": "한 줄 근거"}, ...]\n\n'
        "공고 목록:\n" + tender_list
    )

    resp = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1)
    )
    raw = resp.text.strip()
    if raw.startswith('```'):
        lines = raw.split('\n')
        raw = '\n'.join(lines[1:])
        if raw.endswith('```'):
            raw = raw[:-3]
    ai_results = json.loads(raw.strip())

    print('=' * 82)
    print(f"{'#':>2}  {'규칙기반':>8}  {'AI배점':>7}  {'차이':>6}  공고명")
    print('=' * 82)
    for i, ((s, ks, ts, as_, btype, t), ai) in enumerate(zip(samples, ai_results), 1):
        diff = ai['score'] - s
        sign = '+' if diff > 0 else ''
        print(f"{i:>2}  {s:>8.1f}  {ai['score']:>7}  {sign}{diff:>5.0f}  {t.title[:44]}")
    print()
    print('상세 AI 근거:')
    print('-' * 82)
    for i, ((s, ks, ts, as_, btype, t), ai) in enumerate(zip(samples, ai_results), 1):
        print(f"{i:>2}. [규칙:{s:.1f} → AI:{ai['score']}] {t.title[:55]}")
        print(f"    사업유형(규칙)={btype}  kw={ks}/type={ts}/agency={as_}")
        print(f"    AI근거: {ai['reason']}")
        print()
