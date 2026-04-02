# 입찰 공고 대시보드

나라장터(G2B), IRIS, LH, 중소벤처24 등 주요 공공기관 입찰 공고를 자동 수집·분석하는 대시보드.

---

## 팀원 배포 가이드

### 사전 준비 (한 번만)

| 항목 | 설치 방법 | 비고 |
|------|-----------|------|
| **Docker Desktop** | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop) | 설치 후 실행 필수 |
| **Git** | [git-scm.com](https://git-scm.com) | 이미 있으면 생략 |
| **settings.json** | 관리자에게 직접 요청 | API 키 포함 파일 |

> **Gemini API 키**는 개인 발급을 권장합니다 → [aistudio.google.com](https://aistudio.google.com) (무료, 5분 소요)

---

### 설치 (3단계)

**1. 저장소 클론**
```
git clone https://github.com/lahinlihi/Searcher.git
cd Searcher
```

**2. 관리자에게 받은 settings.json 을 data 폴더에 복사**
```
data\settings.json   ← 여기에 붙여넣기
```

**3. setup.bat 더블클릭**

설치가 완료되면 브라우저에서 자동으로 열립니다 → `http://localhost:5002`

---

### 이후 업데이트

새 기능이 추가되거나 크롤러가 수정되면:

```
docker_update.bat 더블클릭
```

자동으로 최신 코드를 받아 재시작합니다.

---

### 개인 설정

`data\settings.json` 에서 본인만의 설정을 변경할 수 있습니다:

| 항목 | 위치 | 설명 |
|------|------|------|
| 관심 키워드 | `user_preferences.interest_keywords` | 대시보드 하이라이트 |
| 제외 키워드 | `user_preferences.exclude_keywords` | 필터링 |
| 크롤링 시간 | `crawl.times` | 기본 `["09:00","17:00"]` |
| 크롤링 사이트 | `crawl.sites.*.enabled` | 사이트별 온/오프 |
| Gemini API 키 | `gemini_api_key` | AI 공고 분석 기능 |

---

### 폴더 구조

```
Searcher/
├── data/                   ← Git 제외 (개인 데이터)
│   ├── settings.json       ← API 키 + 개인 설정 (관리자에게 받기)
│   └── tenders.db          ← 크롤링 데이터 (자동 생성)
├── crawlers/               ← 크롤러 코드 (Git 공유)
├── templates/              ← 화면 템플릿 (Git 공유)
├── setup.bat               ← 최초 설치
├── docker_update.bat       ← 업데이트
└── docker-compose.yml
```

---

### 문제 해결

| 증상 | 해결 |
|------|------|
| `http://localhost:5002` 접속 안 됨 | Docker Desktop 실행 여부 확인, `docker compose ps` |
| 크롤링이 안 됨 | `data\settings.json` 의 API 키 확인 |
| 업데이트 후 화면이 이상함 | 브라우저 강력 새로고침 (Ctrl+Shift+R) |
| Docker 빌드 실패 | `docker compose logs` 로 오류 확인 |
