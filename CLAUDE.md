# CLAUDE.md — 프로젝트 협업 규칙

---

## 안정 동작 코드 수정 금지 규칙 (최우선 원칙)

### 원칙
현재 정상 동작 중인 코드(에러 로그 없이 돌아가던 로직)를 "더 나은 방법"이라는 이유로
교체하기 전에, 반드시 다음을 먼저 수행한다:

1. 실제 문제가 재현되는 증거를 먼저 확보한다 (로그, 에러 메시지, 재현 스크립트)
2. 원인이 정말 그 코드에 있는지 격리 테스트로 확인한다 (다른 원인 배제)
3. 수정안을 적용하기 전, 수정으로 새로 생기는 실패 모드가 있는지 점검한다
   (예: 매 호출마다 네트워크 요청이 추가되는가? 동시 실행 시 충돌하는가?)
4. 수정 후에는 반드시 실제 동작 테스트로 검증한다 (로그 확인만으로 "적용 완료" 선언 금지)

### 배경
ChromeDriver 버전 불일치 문제를 고치려고 안정적으로 동작하던 Selenium Manager
방식을 webdriver-manager로 교체했으나, 이 변경 자체가 매 크롤러 실행마다
네트워크 확인/다운로드를 유발해 오히려 크롤러 크래시를 일으켰다.
"고치려는 시도"가 실제로는 더 큰 문제를 만든 사례.

---

## 카카오 OAuth 설정 규칙 (중요)

### Redirect URI 등록 위치
카카오 Developers에서 Redirect URI는 **"카카오 로그인 → 일반"이 아니라**
**앱 설정 → 플랫폼 키 → REST API 키 수정** 페이지의 "카카오 로그인 리다이렉트 URI" 항목에 등록한다.
"카카오 로그인 → 일반" 탭에는 해당 항목이 없다. 이 사실을 사용자에게 안내할 때 절대 "일반 탭에 있다"고 하지 않는다.

### 클라이언트 시크릿
- 콘솔에서 활성화 **OFF** 시: `client_secret` 제거, `token_endpoint_auth_method='none'` 사용
- 콘솔에서 활성화 **ON** 시: `.env`에 `KAKAO_CLIENT_SECRET` 등록, `token_endpoint_auth_method='client_secret_post'` 사용
- 기본값(OFF)으로 운영하는 것이 간단함. 시크릿 값 불일치 시 `Bad client credentials` 오류 발생

---

## Searcher 프로젝트 — 코드 수정 후 서버 자동 재시작 규칙

### 규칙: 서버 재시작이 필요한 작업 완료 후 자동으로 재시작 실행

Flask 서버는 코드 변경 사항을 실시간 반영하지 않으므로, 아래 파일 수정 시 작업 완료 즉시
자동으로 서버를 재시작해야 한다. 사용자에게 "서버 재시작이 필요합니다"라고 안내만 하고
끝내지 말고, 직접 재시작까지 수행한다.

#### 재시작이 필요한 작업 목록
- `routes/*.py` 수정 (API 엔드포인트, 라우팅 로직)
- `crawlers/*.py` 수정
- `scheduler.py` 수정
- `app.py` 수정
- `database.py` 수정
- `document_analyzer.py` 수정

#### ⚠️ 절대 금지 사항

- `cmd /c "taskkill /PID $PID /F"` — Git Bash(MSYS)에서 경로 변환 문제로 프로세스를 죽이지 못하는 경우가 있음. **사용 금지**
- **포트 조회만으로 "종료됨"·"기동됨"을 판단하지 않는다.** `Get-NetTCPConnection -LocalPort 5002 -State Listen` 과 `netstat` 은
  서버가 응답 중인데도 5002 LISTEN 줄을 보여주지 않는 경우가 있다(2026-11-05, 11-17 확인). 구버전 프로세스를 놓치면
  구버전 코드가 계속 서빙된다. **`app.py` 를 실행 중인 python 프로세스 목록**으로 판단한다.
- HTTP 응답 확인만으로 "코드 적용 완료" 선언 — 구버전 서버도 HTTP 응답을 반환함
- `nohup python app.py &` 로 띄우기 — 세션이 끝나면 서버도 함께 내려간다(2026-11-05: 서버가 죽어 07:30 작업이 돌지 않음)
- 크롤링이 진행 중일 때 재시작 — 수집 중이던 결과를 잃고 Selenium 브라우저가 주인 없이 남는다

