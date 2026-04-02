@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 시스템 - Windows 서비스 등록
echo ========================================
echo.
echo 이 스크립트는 NSSM을 사용하여
echo Flask 서버를 Windows 서비스로 등록합니다.
echo.
echo 주의: NSSM(nssm.exe)이 필요합니다.
echo ========================================
echo.

REM 관리자 권한 확인
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] 관리자 권한이 필요합니다.
    echo.
    echo 이 파일을 마우스 우클릭하여
    echo "관리자 권한으로 실행"을 선택해주세요.
    echo.
    pause
    exit /b 1
)

REM Python 경로 찾기
echo [1/5] Python 경로 확인 중...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] Python을 찾을 수 없습니다.
    echo Python이 PATH에 등록되어 있는지 확인해주세요.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%i in ('where python') do set PYTHON_PATH=%%i
echo ✓ Python 경로: %PYTHON_PATH%

REM NSSM 확인
echo.
echo [2/5] NSSM 확인 중...
where nssm >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [경고] NSSM이 설치되어 있지 않습니다.
    echo.
    echo NSSM 다운로드 및 설치 방법:
    echo 1. https://nssm.cc/download 방문
    echo 2. NSSM 다운로드 후 압축 해제
    echo 3. nssm.exe를 C:\Windows\System32 폴더에 복사
    echo 4. 이 스크립트를 다시 실행
    echo.
    echo 또는 아래 명령어로 자동 다운로드:
    echo   install_nssm.bat
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%i in ('where nssm') do set NSSM_PATH=%%i
echo ✓ NSSM 경로: %NSSM_PATH%

REM 기존 서비스 확인
echo.
echo [3/5] 기존 서비스 확인 중...
sc query TenderDashboard >nul 2>&1
if %errorlevel% equ 0 (
    echo 기존 서비스가 발견되었습니다.
    choice /C YN /M "기존 서비스를 제거하고 다시 설치하시겠습니까?"
    if errorlevel 2 (
        echo 설치를 취소했습니다.
        pause
        exit /b 0
    )
    echo 기존 서비스 중지 및 제거 중...
    nssm stop TenderDashboard >nul 2>&1
    timeout /t 2 /nobreak >nul
    nssm remove TenderDashboard confirm >nul 2>&1
    echo ✓ 기존 서비스가 제거되었습니다.
) else (
    echo ✓ 기존 서비스가 없습니다.
)

REM 서비스 설치
echo.
echo [4/5] 서비스 설치 중...
set APP_PATH=%~dp0app.py
set WORK_DIR=%~dp0

nssm install TenderDashboard "%PYTHON_PATH%" "%APP_PATH%"

if %errorlevel% neq 0 (
    echo [오류] 서비스 설치에 실패했습니다.
    pause
    exit /b 1
)

echo ✓ 서비스가 설치되었습니다.

REM 서비스 설정
echo.
echo [5/5] 서비스 설정 중...
nssm set TenderDashboard AppDirectory "%WORK_DIR%"
nssm set TenderDashboard DisplayName "입찰공고 통합 검색 시스템"
nssm set TenderDashboard Description "Flask 기반 입찰공고 통합 검색 시스템"
nssm set TenderDashboard Start SERVICE_AUTO_START
nssm set TenderDashboard AppStdout "%WORK_DIR%logs\service_stdout.log"
nssm set TenderDashboard AppStderr "%WORK_DIR%logs\service_stderr.log"
nssm set TenderDashboard AppRotateFiles 1
nssm set TenderDashboard AppRotateBytes 1048576

echo ✓ 서비스 설정이 완료되었습니다.

echo.
echo ========================================
echo ✓ 설치 완료!
echo ========================================
echo.
echo 서비스 정보:
echo - 서비스 이름: TenderDashboard
echo - 표시 이름: 입찰공고 통합 검색 시스템
echo - 시작 유형: 자동 (부팅 시 자동 시작)
echo - 로그 위치: %WORK_DIR%logs\
echo.
echo ========================================
echo.
echo 다음 단계:
echo.
echo 1. 서비스 시작:
echo    nssm start TenderDashboard
echo    또는 service_start.bat 실행
echo.
echo 2. 서비스 상태 확인:
echo    nssm status TenderDashboard
echo    또는 service_status.bat 실행
echo.
echo 3. 브라우저에서 http://localhost:5000 접속
echo.
echo 4. 서비스 관리:
echo    - 중지: service_stop.bat
echo    - 재시작: service_restart.bat
echo    - 제거: uninstall_service.bat
echo.
echo ========================================
echo.

choice /C YN /M "지금 서비스를 시작하시겠습니까?"
if errorlevel 2 (
    echo.
    echo service_start.bat을 실행하여 나중에 시작할 수 있습니다.
    echo.
    pause
    exit /b 0
)

echo.
echo 서비스 시작 중...
nssm start TenderDashboard

if %errorlevel% equ 0 (
    echo ✓ 서비스가 시작되었습니다.
    echo.
    echo 15초 후 자동으로 브라우저가 열립니다...
    timeout /t 15 /nobreak >nul
    start http://localhost:5000
) else (
    echo [오류] 서비스 시작에 실패했습니다.
    echo logs\service_stderr.log 파일을 확인해주세요.
)

echo.
pause
