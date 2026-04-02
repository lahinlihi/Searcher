# Create startup shortcut for Tender Dashboard
$WshShell = New-Object -ComObject WScript.Shell
$StartupFolder = [System.Environment]::GetFolderPath('Startup')
$TargetPath = "D:\tender_dashboard\start_server_background.vbs"
$ShortcutPath = Join-Path $StartupFolder "TenderDashboard.lnk"

# Remove existing shortcut
if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
    Write-Host "Removed existing shortcut"
}

# Create new shortcut
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = "D:\tender_dashboard"
$Shortcut.Description = "Tender Dashboard Auto Start"
$Shortcut.WindowStyle = 7
$Shortcut.Save()

Write-Host "SUCCESS: Shortcut created at: $ShortcutPath"
Write-Host "Target: $TargetPath"
Write-Host ""
Write-Host "The server will auto-start on next login!"
