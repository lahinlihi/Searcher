"""적합도 점수의 새 눈금 (제품 계약서 3부).

scoring.py 가 내는 키워드·유형 점수를 0~100 으로 다시 펴고, 담은 공고가 5건 이상이면 닮음 점수와 평균을 낸다.
발주처는 적합도에 넣지 않는다. 적합도는 "일이 우리와 맞는가"만 말하고, 발주처는 표시(중점 / 후순위)와
순서로 따로 다룬다 (3부 22.4). 위쪽은 DB 를 모르는 순수 함수, 아래쪽 Scorer 가 DB 를 읽는다.
"""

KEYWORD_FULL_X = 3.0     # 정확 일치 3건 분량(가중 합 3.0)이면 키워드 만점
KEYWORD_MAX = 45.0
TYPE_DEFAULT_MAX = 25.0
CASE_SIM_LO = 0.35       # 담은 공고와의 닮음이 이 값이면 사례 점수 0
CASE_SIM_HI = 0.80       # 이 값이면 100
CASE_MIX = 0.5           # 사례 점수가 차지하는 몫
MARK_KEY = 'key'         # 중점 발주처
MARK_LOW = 'low'         # 후순위 발주처
MARKS = (MARK_KEY, MARK_LOW)
VEC_CHUNK = 2000         # 사례 점수를 낼 때 한 번에 읽는 벡터 수


def type_max(type_weights):
    """계정의 유형 만점. 사용자가 정한 유형 점수(2.0 초과) 가운데 가장 큰 값, 다만 25 아래로는 내려가지 않는다.
    가중치를 주지 않은 유형은 25점을 받으므로, 유형 하나만 '낮음 15'로 둔 계정의 만점을 15로 잡으면
    다른 모든 공고의 점수가 올라 버린다."""
    vals = [float(v) for v in (type_weights or {}).values() if v is not None and float(v) > 2.0]
    return max(vals + [TYPE_DEFAULT_MAX])


def base_score(keyword_raw, type_score, tmax):
    """키워드(0~45 원점수)와 유형 점수로 0~100 기본 점수를 낸다."""
    kw = KEYWORD_MAX * min(1.0, (float(keyword_raw or 0) / 10.0) / KEYWORD_FULL_X)
    total = (kw + float(type_score or 0)) / (KEYWORD_MAX + float(tmax)) * 100.0
    return max(0.0, min(100.0, total))


def case_to_100(sim):
    """담은 공고와의 닮음(코사인)을 0~100 으로 옮긴다."""
    t = (float(sim) - CASE_SIM_LO) / (CASE_SIM_HI - CASE_SIM_LO)
    return max(0.0, min(1.0, t)) * 100.0


def agency_mark(agency, demand_agency, marks):
    """등록된 발주처 이름이 발주기관·수요기관에 들어 있으면 그 표시('key' / 'low'), 없으면 None.
    여럿이 걸리면 가장 긴 이름을 따르고, 길이가 같으면 후순위를 따른다 (등록 순서에 좌우되지 않게)."""
    if not marks:
        return None
    text = f"{agency or ''} {demand_agency or ''}".lower()
    best_len, best = 0, None
    for name, mark in marks.items():
        n = (name or '').strip().lower()
        if not n or n not in text:
            continue
        if len(n) > best_len or (len(n) == best_len and mark == MARK_LOW):
            best_len, best = len(n), mark
    return best


def matched_agency_name(agency, demand_agency, names):
    """걸린 등록 이름 가운데 가장 긴 것 (화면에서 발주처별로 묶을 때 쓴다). 없으면 None."""
    text = f"{agency or ''} {demand_agency or ''}".lower()
    hits = [n for n in names if n and n.strip().lower() in text]
    return max(hits, key=len) if hits else None


def combine(base, case100):
    """기본 점수에 사례 점수를 섞는다. 0~100, 소수 1자리. 발주처는 들어가지 않는다."""
    mixed = float(base) if case100 is None else float(base) * (1 - CASE_MIX) + float(case100) * CASE_MIX
    return round(max(0.0, min(100.0, mixed)), 1)


def rank_key(total, mark, date_ord=0, price=0):
    """목록 순서: 후순위 발주처는 맨 아래 → 적합도 높은 순 → 같으면 중점 발주처 먼저 → 공고일 최신 → 금액 큰 순."""
    return (1 if mark == MARK_LOW else 0, -float(total or 0), 0 if mark == MARK_KEY else 1, -date_ord, -(price or 0))


# ── 여기부터는 DB 를 읽는다 ───────────────────────────────────────────────────

def load_agency_marks(user_id):
    """{발주처 이름: 'key' | 'low'}. 표시(mark)가 있는 등록만 — 예전 값(weight)만 있는 등록은 아무 영향이 없다."""
    if user_id is None:
        return {}
    from database import AgencyWeight
    rows = AgencyWeight.query.filter(AgencyWeight.user_id == user_id, AgencyWeight.mark.in_(MARKS)).all()
    return {r.agency_name: r.mark for r in rows if r.agency_name}


