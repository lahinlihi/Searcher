@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 시스템 - 시작 프로그램 등록
echo ========================================
echo.
echo 이 스크립트는 Windows 시작 프로그램 폴더에
echo 바로가기를 생성합니다.
echo.
echo 로그인 시 자동으로 서버가 실행됩니다.
echo ========================================
echo.

REM 현재 디렉토리 저장
set SCRIPT_DIR=%~dp0

REM 시작 프로그램 폴더 경로
set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

echo [1/2] 시작 프로그램 폴더 확인 중...
echo 경로: %STARTUP_FOLDER%
echo.

REM 기존 바로가기 삭제
if exist "%STARTUP_FOLDER%\입찰공고시스템.lnk" (
    echo 기존 바로가기를 삭제합니다...
    del "%STARTUP_FOLDER%\입찰공고시스템.lnk"
)

echo [2/2] 바로가기 생성 중...

REM VBScript로 바로가기 생성
set VBS_FILE=%TEMP%\create_shortcut.vbs
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_FILE%"
echo sLinkFile = "%STARTUP_FOLDER%\입찰공고시스템.lnk" >> "%VBS_FILE%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_FILE%"
echo oLink.TargetPath = "%SCRIPT_DIR%start_server_silent.bat" >> "%VBS_FILE%"
echo oLink.WorkingDirectory = "%SCRIPT_DIR%" >> "%VBS_FILE%"
echo oLink.Description = "입찰공고 통합 검색 시스템" >> "%VBS_FILE%"
echo oLink.WindowStyle = 7 >> "%VBS_FILE%"
echo oLink.Save >> "%VBS_FILE%"

cscript //nologo "%VBS_FILE%"
del "%VBS_FILE%"

if exist "%STARTUP_FOLDER%\입찰공고시스템.lnk" (
    echo.
    echo ========================================
    echo ✓ 설치 완료!
    echo ========================================
    echo.
    echo ✓ 바로가기 위치: %STARTUP_FOLDER%
    echo ✓ 실행 파일: start_server_silent.bat
    echo.
    echo 다음 로그인 시 자동으로 서버가 실행됩니다.
    echo.
    echo 지금 바로 테스트하려면:
    echo - 아래에서 Y를 입력하세요
    echo.
    echo ========================================
    echo.

    choice /C YN /M "지금 서버를 시작하시겠습니까"
    if errorlevel 2 goto END
    if errorlevel 1 goto START_NOW

    :START_NOW
    echo.
    echo 서버 시작 중...
    start "" "%SCRIPT_DIR%start_server_silent.bat"
    timeout /t 5 /nobreak > nul
    echo.
    echo ✓ 서버가 시작되었습니다!
    echo.
    echo 브라우저에서 http://localhost:5000 으로 접속하세요
    echo.

) else (
    echo.
    echo [오류] 바로가기 생성에 실패했습니다.
    echo.
    echo 수동 설정 방법:
    echo 1. Windows 키 + R 누르기
    echo 2. "shell:startup" 입력 후 Enter
    echo 3. start_server_silent.bat 파일의 바로가기를 해당 폴더에 생성
    echo.
)

:END
echo.
pause
