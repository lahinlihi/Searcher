@echo off
chcp 65001 >nul
setlocal

echo ====================================================
echo  입찰 대시보드 업데이트
echo ====================================================
echo.

cd /d "%~dp0"

:: ── 1. Git pull ─────────────────────────────────────
echo [1/4] Git pull - 최신 코드 받기...
git pull --ff-only
if %ERRORLEVEL% NEQ 0 (
    echo [오류] git pull 실패. 로컬 변경사항이 있는지 확인하세요.
    echo        git status 명령으로 확인 후 수동으로 병합하세요.
    pause
    exit /b 1
)

:: ── 2. 패키지 업데이트 ──────────────────────────────
echo.
echo [2/4] Python 패키지 업데이트...
python -m pip install -r requirements.txt --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [경고] 일부 패키지 설치 실패. 계속 진행합니다.
)

:: ── 3. 실행 중인 서버 중지 ──────────────────────────
echo.
echo [3/4] 서버 재시작...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5002.*LISTENING"') do (
    echo   PID %%a 종료 중...
    powershell -Command "Stop-Process -Id %%a -Force -ErrorAction SilentlyContinue"
)
timeout /t 2 /nobreak >nul

:: ── 4. 서버 재시작 ──────────────────────────────────
echo [4/4] 서버 시작...
start "TenderDashboard" /min python -u app.py

:: 서버 기동 대기
timeout /t 3 /nobreak >nul
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5002.*LISTENING"') do (
    echo.
    echo ====================================================
    echo  업데이트 완료! 서버가 실행 중입니다.
    echo  주소: http://localhost:5002
    echo ====================================================
    goto :done
)
echo [경고] 서버 시작을 확인할 수 없습니다. 로그를 확인하세요.

:done
endlocal
