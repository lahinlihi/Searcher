# 운영 로그 (6부) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서버에서 일어나는 모든 작업이 시각·수준·출처와 함께 남고, 오류는 묶여서 화면에서 보고 해결 메모를 달 수 있으며, 서버가 꺼지면 스스로 다시 뜨고 알린다.

**Architecture:** 새 패키지 `opslog/` 가 표준 `logging` 을 설정해 날짜별 파일 세 개(`logs/app.log`, `logs/app.jsonl`, `logs/error.log`)에 쓴다. 기존 `print()` 424곳은 고치지 않고 표준 출력을 로거로 받아 넘긴다. 오류 묶음·감사 기록·작업 실행 기록은 본 DB 와 분리한 `data/ops.db`(sqlite, WAL)에 둔다. 서버 밖의 `tools/watchdog.py` 가 작업 스케줄러로 5분마다 돌며 생존 신호를 본다.

**Tech Stack:** Python 3.14 표준 라이브러리(`logging`, `logging.handlers`, `contextvars`, `faulthandler`, `sqlite3`), Flask, 기존 `newsletter._send_one`(알림 메일), Windows 작업 스케줄러(`schtasks`). 새 의존성 없음.

**Spec:** `docs/product-contract.md` 6부 (41~47절)

## Global Constraints

- 로그 쓰기가 실패해도 본 작업은 계속된다. `opslog` 의 공개 함수는 예외를 밖으로 내지 않는다.
- 기록 금지: 비밀번호, API 키, 세션 쿠키, `Authorization`/`Cookie` 헤더, 메일 본문, 메모·회의 내용. 메일 주소는 `ab***@domain` 으로 가린다. 키 이름에 `password|secret|token|key|cookie|authorization` 이 들어간 값은 `***` 로 바꾼다.
- 기존 `print()` 를 일괄 치환하지 않는다 (프로젝트 규칙 "안정 동작 코드 수정 금지").
- 보관: 일반 로그 30일, `error.log`·`error_events`·`audit_log` 180일. (사용자 미응답 — 설계안의 기본값)
- 알림: 관리자 메일(`settings.json` 의 `ops.alert_email`, 없으면 알림을 보내지 않고 WARNING 한 줄). 같은 지문의 알림은 하루 한 번. (사용자 미응답 — 기본값)
- 서버가 꺼지면 감시가 자동으로 다시 띄우고 알린다. (사용자 미응답 — 권고안)
- 시각은 KST, ISO 8601, 밀리초까지.
- `data/ops.db` 는 `data/tenders.db` 와 다른 파일이다. 테스트는 `opslog.store.DB_PATH` 를 tmp 로 바꿔 운영 파일을 건드리지 않는다.
- 로그 화면과 API 는 `admin_required`.
- 서버 코드(`app.py`, `scheduler.py`, `routes/*.py`)를 바꾼 작업은 CLAUDE.md 의 6단계 재시작 후 **실행 중인 서버**에서 확인한다. 단 3단계의 서버 시작은 Task 8 이후 `start_server.vbs` 를 WMI 로 실행하는 방식을 쓴다.
- 커밋은 사용자가 요청할 때만. 작업은 워크트리 `.claude/worktrees/ops-logging` 에서 한다 (master 는 크롤 뒤 자동 커밋된다).

## Review Focus

- 로그 디렉터리에 쓸 수 없을 때(권한, 디스크 가득) — 서버는 뜨고 요청은 정상 응답해야 한다. → Task 1
- 받아 넘긴 표준 출력 안에서 다시 로그가 표준 출력으로 나가 무한 반복되는 경우 — 한 번만 기록돼야 한다. → Task 2
- 같은 오류가 초당 수백 번 날 때 — `error_events` 는 한 행이고 횟수만 오르며, 알림 메일은 한 통이어야 한다. → Task 4, Task 9
- 요청 ID 가 스레드 사이에서 섞이는 경우(waitress 스레드 8개) — 각 요청의 줄에 자기 ID 만 찍혀야 한다. → Task 3
- 감시 스크립트가 서버 기동 중(임베딩 로딩으로 신호가 아직 없음)에 또 띄우는 경우 — 프로세스가 살아 있으면 띄우지 않는다. → Task 8

