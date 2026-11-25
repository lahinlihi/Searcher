# 적합도 점수 재정리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 적합도를 100점 눈금으로 다시 만들고(키워드 만점 조정, 사례 50% 혼합), 발주처는 등록한 곳만 가감점으로 움직이며, 중점 발주처의 새 공고를 대시보드에 따로 모은다.

**Architecture:** `scoring.py` 는 건드리지 않는다. 새 모듈 `relevance.py` 가 `scoring._score_and_type` 의 키워드·유형 점수를 받아 새 눈금으로 환산하고, 사례 점수와 발주처 가감점을 얹는다. 점수를 쓰는 모든 화면·API 는 `relevance.Scorer` 하나를 지난다. 발주처 가감점은 `agency_weights.adjust` 새 칸에 두고 예전 `weight` 값은 지우지 않는다.

**Tech Stack:** Flask, Flask-SQLAlchemy(sqlite), numpy, pytest. 프런트는 기존 바닐라 JS (`static/js/tender-row.js` 가 공고 한 줄을 그린다).

**Spec:** `docs/product-contract.md` 3부 (20~26절)

## Global Constraints

- `scoring.py` 의 함수 본문을 바꾸지 않는다 (안정 동작 코드). 새 계산은 `relevance.py` 에 둔다.
- 키워드 만점 지점 `KEYWORD_FULL_X = 3.0`. 키워드 만점 45. 유형 만점 = 계정의 유형 가중치(2.0 초과 값) 중 최댓값, 없으면 25.
- 사례 점수 환산: 유사도 `CASE_SIM_LO = 0.35` → 0점, `CASE_SIM_HI = 0.80` → 100점, 그 사이 직선. 혼합 비율 `CASE_MIX = 0.5`. 좋은 사례 5건 미만(`case_scoring.MIN_CASES`)이면 섞지 않는다.
- 발주처 가감점 범위 −30 ~ +30. 등록하지 않은 발주처는 0.
- 적합도는 0~100 으로 자르고 소수 1자리로 반올림한다.
- 요청 처리 중 임베딩 모델을 새로 부르지 않는다. `tender_vectors.load` 로 저장된 벡터만 읽는다 (`ensure` 금지).
- 테스트: `python -m pytest tests -q -p no:cacheprovider`. 운영 DB(`data/tenders.db`)에 쓰는 명령을 계획 실행 중에 돌리지 않는다.
- 커밋은 사용자가 요청할 때만 한다. 각 Task 의 마지막 단계는 "테스트 전체 통과 확인"이다.
- `routes/*.py`, `database.py` 가 바뀌므로 운영 반영 때 프로젝트 `CLAUDE.md` 의 서버 재시작 6단계를 따른다.

## Review Focus

- 좋은 사례는 5건 이상인데 후보 공고의 벡터가 없다(방금 수집됨) → 그 공고는 오류 없이 기본 점수만 받아야 한다. (Task 2)
- 발주처 이름이 두 등록값에 모두 걸린다("서울", "서울시교육청") → 더 긴 이름의 가감점이 적용돼야 한다. (Task 1)
- 관심 키워드가 하나도 없는 계정 → 모든 점수 0, 사례 혼합도 하지 않는다(지금 동작 유지). (Task 2)
- 가감점으로 100 을 넘거나 0 아래로 내려간다 → 0~100 으로 잘린다. 관심공고 라벨 보너스를 더한 뒤에도 100 을 넘지 않는다. (Task 1, Task 4)
- `adjust` 가 NULL 인 예전 등록 행(옮기기 전) → 0 으로 취급한다. (Task 3)

## File Structure

| 파일 | 책임 |
|---|---|
| `relevance.py` (새) | 새 눈금 계산식(순수 함수)과 `Scorer` |
| `database.py` | `AgencyWeight.adjust` 칸 + 마이그레이션 한 줄 |
| `routes/filters.py`, `templates/filters.html` | 발주처 가감점 등록 API·화면 |
| `routes/tenders.py`, `routes/bookmarks.py`, `routes/pages.py`, `routes/cases.py`, `missed_diagnosis.py`, `case_eval.py`, `tender_brief.py` | 점수 호출부를 `Scorer` 로 교체 |
| `static/js/tender-row.js`, `static/js/dashboard.js`, `static/js/search.js`, `templates/detail.html`, `templates/dashboard.html` | 구성 표시, 다시 정렬 제거, 중점 발주처 탭 |
| `tools/agency_adjust_migrate.py` (새) | 예전 값 → 새 값 옮기는 표 출력 / 적용 |
| `tests/test_relevance.py` (새), `tests/test_agency_adjust.py` (새), `tests/test_key_agencies.py` (새) | 테스트 |

