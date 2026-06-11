# CLAUDE.md — 프로젝트 협업 규칙

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
- 포트 확인 없이 "재시작 완료" 선언 — 구버전 프로세스가 살아있으면 구버전 코드가 계속 서빙됨
- HTTP 200/302 확인만으로 "코드 적용 완료" 선언 — 구버전 서버도 HTTP 응답을 반환함

#### 서버 재시작 절차 — 6단계 필수

**Step 1: PowerShell로 기존 프로세스 종료**
```bash
# Git Bash에서 실행
powershell -Command "
\$p = (Get-NetTCPConnection -LocalPort 5002 -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1
if (\$p) { Stop-Process -Id \$p -Force; Write-Host \"PID \$p 종료\" }
else { Write-Host '포트 5002 미사용' }
"
```

**Step 2: 포트 해제 확인 (최대 10초 대기)**
```bash
for i in $(seq 1 10); do
    r=$(powershell -Command "Get-NetTCPConnection -LocalPort 5002 -ErrorAction SilentlyContinue" 2>/dev/null)
    [ -z "$r" ] && echo "포트 5002 해제 확인" && break
    echo "대기 중... ${i}초"; sleep 1
done
```

**Step 3: 새 서버 시작**
```bash
cd /c/Users/USER/Searcher
nohup python app.py > server_restart.log 2>&1 &
echo "새 PID: $!"
```

**Step 4: 서버 HTTP 응답 확인 (최대 15초 대기)**
```bash
for i in $(seq 1 15); do
    s=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5002/ 2>/dev/null)
    { [ "$s" = "200" ] || [ "$s" = "302" ]; } && echo "서버 기동 확인: HTTP $s" && break
    echo "대기 중... ${i}초"; sleep 1
done
```

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
> 예시: 반기 제거 패턴 확인 → `assert '상하반기' in src`
> Step 5 실패 시: `cat server_restart.log` 로 에러 확인 후 원인 분석

**Step 6: 사용자에게 보고**
Step 1~5가 모두 통과한 이후에만 "적용 완료"를 보고한다.

---

## Searcher 프로젝트 — 공공데이터포털(G2B) API 레이트 리밋 규칙

### 규칙: API 요청을 인위적으로 증폭시키지 않는다

공공데이터포털 G2B API는 API 키 기준으로 레이트 리밋을 적용한다. 429 응답 발생 시
최대 1시간 차단되며, 차단 중에는 모든 요청이 실패한다.

#### 잘못된 접근 (절대 금지)
- 날짜 범위를 인위적으로 월별/분기별로 쪼개서 60~120개 요청을 한꺼번에 발송
- 테스트 목적으로 동일 API를 반복 호출 (loop, 배치 등)

#### 올바른 접근
- **5년 단일 범위** (`inqryBgnDt` ~ `inqryEndDt`)로 1회 요청 후 페이지네이션
- 특정 공고명 검색 → 통상 결과 수십 건 → **엔드포인트당 1~2 요청으로 충분**
- 결과가 100건 초과할 때만 페이지를 추가로 요청

#### 테스트 시 주의
- G2B API 연결 테스트는 **단일 요청**으로만 수행
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