"""
로컬 임베딩 모델 vs 규칙 기반 점수 비교 테스트
"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')

# ── 1. 모델 로딩 ────────────────────────────────────────────────────────────
print("=" * 60)
print("1단계: 모델 다운로드 및 로딩 (최초 1회만 다운로드)")
print("=" * 60)
t0 = time.time()
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

MODEL_NAME = 'jhgan/ko-sroberta-multitask'  # 350MB, 한국어 특화
model = SentenceTransformer(MODEL_NAME)
print(f"모델 로딩 완료: {time.time()-t0:.1f}초")
print()

# ── 2. 임베딩 기반 점수 함수 ────────────────────────────────────────────────
def embed_score(tender_title, interest_keywords, core_keywords=None):
    """
    관심 키워드 프로필과 공고 제목 간 코사인 유사도 → 최대 45점
    핵심 키워드가 제목에 포함되면 유사도 보정 (+0.1)
    """
    user_profile = ' '.join(interest_keywords)
    vecs = model.encode([tender_title, user_profile])
    sim = float(cosine_similarity([vecs[0]], [vecs[1]])[0][0])

    # 핵심 키워드 직접 포함 보정
    if core_keywords:
        title_lower = tender_title.lower()
        if any(ck.lower() in title_lower for ck in core_keywords):
            sim = min(1.0, sim + 0.10)

    return round(sim * 45, 1), round(sim, 3)

# ── 3. 샘플 공고 로드 ────────────────────────────────────────────────────────
print("2단계: DB에서 샘플 공고 로드")
from app import app
from database import db, Tender, AgencyWeight
from scoring import _score_and_type, load_user_prefs
from datetime import datetime

with app.app_context():
    prefs = load_user_prefs(1)
    kws  = prefs['interest_keywords']
    tw   = prefs['type_weights']
    ck   = prefs['core_keywords']
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
        scored.append((s, ks, ts, as_, btype, t))
    scored.sort(key=lambda x: -x[0])

    total = len(scored)
    # 상위 5, 중간 3, 하위 5 (다양한 구간)
    samples = scored[:5] + scored[total//2:total//2+3] + scored[-5:]
    samples = samples[:13]

    print(f"  관심 키워드 {len(kws)}개, 핵심 키워드 {len(ck)}개")
    print(f"  샘플 {len(samples)}개 선정\n")

    # ── 4. 비교 계산 ─────────────────────────────────────────────────────────
    print("3단계: 임베딩 점수 계산 중...")
    t1 = time.time()
    results = []
    for s_rule, ks, ts, as_, btype, t in samples:
        e_kw, sim = embed_score(t.title, kws, ck)
        # 가중 합산: 규칙(60%) + 임베딩(40%)
        # 단, type/agency 점수는 그대로 유지, keyword 점수만 블렌딩
        blended_kw = round(ks * 0.6 + e_kw * 0.4, 1)
        blended_total = round(blended_kw + ts + as_, 1)
        results.append({
            'title': t.title,
            'agency': t.agency,
            'btype': btype,
            'rule_kw': ks, 'rule_type': ts, 'rule_agency': as_,
            'rule_total': s_rule,
            'embed_kw': e_kw,
            'similarity': sim,
            'blend_kw': blended_kw,
            'blend_total': blended_total,
        })
    elapsed = time.time() - t1
    print(f"  {len(samples)}개 처리 완료: {elapsed:.2f}초 (평균 {elapsed/len(samples)*1000:.0f}ms/건)\n")

    # ── 5. 결과 출력 ──────────────────────────────────────────────────────────
    print("=" * 90)
    print(f"{'#':>2}  {'규칙합계':>7}  {'혼합합계':>7}  {'차이':>5}  {'유사도':>5}  공고명")
    print("=" * 90)
    for i, r in enumerate(results, 1):
        diff = r['blend_total'] - r['rule_total']
        sign = '+' if diff > 0 else ''
        print(f"{i:>2}  {r['rule_total']:>7.1f}  {r['blend_total']:>7.1f}  "
              f"{sign}{diff:>4.1f}  {r['similarity']:>5.3f}  {r['title'][:44]}")

    print()
    print("상세 점수 분해:")
    print("-" * 90)
    for i, r in enumerate(results, 1):
        print(f"{i:>2}. {r['title'][:55]}")
        print(f"    규칙: kw={r['rule_kw']:>5.1f} + type={r['rule_type']:>4.1f}({r['btype']}) "
              f"+ agency={r['rule_agency']:>3.1f} = {r['rule_total']:>5.1f}")
        print(f"    혼합: kw={r['blend_kw']:>5.1f}(규칙{r['rule_kw']:.1f}×0.6 "
              f"+ 임베딩{r['embed_kw']:.1f}×0.4) + type={r['rule_type']:>4.1f} "
              f"+ agency={r['rule_agency']:>3.1f} = {r['blend_total']:>5.1f}")
        print()

    # ── 6. 주목할 케이스 ──────────────────────────────────────────────────────
    print("=" * 60)
    print("주목할 케이스 (차이 ±5점 이상):")
    print("=" * 60)
    notable = sorted(results, key=lambda x: abs(x['blend_total']-x['rule_total']), reverse=True)
    for r in notable[:5]:
        diff = r['blend_total'] - r['rule_total']
        direction = "임베딩이 높게 평가" if diff > 0 else "규칙이 높게 평가"
        print(f"  {direction} ({diff:+.1f}점): {r['title'][:50]}")
        print(f"    유사도={r['similarity']:.3f}  임베딩kw={r['embed_kw']}  규칙kw={r['rule_kw']}")