---

### Task 1: 로그 기반 — 설정, 파일 세 개, 순환과 보관

**Files:**
- Create: `opslog/__init__.py`, `opslog/setup.py`, `opslog/redact.py`
- Test: `tests/test_opslog_setup.py`

**Interfaces:**
- Produces:
  - `opslog.setup.configure(log_dir: str = 'logs', level: int = logging.INFO) -> bool` — 여러 번 불러도 핸들러가 한 벌만 붙는다. 디렉터리를 만들 수 없으면 `False` 를 돌려주고 stderr 핸들러만 붙인다.
  - `opslog.get_logger(name: str) -> logging.Logger` (`hs.<name>`)
  - `opslog.event(logger, level: int, event: str, msg: str = '', **fields) -> None` — `fields` 는 JSON 줄의 `extra` 로 들어간다.
  - `opslog.redact.scrub(value) -> value` (dict/list 재귀), `opslog.redact.mask_email(s: str) -> str`
  - `opslog.setup.purge_old(log_dir: str, now: datetime | None = None) -> int` — 지운 파일 수
  - 상수 `KEEP_DAYS = 30`, `KEEP_DAYS_ERROR = 180`
  - JSON 줄의 키: `ts, level, logger, event, msg, request_id, run_id, user_id, extra, exc`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_three_files_and_json_shape(tmp_path):
    assert setup.configure(str(tmp_path)) is True
    log = opslog.get_logger('t')
    opslog.event(log, logging.INFO, 'crawl.done', '크롤 완료', count=3)
    log.error('터짐', exc_info=ValueError('x'))
    _flush()
    rec = [json.loads(l) for l in (tmp_path / 'app.jsonl').read_text('utf-8').splitlines()]
    assert rec[0]['event'] == 'crawl.done' and rec[0]['extra'] == {'count': 3} and rec[0]['level'] == 'INFO'
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+09:00', rec[0]['ts'])
    assert 'ValueError' in rec[1]['exc']
    assert '크롤 완료' in (tmp_path / 'app.log').read_text('utf-8')
    err = (tmp_path / 'error.log').read_text('utf-8')
    assert '터짐' in err and '크롤 완료' not in err          # WARNING 이상만

def test_configure_twice_does_not_duplicate_lines(tmp_path): ...   # 한 줄만
def test_restart_appends_instead_of_overwriting(tmp_path): ...     # 핸들러 닫고 다시 configure → 앞 줄이 남아 있다
def test_unwritable_dir_returns_false_and_does_not_raise(tmp_path, monkeypatch): ...  # os.makedirs 가 OSError
def test_secrets_are_scrubbed():
    assert redact.scrub({'password': 'p', 'api_key': 'k', 'n': 1, 'a': {'Cookie': 'c'}}) == {'password': '***', 'api_key': '***', 'n': 1, 'a': {'Cookie': '***'}}
    assert redact.mask_email('someone@example.com') == 'so***@example.com'
