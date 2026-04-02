@echo off
chcp 65001 > nul
echo ========================================
echo 서비스 중지
echo ========================================
echo.

where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] NSSM이 설치되어 있지 않습니다.
    pause
    exit /b 1
)

nssm stop TenderDashboard

if %errorlevel% equ 0 (
    echo ✓ 서비스가 중지되었습니다.
) else (
    echo [오류] 서비스 중지에 실패했습니다.
)

echo.
pause
