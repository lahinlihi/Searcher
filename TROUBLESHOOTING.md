# 자동 실행 문제 해결 가이드

## 자주 발생하는 문제

### 1. 서버가 자동으로 시작되지 않음

**증상:** 컴퓨터를 켜도 서버가 실행되지 않음

**해결 방법:**

#### A. Python 경로 확인
```batch
where python
```
- 결과가 없으면: Python을 PATH에 추가하거나 재설치
- `C:\Python314\python.exe`가 나오면 정상

#### B. 작업 스케줄러 확인 (방법 2 사용 시)
1. `Win + R` → `taskschd.msc` 입력
2. "TenderDashboard" 작업 찾기
3. 우클릭 → "실행"으로 테스트
4. "기록" 탭에서 오류 메시지 확인

#### C. 시작 프로그램 확인 (방법 1 사용 시)
1. `Win + R` → `shell:startup` 입력
2. "입찰공고시스템.lnk" 바로가기 확인
3. 우클릭 → "속성" → 대상 경로 확인

### 2. 포트 5001이 이미 사용 중

**증상:** "Address already in use" 오류

**해결 방법:**

#### A. 사용 중인 프로세스 확인
```batch
netstat -ano | findstr :5001
```

#### B. 프로세스 종료
```batch
# PID 확인 후
taskkill /PID <프로세스ID> /F
```

#### C. 포트 번호 변경 (최후의 수단)
`config.py` 파일 수정:
```python
PORT = 5002  # 다른 포트로 변경
```

### 3. Python 프로세스는 실행 중인데 접속 안 됨

**증상:** `test_auto_start.bat`에서 Python은 실행 중이나 브라우저 접속 실패

**해결 방법:**

#### A. 로그 확인
```batch
cd tender_dashboard
type logs\startup_error.log
```

#### B. 수동으로 실행해서 오류 확인
```batch
cd tender_dashboard
python app.py
```
- 오류 메시지를 확인하고 필요한 패키지 설치

#### C. 패키지 재설치
```batch
cd tender_dashboard
pip install -r requirements.txt
```

### 4. 관리자 권한 문제

**증상:** "액세스가 거부되었습니다" 오류

**해결 방법:**

#### A. 관리자 권한으로 실행
1. 배치 파일 우클릭
2. "관리자 권한으로 실행" 선택

#### B. UAC 설정 확인
1. `Win + R` → `UserAccountControlSettings` 입력
2. 알림 수준을 적절히 조정

### 5. 자동 시작 후 바로 종료됨

**증상:** 서버가 시작되었다가 몇 초 후 종료

**해결 방법:**

#### A. 오류 로그 확인
1. `test_auto_start.bat` 실행
2. `logs/startup_error.log` 확인

#### B. 데이터베이스 확인
```batch
cd tender_dashboard
# data 폴더 확인
dir data
```
- `tenders.db` 파일이 손상되었을 수 있음
- 백업이 있다면 복원, 없다면 재생성

#### C. 작업 디렉토리 문제
작업 스케줄러 또는 바로가기의 "시작 위치"가 올바른지 확인:
```
D:\tender_dashboard
```

### 6. VBS 스크립트 오류

**증상:** VBS 실행 시 오류 메시지

**해결 방법:**

#### A. 파일 인코딩 확인
`start_server_background.vbs` 파일이 UTF-8로 저장되었는지 확인

#### B. 파일 재생성
```batch
install_auto_start_improved.bat
```
다시 실행하여 파일 재생성

## 진단 체크리스트

다음을 순서대로 확인하세요:

- [ ] Python이 설치되어 있고 PATH에 등록되어 있음
- [ ] `test_auto_start.bat` 실행 결과 확인
- [ ] 포트 5001이 사용 가능함
- [ ] `data` 폴더에 `tenders.db` 파일이 있음
- [ ] 자동 시작이 올바르게 설정되어 있음
- [ ] 관리자 권한으로 실행했음
- [ ] 방화벽이 Python을 차단하지 않음

## 완전 초기화 방법

모든 방법이 실패한 경우:

### 1. 자동 시작 제거
```batch
uninstall_auto_start_improved.bat
```

### 2. 실행 중인 Python 프로세스 종료
```batch
taskkill /F /IM python.exe
```

### 3. 패키지 재설치
```batch
cd tender_dashboard
pip install -r requirements.txt --force-reinstall
```

### 4. 수동 테스트
```batch
python app.py
```
브라우저에서 `http://localhost:5001` 접속 확인

### 5. 자동 시작 재설정
```batch
install_auto_start_improved.bat
```

## 여전히 해결되지 않는 경우

다음 정보를 수집하여 문의하세요:

1. **시스템 정보**
   ```batch
   systeminfo | findstr /C:"OS" /C:"버전"
   ```

2. **Python 정보**
   ```batch
   python --version
   where python
   ```

3. **테스트 결과**
   ```batch
   test_auto_start.bat 실행 결과 전체 복사
   ```

4. **로그 파일**
   ```
   logs/startup_error.log 내용
   ```

5. **오류 스크린샷**
   - 오류 메시지 전체 캡처
