# 고급 설정 가이드

입찰공고 시스템을 Windows 작업 스케줄러 또는 Windows 서비스로 등록하여 자동 시작하는 방법입니다.

---

## 📋 목차

1. [방법 비교](#방법-비교)
2. [방법 1: 작업 스케줄러 (권장)](#방법-1-작업-스케줄러-권장)
3. [방법 2: Windows 서비스 (고급)](#방법-2-windows-서비스-고급)
4. [문제 해결](#문제-해결)

---

## 방법 비교

| 특징 | 작업 스케줄러 | Windows 서비스 | 시작 프로그램 |
|------|--------------|---------------|-------------|
| **난이도** | 쉬움 | 보통 (NSSM 필요) | 매우 쉬움 |
| **안정성** | 높음 | 매우 높음 | 보통 |
| **로그인 필요** | 아니오 | 아니오 | 예 |
| **관리 편의성** | 높음 | 높음 | 낮음 |
| **자동 재시작** | 예 (설정 가능) | 예 (기본) | 아니오 |
| **권장 용도** | 일반 사용 | 서버/프로덕션 | 개발/테스트 |

### 추천

- **일반 사용자**: 작업 스케줄러 (방법 1)
- **서버 환경**: Windows 서비스 (방법 2)
- **개발/테스트**: 시작 프로그램 (QUICK_START.md 참고)

---

## 방법 1: 작업 스케줄러 (권장)

### ✨ 자동 설치 (가장 쉬움)

#### 1단계: 설치 스크립트 실행

1. `install_auto_start.bat` 파일을 **마우스 우클릭**
2. **"관리자 권한으로 실행"** 선택
3. 완료!

```
✓ 자동으로 작업 스케줄러에 등록
✓ 부팅 후 1분 뒤 서버 자동 시작
✓ 실패 시 자동으로 3회 재시도
```

#### 2단계: 테스트

```bat
test_auto_start.bat 실행 (관리자 권한으로)
```

- 작업이 정상적으로 실행되는지 테스트
- 서버가 시작되는지 확인
- 브라우저에서 http://localhost:5000 접속

#### 3단계: 확인 (선택)

작업 스케줄러에서 직접 확인하려면:

1. `Win + R` → `taskschd.msc` 입력
2. "입찰공고_자동시작" 작업 확인

#### 제거

```bat
uninstall_auto_start.bat 실행 (관리자 권한으로)
```

---

### 🔧 수동 설정 (상세)

자동 설치가 실패하거나 세부 설정을 변경하고 싶은 경우:

#### 1단계: 작업 스케줄러 열기

1. `Win + R` 키
2. `taskschd.msc` 입력 → Enter

#### 2단계: 작업 만들기

1. 우측 패널에서 **"작업 만들기"** 클릭
   - ⚠️ 주의: "기본 작업 만들기"가 아님!

#### 3단계: 일반 탭

```
이름: 입찰공고_자동시작
설명: 부팅 시 Flask 서버 자동 시작

보안 옵션:
  ☑ 사용자의 로그온 여부에 관계없이 실행
  ☑ 가장 높은 수준의 권한으로 실행
```

#### 4단계: 트리거 탭

1. **"새로 만들기"** 클릭
2. **작업 시작**: "시작할 때" 선택
3. **고급 설정**:
   - 작업 지연 시간: 1분 (선택)
   - ☑ 사용
4. **확인**

#### 5단계: 동작 탭

1. **"새로 만들기"** 클릭
2. **동작**: "프로그램 시작"
3. **프로그램/스크립트**:
   ```
   D:\tender_dashboard\start_server_background.vbs
   ```
4. **시작 위치** (선택):
   ```
   D:\tender_dashboard
   ```
5. **확인**

#### 6단계: 조건 탭

```
전원:
  ☐ AC 전원을 사용하는 경우에만 작업 시작 (체크 해제)
  ☐ 배터리 모드로 전환할 경우 중지 (체크 해제)

네트워크:
  ☐ 다음 네트워크 연결을 사용할 수 있는 경우에만 시작 (체크 해제)
```

#### 7단계: 설정 탭

```
☑ 요청 시 작업 실행 허용
☑ 작업이 실패하면 다시 시작
   간격: 1분
   최대 3회 시도
☐ 작업이 요청 시 실행되지 않으면... (체크 해제)
```

#### 8단계: 저장

1. **확인** 클릭
2. Windows 계정 비밀번호 입력 (요청 시)
3. 완료!

#### 테스트

1. 작업 스케줄러에서 "입찰공고_자동시작" 우클릭
2. **"실행"** 클릭
3. 1분 후 http://localhost:5000 접속

---

### 📝 XML 가져오기 (대안)

`TenderDashboard_Task.xml` 파일을 사용하여 더 빠르게 등록:

#### 방법 A: 자동 스크립트

```bat
install_auto_start.bat 실행 (관리자 권한)
```

#### 방법 B: 수동 가져오기

1. 작업 스케줄러 열기 (`taskschd.msc`)
2. **"작업 가져오기..."** 클릭
3. `TenderDashboard_Task.xml` 선택
4. 작업 이름 확인: "입찰공고_자동시작"
5. **확인**

⚠️ 주의: XML 파일 내 경로가 정확한지 확인 (D:\tender_dashboard)

---

## 방법 2: Windows 서비스 (고급)

Windows 서비스로 등록하면 가장 안정적으로 실행됩니다.

### 특징

✅ 로그인 없이도 실행
✅ 자동 재시작 기능
✅ Windows 서비스 관리자에서 관리
✅ 시스템 부팅 시 자동 시작
✅ 로그 파일 자동 생성

### 사전 준비: NSSM 설치

NSSM(Non-Sucking Service Manager)이 필요합니다.

#### 방법 1: 자동 설치 안내

```bat
install_nssm.bat 실행 (관리자 권한)
```

- 다운로드 페이지 자동 열림
- 설치 안내 제공

#### 방법 2: 수동 설치

1. https://nssm.cc/download 방문
2. 최신 버전 다운로드
3. 압축 해제
4. `win64\nssm.exe` 파일을 `C:\Windows\System32\` 폴더에 복사

#### 확인

```bat
nssm version
```

---

### ✨ 자동 설치

#### 1단계: 서비스 설치

```bat
install_as_service.bat 실행 (관리자 권한)
```

자동으로 수행:
- Python 경로 확인
- NSSM 확인
- 서비스 등록
- 서비스 설정
- 로그 설정

#### 2단계: 서비스 시작

설치 완료 후 즉시 시작 또는:

```bat
service_start.bat
```

#### 3단계: 확인

```bat
service_status.bat
```

또는 브라우저에서 http://localhost:5000 접속

---

### 🔧 수동 설정 (상세)

#### 1단계: Python 경로 확인

```bat
where python
```

결과 예: `C:\Users\USER\AppData\Local\Programs\Python\Python39\python.exe`

#### 2단계: 서비스 등록

관리자 권한 명령 프롬프트에서:

```bat
cd D:\tender_dashboard

nssm install TenderDashboard
```

GUI 창이 열립니다.

#### 3단계: Application 탭 설정

```
Path: C:\Users\USER\AppData\Local\Programs\Python\Python39\python.exe
Startup directory: D:\tender_dashboard
Arguments: app.py
```

#### 4단계: Details 탭 설정

```
Display name: 입찰공고 통합 검색 시스템
Description: Flask 기반 입찰공고 통합 검색 시스템
Startup type: Automatic
```

#### 5단계: I/O 탭 설정 (로그)

```
Output (stdout): D:\tender_dashboard\logs\service_stdout.log
Error (stderr): D:\tender_dashboard\logs\service_stderr.log
```

#### 6단계: Rotation 탭 설정

```
☑ Rotate files
☑ Restrict file sizes
  1048576 bytes (1MB)
```

#### 7단계: 설치

**"Install service"** 클릭

#### 8단계: 서비스 시작

```bat
nssm start TenderDashboard
```

---

### 서비스 관리

#### 시작
```bat
service_start.bat
# 또는
nssm start TenderDashboard
```

#### 중지
```bat
service_stop.bat
# 또는
nssm stop TenderDashboard
```

#### 재시작
```bat
service_restart.bat
# 또는
nssm restart TenderDashboard
```

#### 상태 확인
```bat
service_status.bat
# 또는
nssm status TenderDashboard
```

#### 서비스 제거
```bat
uninstall_service.bat
# 또는
nssm remove TenderDashboard confirm
```

#### 서비스 설정 편집
```bat
nssm edit TenderDashboard
```

---

### 로그 확인

서비스로 실행 시 로그 위치:

```
D:\tender_dashboard\logs\service_stdout.log  # 일반 로그
D:\tender_dashboard\logs\service_stderr.log  # 오류 로그
```

실시간 로그 확인 (PowerShell):

```powershell
Get-Content D:\tender_dashboard\logs\service_stderr.log -Wait -Tail 50
```

---

## 문제 해결

### 작업 스케줄러

#### 작업이 실행되지 않음

1. **권한 확인**
   - "가장 높은 수준의 권한으로 실행" 체크 확인

2. **경로 확인**
   ```bat
   # TenderDashboard_Task.xml 열어서 경로 확인
   D:\tender_dashboard\start_server_background.vbs
   ```

3. **수동 실행 테스트**
   ```bat
   start_server.bat
   ```
   - 오류 메시지 확인

4. **로그 확인**
   - 작업 스케줄러에서 작업 우클릭 → 속성 → 기록
   - `D:\tender_dashboard\logs\` 폴더 확인

#### 작업이 등록되지 않음

```bat
# 관리자 권한으로 재시도
install_auto_start.bat
```

---

### Windows 서비스

#### NSSM을 찾을 수 없음

```bat
# NSSM 설치
install_nssm.bat

# 또는 수동 설치
# 1. https://nssm.cc/download
# 2. nssm.exe를 C:\Windows\System32에 복사
```

#### 서비스가 시작되지 않음

1. **Python 경로 확인**
   ```bat
   where python
   ```

2. **로그 확인**
   ```bat
   type D:\tender_dashboard\logs\service_stderr.log
   ```

3. **수동 실행 테스트**
   ```bat
   cd D:\tender_dashboard
   python app.py
   ```

4. **서비스 재설치**
   ```bat
   uninstall_service.bat
   install_as_service.bat
   ```

#### 서비스가 자동으로 중지됨

1. **로그 확인**
   - `logs\service_stderr.log` 오류 확인

2. **포트 충돌**
   ```bat
   netstat -ano | findstr :5000
   ```
   - 다른 프로그램이 5000번 포트 사용 중인지 확인

3. **의존성 확인**
   ```bat
   pip install -r requirements.txt
   ```

---

### 일반 문제

#### Python을 찾을 수 없음

```bat
# Python 경로 확인
where python

# PATH에 추가되지 않은 경우
# 제어판 → 시스템 → 고급 시스템 설정 → 환경 변수
# Path에 Python 경로 추가
```

#### 포트 5000이 이미 사용 중

```bat
# 사용 중인 프로세스 확인
netstat -ano | findstr :5000

# 프로세스 종료
taskkill /PID [PID번호] /F

# 또는 config.py에서 포트 변경
PORT = 5001
```

#### 방화벽 차단

1. Windows Defender 방화벽 열기
2. "Windows Defender 방화벽을 통해 앱 또는 기능 허용"
3. Python 찾기 또는 추가
4. 개인 및 공용 네트워크 모두 허용

---

## 추가 팁

### 여러 설정 방법 비교

| 상황 | 추천 방법 |
|------|----------|
| 개인 PC, 가끔 사용 | 시작 프로그램 (QUICK_START.md) |
| 개인 PC, 자주 사용 | 작업 스케줄러 |
| 회사 서버 | Windows 서비스 |
| 개발/테스트 | 수동 실행 (start_server.bat) |

### 성능 최적화

#### 부팅 지연 설정

작업 스케줄러/서비스 모두:
- 부팅 후 1-2분 지연 추천
- 다른 시스템 서비스가 먼저 시작되도록

#### 자동 재시작 설정

**작업 스케줄러**:
- 실패 시 1분 간격으로 3회 재시도

**Windows 서비스** (NSSM):
```bat
nssm set TenderDashboard AppExit Default Restart
nssm set TenderDashboard AppRestartDelay 60000
```

---

## 요약

### 빠른 설치 (작업 스케줄러)

```bat
1. install_auto_start.bat 실행 (관리자 권한)
2. test_auto_start.bat로 테스트
3. 완료!
```

### 빠른 설치 (Windows 서비스)

```bat
1. install_nssm.bat 실행 → NSSM 다운로드
2. nssm.exe를 C:\Windows\System32에 복사
3. install_as_service.bat 실행 (관리자 권한)
4. 완료!
```

---

더 자세한 내용은 다음 문서 참고:
- 기본 사용법: `QUICK_START.md`
- 전체 기능: `README.md`
- 자동 시작 기초: `AUTO_START_GUIDE.md`