class Scorer:
    """한 계정의 공고들에 적합도를 붙인다. 대시보드·검색·관심공고·상세·진단·뉴스레터가 모두 이것을 지난다.

    설정·발주처 표시·좋은 사례 벡터는 만들 때 한 번만 읽는다. 요청 하나 안에서 만들어 쓰고 버린다.
    """

    def __init__(self, user_id, vec_conn=None):
        import scoring
        self.user_id = user_id
        prefs = scoring.load_user_prefs(user_id)
        self.keywords = prefs['interest_keywords']
        self.type_weights = prefs['type_weights']
        self.core_keywords = prefs['core_keywords']
        self.tmax = type_max(self.type_weights)
        self.marks = load_agency_marks(user_id)
        self._vec_conn = vec_conn
        self._good = []          # 벡터가 있는 좋은 사례 (Tender)
        self._G = None           # 그 벡터 행렬
        self._load_cases()

    def _with_conn(self, fn):
        import tender_vectors
        conn = self._vec_conn or tender_vectors.connect()
        try:
            return fn(conn)
        finally:
            if self._vec_conn is None:
                conn.close()

    def _load_cases(self):
        import numpy as np
        import case_scoring
        import tender_vectors
        from database import Tender
        if self.user_id is None:
            return
        try:
            gids = case_scoring.good_case_ids(self.user_id)
            if len(gids) < case_scoring.MIN_CASES:
                return
            good = Tender.query.filter(Tender.id.in_(gids)).all()
            vecs = self._with_conn(lambda c: tender_vectors.load(c, [t.id for t in good]))
            good = [t for t in good if t.id in vecs]
            if len(good) < case_scoring.MIN_CASES:
                return
            self._good = good
            self._G = np.stack([vecs[t.id] for t in good]).astype(np.float32)
        except Exception as e:
            print(f'[적합도] 사례 점수 생략: {e}', flush=True)
            self._good, self._G = [], None

    def _case_scores(self, tenders):
        """{tender.id: (사례 점수 0~100, 가장 닮은 사례 Tender)}. 사례를 쓰지 않는 계정이면 빈 dict."""
        if self._G is None or not tenders:
            return {}
        import numpy as np
        import case_scoring
        import tender_vectors
        pos = {t.id: j for j, t in enumerate(self._good)}
        out = {}

        def run(conn):
            # 검색은 조건에 맞는 공고를 전부 점수 낸다(수만 건일 수 있다) — 벡터를 한꺼번에 쌓지 않고 나눠 읽는다
            for k in range(0, len(tenders), VEC_CHUNK):
                chunk = tenders[k:k + VEC_CHUNK]
                vecs = tender_vectors.load(conn, [t.id for t in chunk])
                cands = [t for t in chunk if t.id in vecs]
                if not cands:
                    continue
                C = np.stack([vecs[t.id] for t in cands]).astype(np.float32)
                sims, nearest = case_scoring.knn_scores(C, self._G, exclude=[pos.get(t.id, -1) for t in cands])
                for t, s, j in zip(cands, sims, nearest):
                    if j >= 0 and np.isfinite(s):
                        out[t.id] = (round(case_to_100(float(s)), 1), self._good[int(j)])

        try:
            self._with_conn(run)
        except Exception as e:
            print(f'[적합도] 사례 점수 생략: {e}', flush=True)
            return {}
        return out

    def score(self, tenders):
        import scoring
        tenders = list(tenders)
        cases = self._case_scores(tenders)
        out = {}
        for t in tenders:
            _, type_name, kw_raw, type_score, _ = scoring._score_and_type(
                t, self.keywords, self.type_weights, None, self.core_keywords)
            mark = agency_mark(t.agency, getattr(t, 'demand_agency', None), self.marks)
            case100, near = cases.get(t.id, (None, None))
            if not self.keywords or type_name == '결과공고' or (kw_raw == 0 and type_score == 0):
                # 관심 키워드가 없는 계정, 결과공고, 키워드도 유형도 잡히지 않은 공고(제외 패턴 포함)는 0점.
                # 닮음만으로는 살리지 않는다
                base, total, case100, near = 0.0, 0.0, None, None
            else:
                base = base_score(kw_raw, type_score, self.tmax)
                total = combine(base, case100)
            out[t.id] = {
                'total': total,
                'business_type': type_name,
                'base': round(base, 1),
                'keyword': round(KEYWORD_MAX * min(1.0, (kw_raw / 10.0) / KEYWORD_FULL_X), 1),
                'type': round(float(type_score), 1),
                'case': case100,
                'agency': mark,          # 'key' / 'low' / None — 점수에는 들어가지 않는 표시
                'nearest_case': {'id': near.id, 'title': near.title} if near is not None else None,
            }
        return out

    def sort(self, tenders, scores=None):
        """후순위 발주처는 맨 아래 → 적합도 높은 순 → 같으면 중점 발주처 먼저 → 공고일 최신 → 금액 큰 순."""
        tenders = list(tenders)
        scores = scores if scores is not None else self.score(tenders)

        def key(t):
            try:
                date_ord = t.announced_date.toordinal() if t.announced_date else 0
            except Exception:
                date_ord = 0
            r = scores[t.id]
            return rank_key(r['total'], r['agency'], date_ord, t.estimated_price or 0)
        return sorted(tenders, key=key)

    @staticmethod
    def breakdown(result):
        """화면에 보여 줄 점수 구성."""
        return {k: result.get(k) for k in ('keyword', 'type', 'case', 'agency', 'base')}
