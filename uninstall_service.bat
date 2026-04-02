@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 시스템 - Windows 서비스 제거
echo ========================================
echo.

REM 관리자 권한 확인
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] 관리자 권한이 필요합니다.
    echo.
    echo 이 파일을 마우스 우클릭하여
    echo "관리자 권한으로 실행"을 선택해주세요.
    echo.
    pause
    exit /b 1
)

REM NSSM 확인
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] NSSM이 설치되어 있지 않습니다.
    pause
    exit /b 1
)

REM 서비스 확인
sc query TenderDashboard >nul 2>&1
if %errorlevel% neq 0 (
    echo [정보] 등록된 서비스가 없습니다.
    pause
    exit /b 0
)

echo 서비스 중지 중...
nssm stop TenderDashboard >nul 2>&1
timeout /t 3 /nobreak >nul

echo 서비스 제거 중...
nssm remove TenderDashboard confirm

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo ✓ 서비스가 제거되었습니다.
    echo ========================================
) else (
    echo [오류] 서비스 제거에 실패했습니다.
)

echo.
pause
