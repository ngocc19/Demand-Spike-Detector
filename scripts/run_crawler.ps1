# ====================================================================
# Wrapper Script - Realtime Weather Crawler
# Chạy mỗi 15 phút qua Task Scheduler (Windows)
# ====================================================================

# Cấu hình
$ProjectDir = "D:\Demand-Spike-Detector"
$PythonExe = "python"
$PythonScript = "$ProjectDir\scripts\realtime_crawler.py"

# Chuyển đến project directory TRƯỚC KHI chạy
Set-Location -Path $ProjectDir

# Log file trong realtime_lake
$LogFile = "$ProjectDir\data\realtime_lake\crawler_cron.log"

# Tạo thư mục nếu chưa có
$RealtimeLakeDir = "$ProjectDir\data\realtime_lake"
if (!(Test-Path $RealtimeLakeDir)) {
    New-Item -ItemType Directory -Path $RealtimeLakeDir -Force | Out-Null
}

# Timestamp
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Chạy script với working directory đúng
Write-Host "[$Timestamp] Starting crawler from $ProjectDir..."

try {
    $output = & $PythonExe $PythonScript 2>&1
    $exitCode = $LASTEXITCODE

    # Ghi log
    "$Timestamp - [START] Running crawler..." | Out-File -FilePath $LogFile -Append -Encoding UTF8
    $output | Out-File -FilePath $LogFile -Append -Encoding UTF8

    if ($exitCode -eq 0) {
        "$Timestamp - [END] Crawler finished successfully" | Out-File -FilePath $LogFile -Append -Encoding UTF8
        Write-Host "[$Timestamp] Crawler finished successfully"
    } else {
        "$Timestamp - [ERROR] Crawler failed with exit code: $exitCode" | Out-File -FilePath $LogFile -Append -Encoding UTF8
        Write-Host "[$Timestamp] Crawler failed with exit code: $exitCode" -ForegroundColor Red
    }
} catch {
    $Timestamp2 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$Timestamp2 - [ERROR] $_" | Out-File -FilePath $LogFile -Append -Encoding UTF8
    Write-Host "[$Timestamp2] ERROR: $_" -ForegroundColor Red
}