#### 서버 재시작 절차 — 6단계 필수

명령은 **PowerShell** 기준이다.

**Step 1: 크롤링 진행 여부 확인 후 기존 프로세스 종료**
```powershell
Set-Location C:\Users\USER\Searcher
python -c "import sqlite3;c=sqlite3.connect('file:data/tenders.db?mode=ro',uri=True);print(c.execute('select status from crawl_logs order by id desc limit 1').fetchone()[0])"
# → running 이면 끝날 때까지 기다린다 (정기 크롤 09:00, 13:00 / 약 7분)

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'app\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "PID $($_.ProcessId) 종료" }
```

**Step 2: 프로세스가 0개인지 확인 (최대 10초 대기)**
```powershell
for ($i=1; $i -le 10; $i++) {
  if (-not (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'app\.py' })) { "app.py 프로세스 0개 확인"; break }
  Start-Sleep 1
}
```

**Step 3: 새 서버 시작**
```powershell
Start-Process -FilePath "C:\Python314\python.exe" -ArgumentList "-u","app.py" `
  -WorkingDirectory "C:\Users\USER\Searcher" `
  -RedirectStandardOutput "C:\Users\USER\Searcher\server_restart.log" `
  -RedirectStandardError  "C:\Users\USER\Searcher\server_restart_err.log" `
  -WindowStyle Hidden -PassThru
```
> `-u` 를 빼면 출력이 버퍼에 쌓여 로그 파일이 한참 동안 0바이트로 남는다(2026-11-17 확인).
> `Start-Process` 로 띄워야 이 세션이 끝나도 서버가 살아 있다.

**Step 4: 서버 HTTP 응답 확인 (최대 90초 대기)**
```powershell
for ($i=1; $i -le 90; $i++) {
  try { $code = (Invoke-WebRequest -Uri "http://localhost:5002/api/memos/unread-count" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop).StatusCode }
  catch { $code = $_.Exception.Response.StatusCode.value__ }
  if ($code -eq 401 -or $code -eq 200) { "서버 기동 확인: HTTP $code"; break }
  Start-Sleep 1
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'app\.py' } | Select-Object ProcessId, CreationDate
```
> `/` 로 확인하지 않는다. localhost 로 `/` 를 열면 공개 도메인으로 301 리다이렉트되므로 200/302 가 나오지 않는다.
> `/api/...` 는 리다이렉트 대상이 아니다. 로그인 없이 부르면 **401 이 정상**이다.
> 프로세스가 **1개**이고 시작 시각이 방금인지 함께 본다.

**Step 5: 신규 코드 적용 확인 (수정한 모듈·함수 기준)**
```bash
cd /c/Users/USER/Searcher
python -c "
import sys, inspect; sys.path.insert(0, '.')
from routes.tenders import 수정한_함수명   # 수정한 모듈/함수로 교체
src = inspect.getsource(수정한_함수명)
assert '핵심_변경_패턴' in src, '신규 코드 미적용!'
print('신규 코드 적용 확인')
"
```
> 이것은 디스크의 코드를 확인할 뿐이다. 가능하면 **실행 중인 서버의 동작**으로도 확인한다
> (바뀐 응답, 서빙되는 JS 내용, 새 로그 문구 등).
> 실패 시: `server_restart_err.log` 와 `server_restart.log` 에서 원인 확인

**Step 6: 사용자에게 보고**
Step 1~5가 모두 통과한 이후에만 "적용 완료"를 보고한다.

---

## Searcher 프로젝트 — 공공데이터포털(G2B) API 규칙

### 규칙 1: API 요청을 인위적으로 증폭시키지 않는다

공공데이터포털 G2B API는 API 키 기준으로 레이트 리밋을 적용한다. 429 응답 발생 시
최대 1시간 차단되며, 차단 중에는 모든 요청이 실패한다. 같은 키를 정기 크롤러도 쓴다.

### 규칙 2: 조회 기간에는 API 가 정한 한도가 있다 — 한도 안에서 가장 넓게 한 번에 요청한다

