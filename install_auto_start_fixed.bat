@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 검색 시스템 자동 시작 설정
echo ========================================
echo.

REM 관리자 권한 확인
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [경고] 이 스크립트는 관리자 권한이 필요할 수 있습니다.
    echo 일반 사용자 모드로 진행합니다...
    echo.
)

REM 현재 디렉토리 저장
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM 시작프로그램 폴더 경로
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo 작업 디렉토리: %SCRIPT_DIR%
echo 시작프로그램 폴더: %STARTUP_FOLDER%
echo.

REM 기존 바로가기 삭제 (있다면)
if exist "%STARTUP_FOLDER%\TenderDashboard.lnk" (
    echo 기존 바로가기를 삭제합니다...
    del "%STARTUP_FOLDER%\TenderDashboard.lnk"
)

REM PowerShell을 사용하여 바로가기 생성
echo 새 바로가기를 생성합니다...
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTUP_FOLDER%\TenderDashboard.lnk'); $Shortcut.TargetPath = '%SCRIPT_DIR%\start_server_background_fixed.vbs'; $Shortcut.WorkingDirectory = '%SCRIPT_DIR%'; $Shortcut.Description = '입찰공고 통합 검색 시스템'; $Shortcut.Save()"

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo [성공] 자동 시작이 설정되었습니다!
    echo ========================================
    echo.
    echo 다음 부팅 시 자동으로 서버가 시작됩니다.
    echo 바로가기 위치: %STARTUP_FOLDER%\TenderDashboard.lnk
    echo.
    echo 자동 시작을 해제하려면 uninstall_auto_start.bat을 실행하세요.
    echo.
) else (
    echo.
    echo [오류] 바로가기 생성에 실패했습니다.
    echo 수동으로 바로가기를 만들어주세요:
    echo 1. 시작프로그램 폴더 열기: shell:startup
    echo 2. start_server_background_fixed.vbs 파일의 바로가기 만들기
    echo.
)

pause
