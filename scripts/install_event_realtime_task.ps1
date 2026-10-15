# ====================================================================
# Install Event Realtime Crawler Task - Windows Task Scheduler
# ====================================================================

$ProjectDir = "D:\AITHUCCHIEN\Demand-Spike-Detector-v0"
$TaskName = "EventRealtimeCrawler_2h"
$ScriptPath = "$ProjectDir\scripts\run_event_realtime.ps1"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  EVENT REALTIME CRAWLER - SETUP" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project Directory: $ProjectDir" -ForegroundColor Gray
Write-Host "Task Name: $TaskName" -ForegroundColor Gray
Write-Host "Interval: Every 2 hours" -ForegroundColor Gray
Write-Host ""

# Xóa task cũ nếu có
Write-Host "[CLEANUP] Removing old task if exists..." -ForegroundColor Yellow
schtasks /Delete /TN "$TaskName" /F 2>$null

# Tạo thư mục nếu chưa có
if (!(Test-Path "$ProjectDir\data\event_realtime")) {
    New-Item -ItemType Directory -Path "$ProjectDir\data\event_realtime" -Force | Out-Null
}

# Tạo task với schtasks.exe
# Chạy mỗi 2 giờ (120 phút)
Write-Host "[INSTALL] Creating scheduled task..." -ForegroundColor Green

$createResult = schtasks /Create `
    /TN "$TaskName" `
    /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -File `"$ScriptPath`"" `
    /SC MINUTE `
    /MO 120 `
    /ST 00:00 `
    /F `
    /RL HIGHEST

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Task created successfully!" -ForegroundColor Green
    Write-Host ""

    # Chạy task ngay để test
    Write-Host "[TEST] Running crawler immediately to verify..." -ForegroundColor Yellow
    & $ScriptPath
    Write-Host ""

} else {
    Write-Host "[ERROR] Failed to create task" -ForegroundColor Red
    Write-Host "Result: $createResult" -ForegroundColor Gray
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  SETUP COMPLETE!" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Task Name: $TaskName" -ForegroundColor White
Write-Host "Schedule: Every 2 hours" -ForegroundColor White
Write-Host "Log File: $ProjectDir\data\event_realtime\cron.log" -ForegroundColor White
Write-Host ""
Write-Host "Kiem tra task:" -ForegroundColor Yellow
Write-Host "  schtasks /Query /TN `"$TaskName`"" -ForegroundColor Gray
Write-Host ""
Write-Host "Xoa task:" -ForegroundColor Yellow
Write-Host "  schtasks /Delete /TN `"$TaskName`" /F" -ForegroundColor Gray
Write-Host ""