**"넓은 범위로 한 번에" 가 항상 가능한 것이 아니다.** API 마다 조회 기간 한도가 있고, 넘으면
데이터가 아니라 오류가 온다.

| API | 확인된 한도 | 근거 |
|---|---|---|
| 입찰공고 목록 `getBidPblancListInfoServc` (정기 크롤러) | **달력 7일** (시작일 00:00 ~ 종료일 23:59 를 포함해 7일) | 2026-11-17 단일 요청으로 확인: 8일 → 오류, 7일·1일 → 정상 |
| 개찰결과·낙찰결과 `...PPSSrch` (과거 이력 조회) | 미확인. 코드(`routes/tenders.py`)는 월 단위로 조회한다 | 코드 주석: "한 달을 넘으면 07 오류" |

- 한도 초과 응답은 HTTP 200 에 `resultCode: 07`, `resultMsg: 입력범위값 초과 에러` 로 온다.
  **429 가 아니다.** 본문 최상위 키가 `response` 가 아니라 `nkoneps.com.response.ResponseError` 라서
  크롤러 로그에는 "잘못된 응답 형식" 으로 찍힌다. 이 문구를 보면 기간 한도부터 의심한다.
- 크롤러의 기간은 `시작 = 오늘 - days_range` 의 00:00 부터 오늘 23:59 까지다. 즉 `days_range` 보다
  **하루 많은** 날짜를 요청한다. 한도가 7일이면 `days_range` 는 **6** 이어야 한다
  (`data/settings.json` 의 `g2b_api.days_range`).
- 한도는 공지 없이 바뀐다. 2026-11-10 까지 8일 범위가 통하다가 11-11 부터 거부됐다.

#### 잘못된 접근 (절대 금지)
- 한도보다 **잘게** 쪼개기 — 7일까지 되는 API 를 하루씩 7번 부르는 것
- 한도를 확인하지 않고 넓은 범위(예: 5년)를 한 번에 요청 — 오류만 돌아온다
- 테스트 목적으로 동일 API를 반복 호출 (loop, 배치 등)

#### 올바른 접근
- 한도 안에서 **가장 넓은 단일 범위**로 1회 요청 후 페이지네이션
- 한도를 넘는 기간이 꼭 필요하면 **한도 단위로만** 나눈다 (그보다 잘게 나누지 않는다)
- 결과가 한 페이지를 넘을 때만 다음 페이지를 요청

#### 테스트 시 주의
- G2B API 연결 테스트는 **단일 요청**으로만 수행한다. 한도를 찾을 때도 요청마다 조건을 하나만 바꾸고,
  각 요청의 조건과 응답을 기록한다 (루프로 범위를 훑지 않는다)
- 로직 검증은 API 호출 없이 Python 내에서 데이터 변환 로직만 단독 실행

---

## Searcher 프로젝트 — 크롤러 수정 후 필수 절차

### 규칙: 크롤러 코드 수정 후 반드시 서버 재시작

이 프로젝트는 Flask 서버(`app.py`)가 시작될 때 모든 크롤러를 임포트하여 `scheduler.crawlers` 딕셔너리에 **인스턴스로 캐싱**한다.

```
서버 시작 → _init_crawlers() → IrisCrawler() 인스턴스 생성 → self.crawlers['iris']에 저장
```

따라서 **서버가 실행 중인 상태에서 크롤러 `.py` 파일을 수정해도, 수동 크롤링을 실행하면 메모리에 남아 있는 구버전 인스턴스가 그대로 사용된다.** (`.pyc` 캐시 문제가 아닌, 런타임 인스턴스 캐시 문제)

#### 반드시 지켜야 할 절차

1. `crawlers/` 또는 `scheduler.py` 파일 수정 완료
2. **서버 프로세스 재시작** (기존 PowerShell 창 종료 → 새로 실행)
3. 재시작 후 수동 크롤링으로 검증

#### 검증 방법 (재시작 없이 코드 레벨에서 빠르게 확인)

서버 재시작 없이 크롤러 동작을 검증할 때는 **직접 Python 스크립트로 실행**:

```bash
cd /c/Users/USER/Searcher
python -u -c "
import sys; sys.path.insert(0, '.')
from crawlers.iris_crawler import IrisCrawler
result = IrisCrawler().crawl()
print(result['count'], 'items')
"
```

