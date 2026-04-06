@echo off
chcp 65001 > nul
setlocal

echo.
echo ================================================
echo   입찰공고 통합 검색 시스템
echo ================================================
echo.

cd /d "%~dp0"

:: ── 1. Python 확인 ──────────────────────────────────────────
echo [1/3] Python 확인 중...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [오류] Python 이 설치되어 있지 않습니다.
    echo.
    echo  해결 방법:
    echo    1. 아래 주소에서 Python 3.12 설치 파일을 내려받으세요.
    echo       https://www.python.org/downloads/
    echo    2. 설치 화면 하단의 "Add Python to PATH" 를 반드시 체크!
    echo    3. 설치 완료 후 이 파일을 다시 실행하세요.
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  Python %PY_VER% 확인.

:: ── 2. 패키지 설치 (미설치 시만 실행) ──────────────────────
echo.
echo [2/3] 패키지 확인 중...
python -c "import flask, waitress, sqlalchemy, apscheduler, selenium, psutil" > nul 2>&1
if %errorlevel% neq 0 (
    echo  필요 패키지 설치 중... (최초 1회, 수 분 소요될 수 있습니다)
    python -m pip install -r requirements.txt -q --disable-pip-version-check
    if %errorlevel% neq 0 (
        echo.
        echo  [오류] 패키지 설치 실패.
        echo         인터넷 연결을 확인하고 다시 실행하세요.
        pause
        exit /b 1
    )
    echo  패키지 설치 완료.
) else (
    echo  패키지 이미 설치됨.
)

:: ── 3. 설정 파일 확인 ───────────────────────────────────────
echo.
echo [3/3] 설정 파일 확인 중...
if not exist "data" mkdir data

if not exist "data\settings.json" (
    if exist "data.example\settings.example.json" (
        copy "data.example\settings.example.json" "data\settings.json" > nul
        echo  settings.json 을 기본값으로 생성했습니다.
        echo  서버 실행 후 설정 페이지에서 키워드와 필터를 설정하세요.
    ) else (
        echo  [오류] data\settings.json 파일이 없습니다.
        echo         관리자에게 settings.json 파일을 받아 data\ 폴더에 복사하세요.
        pause
        exit /b 1
    )
) else (
    echo  settings.json 확인.
)

:: ── 서버 시작 ────────────────────────────────────────────────
echo.
echo ================================================
echo   서버 시작 중...
echo   브라우저: http://localhost:5002
echo   종료:     이 창에서 Ctrl+C
echo ================================================
echo.

python -u app.py

echo.
echo 서버가 종료되었습니다.
pause
endlocal
