# Kế Hoạch Crawl Dữ Liệu Sự Kiện (Cập nhật theo Cấu trúc Dự án)

Tài liệu này hướng dẫn cách thu thập sự kiện, tích hợp logic ước tính số lượng người tham dự, và đồng bộ với cấu trúc thư mục hiện tại của dự án (`Demand-Spike-Detector-v0`).

## 1. Cấu Trúc Dữ Liệu Đầu Ra Mới (`data/events.csv`)

File `events.csv` nằm trong thư mục `data/` có các cột sau. `source_url` phải
là URL công khai của bài viết/trang trận đấu chứa sự kiện, không phải endpoint
API kỹ thuật. Nếu chưa tìm được bài nguồn thì không đưa bản ghi đó vào CSV;
đưa vào quarantine và thử lại ở lần crawl tiếp theo.

`attendance_source_url` là URL bài viết dùng làm bằng chứng cho số khán giả.
Trường này được để trống khi `estimated_attendees` chưa có số liệu được báo cáo.

| event_name | venue | start_time | end_time | type | estimated_attendees | source_url | attendance_source_url |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Concert BlackPink | SVD My Dinh | 2023-07-29 19:30:00 | 2023-07-29 22:00:00 | concert |  | https://nguon-chinh-thuc.example/event |  |
| CLB Ha Noi vs HAGL | SVD Hang Day | 2024-05-15 19:15:00 | 2024-05-15 21:15:00 | football | 18000 | https://nguon-chinh-thuc.example/match | https://nguon-bao-chi.example/match-attendance |
| Tech Summit 2024 | NCC | 2024-09-05 08:00:00 | 2024-09-05 17:00:00 | conference |  | https://nguon-chinh-thuc.example/event |

Pipeline cũng tạo data/events.xlsx với năm sheet: football, concert, festival,
exhibition và other. events.csv vẫn là bản dữ liệu chuẩn một bảng để các job
feature/model đọc; workbook chỉ là lớp xuất phục vụ kiểm tra và phân tích.

## 2. Chiến Lược Ước Tính Số Người Tham Dự (Attendees)

Theo yêu cầu hiện tại, chỉ ghi số người tham dự khi nguồn công bố trực tiếp.
Nếu không có thông tin thì để trống `estimated_attendees`; heuristic theo sức
chứa hiện đang tắt trong cấu hình.

Mapping sức chứa dưới đây chỉ là tài liệu tham khảo cho một phiên bản mô hình
sau này, khi bạn chủ động bật heuristic và chấp nhận nhãn ước tính.

**Bảng Sức Chứa (Capacity Mapping) các địa điểm lớn ở Hà Nội:**
*   `SVD My Dinh`: 40,000 người (Fill rate: Bóng đá V-League ~30%, Bóng đá ĐTQG ~90%, Concert ~80-100%)
*   `SVD Hang Day`: 22,500 người (Fill rate: V-League ~50-80%)
*   `Cung Dien Kinh (My Dinh)`: 3,000 người
*   `Cung The Thao Quan Ngua`: 5,500 người
*   `Trung tam Hoi nghi Quoc gia (NCC)`: 3,500 người
*   `Cung Van hoa Huu nghi Viet Xo`: 1,200 người
*   `ICE Hanoi (Tran Hung Dao)`: Tùy hội chợ, thường ~2,000 - 5,000 lượt khách/ngày.
*   `Pho di bo Ho Guom`: ~10,000 - 20,000 lượt khách (dành cho festival ngoài trời).

## 3. Triển Khai Trong `event_plugin.py`

File `src/pipeline/plugins/event_plugin.py` sẽ đóng vai trò là nơi chứa các script crawl này. Nhiệm vụ của nó là fetch data, map sức chứa, và lưu kết quả vào `data/events.csv`.

### Nguồn Crawl Khuyến Nghị:
1.  **Ticketbox API (Concert/Festival):**
    *   Bắt API ẩn qua F12 (Network tab) trên ticketbox.vn.
    *   Lọc các sự kiện có `location` thuộc Hà Nội.
    *   Dùng tên `venue` trả về để lookup trong bảng Capacity Mapping.
2.  **VPF / Soccerway (Bóng đá):**
    *   Cào bảng lịch thi đấu V-League từ web `vpf.vn`.
    *   Lọc các trận đấu tại `SVD Hàng Đẫy` và `SVD Mỹ Đình`.
