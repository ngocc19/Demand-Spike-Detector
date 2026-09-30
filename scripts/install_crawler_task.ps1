# ====================================================================
# Install Realtime Crawler Task - Windows Task Scheduler
# Chạy PowerShell AS ADMIN để thực thi script này
# ====================================================================

# Kiểm tra quyền Admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Red
    Write-Host "  CANH BAO: CHAY QUYEN ADMINISTRATOR" -ForegroundColor Red
    Write-Host "============================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "VUI LONG CHAY POWERShell AS ADMIN" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Cach thuc:" -ForegroundColor White
    Write-Host "1. Click chuot phai vao Start Menu" -ForegroundColor Gray
    Write-Host "2. Chon 'Terminal (Admin)' hoac 'Windows PowerShell (Admin)'" -ForegroundColor Gray
    Write-Host "3. Copy duong dan sau vao terminal:" -ForegroundColor Gray
    Write-Host "   cd '$PSScriptRoot'" -ForegroundColor Cyan
    Write-Host "   .\install_crawler_task.ps1" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}

# Cấu hình
$ProjectDir = "D:\Demand-Spike-Detector"
$TaskName = "RealtimeCrawler_15min"
$ScriptPath = "$ProjectDir\scripts\run_crawler.ps1"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  REALTIME CRAWLER - INSTALLATION" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project Directory: $ProjectDir" -ForegroundColor Gray
Write-Host "Task Name: $TaskName" -ForegroundColor Gray
Write-Host ""

# Xóa task cũ nếu có
Write-Host "[CLEANUP] Removing old task if exists..." -ForegroundColor Yellow
schtasks /Delete /TN "$TaskName" /F 2>$null

# Tạo thư mục data nếu chưa có
if (!(Test-Path "$ProjectDir\data")) {
    New-Item -ItemType Directory -Path "$ProjectDir\data" -Force | Out-Null
}
if (!(Test-Path "$ProjectDir\data\realtime_lake")) {
    New-Item -ItemType Directory -Path "$ProjectDir\data\realtime_lake" -Force | Out-Null
}

# Tạo task với schtasks.exe
Write-Host "[INSTALL] Creating scheduled task..." -ForegroundColor Green

$createResult = schtasks /Create `
    /TN "$TaskName" `
    /TR "powershell.exe -ExecutionPolicy Bypass -NoProfile -File `"$ScriptPath`"" `
    /SC MINUTE `
    /MO 15 `
    /ST 00:00 `
    /F `
    /RL HIGHEST

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Task created successfully!" -ForegroundColor Green

    # Chạy task ngay
    Write-Host "[START] Starting task immediately..." -ForegroundColor Green
    schtasks /Run /TN "$TaskName" 2>$null

    Start-Sleep -Seconds 2

} else {
    Write-Host "[ERROR] Failed to create task" -ForegroundColor Red
    Write-Host "Result: $createResult" -ForegroundColor Gray
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  INSTALLATION COMPLETE!" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Task Name: $TaskName" -ForegroundColor White
Write-Host "Schedule: Every 15 minutes" -ForegroundColor White
Write-Host "Log File: $ProjectDir\data\crawler_cron.log" -ForegroundColor White
Write-Host "Data Lake: $ProjectDir\data\realtime_lake\" -ForegroundColor White
Write-Host ""

# Hiển thị thông tin task
Write-Host "Task Info:" -ForegroundColor Yellow
schtasks /Query /TN "$TaskName" /FO LIST 2>$null

Write-Host ""
Write-Host "Kiem tra:" -ForegroundColor Yellow
Write-Host "1. Open Task Scheduler (Win+R > taskschd.msc)" -ForegroundColor Gray
Write-Host "2. Find task: $TaskName" -ForegroundColor Gray
Write-Host "3. Check log: $ProjectDir\data\crawler_cron.log" -ForegroundColor Gray
Write-Host ""
