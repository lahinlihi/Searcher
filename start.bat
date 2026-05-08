@echo off
title 입찰공고 통합 검색 - Launcher
cd /d "%~dp0"

echo ============================================
echo   입찰공고 통합 검색 시스템 시작
echo ============================================
echo.
echo [1] Flask 앱을 새 창으로 시작합니다...
start "Flask App" cmd /c start_app.bat

echo [2] 3초 후 Cloudflare 터널을 시작합니다...
timeout /t 3 /nobreak >nul

echo [3] Cloudflare 터널 창을 엽니다...
echo     (터널 창에 표시되는 trycloudflare.com URL로 외부 접속 가능)
start "Cloudflare Tunnel" cmd /c start_tunnel.bat

echo.
echo 두 창이 열렸습니다.
echo - Flask 창: 앱 실행 로그
echo - Tunnel 창: 공개 URL 표시 (trycloudflare.com)
echo.
pause
