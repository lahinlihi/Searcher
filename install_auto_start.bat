@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 시스템 - 자동 시작 설치
echo ========================================
echo.
echo 이 스크립트는 Windows 작업 스케줄러에
echo 자동 시작 작업을 등록합니다.
echo.
echo 부팅 시 자동으로 서버가 실행됩니다.
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

echo [1/3] 기존 작업 확인 중...
schtasks /Query /TN "입찰공고_자동시작" >nul 2>&1
if %errorlevel% equ 0 (
    echo 기존 작업이 발견되었습니다. 삭제 중...
    schtasks /Delete /TN "입찰공고_자동시작" /F >nul 2>&1
)

echo.
echo [2/3] 작업 스케줄러에 등록 중...
schtasks /Create /XML "%~dp0TenderDashboard_Task.xml" /TN "입찰공고_자동시작"

if %errorlevel% equ 0 (
    echo.
    echo [3/3] 설치 완료!
    echo ========================================
    echo.
    echo ✓ 작업 이름: 입찰공고_자동시작
    echo ✓ 실행 시점: 컴퓨터 부팅 후 1분 뒤
    echo ✓ 실행 파일: start_server_background.vbs
    echo.
    echo 이제 컴퓨터를 재시작하면 자동으로 서버가 실행됩니다.
    echo.
    echo ========================================
    echo.
    echo 추가 작업:
    echo - 작업 확인: 작업 스케줄러 열기 (taskschd.msc)
    echo - 즉시 테스트: test_auto_start.bat 실행
    echo - 제거: uninstall_auto_start.bat 실행
    echo.
) else (
    echo.
    echo [오류] 작업 스케줄러 등록에 실패했습니다.
    echo.
    echo 해결 방법:
    echo 1. TenderDashboard_Task.xml 파일이 있는지 확인
    echo 2. 관리자 권한으로 실행했는지 확인
    echo 3. 수동 설정 가이드(AUTO_START_GUIDE.md) 참고
    echo.
)

pause
