# Searcher 프로젝트 인수인계 문서

> 작성일: 2026-05-19  
> 목적: 다른 Claude Code 인스턴스가 이 프로젝트를 바로 이어받아 작업할 수 있도록  
> 서버 주소: `http://localhost:5002`

---

## 1. 프로젝트 개요

**입찰공고 통합 검색 시스템** — 나라장터(G2B) 및 여러 기관 사이트의 입찰 공고를
자동 수집·분류·점수화하고, 팀원들이 웹 브라우저로 검색·북마크·분석할 수 있는
Flask 기반 내부 웹 애플리케이션.

### 핵심 기능
| 기능 | 설명 |
|---|---|
| 자동 크롤링 | 09:00 / 17:00 자동 실행, 수동 즉시 실행 가능 |
| 통합 검색 | 포함/제외 키워드, 상태, 금액, 지역, 수요기관, 날짜 필터 |
| 매칭 점수 | 키워드·사업유형·기관가중치 기반 적합도 점수 |
| AI 분석 | Gemini API로 공고 첨부문서 분석 (자격요건, 예산 등 추출) |
| 북마크 | 관심공고 라벨링 (수행가능/경험있음/관심사/참고용) |
| 필터 관리 | 관심 키워드·제외 키워드·예산범위 사용자별 저장 |
| 수행이력 조회 | 특정 공고의 과거 낙찰 이력을 G2B API에서 검색 |
| 회원 관리 | admin/moderator/user 3단계 역할, 회원 추가·삭제 |
| 설정 | API 키, 이메일 알림, 데이터 보존 기간 등 |

---

## 2. 기술 스택

```
Backend  : Python 3.11+, Flask 3.0, SQLAlchemy 2.x, APScheduler 3.10
DB       : SQLite (data/tenders.db)
WSGI     : waitress (포트 5002)
Frontend : Jinja2 템플릿, Tailwind CSS (CDN), Vanilla JS, jQuery, Chart.js
AI       : Google Gemini API (google-generativeai)
크롤링   : requests, BeautifulSoup4, Selenium (일부 사이트)
```

---

## 3. 폴더 구조

```
Searcher/
├── app.py                    # Flask 앱 진입점, 블루프린트 등록
├── config.py                 # 포트(5002), DB 경로, 크롤링 시간 등 상수
├── database.py               # SQLAlchemy 모델 전체 정의
├── scheduler.py              # APScheduler 래퍼, 크롤러 인스턴스 캐시
├── scoring.py                # 공고 적합도 점수 계산 로직
├── filters.py                # 필터 적용 헬퍼
├── deduplication.py          # 공고 중복 제거
├── document_analyzer.py      # Gemini AI 분석 (첨부문서 다운로드 → 분석)
├── email_notifier.py         # 이메일 알림
├── excel_exporter.py         # Excel 내보내기
├── decorators.py             # @login_required 등 데코레이터
├── settings_manager.py       # data/settings.json 읽기/쓰기
├── data_manager.py           # 데이터 CRUD 헬퍼
│
├── routes/                   # Flask 블루프린트
│   ├── auth.py               # 로그인/로그아웃
│   ├── admin.py              # 회원 관리 (admin/moderator 전용)
│   ├── pages.py              # 메인·상세 페이지 렌더링
│   ├── tenders.py            # 검색 API, 수행이력 조회 API
│   ├── bookmarks.py          # 관심공고 CRUD
│   ├── filters.py            # 필터 프리셋 CRUD
│   ├── settings.py           # 설정 API
│   ├── data.py               # 크롤링 실행·현황 API
│   └── analysis.py           # AI 분석 요청 API
│
├── crawlers/                 # 사이트별 크롤러
│   ├── base_crawler.py       # 공통 베이스
│   ├── g2b_api_crawler.py    # 나라장터 Open API (입찰공고)
│   ├── g2b_pre_spec_crawler.py # 나라장터 사전규격
│   ├── iris_crawler.py       # IRIS (한국연구재단)
│   ├── lh_api_crawler.py     # LH 공사
│   ├── koica_api_crawler.py  # KOICA
│   ├── kosmes_crawler.py     # 중소기업진흥공단
│   ├── sbiz24_crawler.py     # 소상공인시장진흥공단
│   ├── smb24_api_crawler.py  # 중소기업24
│   ├── seoul_contract_crawler.py # 서울시 계약
│   ├── kist_bid_crawler.py   # KIST 입찰
│   ├── kist_notice_crawler.py # KIST 공지
│   ├── rss_crawler.py        # RSS 피드 범용
│   ├── generic_crawler.py    # 범용 HTML 크롤러
│   └── ...
│
├── templates/
│   ├── base.html             # 공통 레이아웃 (Nav 2행 구조)
│   ├── dashboard.html        # 메인화면
│   ├── search.html           # 상세검색 (접이식 상세옵션)
│   ├── detail.html           # 공고 상세 (AI분석, 수행이력, 메모)
│   ├── bookmarks.html        # 관심공고
│   ├── filters.html          # 필터 관리
│   ├── admin_users.html      # 회원 관리
│   ├── settings.html         # 시스템 설정
│   ├── logs.html             # 크롤링 로그
│   └── login.html            # 로그인
│
├── static/
│   ├── css/style.css         # 공통 CSS (Tailwind 커스텀 컴포넌트)
│   └── js/
│       ├── search.js         # 검색 페이지 JS (필터, 결과 렌더링)
│       ├── dashboard.js      # 대시보드 JS
│       ├── bookmarks.js      # 관심공고 JS
│       ├── filters.js        # 필터 관리 JS
│       ├── settings.js       # 설정 JS
│       └── logs.js           # 로그 JS
│
├── data/
│   ├── tenders.db            # SQLite DB (git 제외)
│   └── settings.json         # 런타임 설정 (API 키 등, git 제외)
│
└── CLAUDE.md                 # Claude Code 협업 규칙 (반드시 읽을 것)
```

