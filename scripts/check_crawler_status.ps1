# ====================================================================
# Check Status - Realtime Crawler Status Script
# Chạy để kiểm tra trạng thái của crawler
# ====================================================================

$ProjectDir = "D:\Demand-Spike-Detector"
$TaskName = "RealtimeCrawler_15min"
$LogFile = "$ProjectDir\data\crawler_cron.log"
$DataLakeDir = "$ProjectDir\data\realtime_lake"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  REALTIME CRAWLER - STATUS CHECK" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Kiểm tra Task Scheduler
Write-Host "[TASK SCHEDULER]" -ForegroundColor Yellow
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($task) {
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue

    Write-Host "  Status: " -NoNewline
    if ($task.State -eq "Ready") {
        Write-Host $task.State -ForegroundColor Green
    } elseif ($task.State -eq "Running") {
        Write-Host $task.State -ForegroundColor Cyan
    } else {
        Write-Host $task.State -ForegroundColor Yellow
    }
    Write-Host "  Last Run: $($taskInfo.LastRunTime)" -ForegroundColor White
    Write-Host "  Next Run: $($taskInfo.NextRunTime)" -ForegroundColor White
    Write-Host "  Last Result: $($taskInfo.LastTaskResult)" -ForegroundColor Gray
} else {
    Write-Host "  Status: NOT INSTALLED" -ForegroundColor Red
}
Write-Host ""

# Kiểm tra Log File
Write-Host "[LOG FILE]" -ForegroundColor Yellow
if (Test-Path $LogFile) {
    $logContent = Get-Content $LogFile -Tail 15
    Write-Host "  Path: $LogFile" -ForegroundColor White
    Write-Host "  Size: $([math]::Round((Get-Item $LogFile).Length / 1KB, 2)) KB" -ForegroundColor White
    Write-Host ""
    Write-Host "  Last 15 entries:" -ForegroundColor Gray
    $logContent | ForEach-Object {
        if ($_ -match "\[ERROR\]") {
            Write-Host "    $_" -ForegroundColor Red
        } elseif ($_ -match "\[START\]") {
            Write-Host "    $_" -ForegroundColor Green
        } elseif ($_ -match "\[END\]") {
            Write-Host "    $_" -ForegroundColor Cyan
        } else {
            Write-Host "    $_" -ForegroundColor DarkGray
        }
    }
} else {
    Write-Host "  Status: NOT FOUND" -ForegroundColor Red
    Write-Host "  Path: $LogFile" -ForegroundColor Gray
}
Write-Host ""

# Kiểm tra Data Lake
Write-Host "[DATA LAKE]" -ForegroundColor Yellow
if (Test-Path $DataLakeDir) {
    $parquetFiles = Get-ChildItem -Path $DataLakeDir -Filter "*.parquet" -ErrorAction SilentlyContinue

    if ($parquetFiles) {
        Write-Host "  Status: $(@($parquetFiles).Count) parquet file(s) found" -ForegroundColor Green
        Write-Host ""

        foreach ($file in $parquetFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 5) {
            $sizeMB = [math]::Round($file.Length / 1MB, 2)
            Write-Host "    $($file.Name) - $sizeMB MB - $($file.LastWriteTime)" -ForegroundColor White
        }
    } else {
        Write-Host "  Status: NO DATA" -ForegroundColor Yellow
    }
} else {
    Write-Host "  Status: NOT FOUND" -ForegroundColor Red
}
Write-Host ""

# Thống kê
Write-Host "[STATISTICS]" -ForegroundColor Yellow
if (Test-Path $LogFile) {
    $startCount = (Select-String -Path $LogFile -Pattern "\[START\]" | Measure-Object).Count
    $endCount = (Select-String -Path $LogFile -Pattern "\[END\]" | Measure-Object).Count
    $errorCount = (Select-String -Path $LogFile -Pattern "\[ERROR\]" | Measure-Object).Count

    Write-Host "  Total Runs: $startCount" -ForegroundColor White
    Write-Host "  Successful: $endCount" -ForegroundColor Green
    Write-Host "  Errors: $errorCount" -ForegroundColor $(if ($errorCount -gt 0) { "Red" } else { "Green" })
}
Write-Host ""

Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Hướng dẫn
Write-Host "QUICK COMMANDS:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Kiem tra Task Scheduler:" -ForegroundColor Gray
Write-Host "    Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Xem log real-time:" -ForegroundColor Gray
Write-Host "    Get-Content '$LogFile' -Tail 20 -Wait" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Xoa task:" -ForegroundColor Gray
Write-Host "    .\uninstall_crawler_task.ps1" -ForegroundColor DarkGray
Write-Host ""