---

### Task 1: 새 눈금 계산식 (`relevance.py` 순수 함수)

**Files:**
- Create: `relevance.py`
- Test: `tests/test_relevance.py`

**Interfaces:**
- Produces:
  - `KEYWORD_FULL_X = 3.0`, `CASE_SIM_LO = 0.35`, `CASE_SIM_HI = 0.80`, `CASE_MIX = 0.5`, `ADJUST_MIN = -30.0`, `ADJUST_MAX = 30.0`
  - `type_max(type_weights: dict | None) -> float`
  - `base_score(keyword_raw: float, type_score: float, tmax: float) -> float` — `keyword_raw` 는 `_score_and_type` 가 돌려준 키워드 점수(0~45), 반환 0~100
  - `case_to_100(sim: float) -> float`
  - `agency_adjust(agency: str | None, demand_agency: str | None, adjusts: dict[str, float]) -> float`
  - `combine(base: float, case100: float | None, adjust: float) -> float` — 반올림·자르기까지

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_relevance.py`

```python
import relevance as R

def test_type_max():
    assert R.type_max(None) == 25.0
    assert R.type_max({}) == 25.0
    assert R.type_max({'교육운영': 45, '행사운영': 15}) == 45.0
    assert R.type_max({'교육운영': 1.2}) == 25.0        # 2.0 이하 값은 예전 배율 방식 — 만점 계산에 넣지 않는다

def test_base_score_matches_measured_examples():
    # 2026-11-25 측정: 계정 5 최고점 24.6+25 → 88.4, 20.0+25 → 78.6 / 계정 1 은 발주처를 빼고 다시 계산
    assert round(R.base_score(24.6, 25.0, 25.0), 1) == 88.4
    assert round(R.base_score(20.0, 25.0, 25.0), 1) == 78.6
    assert R.base_score(45.0, 25.0, 25.0) == 100.0       # x = 4.5 ≥ 3.0 → 키워드 만점
    assert R.base_score(30.0, 45.0, 45.0) == 100.0
    assert R.base_score(0.0, 0.0, 25.0) == 0.0

def test_case_to_100():
    assert R.case_to_100(0.35) == 0.0 and R.case_to_100(0.2) == 0.0
    assert R.case_to_100(0.80) == 100.0 and R.case_to_100(0.95) == 100.0
    assert round(R.case_to_100(0.575), 1) == 50.0

def test_agency_adjust():
    adj = {'서울': 10.0, '서울시교육청': -30.0, '한국콘텐츠진흥원': 20.0}
    assert R.agency_adjust('부산광역시', None, adj) == 0.0
    assert R.agency_adjust('한국콘텐츠진흥원 본원', None, adj) == 20.0
    assert R.agency_adjust('조달청', '한국콘텐츠진흥원', adj) == 20.0      # 수요기관도 본다
    assert R.agency_adjust('서울시교육청 학교지원과', None, adj) == -30.0   # 더 긴 이름이 이긴다
    assert R.agency_adjust(None, None, adj) == 0.0
    assert R.agency_adjust('서울', None, {}) == 0.0