수동 크롤링 버튼(웹 UI)은 서버 재시작 후에만 신뢰할 수 있다.

---

## Searcher 프로젝트 — 크롤러는 "0건"을 성공으로 보고하지 않는다

### 원칙
크롤러가 예외 없이 끝났다는 것과 수집이 됐다는 것은 다르다. **"성공, 0건" 이 몇 번 이어지면
고장으로 본다.** 수집 결과를 볼 때는 성공 표시가 아니라 **사이트별 마지막 적재일**을 본다.

```sql
SELECT source_site, COUNT(*), MAX(substr(created_at,1,10)) AS last_new
FROM tenders GROUP BY source_site ORDER BY last_new;
```

### 배경 (2026-11-17 에 한꺼번에 발견)
로그 화면에는 전부 "성공" 으로 떠 있었다.

| 사이트 | 겉보기 | 실제 | 멈춘 기간 |
|---|---|---|---|
| 경상북도 | 성공, 0건 | 사이트 개편으로 선택자가 맞지 않음 | 2개월 |
| 대구테크노파크 | 성공, 100건 | 상세 링크가 없어 전부 목록 주소를 URL 로 가짐 → URL 중복 판정이 전부 버림 | 4개월 |
| 광진구 | 성공, 10건 | 구청 RSS 피드가 2025-08 글에서 멈춰 있음 (외부 원인) | 7개월 |
| 나라장터 입찰공고 | **실패** 로 표시됐으나 엿새 방치 | API 기간 한도 변경 | 6일 |

### 지켜야 할 것
- 새 크롤러·새 사이트 설정은 **첫 페이지를 받았는데 0건이면 오류로 기록**한다 (`self.errors` 에 추가 → `success=False`)
- "수집 N건" 만 보고 끝내지 않는다. **신규로 저장된 건수**를 함께 본다. 수집은 되는데 저장이 0이면 중복 판정을 의심한다
- 상세 링크가 없는 사이트는 URL 이 목록 주소로 채워진다. 이 URL 은 공고의 고유값이 아니다
- 크롤러를 고친 뒤 검증은 **실제 크롤 1회 후 DB 에 새 행이 들어왔는지**로 한다

---

## Project Initialization & Feature Planning Rule

### Target Files

- Project folder root: `CLAUDE.md`, `README.md`, `docs/product-contract.md`

### Principle

Before generating the initial project structure for a new project, first define:

- Core features
- Primary user flows
- Acceptance criteria for each flow
- Core E2E scenarios that must pass

Write them in `docs/product-contract.md` first.

Then:

1. Summarize the core features in `README.md`
2. Design routes, data model, and folder structure based on the defined flows
3. Implement only after the product contract is clear

### Scope

Apply this rule:

- When starting a new project
- When resetting project architecture
- When adding a major new feature that changes core user flows

---

## CLAUDE.md Improvement Rule

### Target File

Current project folder root: `CLAUDE.md`

### Principle

If you encounter and resolve an error, and if that error is not a simple technical mistake but caused by knowledge limitations or coding style, propose to the user to update `CLAUDE.md` with a fundamental solution to prevent that error.

### Example

> Situation: Wrote code following Tailwind CSS v3, an error occurred, and found the solution in the v4 documentation.
>
> Improvement: "Use Tailwind CSS according to the v4 usage released in 2025. If unsure, refer to the documentation."

---

## React + Vite Development Rules (npm)

**Stack is fixed:** React + TypeScript + Vite + Tailwind CSS + Motion (Framer Motion) + Firebase + React-Router-Dom + Zustand + Tanstack Query (v5)

**Mobile-First Design:** Always design and implement for mobile screens first, then scale up to larger screens.

**Run lint, npm run build, tsc:** Always debug after jobs done.

---

### 1) Fixed stack and allowed libraries

Use exactly these libraries for the listed responsibilities:

| Responsibility | Library |
|---|---|
| Build/dev | Vite |
| UI | React |
| Language | TypeScript (strict) |
| Styling | Tailwind CSS |
| Animation | Motion (Framer Motion) |
| Backend SDK | Firebase Web SDK (modular v9+) |
| Global State | Zustand |
| Data Fetch / Server State | @tanstack/react-query (v5+) |