def test_purge_keeps_30_days_and_error_180(tmp_path): ...          # app.log.2026-10-20 삭제, error.log.2026-10-20 유지, error.log.2026-05-01 삭제
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_opslog_setup.py -q` → `ModuleNotFoundError: opslog`
- [ ] **Step 3: 구현** — `TimedRotatingFileHandler(when='midnight', encoding='utf-8', delay=True)` 세 개. JSON 포매터는 `extra` 를 `scrub` 에 통과시킨다. 자동 `backupCount` 는 쓰지 않고 `purge_old` 가 파일 이름의 날짜로 지운다(파일마다 기한이 다르다).
- [ ] **Step 4: 통과 확인** — 같은 명령 → 6 passed
- [ ] **Step 5: Commit** (사용자 요청 시)

### Task 2: 표준 출력 받아 넘기기, 시작·종료 기록, 잡히지 않은 예외

**Files:**
- Create: `opslog/capture.py`, `opslog/lifecycle.py`
- Modify: `app.py:330-345` (`__main__` 맨 앞에서 `configure` → `capture.install` → `lifecycle.install`)
- Test: `tests/test_opslog_capture.py`

**Interfaces:**
- Consumes: Task 1 의 `configure`, `get_logger`, `event`
- Produces:
  - `opslog.capture.install() -> None` / `uninstall() -> None` — `sys.stdout`→`hs.stdout` INFO, `sys.stderr`→`hs.stderr` WARNING. 줄 단위. 원래 스트림에도 그대로 쓴다(`server_restart.log` 가 계속 채워진다).
  - 받아 넘긴 줄의 수준 추정: 줄에 `실패|오류|Error|Traceback|Exception` 이 있으면 ERROR, `경고|WARNING|무시` 면 WARNING.
  - `opslog.lifecycle.install(log_dir: str) -> dict` — 반환 `{'previous_exit': 'clean'|'unclean'|'first', 'version': <git 짧은 해시 또는 'unknown'>, 'pid': int}`. `logs/server.state`(JSON: pid, started_at, clean_exit) 를 쓰고 `atexit` 에서 `clean_exit=true` 로 바꾼다. `sys.excepthook`, `threading.excepthook` 을 걸어 CRITICAL 로 스택을 남긴다. `faulthandler.enable(file=<logs/fault.log>)`.
  - 사건 이름: `server.start`, `server.stop`, `server.uncaught`, `thread.uncaught`

- [ ] **Step 1: 실패하는 테스트**

```python
def test_print_lands_in_log_with_timestamp_and_still_reaches_stdout(tmp_path, capsys): ...
    # print('[크롤] 완료') → app.jsonl 에 logger 'hs.stdout', msg '[크롤] 완료'; capsys 에도 그대로
def test_error_looking_print_becomes_error(tmp_path): ...            # print('[git] push 실패: x') → level ERROR
def test_no_feedback_loop(tmp_path): ...                             # stderr 핸들러가 붙어 있어도 한 줄은 한 번만 기록
def test_previous_exit_states(tmp_path):
    assert lifecycle.install(str(tmp_path))['previous_exit'] == 'first'
    # atexit 을 부르지 않고 다시 install → 'unclean'; lifecycle.mark_clean() 뒤 install → 'clean'
def test_thread_exception_is_logged_critical(tmp_path): ...          # 스레드에서 raise → app.jsonl 에 event 'thread.uncaught', exc 에 스택
```

- [ ] **Step 2: 실패 확인** → 5 failed
- [ ] **Step 3: 구현** — 재진입 방지는 스레드 로컬 깃발. 파일 핸들러는 원래 스트림을 쓰지 않으므로 반복이 생기는 경로는 stderr 폴백 핸들러뿐이다: 그 핸들러는 `sys.__stderr__` 에 쓴다.
- [ ] **Step 4: 통과 확인** → 5 passed; 전체 `python -m pytest tests -q`
- [ ] **Step 5: 운영 확인** — 재시작 후 `logs/app.log` 에 `server.start` 줄(버전·PID·`previous_exit`)과 기존 `[스케줄러]` 출력이 시각과 함께 있다.
- [ ] **Step 6: Commit** (요청 시)

### Task 3: 요청 로그와 요청 ID

**Files:**
- Create: `opslog/context.py`, `opslog/web.py`
- Modify: `app.py` (`opslog.web.init_app(app)` 한 줄, `internal_error` 는 Task 4)
- Test: `tests/test_opslog_web.py`

**Interfaces:**
- Produces:
  - `opslog.context.request_id: ContextVar[str | None]`, `run_id: ContextVar[str | None]`, `user_id: ContextVar[int | None]`; `opslog.context.new_id() -> str` (12자 hex). JSON 포매터가 이 값을 찍는다(Task 1 의 포매터에 연결).
  - `opslog.web.init_app(app) -> None` — `before_request` 에서 ID 발급, `after_request` 에서 `http.request` 한 줄(`method, path, status, ms, user_id, ip`)과 응답 헤더 `X-Request-Id`. `/static/` 과 `/favicon.ico` 는 기록하지 않는다. 쿼리 문자열은 기록하지 않는다. 500 이상은 ERROR, 400~499 는 INFO(404·401 포함), 1초 넘으면 WARNING `http.slow`.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_request_line_fields(app, client, logdir):
    r = client.get('/api/memos/unread-count?secret=abc')
    rec = _last(logdir, 'http.request')
    assert rec['extra']['path'] == '/api/memos/unread-count' and rec['extra']['status'] == 401 and 'abc' not in json.dumps(rec)
    assert r.headers['X-Request-Id'] == rec['request_id'] and len(rec['request_id']) == 12
def test_static_is_not_logged(app, client, logdir): ...
def test_lines_inside_a_request_carry_its_id(app, client, logdir): ...   # 뷰 안의 print 가 같은 request_id
def test_ids_do_not_leak_between_threads(app, logdir): ...              # 스레드 8개 동시 요청, 각 줄의 id 가 자기 응답 헤더와 같다
def test_logged_in_user_id_is_recorded(app, client, login, make_user, logdir): ...
```

