# 크롤러 설정 가이드

## 전역 기본 설정

모든 크롤러에 적용되는 기본 수집 기준을 설정할 수 있습니다.

### 설정 파일 위치
`data/settings.json`

### 전역 기본값 설정

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

**설정 항목:**
- `days_range`: 조회 기간 (일 단위, 기본값: 7일)
- `num_of_rows`: 페이지당 수집 건수 (기본값: 100건)
- `max_pages`: 최대 수집 페이지 수 (null = 제한 없음)
- `max_items`: RSS 피드 최대 항목 수 (기본값: 20개)
- `enabled`: 크롤러 활성화 여부 (기본값: true)

---

## 개별 크롤러 설정

특정 크롤러만 다른 설정을 사용하려면 개별 크롤러 설정에서 값을 지정하세요.
개별 설정이 전역 기본값을 덮어씁니다.

### 예시 1: 나라장터 사전규격 (7일 수집)

```json
{
  "crawl": {
    "sites": {
      "g2b_pre_spec": {
        "crawler_type": "pre_spec",
        "days_range": 7,
        "num_of_rows": 100,
        "name": "나라장터 사전규격 (용역)"
      }
    }
  }
}
```

### 예시 2: 행정안전부 대통령공고 (4년 수집)

대통령공고는 발행 빈도가 낮아 긴 조회 기간을 사용합니다.

```json
{
  "crawl": {
    "sites": {
      "mois_predece": {
        "crawler_type": "mois_predece",
        "days_range": 1460,
        "num_of_rows": 100,
        "name": "행정안전부 대통령공고"
      }
    }
  }
}
```

---

## 설정 변경 방법

### 1. 전역 기본값 변경

모든 크롤러의 조회 기간을 14일로 변경:

```json
{
  "crawl": {
    "global_defaults": {
      "days_range": 14,
      "num_of_rows": 100
    }
  }
}
```

### 2. 특정 크롤러만 변경

LH 입찰정보만 30일로 변경:

```json
{
  "crawl": {
    "sites": {
      "lh_api": {
        "crawler_type": "lh_api",
        "days_range": 30,
        "num_of_rows": 100
      }
    }
  }
}
```

---

## 크롤러 타입별 적용 가능 설정

| 크롤러 타입 | days_range | num_of_rows | max_pages | max_items |
|------------|------------|-------------|-----------|-----------|
| api (나라장터 API) | O | O | - | - |
| pre_spec (사전규격) | O | O | - | - |
| lh_api (LH API) | O | O | - | - |
| smb24_api (중소벤처24) | O | O | - | - |
| mois_predece (대통령공고) | O | O | - | - |
| kist_bid (KIST API) | O | O | - | - |
| koica_api (KOICA API) | O | O | - | - |
| rss (RSS 피드) | - | - | - | O |
| kist_notice (KIST 공지) | - | - | O | - |
| iris (IRIS) | - | - | - | - |
| generic (일반) | - | - | O | - |

---

## 프로그래밍 방식 사용

Python 코드에서 전역 기본값을 포함한 설정을 가져오는 방법:

```python
from settings_manager import settings_manager

# 전역 기본값과 병합된 크롤러 설정 가져오기
config = settings_manager.get_crawler_config('g2b_api')

# config에는 전역 기본값과 개별 설정이 병합되어 있음
print(config['days_range'])  # 7 (전역 기본값 또는 개별 설정)
print(config['num_of_rows']) # 100
```

### 크롤러 구현 예시

```python
from settings_manager import settings_manager

class MyApiCrawler:
    def __init__(self, site_config):
        # 전역 기본값과 병합
        self.config = settings_manager.get_crawler_config(
            'my_api',
            site_config
        )

        # 설정 사용
        self.days_range = self.config.get('days_range', 7)
        self.num_of_rows = self.config.get('num_of_rows', 100)

    def crawl(self):
        # 설정된 days_range 사용
        print(f"최근 {self.days_range}일 데이터 수집")
```

---

## 자동 크롤링 스케줄 변경

크롤링 실행 시간을 변경하려면:

```json
{
  "crawl": {
    "auto_enabled": true,
    "times": [
      "06:00",
      "12:00",
      "18:00"
    ]
  }
}
```

---

## 참고사항

1. **설정 파일 백업**: 설정 변경 전 `data/settings.json` 파일을 백업하세요.

2. **JSON 형식 검증**: JSON 형식이 올바른지 확인하세요.
   - 온라인 JSON 검증기: https://jsonlint.com/

3. **재시작 필요**: 설정 변경 후 서버를 재시작해야 적용됩니다.
   ```bash
   # 서버 중지
   Ctrl+C

   # 서버 재시작
   python app.py
   ```

4. **검증 스크립트**: 설정 변경 후 크롤러 동작을 확인하세요.
   ```bash
   python quick_validate_crawlers.py
   ```

---

## 문제 해결

### Q: 전역 기본값을 변경했는데 적용되지 않아요

A: 개별 크롤러 설정에서 동일한 항목을 지정하면 전역 기본값이 덮어씌워집니다.
   개별 설정에서 해당 항목을 제거하거나 원하는 값으로 변경하세요.

### Q: 특정 크롤러만 다른 조회 기간을 사용하고 싶어요

A: 해당 크롤러 설정에 `days_range`를 추가하세요.

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

### Q: RSS 크롤러에는 days_range가 적용되나요?

A: RSS 크롤러는 `max_items` 설정을 사용합니다. `days_range`는 API 기반 크롤러에만 적용됩니다.

---

## 추가 정보

- 크롤러 수집 기준: `CRAWLER_CRITERIA.md`
- 크롤러 검증: `validate_crawlers.py` 또는 `quick_validate_crawlers.py`
- 설정 관리 코드: `settings_manager.py`
