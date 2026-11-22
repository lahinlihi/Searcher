# 사례로 배우는 점수 (1차) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 놓친 공고를 신고하면 대시보드 어느 단계에서 빠졌는지 답하고, 북마크·신고 공고를 사례로 삼아 비슷한 공고를 찾아 주며, 그 효과를 채점으로 재고, 효과가 확인된 사용자만 대시보드 정렬을 사례 점수로 바꿀 수 있게 한다.

**Architecture:** 공고 제목 벡터는 별도 파일 `data/vectors.db`에 저장한다(수집 직후 + 일괄 채우기). 사례 점수는 "좋은 사례 중 가장 비슷한 3건의 평균 코사인 유사도"를 numpy로 계산하는 순수 함수다. 진단은 대시보드가 실제로 쓰는 SQLAlchemy 조건을 그 공고 하나에 하나씩 적용해 어디서 빠지는지 본다(조건을 파이썬으로 다시 짜지 않는다). 새 화면은 `/cases` 한 페이지와 대시보드의 새 구역 하나다.

**Tech Stack:** Flask, Flask-SQLAlchemy(sqlite), sentence-transformers `jhgan/ko-sroberta-multitask`(이미 설치·사용 중), numpy, pytest 9, 기존 Tailwind CDN + 바닐라 JS 화면.

**Spec:** `docs/product-contract.md`

## Global Constraints

- 기존 점수 함수 `scoring._score_and_type` 은 고치지 않는다. 옆에 더한다.
- 좋은 사례가 **5건 미만**인 사용자는 대시보드 응답이 이 기능 도입 전과 **완전히 같아야** 한다 (시나리오 6).
- 사례 = 그 사용자의 북마크(`bookmarks.user_id` 일치) ∪ 신고·[좋음]으로 넣은 공고. 열람 기록은 쓰지 않는다. 제외(`dismissed_tenders`)는 1차에서 점수에 쓰지 않는다.
- 사례 점수 = 좋은 사례 벡터 중 유사도 상위 **3**건의 평균. 사례가 3건 미만일 때는 있는 만큼 평균 (5건 미만이면 어차피 꺼진다).
- 진단·채점·정렬의 기준 화면은 **대시보드** (관심 키워드 필터, 제외 목록, 구역별 상위 **24**건). 검색 목록과 메일 입찰동향은 건드리지 않는다.
- 정렬 전환을 켜도 관심 키워드 필터는 유지한다. 바뀌는 것은 필터를 통과한 공고의 순서뿐.
- 채점 후보 = 정답 공고마다 그 공고 `created_at` **앞뒤 7일** 안에 적재된 공고, `status != '결과공고'`. 마감 여부는 따지지 않는다. 자기 자신은 사례에서 빼고(leave-one-out) 후보에서도 뺀다.
- 채점 숫자 두 가지: ① 전체 후보 중 등수(관심 필터를 통과 못 한 공고는 현재 방식에서 0점) ② 관심 필터 통과 후보 중 등수(정답도 통과한 것만). 전환 판정은 ②의 순위 중앙값.
- 나라장터 API 호출을 늘리지 않는다 (이 기능은 외부 API를 부르지 않는다).
- 벡터 저장이 실패해도 크롤은 성공으로 끝난다. 실패는 로그에 남긴다.
- 임베딩 모델을 못 불러오면 사례 점수 없이 기존 화면이 그대로 동작한다.
- `routes/`, `scheduler.py`, `app.py`, `database.py` 를 고친 뒤에는 CLAUDE.md 의 6단계 재시작 절차를 따른다. 크롤(09:00·13:00)·HR뉴스(07:30) 중에는 재시작·일괄 채우기를 하지 않는다.
- `hr_news` 등 뉴스레터 자료는 건드리지 않는다.
- 커밋은 사용자가 요청할 때만 한다. 아래 "Commit" 단계는 커밋 지점 표시이며, 실제 커밋 전에 사용자 확인을 받는다.

### 작업 위치

정기 크롤 뒤 `git_sync.push()` 가 작업 트리 전체를 자동 커밋·푸시한다. 반쯤 된 코드가 master 에 쓸려 들어가지 않도록 **Task 1~7 은 git worktree 의 별도 브랜치(`feature/case-scoring`)에서** 한다 (`superpowers:using-git-worktrees`). worktree 에는 `data/`(gitignore)가 없으므로 Task 1~7 의 테스트는 임시 DB만 쓴다. Task 8 은 사용자 승인을 받아 master 에 병합한 뒤 본 checkout 에서 한다.