def test_combine():
    assert R.combine(80.0, None, 0.0) == 80.0
    assert R.combine(80.0, 60.0, 0.0) == 70.0
    assert R.combine(80.0, None, 20.0) == 100.0
    assert R.combine(95.0, None, 20.0) == 100.0          # 위로 자름
    assert R.combine(20.0, None, -30.0) == 0.0           # 아래로 자름
    assert R.combine(80.0, 60.0, -30.0) == 40.0
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_relevance.py -q -p no:cacheprovider` → `ModuleNotFoundError: relevance`
- [ ] **Step 3: `relevance.py` 에 위 상수와 함수 구현**
  - `base_score`: 키워드 = `45 * min(1, (keyword_raw / 10) / KEYWORD_FULL_X)`, 결과 = `(키워드 + type_score) / (45 + tmax) * 100`, 100 에서 자름.
  - `agency_adjust`: 수요기관·발주기관 이름에 부분 일치하는 등록 이름 가운데 **가장 긴 것**의 값.
  - `combine`: `case100` 이 None 이면 `base`, 아니면 `base*(1-CASE_MIX) + case100*CASE_MIX`; 가감점을 더하고 0~100 으로 자른 뒤 소수 1자리.
- [ ] **Step 4: 통과 확인** — 같은 명령 → `5 passed`

---

### Task 2: `Scorer` — 한 계정의 공고들에 점수 붙이기

**Files:**
- Modify: `relevance.py`
- Test: `tests/test_relevance.py`

**Interfaces:**
- Consumes: Task 1 의 함수, `scoring.load_user_prefs`, `scoring._score_and_type`, `case_scoring.good_case_ids`, `case_scoring.knn_scores`, `case_scoring.MIN_CASES`, `tender_vectors.connect/load`
- Produces:
  - `load_agency_adjusts(user_id) -> dict[str, float]` — `AgencyWeight.adjust` 가 NULL 이 아닌 행만
  - `class Scorer(user_id, vec_conn=None)` — 생성 때 prefs·가감점·좋은 사례 벡터를 한 번 읽는다
  - `Scorer.score(tenders) -> dict[int, dict]` — 값: `{'total': float, 'business_type': str, 'base': float, 'keyword': float, 'type': float, 'case': float | None, 'agency': float, 'nearest_case': {'id', 'title'} | None}`. `keyword` 는 새 눈금의 키워드 점수(0~45), `case` 는 0~100.
  - `Scorer.sort(tenders) -> list` — total 내림차순, 같으면 공고일 최신, 금액 큰 순 (`smart_sort_tenders_by_keyword_count` 와 같은 2·3순위)
  - `Scorer.breakdown(result: dict) -> dict` — 화면용 `{'keyword','type','case','agency','base'}` (None 은 그대로)

- [ ] **Step 1: 실패하는 테스트 추가** — `tests/test_relevance.py`. 벡터는 `tests/test_case_scoring.py` 가 쓰는 방식(임시 `vectors.db` 에 직접 `tender_vectors.store`)을 따른다. 관심 키워드는 `UserPreference` 에 넣는 기존 테스트의 도우미를 재사용한다.

```python
def test_scorer_without_cases_uses_base_only(app, make_user, make_tender, set_prefs):
    u = make_user(); set_prefs(u, interest_keywords=['교육'])
    t = make_tender(title='AI 교육 운영 용역')
    r = R.Scorer(u.id).score([t])[t.id]
    assert r['case'] is None and r['agency'] == 0.0
    assert r['total'] == round(r['base'], 1)

def test_scorer_no_keywords_gives_zero(app, make_user, make_tender):
    u = make_user(); t = make_tender(title='AI 교육 운영 용역')
    assert R.Scorer(u.id).score([t])[t.id]['total'] == 0.0

def test_scorer_mixes_case_when_five_cases(app, make_user, make_tender, set_prefs, vec_db, bookmark):
    # 좋은 사례 5건(벡터 e0), 후보 a(벡터 e0 = 유사도 1.0), 후보 b(벡터 e1 = 유사도 0.0), 후보 c(벡터 없음)
    ...
    res = R.Scorer(u.id, vec_conn=vec_db).score([a, b, c])
    assert res[a.id]['case'] == 100.0 and res[b.id]['case'] == 0.0
    assert res[a.id]['total'] == round(res[a.id]['base'] * 0.5 + 50.0, 1)
    assert res[c.id]['case'] is None and res[c.id]['total'] == round(res[c.id]['base'], 1)   # 벡터 없는 공고
    assert res[a.id]['nearest_case']['id'] in good_ids

def test_scorer_excludes_self_from_cases(...):
    # 담은 공고 자신을 점수 낼 때 자기 벡터는 비교에서 빠진다 → case < 100
    ...

def test_scorer_applies_agency_adjust(app, make_user, make_tender, set_prefs, add_adjust):
    u = make_user(); set_prefs(u, interest_keywords=['교육'])
    add_adjust(u, '테스트기관', 20.0)
    t = make_tender(title='AI 교육 운영 용역', agency='테스트기관')
    r = R.Scorer(u.id).score([t])[t.id]
    assert r['agency'] == 20.0 and r['total'] == min(100.0, round(r['base'] + 20.0, 1))

def test_sort_orders_by_total_then_date(...):
    ...