- Use Tanstack Query **strictly** for asynchronous server state and data fetching.
- Use Zustand **only** for synchronous, global client UI state (e.g., dark mode, sidebar open/close, multi-step form data).
- Do not add alternatives for the same responsibility.

**Forbidden additions:**
- Animation: react-spring, gsap wrappers → use Motion
- Styling: styled-components, emotion, CSS frameworks → use Tailwind

---

### 2) README.md is the source of truth (keep it correct)

**Before doing any of these:**
- Installing a package
- Creating a folder
- Adding a new feature (anything user-facing or cross-cutting)

**Do this first:**
1. Open `README.md`
2. Check: `features` (already implemented?), `project-structure` (where does this belong?), any conventions

If an equivalent feature or module exists, extend it. Do not re-create it.

**After doing any of these:**
- Update `README.md` immediately: `project-structure` and `features` sections

**After any change, verify these three agree:**
- `README.md` (what exists and how to run it)
- `package.json` (scripts + deps)
- `package-lock.json` (locked dependency graph)

No contradictions allowed.

---

### 3) Dependency management with npm (reproducible installs)

- Use **npm only**
- Commit **`package-lock.json`** with every dependency change
- Do not edit `package-lock.json` manually

---

### 4) Project structure (prevents duplicate code)

```
src
+-- assets            # Static files (images, fonts, etc.)
+-- components        # Shared UI components used across the entire app
+-- features          # Domain-specific logic and components (e.g., features/auth)
+-- pages             # Route-level files only; split large files into features/ or components/
+-- store             # Zustand stores for global state
+-- firebase
|   +-- config.ts     # Firebase init and exports (hardcode firebaseConfig here)
|   +-- auth.ts       # (ONLY IF AUTH REQUESTED) Pure auth business logic
+-- utils             # Shared utility functions
+-- main.tsx          # Main app component; contains providers
+-- router.tsx        # Routes (path ↔ page mapping only; use React-Router v6+)
```

Root: `.gitignore`, `eslint.config.js`, `index.html`, `package-lock.json`, `package.json`, `README.md`, `tsconfig.*.json`, `vite.config.ts`, `public/`, `node_modules/`

---

### 5) TypeScript rules

`tsconfig.json` must keep:
- `"strict": true`
- `"noUncheckedIndexedAccess": true` (recommended)
- `"noImplicitOverride": true` (recommended)

Do not use `any`. Use `unknown` for untrusted values.

---

### 6) Firebase rules (single init, modular imports)

- Use Firebase modular SDK (v9+)
- Create Firebase app and exported clients in exactly one place: `src/firebase/config.ts`
- No other file calls `initializeApp`
- Import style must be modular:

```typescript
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";
```

---

### 7) Motion (Framer Motion) rules

- Use Motion components for animation (`motion.div`, etc.)
- Prefer variants for consistency; store common variants in `src/utils/motionPresets.ts`
- Do not introduce additional animation libraries

---

### 8) Tailwind rules

- Use Tailwind for all styling
- Keep global CSS minimal
- Do not use arbitrary hex values (e.g., `text-[#ff5733]`)
- Use Tailwind's default color palette for generic styling; define brand colors (primary, secondary, background) using CSS Variables in `index.css`

---

### 9) Firebase config & rules setup (NO .env required)

*(Note: Setup Firestore rules and Auth config ONLY IF explicitly requested by the user)*

**DO NOT use `.env` files for Firebase client configuration.**

Firebase client config values (`apiKey`, `projectId`, `appId`) are safe to expose in client-side code per official Firebase documentation. Hardcode the `firebaseConfig` object directly in `src/firebase/config.ts`:

```typescript
const firebaseConfig = {
  apiKey: "AIzaS...",
  authDomain: "real-id.firebaseapp.com",
  projectId: "real-id",
  storageBucket: "real-id.firebasestorage.app",
  messagingSenderId: "realvalue",
  appId: "realvalue:web:realvalue"
};
```

Firestore rules:
- `general` (collection) / `base` (doc): `allow read: if true`
- `users` (collection) / `uid` (doc):