## Review Focus

1. **벡터가 아직 없는 공고** (일괄 채우기 전, 또는 수집 직후 저장 실패) — 대시보드는 없는 것만 그 자리에서 계산해 저장하고, 모델이 없으면 사례 점수 없이 응답한다. → Task 6 `test_dashboard_missing_vectors_computed_on_the_fly`, `test_dashboard_without_model_unchanged`
2. **같은 공고를 두 번 신고·[좋음]** — 사례는 한 번만 들어가고 오류가 나지 않는다. → Task 1 `test_add_case_idempotent`
3. **북마크이면서 신고도 한 공고** — 사례 수를 두 번 세지 않는다. → Task 3 `test_good_case_ids_union_no_double_count`
4. **신고 입력이 공백·특수문자뿐이거나 매우 짧음** (`"용역"` 같은 한 단어) — 빈 입력은 400, 짧은 제목은 후보를 최대 20건만 돌려준다. → Task 4 `test_find_tender_blank_and_limit`
5. **채점할 정답이 0건이거나 후보에 벡터가 없음** — 채점은 오류 없이 "정답 0건"/"벡터 없는 후보 N건"을 돌려주고, 이 결과로는 정렬을 켤 수 없다. → Task 5 `test_evaluate_no_answers`, Task 6 `test_sort_setting_rejected_without_eval`

---

### Task 1: 테스트 기반 + 새 테이블

**Files:**
- Create: `tests/__init__.py`(빈 파일), `tests/conftest.py`, `tests/test_case_store.py`
- Modify: `database.py` (모델 4개 추가, 파일 끝 `init_db` 앞)
- Create: `case_store.py`

**Interfaces:**
- Produces (database.py 모델):
  - `CaseExample(user_id:int, tender_id:int, source:str['report'|'similar'], created_at:datetime)` — `__tablename__='case_examples'`, `UniqueConstraint('user_id','tender_id')`
  - `MissedReport(id, user_id, query:str, tender_id:int|None, verdict:str, detail:str(JSON), source_note:str|None, created_at)` — `'missed_reports'`
  - `CaseEvalRun(id, user_id, run_at:datetime, metrics:str(JSON))` — `'case_eval_runs'`
  - `CaseSortSetting(user_id PK, enabled:bool, changed_at)` — `'case_sort_settings'`
- Produces (case_store.py, 모두 현재 `db.session` 사용):
  - `add_case(user_id:int, tender_id:int, source:str) -> bool` (새로 넣었으면 True, 이미 있으면 False)
  - `remove_case(user_id:int, tender_id:int) -> bool`
  - `case_tender_ids(user_id:int) -> set[int]` (case_examples 만)
  - `save_report(user_id, query, tender_id, verdict, detail:dict, source_note=None) -> int`
  - `report_counts(user_id) -> dict[str,int]` (verdict별 건수)
  - `save_eval(user_id, metrics:dict) -> int`, `latest_eval(user_id) -> dict|None`, `eval_history(user_id, limit=20) -> list[dict]` (각 dict 에 `run_at` ISO 문자열 포함)
  - `get_sort_enabled(user_id) -> bool`, `set_sort_enabled(user_id, enabled:bool) -> None`
- Produces (tests/conftest.py): fixture `app` (임시 sqlite 파일로 `Flask` 앱 생성, `db.init_app`, `db.create_all()`; `app.py` 는 임포트하지 않는다 — 스케줄러가 뜬다), fixture `make_tender(**kw) -> Tender` (기본값: `title`, `agency='테스트기관'`, `tender_number` 고유, `source_site='나라장터 API (용역)'`, `status='일반'`, `bid_method='일반경쟁'`, `announced_date=now`, `deadline_date=now+10d`, `created_at=now`), fixture `make_user(role='user') -> User`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_case_store.py`

```python
def test_add_case_idempotent(app, make_user, make_tender):
    u, t = make_user(), make_tender(title='AI 교육 운영 용역')
    assert case_store.add_case(u.id, t.id, 'report') is True
    assert case_store.add_case(u.id, t.id, 'similar') is False
    assert case_store.case_tender_ids(u.id) == {t.id}

