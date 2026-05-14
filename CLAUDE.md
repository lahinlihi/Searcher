# CLAUDE.md — 프로젝트 협업 규칙

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
