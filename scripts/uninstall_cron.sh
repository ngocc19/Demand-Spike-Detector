#!/bin/bash

# ====================================================================
# Uninstall Realtime Crawler Cron Job - Linux
# Chạy script này để gỡ cài đặt cron job
# ====================================================================

# Màu sắc cho output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}  REALTIME CRAWLER - UNINSTALL${NC}"
echo -e "${YELLOW}============================================${NC}"
echo ""

# Xóa cron job
echo -e "${YELLOW}[REMOVE] Removing cron job...${NC}"
crontab -l 2>/dev/null | grep -v "realtime_crawler" | grep -v "run_crawler.sh" | crontab -
echo -e "${GREEN}[OK] Cron job removed${NC}"
echo ""

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  UNINSTALL COMPLETE!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "Data files van con trong thu muc data/." -ForegroundColor Gray
echo ""