def test_remove_case(app, make_user, make_tender): ...      # add → remove True → ids == set() → remove 다시 False
def test_report_counts(app, make_user):                     # '순위 낮음' 2건, '수집 안 됨' 1건 저장 → {'순위 낮음': 2, '수집 안 됨': 1}
def test_eval_roundtrip(app, make_user):                    # save_eval 2회 → latest_eval 은 두 번째 metrics, eval_history 길이 2, 최신순
def test_sort_setting_default_off(app, make_user):          # get False → set True → get True → set False → get False
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_case_store.py -q` → `ModuleNotFoundError: case_store` 또는 import 오류
- [ ] **Step 3: 모델 4개(`database.py`)와 `case_store.py` 구현.** `add_case` 는 먼저 조회하고 없을 때만 넣는다(IntegrityError 에 기대지 않는다). 기존 `init_db` 의 `db.create_all()` 이 새 테이블을 만들므로 마이그레이션 목록은 건드리지 않는다.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests -q` → `5 passed`
- [ ] **Step 5: 커밋 지점** — `tests/ case_store.py database.py` "사례 점수: 테이블과 저장 함수"

---

### Task 2: 공고 제목 벡터 저장소

**Files:**
- Create: `tender_vectors.py`, `tests/test_tender_vectors.py`
- Modify: `scoring.py:14` — `_get_embed_model(block: bool = False)` (기본값 동작 그대로. `block=True` 면 잠금을 기다려 모델을 돌려준다. 로드 실패 시 None)

**Interfaces:**
- Produces:
  - `VEC_DB_PATH = <프로젝트>/data/vectors.db`, `MODEL_NAME = 'jhgan/ko-sroberta-multitask'`, `DIM = 768`
  - `connect(path: str | None = None) -> sqlite3.Connection` — 테이블 `tender_vecs(tender_id INTEGER PRIMARY KEY, model TEXT NOT NULL, vec BLOB NOT NULL)`, WAL
  - `encode(titles: list[str], encoder=None) -> np.ndarray` — shape `(n, 768)`, float32, L2 정규화. `encoder` 미지정 시 `scoring._get_embed_model(block=True)`; 모델이 None 이면 `EmbeddingUnavailable` 예외
  - `store(conn, ids: list[int], vecs: np.ndarray) -> None` — float16 으로 저장, `INSERT OR REPLACE`
  - `load(conn, ids: Iterable[int]) -> dict[int, np.ndarray]` — float32 로 복원, 없는 id 는 키 없음
  - `ensure(conn, tenders: list[Tender], encoder=None) -> dict[int, np.ndarray]` — 없는 것만 인코딩·저장 후 전부 반환. 모델이 없으면 있는 것만 반환(예외 없음)
  - `encode_missing(batch: int = 512, max_seconds: float | None = None, path=None) -> int` — 본 DB(`tenders`)에서 벡터 없는 공고를 id 순으로 채우고 채운 건수 반환. 읽기는 `hr_news.DB_PATH` 를 `mode=ro` 로 연다
  - CLI: `python -u tender_vectors.py --backfill [--max-minutes N]` — 진행 상황을 1,000건마다 출력

- [ ] **Step 1: 실패하는 테스트** — 가짜 인코더(`lambda titles: 고정 난수 행렬`)를 넘긴다. 실제 모델은 쓰지 않는다.