- [ ] **Step 2~4:** 실패 확인 → 구현 → 5 passed
- [ ] **Step 5: 운영 확인** — 재시작 후 `curl -i http://localhost:5002/api/memos/unread-count` 의 `X-Request-Id` 값으로 `logs/app.jsonl` 에서 그 줄을 찾는다.
- [ ] **Step 6: Commit** (요청 시)

### Task 4: ops.db 와 오류 묶기

**Files:**
- Create: `opslog/store.py`, `opslog/errors.py`
- Modify: `app.py:207-210` (`internal_error`), `opslog/web.py`(잡히지 않은 요청 예외), `opslog/lifecycle.py`(훅에서 `capture` 호출)
- Test: `tests/test_opslog_errors.py`

**Interfaces:**
- Produces:
  - `opslog.store.DB_PATH = 'data/ops.db'`; `opslog.store.connect() -> sqlite3.Connection` (WAL, `row_factory=Row`, 스키마 보장, `timeout=5`)
  - 표 `error_events(id, fingerprint UNIQUE, exc_type, location, message, traceback, context JSON, count, first_seen, last_seen, status, note, resolved_at, last_alert_date)` — `status ∈ new|seen|resolved|regressed`
  - `opslog.errors.fingerprint(exc: BaseException) -> str` — 예외 종류 + 프로젝트 안 가장 깊은 프레임의 `파일:함수`(줄 번호 제외 — 코드가 밀려도 같은 묶음)의 sha1 앞 16자
  - `opslog.errors.capture(exc, *, where: str = '', **context) -> int | None` — 반환 event id. 같은 지문이면 `count+1`, `last_seen`·`traceback`·`context` 갱신. `resolved` 였으면 `regressed`. `context` 는 `scrub` 후 저장. 메시지는 500자, 스택은 20000자에서 자른다.
  - `opslog.errors.set_status(event_id: int, status: str, note: str | None = None) -> bool`
  - `opslog.errors.listing(status: str | None = None, limit: int = 100) -> list[dict]`, `opslog.errors.get(event_id) -> dict | None`
  - 500 응답 본문: `{'error': 'Internal server error', 'request_id': <id>}`

- [ ] **Step 1: 실패하는 테스트**

```python
def test_same_error_is_one_row_with_count(ops):
    for _ in range(300): errors.capture(_raise_value_error(), where='t')
    rows = errors.listing()
    assert len(rows) == 1 and rows[0]['count'] == 300 and rows[0]['status'] == 'new'
def test_different_location_is_a_different_group(ops): ...
def test_resolved_then_recurs_becomes_regressed_and_keeps_note(ops): ...
def test_context_is_scrubbed(ops): ...                 # capture(e, password='p') → 저장본에 'p' 없음
def test_capture_never_raises_when_db_is_broken(ops, monkeypatch): ...   # connect 가 OperationalError → None
def test_unhandled_view_exception_is_captured_with_request_id(app, client, ops, logdir):
    r = client.get('/__boom')                          # 테스트에서 등록한 raise 뷰
    assert r.status_code == 500 and r.get_json()['request_id']
    ev = errors.listing()[0]
    assert ev['exc_type'] == 'RuntimeError' and json.loads(ev['context'])['request_id'] == r.get_json()['request_id']
```

