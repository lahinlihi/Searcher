@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 통합 검색 시스템 시작 중...
echo ========================================
echo.

cd /d %~dp0

REM Python 경로 확인
where python > nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] Python이 설치되어 있지 않거나 PATH에 등록되지 않았습니다.
    pause
    exit /b 1
)

REM waitress 설치 확인 (없으면 설치)
python -c "import waitress" 2>nul
if %errorlevel% neq 0 (
    echo [설치] waitress 패키지 설치 중...
    pip install waitress
)

echo 서버 시작 중... (포트 5002)
echo 브라우저에서 http://localhost:5002 으로 접속하세요
echo 종료하려면 Ctrl+C를 누르세요
echo ========================================
echo.

REM -u : 출력 버퍼링 비활성화 (로그 즉시 표시)
python -u app.py

pause
