#!/bin/bash

# ====================================================================
# Install Realtime Crawler Cron Job - Linux
# Chạy script này 1 lần duy nhất để cài đặt cron job
# ====================================================================

# Màu sắc cho output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  REALTIME CRAWLER - LINUX INSTALLATION${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Cấu hình - SỬA ĐƯỜNG DẪN THEO SERVER CỦA BẠN
PROJECT_DIR="/opt/demand-spike-detector"
SCRIPT_PATH="$PROJECT_DIR/scripts/run_crawler.sh"
CRON_LINE="*/15 * * * * $SCRIPT_PATH >> $PROJECT_DIR/data/cron_wrapper.log 2>&1"

# Kiểm tra đường dẫn
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}[ERROR] Project directory not found: $PROJECT_DIR${NC}"
    echo "Vui long sua duong dan trong script nay."
    exit 1
fi

if [ ! -f "$SCRIPT_PATH" ]; then
    echo -e "${RED}[ERROR] Script not found: $SCRIPT_PATH${NC}"
    exit 1
fi

# Phân quyền execute cho script
echo -e "${YELLOW}[SETUP] Setting execute permissions...${NC}"
chmod +x "$SCRIPT_PATH"

# Tạo thư mục data nếu chưa có
mkdir -p "$PROJECT_DIR/data"
mkdir -p "$PROJECT_DIR/data/realtime_lake"

echo -e "${GREEN}[OK] Directories created/verified${NC}"
echo ""

# Xóa cron cũ nếu có
echo -e "${YELLOW}[CLEANUP] Removing old cron entries...${NC}"
crontab -l 2>/dev/null | grep -v "realtime_crawler" | grep -v "$SCRIPT_PATH" | crontab - 2>/dev/null
echo -e "${GREEN}[OK] Old entries removed${NC}"
echo ""

# Thêm cron mới
echo -e "${YELLOW}[INSTALL] Adding cron job...${NC}"
(crontab -l 2>/dev/null; echo "") | crontab - 2>/dev/null
(crontab -l 2>/dev/null; echo "# ============================================================") | crontab -
(crontab -l 2>/dev/null; echo "# REALTIME CRAWLER - Chay moi 15 phut") | crontab -
(crontab -l 2>/dev/null; echo "# ============================================================") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
echo -e "${GREEN}[OK] Cron job added${NC}"
echo ""

# Test chạy script ngay
echo -e "${YELLOW}[TEST] Running crawler now...${NC}"
$SCRIPT_PATH
echo ""

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  INSTALLATION COMPLETE!${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo -e "Project Directory: ${WHITE}$PROJECT_DIR${NC}"
echo -e "Script: ${WHITE}$SCRIPT_PATH${NC}"
echo -e "Log File: ${WHITE}$PROJECT_DIR/data/crawler_cron.log${NC}"
echo -e "Data Lake: ${WHITE}$PROJECT_DIR/data/realtime_lake/${NC}"
echo ""
echo -e "Kiem tra cron:${NC}"
echo -e "  crontab -l"
echo ""
echo -e "Xem log:${NC}"
echo -e "  tail -f $PROJECT_DIR/data/crawler_cron.log"
echo ""
echo -e "Xoa cron job:${NC}"
echo -e "  crontab -e"
echo -e "  (xoa 4 dong lien quan den realtime_crawler)"
echo ""
