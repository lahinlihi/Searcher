# Test Auto Start Configuration
Write-Host "========================================"
Write-Host "Tender Dashboard - Auto Start Test"
Write-Host "========================================"
Write-Host ""

# Check startup folder
$StartupFolder = [System.Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $StartupFolder "TenderDashboard.lnk"

Write-Host "[1/4] Checking Startup Folder..."
if (Test-Path $ShortcutPath) {
    Write-Host "  SUCCESS: Shortcut exists at $ShortcutPath" -ForegroundColor Green

    # Check shortcut details
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    Write-Host "  Target: $($Shortcut.TargetPath)"
    Write-Host "  Working Directory: $($Shortcut.WorkingDirectory)"
} else {
    Write-Host "  WARNING: No shortcut found" -ForegroundColor Yellow
}
Write-Host ""

# Check scheduled task
Write-Host "[2/4] Checking Task Scheduler..."
$Task = Get-ScheduledTask -TaskName "TenderDashboard" -ErrorAction SilentlyContinue
if ($Task) {
    Write-Host "  SUCCESS: Task 'TenderDashboard' is registered" -ForegroundColor Green
    Write-Host "  State: $($Task.State)"
} else {
    Write-Host "  INFO: No scheduled task found (using startup folder instead)" -ForegroundColor Cyan
}
Write-Host ""

# Check if Python is running
Write-Host "[3/4] Checking Server Status..."
$PythonProcess = Get-Process -Name python -ErrorAction SilentlyContinue
if ($PythonProcess) {
    Write-Host "  SUCCESS: Python process is running" -ForegroundColor Green
    Write-Host "  Process ID: $($PythonProcess.Id)"
    Write-Host "  Memory: $([math]::Round($PythonProcess.WorkingSet64/1MB, 2)) MB"
} else {
    Write-Host "  INFO: Python is not currently running" -ForegroundColor Cyan
}
Write-Host ""

# Check port 5001
Write-Host "[4/4] Checking Port 5001..."
$Port5001 = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue
if ($Port5001) {
    Write-Host "  SUCCESS: Port 5001 is listening" -ForegroundColor Green
    Write-Host "  Process ID: $($Port5001.OwningProcess)"
    Write-Host ""
    Write-Host "  Server is running at: http://localhost:5001" -ForegroundColor Green
} else {
    Write-Host "  INFO: Port 5001 is not in use" -ForegroundColor Cyan
    Write-Host "  Server may not be running yet"
}
Write-Host ""

Write-Host "========================================"
Write-Host "Summary:"
Write-Host "========================================"
if (Test-Path $ShortcutPath) {
    Write-Host "Auto-start: CONFIGURED (Startup Folder)" -ForegroundColor Green
    Write-Host "Next Login: Server will start automatically" -ForegroundColor Green
} elseif ($Task) {
    Write-Host "Auto-start: CONFIGURED (Task Scheduler)" -ForegroundColor Green
    Write-Host "Next Boot: Server will start automatically" -ForegroundColor Green
} else {
    Write-Host "Auto-start: NOT CONFIGURED" -ForegroundColor Yellow
}

if ($Port5001) {
    Write-Host "Server Status: RUNNING on http://localhost:5001" -ForegroundColor Green
} else {
    Write-Host "Server Status: NOT RUNNING" -ForegroundColor Yellow
}
Write-Host "========================================"
Write-Host ""
