"""
임베딩 노이즈 케이스 분석 — 규칙 점수 낮은데 임베딩이 높게 준 공고 목록
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from app import app
from database import db, Tender, AgencyWeight
from scoring import _score_and_type, load_user_prefs
from datetime import datetime
import time

MODEL_NAME = 'jhgan/ko-sroberta-multitask'
print(f"모델 로딩 중...")
t0 = time.time()
model = SentenceTransformer(MODEL_NAME)
print(f"완료: {time.time()-t0:.1f}초\n")

def embed_score(title, kws, ck=None):
    user_profile = ' '.join(kws)
    vecs = model.encode([title, user_profile])
    sim = float(cosine_similarity([vecs[0]], [vecs[1]])[0][0])
    if ck:
        if any(c.lower() in title.lower() for c in ck):
            sim = min(1.0, sim + 0.10)
    return round(sim * 45, 1), round(sim, 3)

with app.app_context():
    prefs = load_user_prefs(1)
    kws = prefs['interest_keywords']
    tw  = prefs['type_weights']
    ck  = prefs['core_keywords']
    aw_rows = AgencyWeight.query.filter_by(user_id=1).all()
    aw = {r.agency_name: r.weight for r in aw_rows}

    now = datetime.now()
    # 규칙 점수 낮은 공고(0~15점) 중 다수를 뽑아서 임베딩이 높게 주는 케이스 추출
    low_scored = Tender.query.filter(
        Tender.deadline_date >= now,
        ~Tender.bid_method.contains('수의계약')
    ).limit(500).all()

    candidates = []
    for t in low_scored:
        s, btype, ks, ts, as_ = _score_and_type(t, kws, tw, aw, ck)
        if s <= 15:  # 규칙 기반 저점수 공고
            candidates.append((s, ks, ts, as_, btype, t))

    print(f"규칙 점수 0~15점 공고: {len(candidates)}개 → 임베딩 계산 중...")
    t1 = time.time()

    noise_results = []
    for s_rule, ks, ts, as_, btype, t in candidates:
        e_kw, sim = embed_score(t.title, kws, ck)
        blended_kw = round(ks * 0.6 + e_kw * 0.4, 1)
        blended_total = round(blended_kw + ts + as_, 1)
        gap = blended_total - s_rule
        noise_results.append({
            'title': t.title,
            'agency': t.agency or '',
            'btype': btype,
            'rule': s_rule,
            'embed_kw': e_kw,
            'sim': sim,
            'blended': blended_total,
            'gap': gap,
        })

    print(f"완료: {time.time()-t1:.1f}초\n")

    # 임베딩이 규칙보다 5점 이상 높게 준 케이스 = 잠재적 노이즈
    noise = [r for r in noise_results if r['gap'] >= 5]
    noise.sort(key=lambda x: -x['gap'])

    print("=" * 85)
    print(f"규칙 저점수인데 임베딩이 5점+ 올린 공고 (총 {len(noise)}건) — 잠재적 노이즈")
    print("=" * 85)

    # 카테고리별로 분류
    categories = {
        '시설·공사·장비': [],
        '통신·IT인프라': [],
        '의료·바이오': [],
        '감리·용역 기타': [],
        '교육·연수 (경계)': [],
        '기타': [],
    }

    for r in noise[:40]:
        title = r['title']
        t_low = title.lower()
        if any(k in title for k in ['공사', '시설', '건물', '장비 교체', '구축', '전산화', '지하', '도로', '수도', '건축']):
            categories['시설·공사·장비'].append(r)
        elif any(k in title for k in ['통신', '네트워크', '인터넷', '서버', 'LAN', 'VPN', '전산실']):
            categories['통신·IT인프라'].append(r)
        elif any(k in title for k in ['의료', '병원', '임상', '한의', '약', '바이오', '건강검진']):
            categories['의료·바이오'].append(r)
        elif any(k in title for k in ['감리', '관리감독', '점검', '검사', '심사']):
            categories['감리·용역 기타'].append(r)
        elif any(k in title for k in ['연수', '자격', '교감', '교장', '연수원', '교원']):
            categories['교육·연수 (경계)'].append(r)
        else:
            categories['기타'].append(r)

    for cat, items in categories.items():
        if not items:
            continue
        print(f"\n▶ {cat} ({len(items)}건)")
        print(f"  {'규칙':>5}  {'혼합':>5}  {'유사도':>6}  공고명")
        print(f"  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*44}")
        for r in items[:8]:
            print(f"  {r['rule']:>5.1f}  {r['blended']:>5.1f}  {r['sim']:>6.3f}  {r['title'][:48]}")

    # 제외 키워드 추천
    print()
    print("=" * 60)
    print("제외 패턴 추천 (반복 등장하는 제목 키워드)")
    print("=" * 60)
    from collections import Counter
    all_noise_titles = ' '.join(r['title'] for r in noise[:40])

    # 자주 등장하는 단어 중 의미있는 것
    import re
    words = re.findall(r'[가-힣]{2,}', all_noise_titles)
    common = Counter(words).most_common(30)
    exclude_candidates = [(w, c) for w, c in common
                          if w not in ['용역', '사업', '공고', '운영', '사전규격', '관리', '지원', '추진',
                                       '경기도', '서울', '부산', '수행', '위탁', '기관', '선정', '모집']
                          and c >= 2]
    print("  단어        빈도  → 제외 추천 여부")
    for w, c in exclude_candidates[:20]:
        # 현재 관심 키워드와 겹치면 제외 추천 안 함
        if w in kws:
            note = "⚠️ 관심 키워드와 겹침 — 제외 금지"
        else:
            note = "→ 제외 후보"
        print(f"  {w:<10} {c:>3}회  {note}")