```python
def test_store_load_roundtrip(tmp_path):        # store 후 load → 원래 정규화 벡터와 np.allclose(atol=1e-3)
def test_load_missing_ids_absent(tmp_path):     # load([1, 999]) 의 키 == {1}
def test_ensure_encodes_only_missing(tmp_path, app, make_tender):   # 인코더 호출 횟수를 세어 이미 있는 1건은 다시 인코딩하지 않음
def test_ensure_without_model_returns_existing(tmp_path, app, make_tender, monkeypatch):
    # scoring._get_embed_model 이 None 을 돌려주게 → 예외 없이 저장돼 있던 것만 반환
def test_encode_normalized():                   # 가짜 인코더 결과의 각 행 norm == 1
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_tender_vectors.py -q` → import 오류
- [ ] **Step 3: 구현.** `encode_missing` 은 `SELECT id, title FROM tenders WHERE id > ? ORDER BY id LIMIT ?` 로 훑고, 벡터 DB 의 id 집합과 비교해 없는 것만 인코딩한다.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests -q` → 전부 통과
- [ ] **Step 5: 커밋 지점** — "사례 점수: 공고 제목 벡터 저장소"

---

### Task 3: 사례 점수 계산

**Files:**
- Create: `case_scoring.py`, `tests/test_case_scoring.py`

**Interfaces:**
- Consumes: `case_store.case_tender_ids`, `tender_vectors.connect/ensure`
- Produces:
  - `MIN_CASES = 5`, `TOP_K = 3`
  - `knn_scores(cand: np.ndarray, good: np.ndarray, k: int = TOP_K) -> tuple[np.ndarray, np.ndarray]` — (점수 0~1, 가장 비슷한 사례의 good 행 번호). `good` 이 0행이면 `ValueError`
  - `good_case_ids(user_id: int) -> set[int]` — 북마크(`Bookmark.user_id == user_id`) ∪ `case_store.case_tender_ids`
  - `score_tenders(user_id: int, tenders: list[Tender], vec_conn=None, encoder=None) -> dict[int, dict] | None` — 좋은 사례 < 5 이거나 벡터를 못 구하면 None. 값: `{'case_score': float(0~100, 소수 1자리), 'nearest_case': {'id': int, 'title': str}}`. 후보가 사례 자신이면 자신을 빼고 계산

- [ ] **Step 1: 실패하는 테스트**

```python
def test_knn_scores_top3_mean():
    good = np.eye(4, dtype=np.float32)            # 사례 4개
    cand = np.array([[1, 1, 1, 0]], np.float32) / np.sqrt(3)
    s, idx = knn_scores(cand, good)
    assert np.isclose(s[0], 1 / np.sqrt(3))       # 상위 3개 유사도 모두 1/√3
    assert idx[0] in (0, 1, 2)

def test_knn_scores_fewer_than_k():               # 사례 2개 → 2개 평균
def test_good_case_ids_union_no_double_count(app, make_user, make_tender):
    # 북마크 1 + 신고 1(같은 공고) + 신고 1(다른 공고) → 길이 2
def test_score_tenders_none_below_min_cases(app, ...):        # 사례 4건 → None
def test_score_tenders_excludes_self(app, ...):               # 사례 5건 중 하나를 후보로 넘기면 nearest_case.id 가 자기 자신이 아님
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_case_scoring.py -q`
- [ ] **Step 3: 구현.** 자기 자신 제외는 유사도 행렬에서 그 칸을 `-inf` 로 두고 상위 k 를 고르는 방식.
- [ ] **Step 4: 통과 확인** — `python -m pytest tests -q`
- [ ] **Step 5: 커밋 지점** — "사례 점수: 계산 함수"

---

### Task 4: 대시보드 조건 꺼내기 + 놓친 공고 진단

**Files:**
- Modify: `routes/tenders.py:158-238` — 구역 조건과 상위 건수를 모듈 함수·상수로 꺼낸다 (`api_dashboard` 동작은 그대로)
- Create: `missed_diagnosis.py`, `tests/test_missed_diagnosis.py`

**Interfaces:**
- Produces (routes/tenders.py):
  - `DASHBOARD_TOP_N = 24`
  - `dashboard_section_queries(now: datetime) -> dict[str, Query]` — 키 `'pre_tenders'`, `'urgent_tenders'`, `'recent_tenders'`. 지금 `api_dashboard` 안의 `sections` 그대로
  - `_apply_interest_filters`, `_title_contains`, `_agency_weights` 는 이미 모듈 함수 (그대로 사용)
- Produces (missed_diagnosis.py):
  - `VERDICTS = ('수집 안 됨', '묶임', '걸러짐', '순위 낮음', '표시 범위 안')`
  - `find_tender(q: str, limit: int = 20) -> list[Tender]` — 빈 문자열(공백 제거 후)이면 `ValueError`. 순서: `tender_number` 일치 → `url` 일치 → 제목 부분 일치(`_title_contains`, 최신 `created_at` 순)
  - `diagnose(tender: Tender, user_id: int) -> dict` — `{'verdict': str, 'reasons': list[str], 'section': str|None, 'as_of': ISO, 'rank': int|None, 'pool': int|None, 'score': float|None, 'breakdown': {'keyword','type','agency'}|None}`

진단 규칙 (작성자 판단 — 계약서 4.1 을 "그 공고가 처음 적재된 시점의 대시보드" 로 해석):
- `as_of = tender.created_at`. 구역은 `dashboard_section_queries(as_of)` 중 `query.filter(Tender.id == tender.id).count() == 1` 인 것. 셋 다 아니면 `걸러짐` + 이유(구역 조건 중 무엇에 걸렸는지: 상태·수의계약·공고일·마감일 각각을 따로 검사해 문장으로).
- `tender.is_duplicate` 이면 `묶임`.
- 제외 목록에 있으면 `걸러짐: 직접 제외함`. 제외 키워드·관심 키워드·금액은 `_apply_interest_filters` 를 조건별로 하나씩 적용해 어느 것에 걸리는지 이유로 적는다 (예: `관심 키워드 없음`, `제외 키워드 '청소'`, `금액 범위 밖`). 하나라도 걸리면 `걸러짐`.
- 다 통과하면 같은 구역·같은 `as_of` 로 관심 필터를 통과한 공고(제외 목록 뺀 것)를 `smart_sort_tenders_by_keyword_count` 로 정렬해 등수를 구한다. 등수 > 24 → `순위 낮음`, 아니면 `표시 범위 안`.

- [ ] **Step 1: 대시보드 보존 테스트 먼저** — `tests/test_dashboard_unchanged.py::test_dashboard_sections_same`: 임시 DB 에 구역별 공고를 몇 건 넣고, `dashboard_section_queries(now)` 의 각 쿼리 결과 id 집합이 꺼내기 전 조건(테스트 안에 원래 조건을 그대로 적은 것)과 같은지 본다. 그리고 `api_dashboard` 응답 키가 `{'summary','pre_tenders','urgent_tenders','recent_tenders','include_keywords','exclude_keywords'}` 그대로인지 본다 (Flask 테스트 클라이언트, `g.user` 는 `login_required` 를 통과하도록 세션 설정 — conftest 에 `login(client, user)` fixture 추가).
- [ ] **Step 2: 진단 테스트**

```python
def test_find_tender_blank_and_limit(app, make_tender):
    with pytest.raises(ValueError): find_tender('   ')
    for i in range(30): make_tender(title=f'교육 용역 {i}')
    assert len(find_tender('용역')) == 20

