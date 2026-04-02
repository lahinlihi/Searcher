# 입찰공고 시스템 자동 시작 설정 가이드

컴퓨터를 켤 때마다 자동으로 Flask 서버가 실행되도록 설정하는 방법입니다.

## 📋 준비된 스크립트

### 1. `start_server.bat`
- **용도**: 서버를 시작하는 배치 파일 (콘솔 창 표시)
- **사용법**: 더블클릭하여 실행
- **특징**: 로그를 확인할 수 있는 콘솔 창이 나타남

### 2. `start_server_background.vbs`
- **용도**: 서버를 백그라운드에서 시작 (콘솔 창 없음)
- **사용법**: 더블클릭하여 실행
- **특징**: 조용히 백그라운드에서 실행

### 3. `stop_server.bat`
- **용도**: 실행 중인 서버를 중지
- **사용법**: 더블클릭하여 실행

### 4. `check_server.bat`
- **용도**: 서버 실행 상태 확인
- **사용법**: 더블클릭하여 실행

---

## 🚀 방법 1: Windows 작업 스케줄러 (권장)

**장점**: 가장 안정적이고 관리하기 쉬움

### 단계별 설정

#### 1단계: 작업 스케줄러 열기
1. `Win + R` 키를 누름
2. `taskschd.msc` 입력 후 Enter
3. 작업 스케줄러가 열림

#### 2단계: 새 작업 만들기
1. 오른쪽 패널에서 **"작업 만들기"** 클릭 (기본 작업이 아님!)

#### 3단계: 일반 탭 설정
```
이름: 입찰공고 시스템 자동 실행
설명: 부팅 시 Flask 서버 자동 시작
보안 옵션:
  ☑ 사용자의 로그온 여부에 관계없이 실행
  ☑ 가장 높은 수준의 권한으로 실행
```

#### 4단계: 트리거 탭 설정
1. **"새로 만들기"** 클릭
2. 작업 시작: **"시작할 때"** 선택
3. 고급 설정:
   - ☑ 사용
4. **확인** 클릭

#### 5단계: 동작 탭 설정
1. **"새로 만들기"** 클릭
2. 동작: **"프로그램 시작"** 선택
3. 프로그램/스크립트:
   ```
   D:\tender_dashboard\start_server_background.vbs
   ```
   또는 찾아보기로 선택
4. 시작 위치 (선택사항):
   ```
   D:\tender_dashboard
   ```
5. **확인** 클릭

#### 6단계: 조건 탭 설정
```
전원:
  ☐ AC 전원을 사용하는 경우에만 작업 시작 (체크 해제)
  ☐ 배터리 모드로 전환할 경우 중지 (체크 해제)
```

#### 7단계: 설정 탭 설정
```
☑ 요청 시 작업 실행 허용
☑ 작업이 실패하면 다시 시작 간격: 1분
```

#### 8단계: 저장
1. **확인** 클릭
2. Windows 계정 비밀번호 입력 (필요시)

### 테스트하기
1. 작업 스케줄러에서 방금 만든 작업을 우클릭
2. **"실행"** 클릭
3. 브라우저에서 `http://localhost:5000` 접속하여 확인

---

## 🚀 방법 2: 시작 프로그램 폴더에 추가

**장점**: 설정이 간단함
**단점**: 로그인해야만 실행됨

### 단계별 설정

#### 1단계: 시작 프로그램 폴더 열기
1. `Win + R` 키를 누름
2. 입력:
   ```
   shell:startup
   ```
3. Enter 키를 누름

#### 2단계: 바로가기 생성
1. 시작 프로그램 폴더가 열리면
2. `start_server_background.vbs` 파일을 이 폴더로 복사 또는
3. `start_server_background.vbs`의 바로가기를 만들어 이 폴더에 붙여넣기

#### 3단계: 테스트
1. 컴퓨터 재시작
2. 로그인 후 자동으로 서버가 시작됨
3. 브라우저에서 `http://localhost:5000` 접속하여 확인

---

## 🚀 방법 3: Windows 서비스 등록 (고급)

**장점**: 가장 안정적, 로그인 없이도 실행
**단점**: 설정이 복잡함

### NSSM 사용 (권장)

#### 1단계: NSSM 다운로드
1. https://nssm.cc/download 방문
2. NSSM 다운로드 및 압축 해제
3. `nssm.exe`를 `C:\Windows\System32`에 복사

#### 2단계: 서비스 설치
1. 관리자 권한으로 명령 프롬프트 실행
2. 입력:
   ```batch
   cd D:\tender_dashboard
   nssm install TenderDashboard
   ```

#### 3단계: NSSM GUI에서 설정
```
Application 탭:
  Path: C:\Python\python.exe (또는 Python 경로)
  Startup directory: D:\tender_dashboard
  Arguments: app.py

Details 탭:
  Display name: 입찰공고 통합 검색 시스템
  Description: Flask 기반 입찰공고 검색 시스템

```

#### 4단계: 서비스 시작
```batch
nssm start TenderDashboard
```

#### 서비스 관리 명령어
```batch
# 서비스 중지
nssm stop TenderDashboard

# 서비스 재시작
nssm restart TenderDashboard

# 서비스 상태 확인
nssm status TenderDashboard

# 서비스 제거
nssm remove TenderDashboard confirm
```

---

## ✅ 확인 방법

### 서버가 실행 중인지 확인
1. `check_server.bat` 실행
2. 또는 브라우저에서 `http://localhost:5000` 접속

### 로그 확인
- 콘솔 창이 보이는 경우: 콘솔에서 확인
- 백그라운드 실행 시: `logs/` 폴더의 로그 파일 확인

---

## 🛠️ 문제 해결

### 서버가 자동으로 시작되지 않는 경우

1. **Python 경로 확인**
   ```batch
   where python
   ```
   - 결과가 없으면 Python을 PATH에 추가

2. **권한 문제**
   - 작업 스케줄러: "가장 높은 수준의 권한으로 실행" 체크
   - 또는 관리자 권한으로 스크립트 실행

3. **포트 충돌**
   ```batch
   netstat -ano | findstr :5000
   ```
   - 다른 프로그램이 5000번 포트를 사용 중인지 확인

### 서버가 실행되었는데 접속이 안 되는 경우

1. **방화벽 확인**
   - Windows 방화벽에서 Python 허용

2. **app.py 설정 확인**
   - `config.py`에서 HOST가 `0.0.0.0`인지 확인

---

## 📝 추천 설정

### 개발/테스트 환경
- **방법 1: Windows 작업 스케줄러** 사용
- 백그라운드 실행 (`start_server_background.vbs`)
- 필요할 때 `check_server.bat`로 상태 확인
- 불필요할 때 `stop_server.bat`로 중지

### 프로덕션 환경
- **방법 3: Windows 서비스** 사용
- NSSM으로 서비스 등록
- 서비스 관리 도구로 제어

---

## 🔄 빠른 시작

가장 간단한 방법:
1. `start_server_background.vbs` 더블클릭
2. 1분 정도 대기
3. 브라우저에서 `http://localhost:5000` 접속

자동 시작 설정:
1. 위의 **방법 1: Windows 작업 스케줄러** 따라하기
2. 컴퓨터 재시작
3. 자동으로 서버 실행 확인

---

## 💡 팁

- 백그라운드로 실행하면 작업 표시줄에 아이콘이 나타나지 않음
- 시스템 리소스를 절약하려면 사용하지 않을 때 `stop_server.bat` 실행
- 크롤링 스케줄은 `config.py`의 `CRAWL_TIMES`에서 수정 가능