```
match /users/{userId}/{document=**} {
  allow read, write: if request.auth != null && request.auth.uid == userId;
}
```

**Exception:** Third-party private keys (e.g., OpenAI, Stripe) must NEVER be hardcoded — MUST use `.env`.

---

## Optional Features: CRUD & Auth (Only when requested)

**DEFAULT TO HOSTING ONLY:** By default, use Firebase only for Hosting. **DO NOT** implement Firebase Auth, Google Login, or Firestore unless the user explicitly requests it.

If Auth or DB features are explicitly requested:
- Do NOT use complex `getDoc` queries that need Firestore index feature
- Write proper `firestore.rules` to ensure each user can access own data only
- Write code that stores user data in Firestore → `users` (collection) → `uid` (doc) when user first signs up

# Project Initialization & Feature Planning Rule
## Target Files
project folder root: CLAUDE.md, README.md, docs/product-contract.md

## Principle
Before generating the initial project structure for a new project, first define:
- core features
- primary user flows
- acceptance criteria for each flow
- Core E2E scenarios that must pass

Write them in docs/product-contract.md first.

Then:
1. summarize the core features in README.md
2. design routes, data model, and folder structure based on the defined flows
3. implement only after the product contract is clear

## Scope
Apply this rule:
- when starting a new project
- when resetting project architecture
- when adding a major new feature that changes core user flows

# CLAUDE.md Improvement
## Target File
Current project folder root, CLAUDE.md

## Principle
If you encounter and resolve an error, and if that error is not a simple technical mistake but caused by your knowledge limitations or coding style, propose to the user to update CLAUDE.md with a fundamental solution to prevent that error.

## Example
Situation: Wrote code following tailwindcss v3, an error occurred, and found the solution in the v4 documentation.
Improvement: "Use tailwindcss according to the V4 usage released in 2025. If unsure, refer to the documentation."

---

# React + Vite Development Rules (npm)

**Stack is fixed:** React + TypeScript + Vite + Tailwind CSS + Motion (Framer Motion) + Firebase + React-Router-Dom + Zustand + Tanstack Query(v5)

**Mobile-First Design:**: Always design and implement for mobile screens first, then scale up to larger screens.

**Run lint, npm run build, tsc**: Always debug after jobs done.

---

## 1) Fixed stack and allowed libraries

Use exactly these libraries for the listed responsibilities:

- **Build/dev:** Vite
- **UI:** React
- **Language:** TypeScript (strict)
- **Styling:** Tailwind CSS
- **Animation:** Motion (Framer Motion)
- **Backend SDK:** Firebase Web SDK (modular v9+)
- **Global State:** Zustand
- **Data Fetch and Server data Management:** @tanstack/react-query(v5+)

Use Tanstack Query STRICTLY for asynchronous server state and data fetching. Use Zustand ONLY for synchronous, global client UI state (e.g., dark mode, sidebar open/close, multi-step form data).

Do not add alternatives for the same responsibility.

Examples of forbidden additions:

- Animation: react-spring, gsap wrappers (use Motion)
- Styling: styled-components, emotion, CSS frameworks (use Tailwind)

# Optional Features: CRUD & Auth (Only when requested)

**🔥 DEFAULT TO HOSTING ONLY:** By default, use Firebase only for Hosting. **DO NOT** implement Firebase Auth, Google Login, or Firestore unless the user explicitly requests database or login functionality.

If the user explicitly requests Auth or DB features, strictly follow these rules:
- DO NOT use complex getDoc queries that needs 'index' feature in firestore.
- write proper firestore.rules to ensure each user can access own data only.
- write code that make user data in firestore > users(collection) > uid(doc), when user first sign up.

---

## 2) README.md is the source of truth (keep it correct)

### Before doing any of these:

- installing a package
- creating a folder
- adding a new feature (anything user-facing or cross-cutting)

Do this first:

1. Open `README.md`
2. Check:
    - `features` (is this already implemented?)
    - `project-structure` (where does this belong?)
    - any conventions (naming, patterns, existing modules)

If an equivalent feature or module exists, extend it. Do not re-create it.

### After doing any of these:

- installing/removing/upgrading packages
- creating a folder
- adding a new feature

Update `README.md` immediately:

