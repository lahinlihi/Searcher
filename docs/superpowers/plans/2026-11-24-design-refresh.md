# 하이-서치 디자인 개편 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 확정된 B 목록형 시안대로 화면의 모습만 바꾼다. 동작·API·주소는 그대로.

**Spec:** `docs/superpowers/specs/2026-11-24-hisearch-design-refresh-design.md` · 시안 https://claude.ai/artifact/RPBi7WfKsqCTrhznzP6so1

## Global Constraints
- API·점수·검색 조건·크롤 코드는 바꾸지 않는다. 바뀌는 파일은 `templates/`, `static/css/`, `static/js/` 의 그리는 부분과 테스트뿐.
- 작업은 worktree 브랜치. 화면마다 임시 서버(운영 DB 사본, 127.0.0.1)에서 PC 1280·휴대폰 390 확인 → 사용자에게 보여 주고 다음 화면.
- `routes/` 를 건드리지 않으므로 서버 재시작은 템플릿·정적 파일만 바뀌는 한 필요 없다(TEMPLATES_AUTO_RELOAD). 병합 뒤 브라우저 강력 새로고침 안내.
- 커밋은 사용자 확인 후.

## Review Focus
1. 사례 점수가 없는 사용자(사례 5건 미만) — 사례 칩이 아예 안 보여야 한다. → Task 2 `test_dashboard_page_renders` + 화면 확인
2. 금액·마감일이 없는 공고 — "금액 미정", "상시"로 보이고 정렬이 깨지지 않는다. → Task 2 JS 단위 확인(node)
3. 아주 긴 제목·기관명 — 줄바꿈되고 가로 스크롤을 만들지 않는다. → 390px 확인
4. 관리자 메뉴 — 일반 사용자에게 "관리" 메뉴 항목이 권한대로만 보인다. → Task 1 `test_nav_admin_items_by_role`
5. 탭 전환 시 이미 받은 데이터를 다시 요청하지 않는다(대시보드 응답 한 번). → 화면 확인(네트워크)

---

### Task 1: 공통 틀과 디자인 규칙
- Create `static/css/hs-theme.css` (토큰 + `hs-btn`, `hs-btn-primary`, `hs-chip`(상태별 변형), `hs-card`, `hs-panel`, `hs-dd`(마감 블록), `hs-kpi`, `hs-tabs`, `hs-row`), Google Fonts 링크.
- Modify `templates/base.html`: 상단 막대(로고·검색창·주 메뉴·"관리" 펼침·사용자), 휴대폰 메뉴. 메뉴 항목과 권한 조건은 지금과 같게.
- Create `tests/test_pages_render.py`: 로그인한 사용자(일반·관리자)로 모든 페이지 GET 200, `test_nav_admin_items_by_role`.
- 확인: 모든 화면이 새 상단 막대로 열린다, 콘솔 오류 0.

### Task 2: 대시보드 B 목록형
- Create `static/js/tender-row.js`: `formatPrice(won)`, `ddInfo(deadlineIso)`, `statusKind(tender)`, `renderTenderRow(t, opts)`.
- Modify `templates/dashboard.html`, `static/js/dashboard.js`: 왼쪽 요약·키워드·필터, 탭, 정렬, "오늘 볼 것", 비슷한 공고 탭(좋음/아님 그대로). 데이터는 `/api/dashboard`·`/api/cases/similar`·`/api/embed-scores` 그대로.
- 확인: node 로 `formatPrice(550000000)=='5.5억'`, `formatPrice(30000000)=='3,000만원'`, `formatPrice(null)=='금액 미정'`, `ddInfo(오늘)=='오늘 마감'`. 개편 전후 탭별 공고 id 목록 같음(실제 DB 사본).

### Task 3: 공고 상세
- Modify `templates/detail.html`(+ 필요 시 `static/js/detail.js` 의 그리는 부분): 핵심 4칸, 정보 표, AI 분석, 메모, 오른쪽 판단 칸. 기존 기능(투찰 계산, 연관 공고, 과거 이력, 메모, 관심) 모두 유지.
- 확인: 사전규격·나라장터·기타 채널 공고 각 1건, 금액·마감 없는 공고 1건을 PC·휴대폰으로 열어 기능 동작.

### Task 4: 상세검색
- Modify `templates/search.html`, `static/js/search.js`: 결과를 `renderTenderRow` 로, 조건 칸을 B 필터 모양으로.
- 확인: 같은 조건의 결과 id·순서가 개편 전과 같음.

### Task 5: 나머지 화면
- 관심공고, 검토공고, 놓친 공고, 로그, 설정, 회원관리, 내 정보, 로그인·가입 화면을 공통 클래스로 정리. 배치는 유지.
- 확인: `test_pages_render` 전부 통과, 각 화면 PC·휴대폰 확인.

### Task 6: 정리와 적용
- `style.css` 에서 더 이상 쓰지 않는 규칙 삭제(템플릿·JS 에서 클래스 검색으로 확인).
- README 반영, 사용자 확인 후 커밋·병합. 병합 뒤 운영 화면 확인은 사용자(로그인 필요).