def test_diagnose_no_interest_keyword(...):     # 관심 키워드 ['교육'], 제목 '2027년 공공앱 운영관리 용역' → '걸러짐', reasons 에 '관심 키워드 없음'
def test_diagnose_excluded_keyword(...):        # 제외 키워드 '청소' → reasons 에 "제외 키워드 '청소'"
def test_diagnose_dismissed(...):               # DismissedTender 있음 → '걸러짐', '직접 제외함'
def test_diagnose_duplicate(...):               # is_duplicate=True → '묶임'
def test_diagnose_low_rank(...):                # 같은 구역·같은 시점에 키워드 많은 공고 30건 + 대상 1건 → '순위 낮음', rank > 24, pool == 31, breakdown 있음
def test_diagnose_in_range(...):                # 대상이 1등 → '표시 범위 안', rank == 1
def test_diagnose_result_notice(...):           # status='결과공고' → '걸러짐', 상태 이유
```

- [ ] **Step 3: 실패 확인** — `python -m pytest tests/test_missed_diagnosis.py tests/test_dashboard_unchanged.py -q`
- [ ] **Step 4: 구현** — 먼저 `routes/tenders.py` 에서 꺼내기만 하고 `test_dashboard_unchanged` 통과 확인, 그다음 `missed_diagnosis.py`.
- [ ] **Step 5: 실제 DB 대조 (읽기 전용, worktree 밖 본 checkout 의 DB)** — `git show master:routes/tenders.py` 를 scratchpad 에 두고, 지난번 `test_filters_equiv.py` 방식으로 사용자 4명의 `api_dashboard` 응답을 꺼내기 전/후로 비교. 기대 출력: `불일치 0건`.
- [ ] **Step 6: 통과 확인** — `python -m pytest tests -q`
- [ ] **Step 7: 커밋 지점** — "놓친 공고 진단 + 대시보드 조건 함수로 꺼냄"

---

### Task 5: 채점

**Files:**
- Create: `case_eval.py`, `tests/test_case_eval.py`

**Interfaces:**
- Consumes: `case_scoring.good_case_ids/knn_scores`, `tender_vectors.connect/ensure`, `routes.tenders._apply_interest_filters`, `scoring.load_user_prefs/_score_and_type`, `case_store.save_eval`
- Produces:
  - `WINDOW_DAYS = 7`
  - `evaluate(user_id: int, vec_conn=None, encoder=None, save: bool = True) -> dict`:

```python
{
  'answers': int, 'cases': int, 'missing_vectors': int,
  'all':      {'current': M, 'case': M},   # ① 전체 후보
  'filtered': {'current': M, 'case': M},   # ② 관심 필터 통과 후보 (정답도 통과한 것만)
}
# M = {'n': int, 'median': float|None, 'top100': int, 'top500': int}
```

규칙: 정답 = `good_case_ids(user_id)`. 정답마다 후보 = `created_at` 이 정답 `created_at ± 7일`, `status != '결과공고'`, 정답 자신 제외. 현재 점수 = 관심 필터 통과 시 `_score_and_type(... embed_sim=None)[0]`, 아니면 0. 사례 점수 = 그 정답을 뺀 나머지 사례로 `knn_scores`. 등수 = 1 + (점수가 정답보다 **큰** 후보 수). 남은 사례가 0건이면 그 정답은 사례 쪽 `n` 에서 뺀다. 같은 후보의 현재 점수는 정답 사이에 캐시한다.

- [ ] **Step 1: 실패하는 테스트** (가짜 인코더: 제목에 '교육' 이 있으면 축 0, '공공앱' 이면 축 1 방향 벡터 + 작은 잡음)

```python
def test_evaluate_no_answers(app, make_user):
    r = evaluate(u.id, vec_conn=..., encoder=fake, save=False)
    assert r['answers'] == 0 and r['filtered']['case']['median'] is None