- [ ] **Step 2~4:** 실패 확인 → 구현 → 6 passed
- [ ] **Step 5: Commit** (요청 시)

### Task 5: 작업 실행 기록 확대

**Files:**
- Create: `opslog/jobs.py`
- Modify: `scheduler.py` (크롤·원격 동기화·git_sync·벡터 저장·보충 실행 진입점), `newsletter.py` (`send_all`, `send_test`), `tender_brief.py` (분류 실행), `routes/analysis.py`(문서 분석 시작점)
- Test: `tests/test_opslog_jobs.py`

**Interfaces:**
- Consumes: `opslog.context.run_id`, `opslog.errors.capture`, `opslog.store.connect`
- Produces:
  - 표 `job_runs_all(id, run_id, job, trigger, started_at, finished_at, ms, status, counts JSON, detail, error_event_id)` — `status ∈ running|ok|partial|empty|failed`, `trigger ∈ schedule|manual|catchup`
  - `opslog.jobs.track(job: str, trigger: str = 'schedule')` — 컨텍스트 매니저. `with track('crawl') as run:` 안에서 `run.count(new=413, found=9751)`, `run.status('partial', '3개 사이트 실패')`. 블록 안에서 예외가 나면 `failed` 로 닫고 `errors.capture` 후 **다시 던진다**. 블록 동안 `run_id` 가 설정된다.
  - `opslog.jobs.recent(job: str | None = None, limit: int = 100) -> list[dict]`
  - `opslog.jobs.expected_today(now) -> list[dict]` — `[{job, due, state: 'done'|'missed'|'pending'|'failed'}]`. 기준: `hr_news` 07:30, `crawl` 09:00·13:00(평일·주말 구분은 `scheduler.py` 의 등록 시각을 읽는다).
  - 기존 `scheduler.job_run_start/finish/job_runs_on` 과 `hr_news` 쪽 `job_runs` 표는 그대로 둔다(보충 실행 판정이 쓰고 있다).
  - 크롤: 사이트 결과가 `success=False` 이거나 첫 페이지 0건이면 그 사이트 이름을 `detail` 에 넣고 `partial`.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_track_records_ok_with_counts_and_duration(ops): ...
def test_track_marks_failed_captures_error_and_reraises(ops):
    with pytest.raises(ZeroDivisionError):
        with jobs.track('crawl'): 1 / 0
    r = jobs.recent()[0]
    assert r['status'] == 'failed' and r['error_event_id'] == errors.listing()[0]['id']
def test_lines_inside_a_job_carry_run_id(ops, logdir): ...
def test_expected_today_reports_missed(ops): ...       # 16:00 인데 crawl 실행 기록 없음 → 09:00, 13:00 'missed'
def test_crawl_with_zero_count_site_is_partial(ops): ...
```

- [ ] **Step 2~4:** 실패 확인 → 구현 → 5 passed; 전체 테스트
- [ ] **Step 5: 운영 확인** — 재시작 후 수동 크롤 대신(같은 API 키를 정기 크롤이 쓴다) 다음 정기 크롤이 끝난 뒤 `job_runs_all` 에 `crawl` 한 행과 그 `run_id` 로 찍힌 로그 줄을 확인한다.
- [ ] **Step 6: Commit** (요청 시)

### Task 6: 감사 로그

**Files:**
- Create: `opslog/audit.py`
- Modify: `routes/auth*.py` 또는 로그인 처리 위치(로그인 성공·실패·로그아웃), `routes/settings.py`(설정 저장), `routes/newsletter.py`(발송, 구독자 추가·삭제, 메일 설정 저장), 회원 관리 라우트(권한 변경·삭제), `routes/reasons.py`·`routes/filters.py` 는 제외(사용자 자신의 일상 조작)
- Test: `tests/test_opslog_audit.py`

**Interfaces:**
- Produces:
  - 표 `audit_log(id, ts, actor_id, actor_name, action, target, detail JSON, ip, request_id)`
  - `opslog.audit.record(action: str, target: str = '', **detail) -> None` — 행위자는 `flask_login.current_user`, 요청 밖이면 `system`
  - `opslog.audit.recent(action_prefix: str | None = None, limit: int = 200) -> list[dict]`
  - 행위 이름: `auth.login`, `auth.login_failed`, `auth.logout`, `user.role_changed`, `user.deleted`, `settings.saved`, `newsletter.sent`, `newsletter.test_sent`, `newsletter.subscriber_added`, `newsletter.subscriber_deleted`, `newsletter.mail_settings_saved`
  - `settings.saved` 의 `detail` 은 **바뀐 키 이름만** 담는다(값은 담지 않는다).

- [ ] **Step 1: 실패하는 테스트**

```python
def test_failed_logins_are_recorded_without_password(app, client, make_user, ops):
    u = make_user()
    for _ in range(5): client.post('/login', data={'username': u.username, 'password': 'WRONG-pw-123'})
    rows = audit.recent('auth.login_failed')
    assert len(rows) == 5 and 'WRONG-pw-123' not in json.dumps(rows, ensure_ascii=False)
