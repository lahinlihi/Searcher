# PowerShell script to create startup shortcut
$WshShell = New-Object -ComObject WScript.Shell
$StartupFolder = [System.Environment]::GetFolderPath('Startup')
$TargetPath = "D:\tender_dashboard\start_server_background.vbs"
$ShortcutPath = "$StartupFolder\입찰공고시스템.lnk"

# Remove existing shortcut if exists
if (Test-Path $ShortcutPath) {
    Remove-Item $ShortcutPath -Force
}

# Create new shortcut
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $TargetPath
$Shortcut.WorkingDirectory = "D:\tender_dashboard"
$Shortcut.Description = "입찰공고 통합 검색 시스템"
$Shortcut.WindowStyle = 7
$Shortcut.Save()

Write-Host "바로가기 생성 완료: $ShortcutPath"
Write-Host "대상 파일: $TargetPath"
