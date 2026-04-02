@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 시스템 - 자동 시작 설정
echo ========================================
echo.
echo 이 스크립트는 Windows 부팅 시 자동으로
echo 입찰공고 시스템을 시작하도록 설정합니다.
echo.
echo 선택 가능한 방법:
echo 1. 시작 프로그램 폴더 (간단, 로그인 후 실행)
echo 2. 작업 스케줄러 (권장, 부팅 시 자동 실행)
echo.
echo ========================================
echo.

choice /C 12 /M "원하는 방법을 선택하세요"
if errorlevel 2 goto TASK_SCHEDULER
if errorlevel 1 goto STARTUP_FOLDER

:STARTUP_FOLDER
echo.
echo [방법 1: 시작 프로그램 폴더]
echo.

REM 현재 디렉토리 저장
set SCRIPT_DIR=%~dp0

REM 시작 프로그램 폴더 경로
set STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup

echo 시작 프로그램 폴더 확인 중...
echo 경로: %STARTUP_FOLDER%
echo.

REM 기존 바로가기 삭제
if exist "%STARTUP_FOLDER%\입찰공고시스템.lnk" (
    echo 기존 바로가기를 삭제합니다...
    del "%STARTUP_FOLDER%\입찰공고시스템.lnk"
)

echo 바로가기 생성 중...

REM VBScript로 바로가기 생성
set VBS_FILE=%TEMP%\create_shortcut.vbs
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_FILE%"
echo sLinkFile = "%STARTUP_FOLDER%\입찰공고시스템.lnk" >> "%VBS_FILE%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_FILE%"
echo oLink.TargetPath = "%SCRIPT_DIR%start_server_background.vbs" >> "%VBS_FILE%"
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
    echo ✓ 다음 로그인 시 자동으로 서버가 실행됩니다.
    echo.
    echo 지금 바로 테스트하려면 Y를 입력하세요
    echo.
    
    choice /C YN /M "지금 서버를 시작하시겠습니까"
    if errorlevel 2 goto END
    if errorlevel 1 goto START_NOW
) else (
    echo.
    echo [오류] 바로가기 생성에 실패했습니다.
    echo.
)
goto END

:TASK_SCHEDULER
echo.
echo [방법 2: 작업 스케줄러]
echo.

REM 현재 디렉토리와 사용자명
set SCRIPT_DIR=%~dp0
for /f "tokens=*" %%a in ('whoami') do set CURRENT_USER=%%a

echo 작업 스케줄러에 등록 중...
echo 사용자: %CURRENT_USER%
echo 경로: %SCRIPT_DIR%
echo.

