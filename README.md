# 입찰공고 통합 검색 시스템

로컬 서버에서 실행되는 정부 입찰공고 통합 검색 웹 대시보드입니다.

## 주요 기능

- **대시보드**: 신규 공고, 사전규격, 마감 임박 공고 요약
- **검색**: 키워드 기반 공고 검색 및 필터링
- **필터 관리**: 자주 사용하는 검색 조건 프리셋 저장
- **통계**: 기관별, 일별 공고 통계 차트
- **자동 크롤링**: 예약된 시간에 자동으로 공고 수집 (Phase 2)

## 기술 스택

### 백엔드
- Flask 3.0
- SQLAlchemy (SQLite)
- APScheduler (백그라운드 크롤링)
- Selenium + BeautifulSoup (크롤링)

### 프론트엔드
- HTML/CSS/JavaScript
- Tailwind CSS
- Chart.js
- jQuery

## 설치 방법

### 1. 필수 요구사항
- Python 3.8 이상
- pip

### 2. 의존성 설치

```bash
cd tender_dashboard
pip install -r requirements.txt
```

### 3. 실행

#### 방법 1: 간편 실행 (권장)
```bash
# 콘솔 창과 함께 실행 (로그 확인 가능)
start_server.bat 더블클릭

# 또는 백그라운드로 조용히 실행
start_server_background.vbs 더블클릭
```

#### 방법 2: 직접 실행
```bash
python app.py
```

브라우저에서 `http://localhost:5000` 접속

#### 자동 시작 설정
컴퓨터를 켤 때마다 자동으로 서버가 실행되도록 설정하려면:
- 📖 `QUICK_START.md` - 빠른 시작 가이드
- 📖 `AUTO_START_GUIDE.md` - 자동 시작 설정 상세 가이드 참고

#### 서버 관리
```bash
check_server.bat   # 서버 상태 확인
stop_server.bat    # 서버 중지
```

## 사용 방법

### 자동 크롤링
서버 시작 시 자동으로 스케줄러가 활성화되며, 매일 정해진 시간에 크롤링을 수행합니다.
- 오전 09:00
- 오후 17:00

크롤링된 결과는 자동으로 DB에 저장되며, 중복 공고는 자동으로 제거됩니다.

### 수동 크롤링
검색 페이지(`/search`)에서 "실시간 크롤링 시작" 버튼을 클릭하면 즉시 크롤링이 시작됩니다.
- 나라장터, LH, 한국전력 사이트에서 공고 수집
- 중복 제거 후 DB 저장
- 완료되면 자동으로 결과 표시

### 필터링
- 검색 페이지에서 키워드, 가격, 상태 등으로 필터링 가능
- 필터 프리셋 저장/관리 기능 제공

## 프로젝트 구조

```
tender_dashboard/
├── app.py                          # Flask 메인 애플리케이션
├── config.py                       # 설정 파일
├── database.py                     # DB 모델 및 초기화
├── scheduler.py                    # 크롤링 스케줄러
├── deduplication.py                # 중복 제거 로직
├── filters.py                      # 필터링 로직
├── requirements.txt                # Python 의존성
│
├── start_server.bat                # 서버 시작 (콘솔 창)
├── start_server_background.vbs     # 서버 시작 (백그라운드)
├── stop_server.bat                 # 서버 중지
├── check_server.bat                # 서버 상태 확인
│
├── README.md                       # 프로젝트 전체 문서
├── QUICK_START.md                  # 빠른 시작 가이드
├── AUTO_START_GUIDE.md             # 자동 시작 설정 가이드
├── CRAWLER_STATUS.md               # 크롤러 현황
│
├── crawlers/                       # 크롤러 모듈
│   ├── base_crawler.py
│   ├── g2b_api_crawler.py          # 나라장터 API
│   ├── g2b_pre_spec_crawler.py     # 사전규격 API
│   ├── generic_crawler.py          # 통합 크롤러
│   └── sungdonggu_crawler.py
│
├── templates/                      # HTML 템플릿
│   ├── base.html
│   ├── dashboard.html
│   ├── search.html
│   ├── filters.html
│   ├── settings.html
│   └── logs.html
│
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── dashboard.js
│       ├── search.js
│       ├── filters.js
│       ├── settings.js
│       └── logs.js
│
├── data/
│   ├── tenders.db                  # SQLite 데이터베이스
│   └── settings.json               # 사이트 설정
│
└── logs/                           # 로그 파일
```

## API 엔드포인트

