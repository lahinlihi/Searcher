@echo off
chcp 65001 > nul
echo ========================================
echo 자동 시작 설정 수정 중...
echo ========================================
echo.

REM 현재 디렉토리 저장
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM 시작프로그램 폴더 경로
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo [1/3] 기존 바로가기 삭제 중...
if exist "%STARTUP_FOLDER%\TenderDashboard.lnk" (
    del "%STARTUP_FOLDER%\TenderDashboard.lnk"
    echo     - 기존 바로가기 삭제 완료
) else (
    echo     - 기존 바로가기 없음
)
echo.

echo [2/3] 새 바로가기 생성 중...
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%STARTUP_FOLDER%\TenderDashboard.lnk'); $Shortcut.TargetPath = '%SCRIPT_DIR%\start_server_background_fixed.vbs'; $Shortcut.WorkingDirectory = '%SCRIPT_DIR%'; $Shortcut.Description = '입찰공고 통합 검색 시스템'; $Shortcut.Save()"

if %errorlevel% equ 0 (
    echo     - 바로가기 생성 완료
) else (
    echo     - [오류] 바로가기 생성 실패
    pause
    exit /b 1
)
echo.

echo [3/3] 설정 테스트 중...
if exist "%STARTUP_FOLDER%\TenderDashboard.lnk" (
    echo     - 바로가기 파일 확인: OK
) else (
    echo     - [오류] 바로가기 파일이 없습니다
    pause
    exit /b 1
)
echo.

echo ========================================
echo [완료] 자동 시작 설정이 수정되었습니다!
echo ========================================
echo.
echo 변경 사항:
echo - 대상 파일: start_server_background_fixed.vbs
echo - 위치: %STARTUP_FOLDER%
echo.
echo 지금 바로 테스트하려면 다음 파일을 실행하세요:
echo   start_server_background_fixed.vbs
echo.
pause
