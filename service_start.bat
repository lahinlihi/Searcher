@echo off
chcp 65001 > nul
echo ========================================
echo 서비스 시작
echo ========================================
echo.

where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] NSSM이 설치되어 있지 않습니다.
    pause
    exit /b 1
)

nssm start TenderDashboard

if %errorlevel% equ 0 (
    echo ✓ 서비스가 시작되었습니다.
    echo.
    echo 잠시 후 http://localhost:5000 으로 접속하세요.
) else (
    echo [오류] 서비스 시작에 실패했습니다.
    echo.
    echo 상태 확인: service_status.bat
    echo 로그 확인: logs\service_stderr.log
)

echo.
pause