---

## 4. DB 모델 요약

| 테이블 | 설명 | 주요 컬럼 |
|---|---|---|
| `tenders` | 공고 원본 | title, agency, tender_number, status, estimated_price, source_site |
| `users` | 사용자 | username, password_hash, role(admin/moderator/user), nickname |
| `user_preferences` | 사용자 관심 키워드/예산 | interest_keywords(JSON), exclude_keywords(JSON), budget_min/max |
| `bookmarks` | 북마크 | tender_id, user_id, label, user_note |
| `filters` | 필터 프리셋 | user_id, name, include_keywords(JSON), is_default |
| `tender_memos` | 공유 메모 | tender_id, user_id, content |
| `tender_analyses` | AI 분석 캐시 | tender_id, gemini_sections(JSON), rule_extract(JSON), model_used |
| `dismissed_tenders` | 관심없음 처리 | user_id, tender_id |
| `agency_weights` | 기관별 가중치 | user_id, agency_name, weight(0~10) |
| `crawl_logs` | 크롤링 이력 | started_at, total_found, new_tenders, site_results(JSON) |

> **User 삭제 시 cascade**: user_preferences, bookmarks, tender_memos,
> dismissed_tenders, agency_weights 모두 `cascade='all, delete-orphan'`
> 설정됨 (2026-05-19 수정 완료).

---

## 5. 주요 API 엔드포인트

### 검색
```
GET  /api/tenders?include_keywords=AI+교육&status=일반&page=1
GET  /api/interest-keywords          # 로그인 사용자 관심 키워드
GET  /api/tenders/<id>/history       # 수행이력 조회 (G2B API)
```

### AI 분석
```
POST /api/analysis/<tender_id>       # AI 분석 실행 (force=1 → 재분석)
GET  /api/analysis/<tender_id>       # 분석 결과 조회
```

### 관리
```
GET  /api/admin/users                # 회원 목록
POST /api/admin/users                # 회원 추가
DELETE /api/admin/users/<id>         # 회원 삭제
GET  /api/crawl/status               # 크롤링 현황
POST /api/crawl/run                  # 수동 크롤링
```

---

## 6. 최근 주요 변경 이력 (2026-05-19 기준)

### 6-1. 내비게이션 2행 구조 (base.html)
PC(lg+) 화면에서 네비게이션을 2행으로 재구성:
- **1행**: 로고 | 둥근 검색창(`navSearch()`) | 사용자명/로그아웃
- **2행**: 메뉴 링크 (메인화면, 상세검색, 관심공고, 필터관리, 회원관리, 설정, 로그)
- 모바일(< lg): 기존 단일행 레이아웃 유지

`navSearch()` 함수: 검색창 Enter/버튼 → `/search?include_keywords=<값>` 이동

### 6-2. 상세검색 페이지 개편 (search.html + search.js)
- 히어로(초기 화면) 제거 → `/search` 접속 시 바로 검색 폼 표시
- "공고 검색" / "검색 조건" 제목 제거
- "포함 키워드" → "키워드 검색" 으로 이름 변경
- "관심 키워드로 검색" 버튼을 입력창 오른쪽에 인라인 배치
- 상세 검색 옵션(제외 키워드, 공고상태, 금액, 지역, 수요기관, 날짜) 기본 접힘
- "상세 검색 옵션 ▼" 토글 버튼으로 펼침/접힘
- 모바일 드로어 진입 시 상세 옵션 자동 펼침
- URL 파라미터 `include_keywords` 자동 처리 (nav 검색 → 자동 검색 실행)

### 6-3. 수행이력 조회 개선 (routes/tenders.py)
**문제**: "AI·디지털 실생활" 같은 중점(·) 복합어 제목에서 연도가 바뀌면
뒤 단어가 변경되어 연도별 동일 사업 매칭 실패

**해결**: 이중 쿼리 전략
```python
_dot_extras = set(_re.findall(r'[가-힣A-Za-z0-9]+·([가-힣A-Za-z0-9]+)', clean))
query_nm_alt = _pick_query(_clean_words, _dot_extras)  # 중점 뒤 단어 제외한 쿼리
_queries = [query_nm] if query_nm_alt == query_nm else [query_nm, query_nm_alt]
# 주 쿼리 0건 + 쿼리 2개 이상일 때만 보조 쿼리 실행
```

