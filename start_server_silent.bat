@echo off
REM 입찰공고 시스템 - 백그라운드 실행 (좀비 소켓 방지: waitress + _free_port 내장)

cd /d "%~dp0"

where python > nul 2>&1
if %errorlevel% neq 0 (
    if exist "C:\Python314\python.exe" (
        start /min "" "C:\Python314\python.exe" -u app.py
    ) else (
        echo [%date% %time%] Python을 찾을 수 없습니다. >> logs\startup_error.log
        exit /b 1
    )
) else (
    start /min "" python -u app.py
)

exit