def test_evaluate_case_beats_current_on_keywordless_answers(...):
    # 사례 6건 모두 '공공앱' 계열(관심 키워드 없음), 후보 100건은 '교육' 계열(키워드 있음)
    # → all.case.median < all.current.median, filtered.current.n == 0
def test_evaluate_window(...):                 # 정답과 20일 떨어진 공고는 후보에 들어가지 않음 (등수에 영향 없음)
def test_evaluate_saves_run(...):              # save=True → case_store.latest_eval(u.id) == 결과
def test_evaluate_skips_result_notices(...):   # status='결과공고' 후보는 세지 않음
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_case_eval.py -q`
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — `python -m pytest tests -q`
- [ ] **Step 5: 커밋 지점** — "사례 점수: 채점"

---

### Task 6: API + 대시보드 연결 + 수집 직후 벡터 저장

**Files:**
- Create: `routes/cases.py`, `tests/test_cases_api.py`
- Modify: `app.py:279-291` (블루프린트 등록), `routes/tenders.py` `api_dashboard` (사례 필드·정렬), `scheduler.py` `_run_crawl_job_locked` (크롤 로그 commit 직후)

**Interfaces:**
- Produces (모두 `@login_required`, 응답 JSON):
  - `POST /api/missed/lookup` `{q}` → `{'candidates': [{'id','title','source_site','created_at','tender_number'}]}`; 빈 q → 400
  - `POST /api/missed/diagnose` `{tender_id}` → `diagnose()` 결과 + `report_id`; `{q, source_note}` (DB 에 없을 때) → `{'verdict': '수집 안 됨', 'report_id'}`
  - `POST /api/cases` `{tender_id, source: 'report'|'similar'}` → `{'added': bool, 'cases': int}`
  - `DELETE /api/cases/<tender_id>` → `{'removed': bool}`
  - `GET /api/cases/similar` → `{'enabled': bool, 'cases': int, 'min_cases': 5, 'items': [...]}` — `enabled=False` 면 items 빈 목록. items: 대시보드 세 구역의 기본 조건(시점=지금)을 통과하지만 **관심 키워드 필터는 통과하지 못한** 공고(제외 키워드·금액·제외 목록은 그대로 적용), 북마크·사례 제외, `case_score` 내림차순 **상위 12건, `case_score >= 50`** (작성자 판단, 9절 위임 사항). 각 item = `Tender.to_dict()` + `case_score` + `nearest_case`
  - `GET /api/cases/eval` → `{'latest': ..., 'history': [...], 'report_counts': {...}}`; `POST /api/cases/eval` → 새로 채점해 저장 후 결과
  - `GET /api/cases/sort-setting` → `{'enabled': bool, 'allowed': bool, 'reason': str|None}`; `POST /api/cases/sort-setting` `{enabled}` — 켜기는 최신 채점의 `filtered.case.median < filtered.current.median` 이고 `filtered.case.n >= 5` 일 때만. 아니면 409 + `reason`. 끄기는 항상 허용
- `api_dashboard` 변경: `score_tenders(uid, 세 구역 후보 전체)` 가 None 이 아니면 각 item 에 `case_score`, `nearest_case` 를 붙인다. `get_sort_enabled(uid)` 이면 **필터 통과 목록을** `case_score` 내림차순(동점은 기존 정렬 순)으로 정렬한 뒤 상위 24건. None 이면 지금 코드 경로 그대로 (필드 추가 없음).
- 크롤 훅: `try: n = tender_vectors.encode_missing(max_seconds=300); print(f'[벡터] 새 공고 {n}건 저장') except Exception as e: print(f'[벡터] 저장 실패: {e}')` — 크롤 성패·`crawl_log` 상태를 바꾸지 않는다.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_dashboard_no_cases_unchanged(client, ...):        # 사례 0건 사용자 → 응답에 'case_score' 문자열이 없음, 순서가 smart_sort 와 같음
def test_dashboard_with_cases_adds_fields(client, ...):    # 사례 5건(가짜 인코더 monkeypatch) → 각 item 에 case_score, nearest_case
def test_dashboard_missing_vectors_computed_on_the_fly(...):   # 벡터 DB 비어 있어도 응답에 case_score 있고, 이후 벡터 DB 행 수 > 0
def test_dashboard_without_model_unchanged(...):           # 인코더 None → 사례 5건이어도 case 필드 없음, 200
def test_sort_on_reorders_only_filtered(...):              # 켜면 관심 키워드 없는 공고는 여전히 목록에 없음, 순서는 case_score 순
def test_sort_off_restores_order(...):                     # 켰다 끄면 끄기 전 응답과 같음 (시나리오 5)
def test_sort_setting_rejected_without_eval(...):          # 채점 없음 → 409
def test_similar_section_only_keywordless(...):            # items 의 제목에 관심 키워드가 없음, 북마크한 공고 없음
def test_similar_section_disabled_below_min(...):          # 사례 4건 → enabled False, items []
def test_dismiss_hides_from_similar(...):                  # POST /api/tenders/<id>/dismiss 후 similar 에서 사라짐 (시나리오 4)
def test_missed_not_found_records_report(...):             # 없는 번호 → '수집 안 됨', report_counts['수집 안 됨'] == 1 (시나리오 3)
def test_crawl_hook_failure_does_not_fail_crawl(...):      # encode_missing 이 예외를 던지게 monkeypatch → 훅 함수가 예외를 밖으로 내지 않음
```

