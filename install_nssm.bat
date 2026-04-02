@echo off
chcp 65001 > nul
echo ========================================
echo NSSM 자동 다운로드 및 설치
echo ========================================
echo.
echo NSSM(Non-Sucking Service Manager)은
echo Windows 서비스를 쉽게 관리할 수 있는 도구입니다.
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

REM 이미 설치되어 있는지 확인
where nssm >nul 2>&1
if %errorlevel% equ 0 (
    echo [정보] NSSM이 이미 설치되어 있습니다.
    for /f "delims=" %%i in ('where nssm') do echo 경로: %%i
    echo.
    choice /C YN /M "다시 설치하시겠습니까?"
    if errorlevel 2 (
        pause
        exit /b 0
    )
)

echo.
echo [안내] NSSM 다운로드
echo ========================================
echo.
echo 이 스크립트는 자동 다운로드를 지원하지 않습니다.
echo 다음 단계를 따라 수동으로 설치해주세요:
echo.
echo 1. 브라우저에서 https://nssm.cc/download 방문
echo 2. 최신 버전의 NSSM 다운로드
echo 3. 압축 해제 후 win64\nssm.exe 파일 찾기
echo 4. nssm.exe를 다음 위치 중 하나에 복사:
echo    - C:\Windows\System32\
echo    - 또는 이 폴더 (D:\tender_dashboard)
echo.
echo ========================================
echo.

choice /C YN /M "다운로드 페이지를 지금 여시겠습니까?"
if errorlevel 2 (
    echo.
    echo 나중에 수동으로 설치해주세요.
    pause
    exit /b 0
)

echo.
echo 브라우저를 여는 중...
start https://nssm.cc/download

echo.
echo ========================================
echo 다운로드 및 설치 후:
echo ========================================
echo.
echo 1. nssm.exe를 C:\Windows\System32에 복사
echo 2. install_as_service.bat을 실행하여 서비스 등록
echo.
pause
