# 빠른 시작 가이드

## 🎯 한 번만 실행하기

### 방법 1: 콘솔 창과 함께 실행 (로그 확인 가능)
```
start_server.bat 더블클릭
```

### 방법 2: 백그라운드로 조용히 실행
```
start_server_background.vbs 더블클릭
```

### 접속
브라우저에서 http://localhost:5000 열기

### 중지
```
stop_server.bat 더블클릭
```

---

## 🔄 자동 시작 설정 (컴퓨터 켤 때마다 자동 실행)

자세한 방법은 `AUTO_START_GUIDE.md` 참고

### 가장 간단한 방법

1. **Win + R** 누르기
2. `shell:startup` 입력 후 Enter
3. `start_server_background.vbs` 파일을 이 폴더에 복사
4. 컴퓨터 재시작
5. 완료! 이제 부팅할 때마다 자동으로 서버가 실행됩니다

---

## 📊 서버 관리

### 서버 상태 확인
```
check_server.bat 더블클릭
```

### 서버 중지
```
stop_server.bat 더블클릭
```

### 서버 재시작
1. `stop_server.bat` 실행
2. `start_server_background.vbs` 실행

---

## ❓ 문제 해결

### "연결을 거부했습니다" 오류
1. `check_server.bat` 실행하여 서버가 실행 중인지 확인
2. 실행 중이 아니면 `start_server.bat` 실행
3. 1분 정도 기다린 후 다시 접속

### Python을 찾을 수 없다는 오류
1. Python이 설치되어 있는지 확인
2. 명령 프롬프트에서 `python --version` 실행
3. 오류가 나면 Python을 PATH에 추가하거나 재설치

### 포트 5000이 이미 사용 중
1. `stop_server.bat` 실행
2. 다른 프로그램이 5000번 포트를 사용하는지 확인:
   ```
   netstat -ano | findstr :5000
   ```
3. 필요시 `config.py`에서 포트 변경

---

## 📁 파일 설명

| 파일 | 용도 |
|------|------|
| `start_server.bat` | 서버 시작 (콘솔 창 표시) |
| `start_server_background.vbs` | 서버 시작 (백그라운드) |
| `stop_server.bat` | 서버 중지 |
| `check_server.bat` | 서버 상태 확인 |
| `AUTO_START_GUIDE.md` | 자동 시작 설정 상세 가이드 |
| `README.md` | 프로젝트 전체 문서 |

---

## 💡 추천 사용 방법

### 일상적인 사용
- `start_server_background.vbs`로 백그라운드 실행
- 필요할 때만 브라우저로 접속
- 컴퓨터 종료 시 자동으로 서버도 종료됨

### 자동 시작 설정 후
- 컴퓨터 켜면 자동으로 서버 실행
- 바로 http://localhost:5000 접속 가능
- 불필요하면 `stop_server.bat`로 중지

---

더 자세한 내용은 다음 파일을 참고하세요:
- 자동 시작 설정: `AUTO_START_GUIDE.md`
- 전체 기능 및 API: `README.md`
- 크롤러 현황: `CRAWLER_STATUS.md`
