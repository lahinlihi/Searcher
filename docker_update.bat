@echo off
chcp 65001 >nul
setlocal

echo ====================================================
echo  입찰 대시보드 - Docker 버전 업데이트
echo ====================================================
echo.

cd /d "%~dp0"

:: ── 1. Git pull ─────────────────────────────────────
echo [1/3] 최신 코드 받기 (git pull)...
git pull --ff-only
if %ERRORLEVEL% NEQ 0 (
    echo [오류] git pull 실패.
    echo        인터넷 연결 또는 GitHub 접근 권한을 확인하세요.
    pause
    exit /b 1
)

:: ── 2. Docker 재빌드 및 재시작 ──────────────────────
echo.
echo [2/3] Docker 컨테이너 재빌드 중...
docker compose down
docker compose up -d --build
if %ERRORLEVEL% NEQ 0 (
    echo [오류] Docker 실행 실패. Docker Desktop이 실행 중인지 확인하세요.
    pause
    exit /b 1
)

:: ── 3. 상태 확인 ────────────────────────────────────
echo.
echo [3/3] 컨테이너 상태 확인...
timeout /t 5 /nobreak >nul
docker compose ps

echo.
echo ====================================================
echo  업데이트 완료!
echo  주소: http://localhost:5002
echo ====================================================
echo.
pause
endlocal
