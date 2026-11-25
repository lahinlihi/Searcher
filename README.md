# 입찰 공고 대시보드

나라장터(G2B), IRIS, LH, 중소벤처24 등 주요 공공기관 입찰 공고를 자동 수집·분석하는 대시보드.

---

## 주요 기능

| 기능 | 화면 | 설명 |
|------|------|------|
| 대시보드 | `/` | 사전규격·신규공고(나라장터·기타 채널)를 관심 키워드로 거르고 적합도순으로 탭마다 15건. 열어 본 공고는 "읽은 공고"로 빠진다 |
| 적합도 (100점) | 모든 목록·상세 | "일이 우리와 맞는가"만 말한다. (키워드 + 사업유형)을 100점으로 환산 → 담은 공고가 5건 이상이면 "담은 공고와 닮은 정도"와 평균. 발주처는 들어가지 않는다. 어느 화면에서나 같은 공고는 같은 점수. 색은 30점 빨강 → 60점 노랑 → 90점 녹색 고정 |
| 발주처 표시 | `/filters` | 발주처마다 중점 또는 후순위를 고른다(점수와 별도, 이름은 두 글자 이상). 중점은 공고에 "중점 발주처"가 표시되고 같은 점수면 위로, 후순위는 "후순위 발주처"로 표시해 목록 맨 아래로 보낸다(숨기지 않는다) |
| 중점 발주처 | `/` 의 탭 | 중점으로 등록한 발주처의 아직 안 본 공고를 적합도·관심 키워드와 상관없이 발주처별로 묶어 15건. 적합도는 일 기준 그대로 보인다 |
| 키워드엔 없지만 비슷한 공고 | `/` 의 탭 | 관심 키워드에는 안 걸렸지만 고른 공고(사례)와 비슷한 공고. [좋음]은 사례로 추가, [아님]은 관심없음 |
| 놓친 공고 신고 | `/cases` | 공고번호·주소·제목을 넣으면 그 공고가 수집 시점의 대시보드 어디에서 빠졌는지(수집 안 됨 / 묶임 / 걸러짐 / 순위 낮음) 답하고, 정답 목록에 넣을 수 있다 |
| 채점 | `/cases` | 정답 목록(북마크 + 신고 공고)이 사례를 섞기 전 점수와 사례 점수에서 각각 몇 등인지 잰다 |
| 상세검색·관심공고·검토공고 | `/search`, `/bookmarks`, `/review-tenders` | |

설계와 근거: `docs/product-contract.md` (1부 사례 점수, 3부 적합도 재정리). 구현 계획: `docs/superpowers/plans/`

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
│   ├── tenders.db          ← 크롤링 데이터 (자동 생성)
│   └── vectors.db          ← 공고 제목 벡터 (사례 점수용, 크롤 뒤 자동 저장)
├── crawlers/               ← 크롤러 코드 (Git 공유)
├── routes/                 ← API·페이지 (cases.py = 놓친 공고·사례·채점)
├── templates/              ← 화면 템플릿 (Git 공유)
├── scoring.py              ← 키워드·사업유형 원점수 (규칙), 관심 설정 읽기
├── relevance.py            ← 적합도(100점 눈금): 원점수 환산 + 사례 50% 혼합. 발주처 표시와 목록 순서(rank_key). 모든 화면이 Scorer 를 지난다
├── tools/agency_mark_migrate.py ← 예전 발주처 가중치(0~10)를 중점/후순위 표시로 옮기는 도구 (기본은 표만 출력)
├── case_store.py           ← 사례·신고·채점 이력 저장
├── case_scoring.py         ← 사례 점수 (비슷한 사례 3건 평균 유사도)
├── case_eval.py            ← 채점
├── missed_diagnosis.py     ← 놓친 공고 진단
├── tender_vectors.py       ← 제목 벡터 저장소 (일괄 채우기: python -u tender_vectors.py --backfill)
├── tests/                  ← pytest (python -m pytest tests)
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