- `project-structure`: add the new folder/module and its role (one line)
- `features`: add/adjust the feature description and entry points

### After any change

Verify these three agree with each other:

- `README.md` (what exists and how to run it)
- `package.json` (scripts + deps)
- `package-lock.json` (locked dependency graph)

No contradictions allowed.

---

## 3) Dependency management with npm (reproducible installs)

### Rules

- Use **npm only**.
- Commit **`package-lock.json`** with every dependency change.
- Do not edit `package-lock.json` manually.

---

## 4) Project structure (prevents duplicate code)

Use this structure and meanings:

src

+-- assets            # assets folder can contain all the static files such as images, fonts, etc.
+-- components        # shared UI components used across the entire application (e.g., Buttons, Modals)
+-- features          # Domain-specific logic and components (e.g., features/auth, features/dashboard)
+-- pages             # Keep files route-level only. If a component gets too large, split it into `features/` or `components/`.
+-- store             # Zustand stores for global state management
+-- firebase          # firebase related files
|   +-- config.ts     # # Firebase init and exports. Hardcode the firebaseConfig object here.
|   +-- auth.ts       # (ONLY IF AUTH REQUESTED) Pure auth business logic (handleSignOut, handleSignIn).
+-- utils             # shared utility functions and libraries
+-- main.tsx          # main application component; contains providers
+-- router.tsx        # application routes. Path ↔ page mapping only. Use React-Router v6+ (createBrowserRouter)

.gitignore, eslint.config.js, index.html, package-lock.json, package.json, README.md, tsconfig.app.json, tsconfig.json, tsconfig.node.json, vite.config.ts, public/, node_modules/

---

## 5) TypeScript rules (keep correctness under AI-generated churn)

- `tsconfig.json` must keep:
    - `"strict": true`
    - `"noUncheckedIndexedAccess": true` (recommended)
    - `"noImplicitOverride": true` (recommended)
- Do not use `any`.
    - Use `unknown` for untrusted values.

---

## 6) Firebase rules (single init, modular imports)

- Use Firebase modular SDK (v9+).
- Create Firebase app and exported clients in exactly one place:
    - `src/firebase/config.ts`
- No other file calls `initializeApp`.
- Import style must be modular:

    `import { initializeApp } from "firebase/app";
    import { getAuth } from "firebase/auth";
    import { getFirestore } from "firebase/firestore";`
    

---

## 7) Motion (Framer Motion) rules (consistent animation strategy)

- Use Motion components for animation (`motion.div`, etc.).
- Prefer variants for consistency:
    - store common variants/presets in `src/utils/motionPresets.ts`
- Do not introduce additional animation libraries.

---

## 8) Tailwind rules (avoid style drift and class chaos)

- Use Tailwind for all styling.
- Keep global CSS minimal.
- Do not use arbitrary hex values (e.g., `text-[#ff5733]`).
- Use Tailwind's default color palette for generic styling, but strictly define Brand colors (primary, secondary, background) using CSS Variables in `index.css`.

---

## 9) Firebase config & rules setup(NO .env required)
*(Note: Setup Firestore rules and Auth config ONLY IF explicitly requested by the user)*
**DO NOT use `.env` files for Firebase client configuration.**
According to official Firebase documentation, values like `apiKey`, `projectId`, and `appId` are safe to expose in client-side code and are intended to be public. Do not waste time setting up environment variables for them. check real value and set

Hardcode the `firebaseConfig` object directly in `src/firebase/config.ts` like this:

```typescript
const firebaseConfig = {
  apiKey: "AIzaS...",
  authDomain: "real-id.firebaseapp.com",
  projectId: "real-id",
  storageBucket: "real-id.firebasestorage.app",
  messagingSenderId: "realvalue",
  appId: "realvalue:web:realvalue"
};
And, for proper protection, write Firestore rules like this:

- **general** (collection) / **base** (doc): allow read for everyone (e.g., `allow read: if true`).
- **users** (collection) / **uid** (doc): restrict access as follows:

`match /users/{userId}/{document=**} {
  allow read, write: if request.auth != null && request.auth.uid == userId;
}`

**Exception"** Third-party private keys (e.g., OpenAI, Stripe) must NEVER be hardcoded and MUST USE .env."