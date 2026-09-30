# Realtime Crawler Scripts

Thư mục chứa các script để deploy và quản lý Realtime Weather Crawler.

## Cấu Trúc File

```
scripts/
├── realtime_crawler.py           # Script chính - crawl dữ liệu real-time
├── run_crawler.ps1               # Wrapper cho Windows (Task Scheduler)
├── run_crawler.sh                # Wrapper cho Linux (Cronjob)
├── install_crawler_task.ps1      # Script cài đặt Task Scheduler (Windows)
├── uninstall_crawler_task.ps1    # Script gỡ Task Scheduler (Windows)
├── install_cron.sh               # Script cài đặt Cronjob (Linux)
├── uninstall_cron.sh            # Script gỡ Cronjob (Linux)
└── check_crawler_status.ps1     # Script kiểm tra trạng thái (Windows)
```

---

## WINDOWS - Hướng Dẫn Sử Dụng

### Bước 1: Cài Đặt (Chạy 1 lần)

1. **Mở PowerShell với quyền Administrator**
   - Click chuột phải vào Start Menu
   - Chọn "Terminal (Admin)" hoặc "Windows PowerShell (Admin)"

2. **Chạy script cài đặt**
   ```powershell
   cd D:\Demand-Spike-Detector\scripts
   .\install_crawler_task.ps1
   ```

3. **Kiểm tra Task Scheduler**
   - Nhấn `Win + R` → gõ `taskschd.msc` → Enter
   - Tìm task: `RealtimeCrawler_15min`

### Bước 2: Kiểm Tra Trạng Thái

```powershell
# Kiểm tra nhanh
.\check_crawler_status.ps1

# Xem log real-time
Get-Content "D:\Demand-Spike-Detector\data\crawler_cron.log" -Tail 50 -Wait
```

### Bước 3: Quản Lý Task

```powershell
# Dừng task
Stop-ScheduledTask -TaskName "RealtimeCrawler_15min"

# Bắt đầu task
Start-ScheduledTask -TaskName "RealtimeCrawler_15min"

# Gỡ cài đặt
.\uninstall_crawler_task.ps1
```

---

## LINUX - Hướng Dẫn Sử Dụng

### Bước 1: Cài Đặt (Chạy 1 lần)

```bash
# Phân quyền cho script
chmod +x scripts/run_crawler.sh
chmod +x scripts/install_cron.sh

# Chạy script cài đặt
./scripts/install_cron.sh
```

### Bước 2: Kiểm Tra

```bash
# Xem cron job đã thêm
crontab -l

# Xem log real-time
tail -f /opt/demand-spike-detector/data/crawler_cron.log

# Đếm số lần chạy trong ngày
grep "$(date '+%Y-%m-%d')" /opt/demand-spike-detector/data/crawler_cron.log | grep "\[START\]" | wc -l
```

### Bước 3: Quản Lý Cron

```bash
# Gỡ cài đặt
./scripts/uninstall_cron.sh

# Hoặc thủ công
crontab -e
# Xóa 4 dòng liên quan đến realtime_crawler
```

---

## Cấu Hình

### Windows - Sửa đường dẫn trong file

Mở `run_crawler.ps1` và sửa dòng:
```powershell
$ProjectDir = "D:\Demand-Spike-Detector"  # SỬA ĐƯỜNG DẪN TẠI ĐÂY
```

### Linux - Sửa đường dẫn trong file

Mở `run_crawler.sh` và sửa dòng:
```bash
PROJECT_DIR="/opt/demand-spike-detector"  # SỬA ĐƯỜNG DẪN TẠI ĐÂY
```

---

## Output

### Log Files
- **Windows:** `data/crawler_cron.log`
- **Linux:** `/opt/demand-spike-detector/data/crawler_cron.log`

### Data Lake
- **Windows:** `data/realtime_lake/weather_YYYY-MM-DD.parquet`
- **Linux:** `/opt/demand-spike-detector/data/realtime_lake/weather_YYYY-MM-DD.parquet`

---

## Cron Expression (Linux)

```
*/15 * * * * /opt/demand-spike-detector/scripts/run_crawler.sh >> /opt/demand-spike-detector/data/cron_wrapper.log 2>&1
```

| Vị trí | Giá trị | Ý nghĩa |
|---------|---------|----------|
| `*/15` | Phút | Mỗi 15 phút |
| `*` | Giờ | Mọi giờ |
| `*` | Ngày | Mọi ngày |
| `*` | Tháng | Mọi tháng |
| `*` | Thứ | Mọi thứ |

---

## Troubleshooting

### Windows

**Task không chạy:**
```powershell
# Kiểm tra lịch sử
Get-ScheduledTaskInfo -TaskName "RealtimeCrawler_15min"

# Xem chi tiết task
Get-ScheduledTask -TaskName "RealtimeCrawler_15min" | Get-ScheduledTaskInfo

# Chạy thủ công để debug
.\run_crawler.ps1
```

### Linux

**Cron không chạy:**
```bash
# Kiểm tra cron service
sudo systemctl status cron

# Xem log hệ thống
grep CRON /var/log/syslog | tail -20

# Test chạy thủ công
/opt/demand-spike-detector/scripts/run_crawler.sh
```
