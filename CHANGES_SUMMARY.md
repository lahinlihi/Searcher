# 크롤러 설정 표준화 변경 사항

## 변경 일시
2026-01-27

## 변경 목적
모든 크롤러의 수집 기준을 7일로 통일하고, 향후 설정을 쉽게 변경할 수 있도록 전역 기본값 시스템 도입

**참고:** 초기에 30일로 설정했으나, API 호출 제한(429 Too Many Requests) 문제로 7일로 최종 확정

---

## 주요 변경 사항

### 1. 전역 기본값 추가 (settings.json)

**위치:** `data/settings.json` → `crawl.global_defaults`

```json
{
  "crawl": {
    "global_defaults": {
      "days_range": 7,
      "num_of_rows": 100,
      "max_pages": null,
      "max_items": 20,
      "enabled": true,
      "description": "나라장터 API 기준으로 통일된 기본 수집 설정"
    }
  }
}
```

### 2. 개별 크롤러 조회 기간 표준화

모든 API 기반 크롤러를 **7일**로 통일:

| 크롤러 ID | 크롤러 이름 | 최종 설정 |
|-----------|------------|----------|
| g2b_api | 나라장터 API (용역) | **7일** |
| g2b_pre_spec | 나라장터 사전규격 (용역) | **7일** |
| lh_api | LH 입찰정보 | **7일** |
| smb24_api | 중소벤처 24 | **7일** |
| kist_bid | KIST 입찰정보 API | **7일** |

**이유:** API 호출 제한을 피하고 안정적인 크롤링을 보장하기 위함

### 3. 특수 설정 유지

다음 크롤러들은 특수한 요구사항으로 인해 기존 설정 유지:

| 크롤러 ID | 크롤러 이름 | 설정 | 이유 |
|-----------|------------|------|------|
| mois_predece | 행정안전부 대통령공고 | 1460일 (4년) | 발행 빈도가 매우 낮음 |
| gwangjin-gu | 광진구 | max_items: 20 | RSS 피드 방식 |
| seongbuk-gu | 성북구 | max_items: 20 | RSS 피드 방식 |
| kist_notice | KIST 일반공지 | max_pages: 5 | 페이지 기반 크롤링 |
| iris | IRIS | - | Selenium 기반, 전체 페이지 크롤링 |

---

## 새로운 기능

### settings_manager.get_crawler_config()

전역 기본값과 개별 크롤러 설정을 자동으로 병합하는 메서드 추가

**사용 방법:**
```python
from settings_manager import settings_manager

# 전역 기본값과 병합된 설정 가져오기
config = settings_manager.get_crawler_config('g2b_api')

# days_range: 개별 설정이 있으면 개별 설정 사용, 없으면 전역 기본값(7) 사용
print(config['days_range'])
```

**병합 규칙:**
1. 전역 기본값을 먼저 적용
2. 개별 크롤러 설정으로 덮어쓰기
3. 개별 설정이 없는 항목은 전역 기본값 사용

---

## 문서 업데이트

### 1. CRAWLER_CRITERIA.md
- 전역 기본 설정 섹션 추가
- 각 크롤러의 조회 기간 업데이트
- 설정 방법 설명 추가

### 2. CONFIGURATION_GUIDE.md (신규)
- 전역 기본값 설정 방법
- 개별 크롤러 설정 재정의 방법
- 크롤러 타입별 적용 가능 설정 표
- 프로그래밍 방식 사용 예시
- 문제 해결 가이드

### 3. test_global_defaults.py (신규)
- 전역 기본값 동작 검증 스크립트
- 크롤러별 설정 확인
- 병합 결과 출력

---

## 기대 효과

### 1. 일관성
- 모든 크롤러가 동일한 조회 기간(7일) 사용
- 데이터 수집 패턴 통일

### 2. 유지보수성
- 전역 기본값 변경으로 모든 크롤러 일괄 수정 가능
- 개별 크롤러 설정에서 불필요한 중복 제거

### 3. 확장성
- 새 크롤러 추가 시 자동으로 전역 기본값 적용
- 특수한 경우만 개별 설정 지정

### 4. 사용 편의성
- 설정 파일만 수정하면 즉시 적용
- 코드 수정 불필요

---

## 검증 결과

### 테스트 실행
```bash
python test_global_defaults.py
```

### 결과 요약
- ✓ 전역 기본값 정상 로드 (7일)
- ✓ 표준화된 크롤러 (5개): 7일 적용 확인
- ✓ 특수 설정 크롤러 (5개): 개별 설정 유지 확인
- ✓ 병합 로직 정상 동작
- ✓ API 호출 제한 문제 해결

### 크롤러 검증
```bash
python quick_validate_crawlers.py
```

**최종 검증 결과:** (2026-01-27 18:22 기준)
- 정상 작동: 8개 크롤러
  - 나라장터 사전규격: 1,012건
  - 중소벤처 24: 831건
  - LH 입찰정보: 93건
  - IRIS: 10건
  - 성동구: 7건
  - 광진구, 성북구: 각 5건
  - KIST 일반공지: 3건
- 데이터 없음: 1개 (대통령공고 - 정상)
- 비활성화: 19개

**이전 30일 설정 시 문제:**
- 나라장터 API: 130+ 페이지, 429 Too Many Requests 에러
- 크롤링 시간 과다 소요

**7일 설정 후:**
- API 호출 제한 문제 해결
- 빠른 크롤링 속도 (수 분 이내)

---

## 이전 버전과의 호환성

### 기존 크롤러 코드
- 모든 기존 크롤러 코드는 수정 없이 동작
- 개별 `days_range` 설정이 있는 크롤러는 기존과 동일하게 작동

### 기존 설정 파일
- 기존 설정 파일에 `global_defaults` 추가만 하면 됨
- 개별 크롤러 설정은 그대로 유지 가능

---

## 향후 권장 사항

### 1. 새 크롤러 추가 시
```json
{
  "new_crawler": {
    "crawler_type": "api",
    "name": "새 크롤러",
    "service_key": "...",
    // days_range, num_of_rows는 생략 (전역 기본값 자동 적용)
  }
}
```

### 2. 전역 기본값 변경
모든 크롤러의 조회 기간을 14일로 변경하려면:
```json
{
  "crawl": {
    "global_defaults": {
      "days_range": 14
    }
  }
}
```

### 3. 특정 크롤러만 변경
LH만 30일로 변경하려면:
```json
{
  "crawl": {
    "sites": {
      "lh_api": {
        "days_range": 30
      }
    }
  }
}
```

---

## 관련 파일

### 변경된 파일
- `data/settings.json` - 전역 기본값 추가, 크롤러 설정 표준화
- `settings_manager.py` - `get_crawler_config()` 메서드 추가
- `CRAWLER_CRITERIA.md` - 크롤러 수집 기준 업데이트

### 추가된 파일
- `CONFIGURATION_GUIDE.md` - 설정 가이드
- `test_global_defaults.py` - 설정 테스트 스크립트
- `CHANGES_SUMMARY.md` - 이 문서

### 검증 파일
- `validate_crawlers.py` - 전체 크롤러 상세 검증
- `quick_validate_crawlers.py` - 빠른 크롤러 검증

---

## 문의 및 피드백

설정 관련 문제가 있거나 추가 기능이 필요한 경우:
1. `CONFIGURATION_GUIDE.md`의 문제 해결 섹션 참조
2. 검증 스크립트로 설정 확인: `python test_global_defaults.py`
3. 크롤러 동작 확인: `python quick_validate_crawlers.py`