3.  **Dữ liệu Tựu trường / Hội nghị (Nhập tay/Tĩnh):**
    *   Do tính chất rời rạc, đối với MVP, hãy tạo 1 list tĩnh trong hàm Python và tự động append vào chung với dữ liệu crawl.

## 4. Code Skeleton cho `event_plugin.py`

Dưới đây là khung code đề xuất để bạn đặt vào `src/pipeline/plugins/event_plugin.py`:

```python
import pandas as pd
import requests
import os
import yaml
from pathlib import Path

# Đường dẫn tĩnh dựa trên cấu trúc dự án
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
EVENTS_CSV_PATH = BASE_DIR / 'data' / 'events.csv'
CONFIG_PATH = BASE_DIR / 'config' / 'factors.yaml'

# Từ điển ánh xạ sức chứa (Nên chuyển vào config/factors.yaml sau)
VENUE_CAPACITY = {
    "SVD My Dinh": 40000,
    "SVD Hang Day": 22500,
    "Trung tam Hoi nghi Quoc gia": 3500,
    "Cung The Thao Quan Ngua": 5500,
    "Pho di bo Ho Guom": 15000,
    "Cung Van hoa Huu nghi Viet Xo": 1200,
    "Nha hat lon": 600
}

def estimate_attendees(venue_name, event_type):
    """Ước tính số người tham gia dựa trên địa điểm và loại sự kiện"""
    # Tìm gần đúng tên địa điểm
    capacity = 1000 # Default fallback
    for key, cap in VENUE_CAPACITY.items():
        if key.lower() in str(venue_name).lower():
            capacity = cap
            break
            
    # Giả định tỷ lệ lấp đầy (Fill Rate)
    fill_rate = {
        'concert': 0.85,
        'football': 0.60,
        'festival': 0.90,
        'conference': 0.70
    }.get(event_type, 0.5)
    
    return int(capacity * fill_rate)

def crawl_ticketbox():
    """Crawl dữ liệu từ Ticketbox API (Ví dụ giả lập)"""
    # api_url = "https://api.ticketbox.vn/..."
    # Lọc các sự kiện ở Hà Nội
    # Map loại sự kiện (concert, festival)
    events = []
    # Ví dụ output sau khi gọi API:
    events.append({
        "event_name": "Concert Ha Anh Tuan",
        "venue": "Trung tam Hoi nghi Quoc gia",
        "start_time": "2024-10-20 20:00:00",
        "end_time": "2024-10-20 23:00:00",
        "type": "concert"
    })
    return events

def crawl_football():
    """Crawl lịch thi đấu (Giả lập)"""
    # Dùng pandas read_html từ vpf.vn, lọc sân Hàng Đẫy/Mỹ Đình
    events = [{
        "event_name": "Ha Noi FC vs Viettel",
        "venue": "SVD Hang Day",
        "start_time": "2024-11-05 19:15:00",
        "end_time": "2024-11-05 21:15:00",
        "type": "football"
    }]
    return events

def run_event_pipeline():
    """Hàm chính để thực thi plugin"""
    all_events = []
    
    # 1. Thu thập dữ liệu
    all_events.extend(crawl_ticketbox())
    all_events.extend(crawl_football())
    
    # Thêm dữ liệu tĩnh (Tựu trường, Lễ hội lớn đã biết)
    all_events.append({
        "event_name": "Khai giang ĐHQG HN",
        "venue": "Khu vuc Xuan Thuy",
        "start_time": "2024-09-05 07:00:00",
        "end_time": "2024-09-05 12:00:00",
        "type": "conference"
    })
    
    # 2. Xử lý logic số người tham dự
    for event in all_events:
        event['estimated_attendees'] = estimate_attendees(event['venue'], event['type'])
        
    # 3. Lưu vào data/events.csv
    df = pd.DataFrame(all_events)
    
    # Nếu file đã tồn tại, có thể merge/update thay vì ghi đè hoàn toàn
    if os.path.exists(EVENTS_CSV_PATH):
        old_df = pd.read_csv(EVENTS_CSV_PATH)
        # Drop duplicates based on name and start_time
        df = pd.concat([old_df, df]).drop_duplicates(subset=['event_name', 'start_time'], keep='last')
        
    df.to_csv(EVENTS_CSV_PATH, index=False)
    print(f"✅ Đã cập nhật {len(df)} sự kiện vào {EVENTS_CSV_PATH}")

if __name__ == "__main__":
    run_event_pipeline()
```
