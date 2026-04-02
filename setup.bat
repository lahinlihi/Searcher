@echo off
chcp 65001 >nul
setlocal

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║          입찰 공고 대시보드 - 초기 설치              ║
echo ╚══════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ── 1. Docker 실행 여부 확인 ─────────────────────────────
echo [1/4] Docker Desktop 확인 중...
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [오류] Docker Desktop이 실행되지 않았습니다.
    echo.
    echo  해결 방법:
    echo    1. Docker Desktop 이 설치되어 있지 않다면:
    echo       https://www.docker.com/products/docker-desktop 에서 설치
    echo    2. 설치되어 있다면 Docker Desktop 앱을 먼저 실행한 후 다시 시도
    echo.
    pause
    exit /b 1
)
echo  Docker Desktop 실행 중 확인 완료.

:: ── 2. data 폴더 생성 ────────────────────────────────────
echo.
echo [2/4] 데이터 폴더 확인 중...
if not exist "data" mkdir data
if not exist "logs" mkdir logs

:: ── 3. settings.json 확인 ────────────────────────────────
echo.
echo [3/4] 설정 파일 확인 중...

if exist "data\settings.json" (
    echo  settings.json 확인 완료.
) else (
    echo.
    echo  ┌─────────────────────────────────────────────────┐
    echo  │  settings.json 파일이 없습니다.                  │
    echo  │                                                  │
    echo  │  관리자에게 받은 settings.json 파일을            │
    echo  │  아래 폴더에 복사한 후 Enter 를 누르세요:        │
    echo  │                                                  │
    echo  │    %~dp0data\
    echo  │                                                  │
    echo  └─────────────────────────────────────────────────┘
    echo.
    :: data 폴더 탐색기로 열기
    explorer "%~dp0data"
    echo  settings.json 복사 완료 후 Enter 를 누르세요...
    pause >nul

    if not exist "data\settings.json" (
        echo.
        echo  [오류] settings.json 파일을 찾을 수 없습니다.
        echo         파일을 복사한 후 다시 실행하세요.
        pause
        exit /b 1
    )
    echo  settings.json 확인 완료.
)

:: ── 4. Docker 빌드 및 시작 ───────────────────────────────
echo.
echo [4/4] Docker 컨테이너 빌드 및 시작 중...
echo       (최초 실행 시 5~10분 소요될 수 있습니다)
echo.
docker compose up -d --build

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [오류] Docker 실행에 실패했습니다.
    echo         docker compose logs 명령으로 오류를 확인하세요.
    pause
    exit /b 1
)

:: ── 완료 ─────────────────────────────────────────────────
echo.
timeout /t 5 /nobreak >nul
echo ╔══════════════════════════════════════════════════════╗
echo ║  설치 완료!                                          ║
echo ║                                                      ║
echo ║  브라우저에서 아래 주소로 접속하세요:                ║
echo ║  http://localhost:5002                               ║
echo ║                                                      ║
echo ║  이후 업데이트: docker_update.bat 실행               ║
echo ╚══════════════════════════════════════════════════════╝
echo.

:: 브라우저 자동 열기
start http://localhost:5002

pause
endlocal