크롤 훅은 `scheduler.py` 안에 `_store_new_vectors()` 라는 작은 함수로 두어 단독 테스트한다 (스케줄러 전체를 돌리지 않는다).

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_cases_api.py -q`
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — `python -m pytest tests -q`, `python -m pyflakes routes/cases.py routes/tenders.py scheduler.py case_*.py tender_vectors.py missed_diagnosis.py` → 출력 없음
- [ ] **Step 5: 커밋 지점** — "사례 점수: API·대시보드 연결·수집 직후 벡터 저장"

---

### Task 7: 화면

**Files:**
- Create: `templates/cases.html`, `static/js/cases.js`
- Modify: `routes/pages.py` (`/cases` 페이지, `@login_required`), `templates/base.html:71-160` (데스크톱·모바일 메뉴 세 곳에 "놓친 공고" 링크, `/bookmarks` 다음), `templates/dashboard.html` (`section-recent` 다음에 `section-similar` 구역), `static/js/dashboard.js` (새 구역 렌더링, 카드에 사례 점수 표시)

**화면 내용:**
- `/cases` 세 부분, 위에서 아래로:
  1. **놓친 공고 신고** — 입력 + [찾기] → 후보 목록 → 하나 고르면 판정 카드 (계약서 4.1 의 화면 예시 형식: 판정, 등수/모수, 점수 내역, 이유 목록) + [정답 목록에 넣기]. 후보가 없으면 "수집 안 됨" 과 출처 메모 입력 + [기록].
  2. **채점** — 최신 결과 표 (행: 현재 방식 / 사례 방식, 열: 순위 중앙값·100등 안·500등 안·n, ①②를 두 표로), [지금 채점], 지난 결과 목록(날짜·② 중앙값 두 개), 신고 판정별 건수.
  3. **사례 점수로 정렬** — 켜기/끄기 스위치. `allowed=False` 면 비활성화하고 `reason` 표시.
- 대시보드 새 구역 "키워드엔 없지만 비슷한 공고" — 기존 카드 렌더러(`renderTenderCard`)를 재사용하고, 카드 아래 "비슷한 사례: {nearest_case.title}" 한 줄과 [좋음] [아님] 버튼. [좋음] = `POST /api/cases {source:'similar'}` 후 카드 제거, [아님] = 기존 `dismissTender()`. `enabled=False` 면 "사례를 5건 이상 모으면 켜집니다 (지금 N건)" 문구와 `/cases` 링크.
- 기존 카드: 응답에 `case_score` 가 있을 때만 점수 옆에 "사례 {case_score}" 배지 + 마우스를 올리면 nearest_case 제목.
- 모바일: 새 구역도 기존 구역처럼 `-mobile` 목록을 둔다. 테스트 화면 폭 375px 에서 가로 스크롤이 없어야 한다.

- [ ] **Step 1: 페이지 라우트 테스트** — `tests/test_cases_api.py::test_cases_page_renders`: 로그인 후 `GET /cases` 200, 본문에 `놓친 공고 신고`, `채점`, `사례 점수로 정렬`
- [ ] **Step 2: 구현**
- [ ] **Step 3: 브라우저 확인 (worktree 에서 임시 포트로 띄운 앱, 임시 DB)** — 내장 브라우저로 `/cases`, `/` 를 열어: 신고 → 판정 카드 표시, [정답 목록에 넣기] 후 사례 수 증가, 새 구역 [좋음]/[아님] 동작, 콘솔 오류 0건, 375px 폭 확인. 임시 서버는 확인 후 내린다.
- [ ] **Step 4: 전체 테스트** — `python -m pytest tests -q`
- [ ] **Step 5: 커밋 지점** — "사례 점수: 화면"

---

### Task 8: 실제 데이터 적용 (master 병합 후, 본 checkout)

사용자 승인을 받아 `feature/case-scoring` 을 master 에 병합한 뒤 진행한다.

- [ ] **Step 1: 시각 확인** — 07:30·09:00·13:00 전후 30분이 아니고, `crawl_logs` 최신 상태가 `running` 이 아님을 CLAUDE.md Step 1 명령으로 확인
- [ ] **Step 2: 서버 재시작** — CLAUDE.md 6단계 절차 그대로 (새 테이블은 `create_all` 이 만든다). Step 5 확인: `python -c "import routes.cases, case_scoring; print('ok')"` + 실행 중 서버에 `GET /api/cases/similar` → 401 (등록됨)
- [ ] **Step 3: 벡터 일괄 채우기 (백그라운드)** — `Start-Process python -ArgumentList "-u","tender_vectors.py","--backfill" -RedirectStandardOutput data\..\backfill_vectors.log -WindowStyle Hidden`. 예상 약 27분(측정: 24,542건 268초). 끝나면 `SELECT COUNT(*) FROM tender_vecs` 가 `tenders` 건수와 같은지 확인
- [ ] **Step 4: 실제 채점 (계정 5번, 읽기 전용 아님 — 결과 1행 저장)** — `python -c "... case_eval.evaluate(5)"` 출력 인용. 기대: `filtered.case.median < filtered.current.median` (시나리오 7). 아니면 멈추고 사용자에게 보고 — 정렬 전환은 켜지지 않는 상태가 정상
- [ ] **Step 5: 시나리오 1~6 확인** — `data/tenders.db` 를 scratchpad 에 복사해 그 사본으로 Flask 테스트 클라이언트를 돌린다 (운영 DB 에 시험 신고를 남기지 않는다). 시나리오 1 "2026년도 IT역량교육과정 위탁운영", 시나리오 2 "2027년 공공앱 운영관리 용역" 의 실제 판정·등수를 인용
- [ ] **Step 6: 다음 크롤 후 확인** — 13:00 또는 09:00 크롤 로그에 `[벡터] 새 공고 N건 저장` 이 찍히고, 그날 새 공고가 `tender_vecs` 에 있는지
- [ ] **Step 7: README·노트** — `README.md` 의 features(놓친 공고 신고·사례 점수·채점·비슷한 공고 구역, 진입점 `/cases`)와 project-structure(`case_store.py`, `case_scoring.py`, `case_eval.py`, `missed_diagnosis.py`, `tender_vectors.py`, `routes/cases.py`, `tests/`, `data/vectors.db`) 갱신. `.notes.md` 에 결정과 실제 수치 기록
- [ ] **Step 8: 사용자 보고** — 채점 숫자, 시나리오 결과, 확인하지 못한 것(로그인한 운영 화면 클릭 확인은 사용자 몫)
