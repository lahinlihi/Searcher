@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 시스템 - 자동 시작 제거
echo ========================================
echo.

REM 시작 프로그램 폴더 바로가기 삭제
set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

if exist "%STARTUP_FOLDER%\입찰공고시스템.lnk" (
    echo [1/2] 시작 프로그램 폴더의 바로가기 삭제 중...
    del "%STARTUP_FOLDER%\입찰공고시스템.lnk"
    echo ✓ 시작 프로그램 바로가기 삭제 완료
) else (
    echo [1/2] 시작 프로그램 폴더에 바로가기가 없습니다.
)

echo.

REM 작업 스케줄러 작업 삭제
schtasks /Query /TN "TenderDashboard" >nul 2>&1
if %errorlevel% equ 0 (
    echo [2/2] 작업 스케줄러에서 작업 삭제 중...
    schtasks /Delete /TN "TenderDashboard" /F
    echo ✓ 작업 스케줄러 작업 삭제 완료
) else (
    echo [2/2] 작업 스케줄러에 등록된 작업이 없습니다.
)

echo.
echo ========================================
echo ✓ 자동 시작 제거 완료!
echo ========================================
echo.
echo 이제 시스템 부팅 시 자동으로 실행되지 않습니다.
echo.
pause
