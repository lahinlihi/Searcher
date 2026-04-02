@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 시스템 - 시작 프로그램 제거
echo ========================================
echo.

REM 시작 프로그램 폴더 경로
set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT_FILE=%STARTUP_FOLDER%\입찰공고시스템.lnk

if exist "%SHORTCUT_FILE%" (
    echo 시작 프로그램에서 제거 중...
    del "%SHORTCUT_FILE%"

    if not exist "%SHORTCUT_FILE%" (
        echo.
        echo ✓ 제거 완료!
        echo.
        echo 다음 로그인부터는 자동으로 실행되지 않습니다.
    ) else (
        echo.
        echo [오류] 제거에 실패했습니다.
    )
) else (
    echo.
    echo [정보] 시작 프로그램에 등록되어 있지 않습니다.
)

echo.
echo ========================================
pause