**G2B API 레이트 리밋 최적화**:
- 조회 범위: 5년(60개월) → **3년(36개월)**으로 축소
- 동시 요청 workers: 40 → **20**으로 감소
- 429 응답 수신 시 재시도 없이 즉시 중단 (`return [], '할당량초과(429)'`)
- 총 최대 요청 수: 360회 → **72회**로 감소

### 6-4. Gemini AI 오류 메시지 개선 (document_analyzer.py)
모든 모델 실패를 "할당량 초과"로 표시하던 문제 수정:
- 503 → "Gemini 서버 과부하"
- 429 → "일일 무료 할당량 초과"
- 404 → "구모델 지원 중단" 안내 추가

사용 모델 목록 (1.5 시리즈 제거 — 현재 API에서 404):
```python
_MODEL_ORDERS = {
    'speed':    ['gemini-2.0-flash-lite', 'gemini-2.0-flash', 'gemini-2.5-flash'],
    'balanced': ['gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-2.5-flash'],
    'quality':  ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-2.0-flash-lite'],
}
```

### 6-5. 회원 삭제 오류 수정 (database.py)
SQLite NOT NULL constraint 오류 해결 — User 모델의 모든 자식 관계에
`cascade='all, delete-orphan'` 추가:
- `TenderMemo.user` backref
- `UserPreference.user` backref
- `AgencyWeight.user` backref
- `DismissedTender.user` backref (관계 자체가 누락되어 신규 추가)

---

## 7. CLAUDE.md 핵심 규칙 요약

> **전체 규칙은 `CLAUDE.md`를 직접 읽을 것** — 아래는 요약만.

### 서버 재시작 자동화
다음 파일 수정 후 **반드시 자동으로 서버 재시작**:
`routes/*.py`, `crawlers/*.py`, `scheduler.py`, `app.py`, `database.py`, `document_analyzer.py`

```bash
# 재시작 명령
OLD_PID=$(netstat -ano 2>/dev/null | grep ':5002' | grep LISTENING | awk '{print $NF}' | head -1)
[ -n "$OLD_PID" ] && cmd /c "taskkill /PID $OLD_PID /F"
cd /c/Users/USER/Searcher
nohup python app.py > server_restart.log 2>&1 &
curl -s -o /dev/null -w "%{http_code}" http://localhost:5002/
# 302 또는 200 → 정상
```

> Windows Git Bash에서 `/F` 같은 플래그는 경로로 해석됨.
> 반드시 `cmd /c "taskkill /PID $PID /F"` 형식 사용.

### G2B API 레이트 리밋
- **절대 금지**: 날짜를 월별로 쪼개서 60~120개 요청 동시 발송
- **올바른 방법**: 36개월, workers=20, 429 즉시 중단
- 테스트는 단일 요청으로만

---

## 8. 개발 환경 & 서버 실행

### 환경
- Windows 11, Python 3.11+
- Git Bash (bash, Unix 경로 사용)
- VS Code + Claude Code 확장

### 서버 시작
```bash
cd /c/Users/USER/Searcher
python app.py
# 또는 백그라운드:
nohup python app.py > server_restart.log 2>&1 &
```

### 설정 파일
`data/settings.json` — Gemini API 키, G2B API 키, 이메일 설정 등
(git에서 제외됨. 관리자에게 직접 요청)

---

## 9. 현재 알려진 이슈 / 다음 작업 후보

| 항목 | 상태 | 메모 |
|---|---|---|
| 상세검색 URL 파라미터 처리 | 완료 | `include_keywords` param → 자동 검색 |
| 모바일 드로어 닫힘 시 상세옵션 상태 | 미처리 | 드로어 닫고 PC로 전환 시 `_advancedOpen` 상태와 DOM 불일치 가능 |
| G2B API 1개월 제한 | 확인됨 | `inqryBgnDt`~`inqryEndDt` 최대 1개월 (초과 시 errorCode "07") |
| Gemini 무료 할당량 | 확인됨 | 2.0-flash 일 1500건, 2.5-flash 일 50건 (한국시간 오후 4~5시 충전) |
| 크롤러 신규 추가 | 미완 | `generic_crawler.py` 활용해 추가 가능 |

---

## 10. 작업 시 주의사항

1. **CLAUDE.md를 항상 먼저 읽을 것** — 서버 재시작, API 레이트 리밋 규칙 포함
2. **템플릿(.html) 수정** → 서버 재시작 불필요 (Flask `TEMPLATES_AUTO_RELOAD=True`)
3. **routes/, database.py 등 수정** → 반드시 서버 재시작
4. **크롤러 수정** → 서버 재시작 필수 (런타임 인스턴스 캐싱 때문)
5. **G2B API 테스트** → 단일 요청만. 루프·배치 절대 금지 (일일 할당량)
6. **Windows Git Bash** → `/F`, `/B` 등 플래그는 `cmd /c "..."` 로 감싸야 함
7. **Gemini 재분석** → `force=1` 파라미터 불필요하게 사용 금지 (할당량 소모)
