@echo off
title Cloudflare Tunnel - ht-search.com
set CLOUDFLARED="C:\Users\USER\AppData\Local\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"

echo [Tunnel] Waiting for Flask to be ready...
timeout /t 3 /nobreak >nul

echo [Tunnel] Starting Cloudflare Tunnel...
echo [Tunnel] Public URL: https://ht-search.com
echo ==============================================================
%CLOUDFLARED% tunnel --config "C:\Users\USER\.cloudflared\config.yml" run ht-search
pause
