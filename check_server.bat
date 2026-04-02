@echo off
chcp 65001 > nul
echo ========================================
echo 서버 상태 확인 중...
echo ========================================
echo.

REM Python 프로세스 확인
tasklist /FI "IMAGENAME eq python.exe" /FI "WINDOWTITLE eq *" 2>nul | find "python.exe" > nul
if %errorlevel% equ 0 (
    echo [실행 중] Python 프로세스가 실행 중입니다.
    echo.
    tasklist /FI "IMAGENAME eq python.exe"
) else (
    tasklist /FI "IMAGENAME eq pythonw.exe" 2>nul | find "pythonw.exe" > nul
    if %errorlevel% equ 0 (
        echo [실행 중] Python 백그라운드 프로세스가 실행 중입니다.
        echo.
        tasklist /FI "IMAGENAME eq pythonw.exe"
    ) else (
        echo [중지됨] Flask 서버가 실행 중이 아닙니다.
    )
)

echo.
echo 포트 5000 사용 확인...
netstat -ano | findstr :5000 > nul
if %errorlevel% equ 0 (
    echo [확인] 포트 5000이 사용 중입니다.
    netstat -ano | findstr :5000
) else (
    echo [정보] 포트 5000이 사용되지 않습니다.
)

echo.
echo ========================================
pause
