# ====================================================================
# Uninstall Realtime Crawler Task - Windows Task Scheduler
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
    exit 1
}

$TaskName = "RealtimeCrawler_15min"

Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "  REALTIME CRAWLER - UNINSTALL" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""

# Kiểm tra task có tồn tại không
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-Host "[STOP] Stopping task..." -ForegroundColor Yellow
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1

    Write-Host "[REMOVE] Removing task..." -ForegroundColor Red
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false

    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "  UNINSTALL COMPLETE!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task '$TaskName' da duoc xoa." -ForegroundColor White
    Write-Host "Data files van con trong thu muc data\" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host "Task '$TaskName' khong ton tai." -ForegroundColor Gray
    Write-Host ""
}