### 페이지
- `GET /` - 메인 대시보드
- `GET /search` - 검색 페이지
- `GET /filters` - 필터 관리 페이지
- `GET /settings` - 설정 페이지
- `GET /logs` - 로그 페이지

### API
**기본 API**
- `GET /api/dashboard` - 대시보드 데이터
- `GET /api/tenders` - 공고 목록 (필터링, 페이징)
- `GET /api/filters` - 필터 프리셋 목록
- `POST /api/filters` - 새 필터 저장
- `PUT /api/filters/:id` - 필터 수정
- `DELETE /api/filters/:id` - 필터 삭제
- `GET /api/logs` - 크롤링 로그
- `GET /api/stats` - 통계 데이터

**크롤링 API (Phase 2)**
- `POST /api/search` - 수동 크롤링 시작
- `GET /api/crawl/status` - 크롤링 상태 조회

**데이터 관리 API (Phase 3)**
- `POST /api/data/delete-old` - 오래된 공고 삭제
- `POST /api/data/reset` - 데이터베이스 초기화
- `GET /api/data/stats` - 데이터베이스 통계
- `POST /api/data/cleanup` - 중복 공고 정리

**Excel 내보내기 API (Phase 3)**
- `GET /api/export/csv` - CSV로 내보내기
- `GET /api/export/excel` - Excel HTML로 내보내기

**설정 관리 API (Phase 3)**
- `GET /api/settings` - 설정 조회
- `POST /api/settings` - 설정 저장
- `POST /api/settings/validate` - 설정 유효성 검사

## 개발 로드맵

### Phase 1: 백엔드 기본 구조 ✅ (완료)
- Flask 앱 설정
- SQLite DB 및 모델
- 기본 API 엔드포인트
- 프론트엔드 기본 UI

### Phase 2: 크롤링 로직 ✅ (완료)
- 나라장터 크롤러 (샘플 데이터 생성)
- LH, 한국전력 크롤러 (샘플)
- 필터링 & 중복 제거
- 스케줄러 연동 (매일 09:00, 17:00 자동 크롤링)
- 실시간 검색 기능 (수동 크롤링 버튼)

### Phase 3: 고급 기능 ✅ (완료)
- 이메일 알림 기능 (SMTP 기반)
- 데이터 관리 기능
  - 오래된 공고 삭제
  - 데이터베이스 초기화
  - 중복 공고 정리
  - 데이터베이스 통계
- Excel/CSV 내보내기
- 설정 저장/불러오기 (JSON 기반)

### Phase 4: 추가 기능 (선택)
- 실제 나라장터 API 연동
- 웹소켓 실시간 업데이트
- 추가 크롤링 사이트

### Phase 5: React 업그레이드 (선택)
- React로 프론트엔드 재작성
- 더 나은 UX/UI

## 데이터베이스 스키마

### tenders (공고)
- id, title, agency, tender_number
- announced_date, deadline_date, opening_date
- estimated_price, bid_method
- status (일반/사전규격)
- source_site, url
- created_at, is_duplicate

### filters (필터 프리셋)
- id, name, is_default
- include_keywords, exclude_keywords
- regions, categories
- min_price, max_price
- days_before_deadline

### crawl_logs (크롤링 로그)
- id, started_at, completed_at
- total_found, new_tenders
- site_results, status, error_message

### bookmarks (즐겨찾기)
- id, tender_id, user_note, created_at

## 설정

`config.py`에서 다음 설정을 변경할 수 있습니다:

- `HOST`: 서버 호스트 (기본: 0.0.0.0)
- `PORT`: 서버 포트 (기본: 5000)
- `CRAWL_TIMES`: 자동 크롤링 시간
- `DATA_RETENTION_DAYS`: 데이터 보관 기간

## 주의사항

- 로컬에서만 실행되므로 인증 기능이 없습니다
- **현재 크롤러는 샘플 데이터 생성 모드**로 작동합니다
  - 실제 나라장터 API나 웹사이트에서 데이터를 가져오지 않습니다
  - 실제 환경에서 사용하려면 `crawlers/g2b_crawler.py`의 `_generate_sample_data()` 메서드를 실제 크롤링 로직으로 교체해야 합니다
- 실제 크롤링 시:
  - 대상 사이트의 이용약관을 반드시 준수하세요
  - 나라장터 API 사용을 권장합니다 (공식 API 제공)
  - 과도한 크롤링은 서버에 부하를 주고 IP 차단될 수 있습니다
  - robots.txt를 확인하고 준수하세요

## 라이선스

개인 사용 목적으로 자유롭게 사용 가능합니다.

## 문의

문제가 발생하면 이슈를 등록해주세요.