```

  필요한 fixture(`set_prefs`, `vec_db`, `bookmark`, `add_adjust`)가 `tests/conftest.py` 에 없으면 거기에 추가한다. `add_adjust` 는 Task 3 의 칸을 쓰므로 이 테스트는 Task 3 Step 3 뒤에 초록이 된다 — Task 2 에서는 `pytest.importorskip` 없이 그대로 두고 Task 3 에서 함께 통과시킨다.

- [ ] **Step 2: 실패 확인** — `AttributeError: module 'relevance' has no attribute 'Scorer'`
- [ ] **Step 3: `Scorer` 구현**
  - `_score_and_type(t, kws, type_weights, None, core)` 를 부르고 반환값의 키워드·유형 점수만 쓴다(총점과 기관 5점은 버린다). 반환 총점이 0 이고 유형이 '결과공고'이거나 키워드 점수·유형 점수가 모두 0 이면 total 0.
  - 사례: `good_case_ids` 가 `MIN_CASES` 이상이고 벡터가 있는 좋은 사례도 `MIN_CASES` 이상일 때만. 후보 벡터는 `tender_vectors.load` 로 읽고, `knn_scores(C, G, exclude=...)` 로 자기 자신을 뺀다. `vec_conn` 이 없으면 `tender_vectors.connect()` 를 열고 닫는다. 벡터 읽기에서 예외가 나면 로그 한 줄(`[적합도] 사례 점수 생략: …`)을 찍고 기본 점수만 쓴다.
- [ ] **Step 4: 통과 확인** (가감점 테스트 제외) — `python -m pytest tests/test_relevance.py -q -p no:cacheprovider -k "not agency_adjust"` → 전부 통과

---

### Task 3: 발주처 가감점 저장과 등록 화면

**Files:**
- Modify: `database.py` (`AgencyWeight`), `routes/filters.py:146-203`, `templates/filters.html:84-120, 522-640`
- Create: `tools/agency_adjust_migrate.py`
- Test: `tests/test_agency_adjust.py`

**Interfaces:**
- Produces:
  - `AgencyWeight.adjust: Float | None` — 가감점(−30~+30). `to_dict()` 에 `'adjust'` 추가. 마이그레이션: `ALTER TABLE agency_weights ADD COLUMN adjust FLOAT` (기존 `cleared_at` 마이그레이션과 같은 자리·같은 방식)
  - `POST /api/agency-weights` body `{agency_name, adjust}` / `PUT /api/agency-weights/<id>` body `{adjust}` — `adjust` 는 −30~30 의 수, 벗어나면 400 `{'error': '가감점은 -30 ~ +30 사이여야 합니다.'}`. 숫자가 아니면 400.
  - `tools/agency_adjust_migrate.py [--apply] [--db PATH]` — 기본은 표만 출력

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_agency_adjust.py`