REM XML 파일 생성
set XML_FILE=%TEMP%\TenderDashboard_Task.xml
echo ^<?xml version="1.0" encoding="UTF-16"?^> > "%XML_FILE%"
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^> >> "%XML_FILE%"
echo   ^<RegistrationInfo^> >> "%XML_FILE%"
echo     ^<Description^>입찰공고 통합 검색 시스템을 부팅 시 자동으로 시작합니다.^</Description^> >> "%XML_FILE%"
echo   ^</RegistrationInfo^> >> "%XML_FILE%"
echo   ^<Triggers^> >> "%XML_FILE%"
echo     ^<BootTrigger^> >> "%XML_FILE%"
echo       ^<Enabled^>true^</Enabled^> >> "%XML_FILE%"
echo       ^<Delay^>PT1M^</Delay^> >> "%XML_FILE%"
echo     ^</BootTrigger^> >> "%XML_FILE%"
echo   ^</Triggers^> >> "%XML_FILE%"
echo   ^<Principals^> >> "%XML_FILE%"
echo     ^<Principal id="Author"^> >> "%XML_FILE%"
echo       ^<UserId^>%CURRENT_USER%^</UserId^> >> "%XML_FILE%"
echo       ^<LogonType^>InteractiveToken^</LogonType^> >> "%XML_FILE%"
echo       ^<RunLevel^>HighestAvailable^</RunLevel^> >> "%XML_FILE%"
echo     ^</Principal^> >> "%XML_FILE%"
echo   ^</Principals^> >> "%XML_FILE%"
echo   ^<Settings^> >> "%XML_FILE%"
echo     ^<MultipleInstancesPolicy^>IgnoreNew^</MultipleInstancesPolicy^> >> "%XML_FILE%"
echo     ^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^> >> "%XML_FILE%"
echo     ^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^> >> "%XML_FILE%"
echo     ^<AllowHardTerminate^>true^</AllowHardTerminate^> >> "%XML_FILE%"
echo     ^<StartWhenAvailable^>true^</StartWhenAvailable^> >> "%XML_FILE%"
echo     ^<RunOnlyIfNetworkAvailable^>false^</RunOnlyIfNetworkAvailable^> >> "%XML_FILE%"
echo     ^<AllowStartOnDemand^>true^</AllowStartOnDemand^> >> "%XML_FILE%"
echo     ^<Enabled^>true^</Enabled^> >> "%XML_FILE%"
echo     ^<Hidden^>false^</Hidden^> >> "%XML_FILE%"
echo     ^<RunOnlyIfIdle^>false^</RunOnlyIfIdle^> >> "%XML_FILE%"
echo     ^<WakeToRun^>false^</WakeToRun^> >> "%XML_FILE%"
echo     ^<ExecutionTimeLimit^>PT0S^</ExecutionTimeLimit^> >> "%XML_FILE%"
echo     ^<Priority^>7^</Priority^> >> "%XML_FILE%"
echo   ^</Settings^> >> "%XML_FILE%"
echo   ^<Actions Context="Author"^> >> "%XML_FILE%"
echo     ^<Exec^> >> "%XML_FILE%"
echo       ^<Command^>wscript.exe^</Command^> >> "%XML_FILE%"
echo       ^<Arguments^>"%SCRIPT_DIR%start_server_background.vbs"^</Arguments^> >> "%XML_FILE%"
echo       ^<WorkingDirectory^>%SCRIPT_DIR%^</WorkingDirectory^> >> "%XML_FILE%"
echo     ^</Exec^> >> "%XML_FILE%"
echo   ^</Actions^> >> "%XML_FILE%"
echo ^</Task^> >> "%XML_FILE%"

REM 기존 작업 삭제 (있을 경우)
schtasks /Query /TN "TenderDashboard" >nul 2>&1
if %errorlevel% equ 0 (
    echo 기존 작업을 삭제합니다...
    schtasks /Delete /TN "TenderDashboard" /F >nul 2>&1
)

REM 작업 등록
echo 작업 스케줄러에 등록 중...
schtasks /Create /TN "TenderDashboard" /XML "%XML_FILE%" /F

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo ✓ 설치 완료!
    echo ========================================
    echo.
    echo ✓ 작업 이름: TenderDashboard
    echo ✓ 부팅 1분 후 자동으로 서버가 실행됩니다.
    echo.
    echo 지금 바로 테스트하려면 Y를 입력하세요
    echo.
    
    choice /C YN /M "지금 서버를 시작하시겠습니까"
    if errorlevel 2 goto CLEANUP
    if errorlevel 1 goto START_NOW
) else (
    echo.
    echo [오류] 작업 스케줄러 등록에 실패했습니다.
    echo 관리자 권한으로 실행해주세요.
    echo.
)

:CLEANUP
del "%XML_FILE%" 2>nul
goto END

:START_NOW
echo.
echo 서버 시작 중...
start "" "%SCRIPT_DIR%start_server_background.vbs"
timeout /t 5 /nobreak > nul
echo.
echo ✓ 서버가 시작되었습니다!
echo.
echo 브라우저에서 http://localhost:5001 으로 접속하세요
echo (서버가 완전히 시작되려면 30초~1분 정도 소요됩니다)
echo.
goto END

:END
echo.
echo ========================================
echo.
pause
