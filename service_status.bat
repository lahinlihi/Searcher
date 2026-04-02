@echo off
chcp 65001 > nul
echo ========================================
echo 서비스 상태 확인
echo ========================================
echo.

where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] NSSM이 설치되어 있지 않습니다.
    pause
    exit /b 1
)

sc query TenderDashboard >nul 2>&1
if %errorlevel% neq 0 (
    echo [정보] 서비스가 등록되어 있지 않습니다.
    echo.
    echo 서비스 등록: install_as_service.bat 실행
    echo.
    pause
    exit /b 0
)

echo NSSM 상태:
nssm status TenderDashboard

echo.
echo ========================================
echo Windows 서비스 상태:
echo ========================================
sc query TenderDashboard

echo.
echo ========================================
echo 포트 5000 사용 확인:
echo ========================================
netstat -ano | findstr :5000

echo.
pause