```python
def test_post_stores_adjust(client, login):            # +20 저장, GET 에 'adjust': 20.0
def test_post_rejects_out_of_range(client, login):     # 31, -31, 'abc' → 400
def test_put_updates_adjust(client, login):
def test_null_adjust_is_ignored(app, make_user):       # weight=10, adjust=None 인 행 → load_agency_adjusts == {}
def test_migration_table():                            # old_to_new(0)==-20, (2.5)==-10, (5)==0, (7.5)==10, (10)==20
```

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
  - `database.py`: 칸과 마이그레이션. 예전 `weight` 칸과 값은 그대로 둔다.
  - `routes/filters.py`: `weight` 검증을 `adjust` 검증으로 교체. 새 행의 `weight` 는 5.0(기본)으로 둔다.
  - `templates/filters.html`: 선택 버튼(0/2.5/5/7.5/10) 대신 숫자 입력(−30~+30, 5 단위 step)과 설명 문구 —
    "등록하지 않은 발주처는 점수에 영향이 없습니다. **더 신경 쓸 발주처는 가점(+)**, **꺼리는 발주처는 감점(−)**을 넣습니다. 가점을 준 발주처의 새 공고는 대시보드 '중점 발주처'에 따로 모입니다."
    84행의 식 설명은 "적합도 = (키워드 + 사업유형)을 100점으로 환산 · 담은 공고가 5건 이상이면 담은 공고와 닮은 정도를 절반 반영 · 발주처 가감점"으로 바꾼다. 목록 칩은 `+20` / `−30` 을 색(가점 `--hs-ok`, 감점 `--hs-bad`)과 함께 보여 준다.
  - `tools/agency_adjust_migrate.py`: `old_to_new(w) = (w - 5) * 4`. 기본 실행은 `계정 | 발주처 | 예전 값 | 새 가감점` 표만 출력하고 아무것도 쓰지 않는다. `--apply` 일 때만 `adjust IS NULL` 인 행에 쓴다.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_agency_adjust.py tests/test_relevance.py -q -p no:cacheprovider` → 전부 통과 (Task 2 의 가감점 테스트 포함)
- [ ] **Step 5: 옮기는 표를 사용자에게 보여 준다** — DB 사본에 대해 `python tools/agency_adjust_migrate.py --db <사본 경로>` 를 돌려 표를 그대로 보고하고, **사용자가 값을 확인하기 전에는 `--apply` 를 돌리지 않는다.**

---

### Task 4: 점수 호출부를 `Scorer` 로 교체

**Files:**
- Modify: `routes/tenders.py` (`_scored_dict`, `api_dashboard`, `api_embed_scores`, 검색 `:560-590`), `routes/bookmarks.py:15-55, 70-130`, `routes/pages.py:95-112`, `routes/cases.py` (`api_similar`, `api_sort_setting`), `missed_diagnosis.py:88-100`, `case_eval.py:40-50`, `tender_brief.py:325-340`
- Modify: `tests/test_dashboard_unchanged.py`, `tests/test_cases_api.py`, `tests/test_missed_diagnosis.py`, `tests/test_case_eval.py`
- Test: `tests/test_relevance.py` (화면 간 일치)

**Interfaces:**
- Consumes: `relevance.Scorer` (Task 2)
- Produces (응답 형태):
  - 공고 dict 의 `relevance_score` = `total`, `business_type`, `score_breakdown = {'keyword', 'type', 'case', 'agency', 'base'}`, 사례가 섞였으면 `nearest_case`
  - `/api/dashboard` 응답에서 `case_sort` 키를 없앤다. 각 구역은 `Scorer.sort` 순서의 상위 `DASHBOARD_TOP_N`
  - `/api/embed-scores` 는 남기되 `Scorer` 결과를 같은 모양(`score, keyword, type, agency, business_type` + `case`)으로 돌려준다 — 임베딩 혼합(`compute_embed_sims`)을 부르지 않는다
  - `/api/cases/sort-setting`: GET 은 `{'enabled': True, 'allowed': True, 'reason': '사례 점수는 적합도에 항상 절반 반영됩니다.'}`, POST 는 같은 값을 돌려주고 아무것도 바꾸지 않는다

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_same_tender_same_score_everywhere(client, login, ...):
    # 같은 공고의 적합도가 /api/dashboard, /api/tenders(검색), /api/bookmarks(라벨 없음), 상세 화면에서 모두 같다
def test_dashboard_has_no_case_sort_flag(...):
def test_dashboard_orders_by_total(...):          # 사례가 섞인 total 순서
def test_bookmark_label_bonus_capped(...):        # total 95 + 라벨 15 → 100.0
def test_embed_scores_returns_scorer_total(...):
def test_brief_min_score_uses_new_scale(...):     # tender_brief 가 Scorer 점수로 min_score 를 비교
```

  기존 테스트 중 `case_sort` 를 기대하는 것(`tests/test_cases_api.py:49,101,103`)은 "플래그 없음 + total 순서"로 고쳐 쓴다. `tests/test_dashboard_unchanged.py` 의 점수 기대값은 새 식으로 다시 계산한 값으로 바꾸되, **구역 소속·fresh·읽은 공고 동작을 보는 단언은 그대로 둔다.**

- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 호출부 교체**
  - 요청 하나에 `Scorer` 는 한 번만 만든다(좋은 사례 벡터를 한 번만 읽게). `_scored_dict(tender, prefs, agency_weights)` 는 `_scored_dict(tender, prefs, result)` 로 바꾸고 호출부가 `scorer.score(목록)` 을 먼저 구해 넘긴다.
  - `api_dashboard`: `_case_scores`, `sort_by_case`, `case_store.get_sort_enabled` 사용을 지운다. 구역별 후보 전체를 한 번에 `score` 하고 `sort`.
  - `missed_diagnosis.diagnose`: 등수와 점수 구성을 `Scorer` 로 낸다(진단 화면의 "키워드 n + 유형 n + 기관 n" 문구는 Task 5 에서 고친다).
  - `case_eval.evaluate`: "지금 점수" 쪽을 `Scorer` 의 `base`(사례를 섞기 전)로 바꾼다 — 채점은 "사례를 섞지 않은 점수 대 사례 점수"의 비교로 남는다.
  - `tender_brief.py`: `_score_and_type`·`compute_embed_sims` 대신 `Scorer`. `min_score` 기본값은 0 이라 그대로 둔다. `data/` 의 저장된 프리셋에 0 이 아닌 `min_score` 가 있으면 값을 바꾸지 말고 보고한다.
  - `scoring.smart_sort_tenders_by_keyword_count`, `compute_embed_sims`, `case_store.get_sort_enabled/set_sort_enabled` 는 지우지 않는다(쓰는 곳만 없앤다). 남은 호출이 없는지 `grep` 으로 확인해 보고한다.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests -q -p no:cacheprovider` → 전부 통과
- [ ] **Step 5: 분포 재확인** — 사본 DB 로 계정 5 의 대시보드 상위 15건을 뽑아 최저 70점 이상, 최고 85점 이상인지 확인하고 출력을 보고한다(3부 23절 수용 기준). 스크립트는 `scratchpad` 의 `score_compare3.py` 를 `Scorer` 를 부르도록 고쳐 쓴다.

---

### Task 5: 화면 — 점수 구성 표시, 다시 정렬 제거

**Files:**
- Modify: `static/js/tender-row.js:92-96`, `static/js/dashboard.js:120-150, 270-335`, `static/js/search.js:22-40`, `templates/detail.html:165-175`, `static/js/cases.js`, `templates/cases.html`
- Test: `tests/test_pages_render.py`

**Interfaces:**
- Consumes: Task 4 의 `score_breakdown = {'keyword','type','case','agency','base'}`
- Produces: `hsScoreTip(score, bd) -> string` (tender-row.js, `module.exports` 에 추가)

- [ ] **Step 1: 실패하는 테스트 작성**
  - node 단위 확인(기존 `hsScoreHue` 확인과 같은 방식):
    `hsScoreTip(83.7, {keyword: 36.9, type: 25, case: 79, agency: 0, base: 88.4})` → `'적합도 83.7 = 키워드·유형 88.4 와 담은 공고 닮음 79.0 의 평균'`
    `hsScoreTip(98.6, {keyword: 30, type: 25, case: null, agency: 20, base: 78.6})` → `'적합도 98.6 = 키워드·유형 78.6 + 발주처 +20'`
    `hsScoreTip(48.6, {keyword: 30, type: 25, case: null, agency: -30, base: 78.6})` → `'적합도 48.6 = 키워드·유형 78.6 + 발주처 −30'`
    `hsScoreTip(null, null)` → `'적합도 없음'`
  - `tests/test_pages_render.py`: 상세 화면 HTML 에 `'기관', score_breakdown.agency, 10` 식의 예전 막대가 없고 `발주처` 와 `키워드·유형` 이 있다.
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**
  - `tender-row.js`: 툴팁을 `hsScoreTip` 으로. 가감점이 0 이 아니면 둘째 줄에 `발주처 +20`(가점, `hs-chip-ok`) / `발주처 −30`(감점, `hs-chip-bad`) 칩을 붙인다.
  - `dashboard.js`: `case_sort` 분기와 임베딩 점수로 다시 정렬하는 코드(`/api/embed-scores` 호출 포함)를 지운다. 서버가 준 순서와 점수를 그대로 쓴다. 정렬 선택(`적합도순`)의 키는 `relevance_score`.
  - `search.js`: `fetchEmbedScores` 호출을 지운다(서버 점수가 최종).
  - `detail.html`: 구성 막대를 `키워드·유형 (base/100)`, 사례가 있으면 `담은 공고와 닮음 (case/100)`, 가감점이 0 이 아니면 `발주처 ±n` 한 줄로.
  - `cases.html`/`cases.js`: "사례 점수순 정렬" 스위치를 "사례 점수는 적합도에 항상 절반 반영됩니다" 안내 한 줄로 바꾼다. 진단 결과의 점수 구성 문구를 새 구성으로.
- [ ] **Step 4: 통과 확인** — node 확인 4건 + `python -m pytest tests -q -p no:cacheprovider`
- [ ] **Step 5: 화면 확인** — 시험 서버(사본 DB)에서 계정 5 로 대시보드·검색·관심공고·상세를 열어, 같은 공고의 점수가 네 화면에서 같은지와 콘솔 오류가 없는지 확인하고 본 값을 보고한다.

---

### Task 6: 중점 발주처 탭

**Files:**
- Modify: `routes/tenders.py`, `templates/dashboard.html`, `static/js/dashboard.js`
- Test: `tests/test_key_agencies.py`

**Interfaces:**
- Consumes: `relevance.load_agency_adjusts`, `relevance.Scorer`, `_handled(uid)`(routes/tenders.py)
- Produces: `GET /api/dashboard/key-agencies` → `{'agencies': [등록 이름...], 'items': [공고 dict...]}`. `items` 는 대시보드 공고 dict 와 같은 모양 + `matched_agency`(걸린 등록 이름).

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_key_agencies.py`

