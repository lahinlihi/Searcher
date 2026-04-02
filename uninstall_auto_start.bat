@echo off
chcp 65001 > nul
echo ========================================
echo 입찰공고 시스템 - 자동 시작 제거
echo ========================================
echo.
echo 이 스크립트는 Windows 작업 스케줄러에서
echo 자동 시작 작업을 제거합니다.
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

echo 작업 확인 중...
schtasks /Query /TN "입찰공고_자동시작" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [정보] 등록된 자동 시작 작업이 없습니다.
    echo.
    pause
    exit /b 0
)

echo.
echo 작업 제거 중...
schtasks /Delete /TN "입찰공고_자동시작" /F

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo ✓ 자동 시작이 제거되었습니다.
    echo.
    echo 이제 컴퓨터를 재시작해도 서버가
    echo 자동으로 실행되지 않습니다.
    echo ========================================
    echo.
) else (
    echo.
    echo [오류] 작업 제거에 실패했습니다.
    echo.
    echo 수동으로 제거하려면:
    echo 1. Win + R 키를 누르고 taskschd.msc 입력
    echo 2. "입찰공고_자동시작" 작업을 찾아 삭제
    echo.
)

pause
