# ====================================================================
# Wrapper Script - Event Realtime Crawler
# Chạy mỗi 2 giờ qua Task Scheduler (Windows)
# ====================================================================

# Cấu hình - UPDATE ĐƯỜNG DẪN CHO ĐÚNG
$ProjectDir = "D:\AITHUCCHIEN\Demand-Spike-Detector-v0"
$PythonExe = "python"
$PythonScript = "$ProjectDir\src\pipeline\event_realtime\cli.py"
$ConfigFile = "$ProjectDir\config\factors_realtime.yaml"

# Chuyển đến project directory TRƯỚC KHI chạy
Set-Location -Path $ProjectDir

# Log file
$LogFile = "$ProjectDir\data\event_realtime\cron.log"

# Tạo thư mục nếu chưa có
if (!(Test-Path "$ProjectDir\data\event_realtime")) {
    New-Item -ItemType Directory -Path "$ProjectDir\data\event_realtime" -Force | Out-Null
}

# Timestamp
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Chạy script với working directory đúng
Write-Host "[$Timestamp] Starting Event Realtime Crawler..."

try {
    # Set PYTHONPATH
    $env:PYTHONPATH = "$ProjectDir\src"

    $output = & $PythonExe -m pipeline.event_realtime.cli --config $ConfigFile --once 2>&1
    $exitCode = $LASTEXITCODE

    # Ghi log
    "$Timestamp - [START] Running event realtime crawler..." | Out-File -FilePath $LogFile -Append -Encoding UTF8
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
