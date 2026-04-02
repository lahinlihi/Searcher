@echo off
echo Creating startup shortcut...

set TARGET=D:\tender_dashboard\start_server_background.vbs
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT=%STARTUP%\TenderDashboard.lnk

powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut('%SHORTCUT%'); $Shortcut.TargetPath = '%TARGET%'; $Shortcut.WorkingDirectory = 'D:\tender_dashboard'; $Shortcut.Save()"

if exist "%SHORTCUT%" (
    echo SUCCESS: Shortcut created at %SHORTCUT%
    echo The server will auto-start on next login
) else (
    echo ERROR: Failed to create shortcut
)

pause
