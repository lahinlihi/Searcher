@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 통합 검색 시스템 중지 중...
echo ========================================
echo.

REM 포트 5002를 점유한 프로세스 PID 확인 후 종료
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5002.*LISTENING"') do (
    echo 서버 프로세스 종료 중 (PID: %%a)
    taskkill /PID %%a /F > nul 2>&1
)

REM 잔여 python.exe / pythonw.exe 종료
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO LIST 2^>nul ^| find "PID:"') do (
    taskkill /PID %%a /F > nul 2>&1
)
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq pythonw.exe" /FO LIST 2^>nul ^| find "PID:"') do (
    taskkill /PID %%a /F > nul 2>&1
)

REM 종료 확인
timeout /t 2 /nobreak > nul
netstat -ano | findstr ":5002.*LISTENING" > nul 2>&1
if %errorlevel% equ 0 (
    echo [경고] 포트 5002가 아직 점유 중입니다. 잠시 후 다시 시도하세요.
) else (
    echo 서버가 정상적으로 중지되었습니다.
)

echo ========================================
pause