```python
def test_lists_new_tenders_of_plus_agencies(...):       # adjust +20 발주처의 공고가 관심 키워드에 안 걸려도 나온다
def test_matches_demand_agency_too(...):
def test_excludes_minus_and_zero_agencies(...):         # adjust -30, 0 인 발주처는 안 나온다
def test_excludes_viewed_bookmarked_dismissed(...):     # 열어 본 것, 담은 것, 관심없음
def test_excludes_expired_and_result_notices(...):      # 마감 지남, status == '결과공고'
def test_keeps_tender_without_deadline(...):            # 마감일이 없는 공고는 남긴다
def test_newest_collected_first_and_limit_15(...):      # created_at 내림차순, 15건
def test_no_plus_agencies_returns_empty(...):           # {'agencies': [], 'items': []}
```

- [ ] **Step 2: 실패 확인** — 404
- [ ] **Step 3: 구현**
  - 서버: 가점(>0) 등록 이름마다 `Tender.agency` 또는 `Tender.demand_agency` 에 부분 일치(`contains`)하는 공고를 한 번의 `or_` 쿼리로. 마감 조건 `deadline_date IS NULL OR deadline_date >= now`. 수의계약도 포함한다(중점 발주처의 움직임은 놓치지 않는다는 목적).
  - 화면: 탭 순서 `전체 · 사전규격 · 나라장터 입찰 · 기타 채널 · 중점 발주처 · 비슷한 공고 · 읽은 공고`. 탭 건수 표시, 등록한 발주처가 없으면 빈 상태 문구 "발주처에 가점을 주면 그 발주처의 새 공고가 여기에 모입니다. [필터관리에서 등록]". 한 줄은 `renderTenderRow` 에 `metaHtml` 로 `발주처 +20` 칩.
  - 열어 보면 다른 탭과 같이 `markRead` 로 빠진다.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests -q -p no:cacheprovider`
- [ ] **Step 5: 화면 확인** — 시험 서버에서 사본 DB 의 계정 5 에 발주처 하나를 +20 으로 등록해 탭에 공고가 모이는지, 0건이면 왜 0건인지(그 발주처의 진행 중 공고 수)를 확인해 보고한다.

---

### Task 7: 문서와 마무리

**Files:**
- Modify: `README.md`(features), `docs/product-contract.md`(3부 상태 → 구현 완료, 22.1 의 임베딩 혼합 결정 기록), `C:\Users\USER\ClaudeDevLog\Searcher\…notes.md`

- [ ] **Step 1:** README 의 적합도·발주처 설명을 새 구조로 고친다.
- [ ] **Step 2:** 계약서 26절 결정 기록에 "임베딩 혼합(규칙 60 + 임베딩 40)은 화면 점수에서 뺐다 — 화면마다 점수가 달라지지 않게, 닮음은 사례 점수가 맡는다"를 추가하고 상태를 바꾼다.
- [ ] **Step 3:** `python -m pytest tests -q -p no:cacheprovider` 전체 통과 출력을 인용해 notes 에 기록한다.
- [ ] **Step 4:** 사용자에게 보고: 옮기는 표(Task 3 Step 5) 확인 요청, 커밋·병합·서버 재시작 승인 요청. 운영 반영 뒤 운영 DB 에 `tools/agency_adjust_migrate.py --apply` 를 돌리는 것도 사용자 승인 뒤에만.