def test_settings_save_records_changed_keys_only(app, client, login, make_user, ops): ...
def test_subscriber_delete_is_recorded_with_masked_email(app, client, login, make_user, ops): ...   # 'wr***@example.com'
def test_record_outside_request_uses_system(ops): ...
```

- [ ] **Step 2~4:** 실패 확인(먼저 `grep -n "def login" routes/*.py auth.py` 로 로그인 처리 위치를 찾아 테스트의 경로·필드 이름을 맞춘다) → 구현 → 4 passed
- [ ] **Step 5: Commit** (요청 시)

### Task 7: 생존 신호와 정리 작업

**Files:**
- Create: `opslog/heartbeat.py`
- Modify: `scheduler.py` (APScheduler 에 1분 간격 `heartbeat.beat`, 매일 03:30 `opslog.maintenance`)
- Test: `tests/test_opslog_heartbeat.py`

**Interfaces:**
- Produces:
  - `opslog.heartbeat.beat(log_dir: str = 'logs') -> None` — `logs/heartbeat` 에 JSON `{ts, pid, version}` 을 임시 파일에 쓰고 `os.replace`
  - `opslog.heartbeat.read(log_dir) -> dict | None`; `opslog.heartbeat.age_seconds(log_dir, now=None) -> float | None`
  - `opslog.maintenance(now=None) -> dict` — `purge_old` + `error_events`/`audit_log` 180일, `job_runs_all` 180일 삭제. 반환 `{files, errors, audit, jobs}`

- [ ] **Step 1: 실패하는 테스트** — `beat` 후 `age_seconds < 2`; 파일 없으면 `None`; 깨진 파일이면 `None`(예외 없음); `maintenance` 가 181일 된 `resolved` 오류는 지우고 `new` 는 남긴다(해결 안 된 오류는 기한이 지나도 남긴다).
- [ ] **Step 2~4:** 실패 확인 → 구현 → 4 passed
- [ ] **Step 5: Commit** (요청 시)

### Task 8: 감시 스크립트와 알림

**Files:**
- Create: `tools/watchdog.py`, `opslog/alerts.py`, `install_watchdog.bat`
- Modify: `opslog/errors.py`(새 오류·다시 생긴 오류에서 `alerts.notify`), `opslog/jobs.py`(실패에서 `alerts.notify`), `CLAUDE.md`(재시작 3단계, 사용자 승인 후)
- Test: `tests/test_opslog_watchdog.py`, `tests/test_opslog_alerts.py`

**Interfaces:**
- Consumes: `heartbeat.age_seconds`, `jobs.expected_today`, `newsletter._send_one(cfg, to_email, subject, html)`, `newsletter.smtp_config()`
- Produces:
  - `opslog.alerts.notify(kind: str, key: str, subject: str, body: str) -> bool` — `kind ∈ error|job|server`. `(kind, key, 날짜)` 가 이미 보냈으면 `False`. 표 `alerts_sent(kind, key, day, sent_at)`. 수신 주소는 `settings.json` 의 `ops.alert_email`; 없으면 보내지 않고 WARNING `alert.no_recipient`. 제목은 `[High-Search 운영] …`.
  - `tools/watchdog.py` 의 `check(now, *, is_running: Callable[[], bool], heartbeat_age: float | None, start: Callable[[], None], notify) -> str` — 반환 `'ok' | 'starting' | 'restarted' | 'hung'`.
    - 프로세스 없음 → `logs/watchdog.log` 에 기록, `start()`, `notify('server', 'down', …)`, `'restarted'`
    - 프로세스 있음, 신호 없음/3분 미만 → `'ok'`
    - 프로세스 있음, 신호가 10분 넘게 끊김, 프로세스 시작 후 5분 지남 → `'hung'` 알림만(자동 종료는 하지 않는다 — 크롤 중일 수 있다)
    - 프로세스 있음, 시작 후 5분 이내 → `'starting'`
    - 그 뒤 `jobs.expected_today` 의 `missed`·`failed` 를 `notify('job', …)`
  - `start()` 의 실제 구현: `wscript.exe start_server.vbs` (vbs 가 재시도와 중복 실행 방지를 이미 한다)
  - `install_watchdog.bat`: `schtasks /Create /TN "HighSearch Watchdog" /SC MINUTE /MO 5 /TR "C:\Python314\pythonw.exe C:\Users\USER\Searcher\tools\watchdog.py" /F` — 사용자가 직접 실행한다.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_dead_server_is_restarted_and_notified_once(ops): ...        # check 두 번 → start 는 두 번 불려도 notify 는 True, False
def test_server_still_booting_is_left_alone(ops): ...                # 시작 2분, 신호 없음 → 'starting', start 안 불림
def test_stale_heartbeat_alerts_but_does_not_kill(ops): ...
def test_missed_job_is_alerted(ops): ...
def test_notify_dedupes_per_day_and_survives_smtp_failure(ops, monkeypatch): ...   # _send_one 이 예외 → False, 예외 없음
def test_no_recipient_configured_logs_warning(ops, logdir): ...
def test_new_error_alerts_once_for_300_occurrences(ops, monkeypatch): ...
```

- [ ] **Step 2~4:** 실패 확인 → 구현 → 7 passed
- [ ] **Step 5: 운영 확인 (사용자와 함께)** — 사용자가 `install_watchdog.bat` 실행 → 크롤이 없는 시간에 서버 프로세스를 죽인다 → 10분 안에 다시 뜨는지, `logs/watchdog.log` 와 새 서버의 `server.start`(`previous_exit: unclean`), 알림 메일을 확인한다. 알림 주소는 사용자가 정한 주소만 쓴다.
- [ ] **Step 6: Commit** (요청 시)

### Task 9: 로그 화면

**Files:**
- Create: `routes/ops.py`, `static/js/ops_logs.js`
- Modify: `templates/logs.html`(탭: 한눈에 · 오류 · 작업 · 전체 로그 · 감사 · 크롤 — 기존 크롤 기록 표는 '크롤' 탭으로 그대로), `app.py`(블루프린트 등록), `static/css/hs-theme.css`(필요한 만큼만)
- Test: `tests/test_ops_api.py`

**Interfaces:**
- Consumes: `errors.listing/get/set_status`, `jobs.recent/expected_today`, `audit.recent`, `heartbeat.read`, `logs/app.jsonl`
- Produces (모두 `admin_required`):
  - `GET /api/ops/summary` → `{server: {started_at, version, pid, previous_exit, heartbeat_age}, jobs_today: [...], open_errors: int}`
  - `GET /api/ops/errors?status=` → 목록; `GET /api/ops/errors/<id>` → 상세 + `related`(같은 `request_id`/`run_id` 의 로그 줄 최대 50개)
  - `POST /api/ops/errors/<id>` `{status, note}` → `{ok: true}`; `status` 가 목록 밖이면 400
  - `GET /api/ops/jobs?job=`; `GET /api/ops/audit?action=`
  - `GET /api/ops/logs?date=YYYY-MM-DD&level=&logger=&q=&id=&limit=` → 그날의 `app.jsonl` 을 뒤에서부터 읽어 거른다. `limit` 최대 500. `date` 는 정규식 검증 후 파일 이름을 만든다(경로 탈출 방지).
  - 화면 문구는 한국어, 시각은 `MM-DD HH:mm:ss`.

- [ ] **Step 1: 실패하는 테스트**

```python
def test_ops_api_requires_admin(app, client, login, make_user): ...            # user·moderator → 403
def test_error_flow_resolve_and_regress(app, client, login, make_user, ops): ...  # 계약서 시나리오 1
def test_error_detail_includes_related_lines(app, client, login, make_user, ops, logdir): ...
def test_logs_filter_by_level_and_request_id(app, client, login, make_user, logdir): ...
def test_logs_rejects_bad_date(app, client, login, make_user):
    for bad in ('../../data/settings', '2026-13-99', 'abc'):
        assert client.get('/api/ops/logs?date=' + bad).status_code == 400
def test_bad_status_is_400(app, client, login, make_user, ops): ...
```

- [ ] **Step 2~4:** 실패 확인 → 구현 → 6 passed
- [ ] **Step 5: 화면 확인** — 시험 서버(운영 DB 사본, 127.0.0.1)에서 다섯 탭을 열어 375px 폭에서 가로 넘침이 없는지, 오류 상세에서 상태를 바꾸고 메모를 저장하는지 본다. 운영 화면은 로그인할 수 없으므로 사용자에게 확인을 부탁한다.
- [ ] **Step 6: Commit** (요청 시)

### Task 10: 삼킨 예외 정리, 런북, 문서

**Files:**
- Modify: `except … pass` 14곳과 정기 작업 경로(`scheduler.py`, `git_sync.py`, `hr_news.py`, `newsletter.py`, `tender_brief.py`)의 `except Exception as e: print(...)` — `opslog.errors.capture(e, where='…')` 를 **추가**한다(기존 print 와 흐름은 그대로)
- Create: `docs/runbook.md`
- Modify: `README.md`(기능·구조), `docs/product-contract.md`(6부 상태), `CLAUDE.md`(로그 위치와 "문제가 생기면 먼저 볼 곳", 사용자 승인 후)
- Test: `tests/test_opslog_swallowed.py`

**Interfaces:**
- Consumes: `errors.capture`
- Produces: `docs/runbook.md` — 항목마다 `증상 / 먼저 볼 로그(파일·화면) / 원인 / 조치`. 첫 항목들: 서버가 꺼짐, 크롤이 "잘못된 응답 형식"(G2B 기간 한도), 사이트 0건, 메일 발송 실패, 5002 포트 점유, 감시가 계속 재기동함.

- [ ] **Step 1: 대상 목록 만들기** — `grep -n -A1 -E "except( Exception)?( as \w+)?:" --include=*.py -r . | grep -B1 -E "^\S+-[0-9]+-\s+pass\s*$"` 의 14곳을 표로 적고, 각각 "의도된 무시(이유를 주석으로)" 인지 "기록해야 함" 인지 나눈다. 의도된 무시는 건드리지 않는다.
- [ ] **Step 2: 실패하는 테스트** — 정기 작업 경로 세 곳(`git_sync.push` 의 예외, 뉴스 수집 실패, 발송 중 한 통 실패)에서 예외를 일으켜 `error_events` 에 행이 생기고 **원래 동작(무시하고 계속)은 그대로**인지 본다.
- [ ] **Step 3~4:** 구현 → 통과; 전체 테스트
- [ ] **Step 5: 문서 갱신과 최종 확인** — 계약서 44절의 수용 기준 일곱 줄을 하나씩 실제 출력으로 확인해 기록한다.
- [ ] **Step 6: Commit** (요청 시)

---

## 실행 순서와 중간 반영

- Task 1 → 2 → 7 → 8 을 먼저 한다. 이 네 개가 운영에 들어가면 "조용히 꺼져 27시간 방치"는 막힌다. 여기서 한 번 운영에 반영한다.
- 이어서 3 → 4 → 5 → 6 → 9 → 10. Task 9 가 끝나면 두 번째로 운영에 반영한다.
- 운영 반영(병합·재시작)은 그때마다 사용자에게 묻는다.
