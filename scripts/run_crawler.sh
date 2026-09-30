#!/bin/bash

# ====================================================================
# Wrapper Script - Realtime Weather Crawler
# Chạy mỗi 15 phút qua Cronjob (Linux)
# ====================================================================

# Cấu hình - SỬA ĐƯỜNG DẪN THEO SERVER CỦA BẠN
PROJECT_DIR="/opt/demand-spike-detector"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
PYTHON_SCRIPT="$PROJECT_DIR/scripts/realtime_crawler.py"
LOG_FILE="$PROJECT_DIR/data/crawler_cron.log"
LOG_DIR="$PROJECT_DIR/data"

# Tạo thư mục log nếu chưa có
mkdir -p "$LOG_DIR"

# Tạo thư mục realtime_lake nếu chưa có
mkdir -p "$PROJECT_DIR/data/realtime_lake"

# Timestamp cho log
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Chạy script
cd "$PROJECT_DIR"

echo "$TIMESTAMP - [START] Running crawler..." >> "$LOG_FILE"

$VENV_PYTHON "$PYTHON_SCRIPT" >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

TIMESTAMP2=$(date '+%Y-%m-%d %H:%M:%S')

if [ $EXIT_CODE -eq 0 ]; then
    echo "$TIMESTAMP2 - [END] Crawler finished successfully" >> "$LOG_FILE"
else
    echo "$TIMESTAMP2 - [ERROR] Crawler failed with exit code: $EXIT_CODE" >> "$LOG_FILE"
fi
