# 입찰공고 시스템 자동 시작 설정 가이드 (개선판)

컴퓨터를 켤 때마다 자동으로 Flask 서버가 실행되도록 설정하는 방법입니다.

## 🚀 간단 설치 (권장)

### 1단계: 설치 스크립트 실행
**`install_auto_start_improved.bat`** 파일을 **관리자 권한으로** 더블클릭합니다.

### 2단계: 방법 선택
두 가지 방법 중 선택할 수 있습니다:

**방법 1: 시작 프로그램 폴더** (간단)
- 장점: 설치가 간단함
- 단점: 로그인해야만 실행됨
- 추천 대상: 개인 PC

**방법 2: 작업 스케줄러** (권장)
- 장점: 부팅 시 자동 실행, 더 안정적
- 단점: 관리자 권한 필요
- 추천 대상: 항상 실행해야 하는 경우

### 3단계: 테스트
설치 후 즉시 테스트하거나, 컴퓨터를 재시작하여 확인합니다.

브라우저에서 `http://localhost:5001` 접속

---

## ✅ 확인 방법

### 자동 시작 설정 확인
**`test_auto_start.bat`** 실행

이 스크립트는 자동으로:
- 시작 프로그램 폴더 확인
- 작업 스케줄러 작업 확인
- 서버 실행 상태 확인
- 포트 5001 사용 확인

### 서버 실행 상태 확인
**`check_server.bat`** 실행

---

## 🔧 문제 해결

### 서버가 자동으로 시작되지 않는 경우

#### 1. Python 경로 문제
```batch
where python
```
결과가 나오지 않으면 Python이 PATH에 없는 것입니다.

**해결 방법:**
- Python을 재설치하며 "Add Python to PATH" 체크
- 또는 수동으로 환경변수에 추가

#### 2. 권한 문제
**해결 방법:**
- 배치 파일을 **관리자 권한으로** 실행
- 작업 스케줄러 설정에서 "가장 높은 수준의 권한으로 실행" 확인

#### 3. 포트 충돌 (5001 포트)
```batch
netstat -ano | findstr :5001
```

**해결 방법:**
- 다른 프로그램이 5001 포트를 사용 중이면 종료
- 또는 `config.py`에서 포트 번호 변경

#### 4. 스크립트 파일 문제
`start_server_background.vbs` 파일이 손상되었을 수 있습니다.

**해결 방법:**
- `install_auto_start_improved.bat`를 다시 실행
- 또는 프로젝트를 다시 다운로드

---

## 🗑️ 자동 시작 제거

**`uninstall_auto_start_improved.bat`** 실행

이 스크립트는 자동으로:
- 시작 프로그램 폴더의 바로가기 삭제
- 작업 스케줄러의 작업 삭제

---

## 📝 수동 설정 (고급)

### Windows 작업 스케줄러 수동 설정

1. `Win + R` → `taskschd.msc` 입력
2. "작업 만들기" 클릭
3. **일반 탭:**
   - 이름: TenderDashboard
   - ☑ 가장 높은 수준의 권한으로 실행
4. **트리거 탭:**
   - 새로 만들기 → "시작할 때" 선택
   - 지연 시간: 1분
5. **동작 탭:**
   - 프로그램/스크립트: `wscript.exe`
   - 인수 추가: `"D:\tender_dashboard\start_server_background.vbs"`
   - 시작 위치: `D:\tender_dashboard`
6. **조건 탭:**
   - ☐ AC 전원을 사용하는 경우에만 작업 시작 (체크 해제)
7. 확인 클릭

---

## 💡 추가 정보

### 로그 확인
서버 시작 오류가 발생하면 다음 위치에서 로그를 확인하세요:
```
D:\tender_dashboard\logs\startup_error.log
```

### 서버 수동 시작/중지
- **시작:** `start_server.bat` (콘솔 창 표시)
- **시작 (백그라운드):** `start_server_background.vbs`
- **중지:** `stop_server.bat`
- **상태 확인:** `check_server.bat`

### 크롤링 스케줄 변경
`config.py` 파일에서 `CRAWL_TIMES` 수정:
```python
CRAWL_TIMES = ['09:00', '17:00']  # 원하는 시간으로 변경
```

---

## 🆘 여전히 문제가 해결되지 않는 경우

다음 정보와 함께 문의하세요:

1. `test_auto_start.bat` 실행 결과
2. `logs/startup_error.log` 파일 내용
3. Python 버전 (`python --version`)
4. Windows 버전

---

## 🎯 빠른 참조

| 작업 | 파일 |
|------|------|
| 자동 시작 설치 | `install_auto_start_improved.bat` |
| 자동 시작 제거 | `uninstall_auto_start_improved.bat` |
| 설정 확인 및 테스트 | `test_auto_start.bat` |
| 서버 상태 확인 | `check_server.bat` |
| 서버 시작 (콘솔) | `start_server.bat` |
| 서버 시작 (백그라운드) | `start_server_background.vbs` |
| 서버 중지 | `stop_server.bat` |

모든 배치 파일은 **관리자 권한으로** 실행하는 것을 권장합니다.
