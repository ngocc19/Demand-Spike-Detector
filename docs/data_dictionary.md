# Data Dictionary - Merged Events Dataset

## Tổng quan

File dữ liệu `events.csv` / `events.xlsx` là kết quả của quá trình **merge** từ nhiều nguồn dữ liệu:

| Nguồn | Source | Mô tả |
|--------|--------|--------|
| **Events** | Web Scraping (VanMieu, Ticketbox, VPF, VFF, etc.) | Thông tin sự kiện văn hóa, lễ hội, concert, football |
| **Weather** | Weather APIs (VCW, OWM) | Dữ liệu thời tiết theo thời gian thực |
| **Holiday** | Vietnamese Calendar API | Ngày lễ, Tết, ngày nghỉ |
| **Flood** | HSDC API | Dữ liệu lũ lụt (đang trong quá trình tích hợp) |

---

## Cách Merge Dữ liệu

### 1. Quy trình tổng quan

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           MERGE PIPELINE                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐                │
│  │   EVENTS    │      │   WEATHER   │      │   HOLIDAY  │                │
│  │  (source)   │      │  (source)   │      │  (source)   │                │
│  └──────┬──────┘      └──────┬──────┘      └──────┬──────┘                │
│         │                     │                     │                       │
│         │  crawl từ          │  fetch từ          │  fetch từ             │
│         │  multiple APIs     │  weather APIs      │  calendar API         │
│         │                     │                     │                       │
│         ▼                     ▼                     ▼                       │
│  ┌─────────────────────────────────────────────────────┐                  │
│  │                  BASE: EVENT SLOTS                   │                  │
│  │  • Mỗi event được expand thành 30-min slots        │                  │
│  │  • Primary Key: h3_index + date + slot_time        │                  │
│  └─────────────────────────┬───────────────────────────┘                  │
│                            │                                               │
│                            │ LEFT JOIN by datetime                         │
│                            ▼                                               │
│  ┌─────────────────────────────────────────────────────┐                  │
│  │              MERGED: EVENT + WEATHER                │                  │
│  │  • Weather impact theo thời gian thực               │                  │
│  │  • Temperature, humidity, precipitation            │                  │
│  └─────────────────────────┬───────────────────────────┘                  │
│                            │                                               │
│                            │ LEFT JOIN by date                             │
│                            ▼                                               │
│  ┌─────────────────────────────────────────────────────┐                  │
│  │           MERGED: EVENT + WEATHER + HOLIDAY         │                  │
│  │  • Holiday flags: is_holiday, holiday_impact       │                  │
│  │  • Tet phases (pre-Tet, Tet, post-Tet)             │                  │
│  └─────────────────────────────────────────────────────┘                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Chi tiết từng bước

#### Bước 1: Crawl Events

```python
# Input: Multiple event sources
# - van_mieu: cultural events, workshops
# - vpf_football: V-League matches
# - vff_football: National team matches
# - ticketbox_concert: Concerts, live shows
# - lehoivietnam: Festivals, public events

# Output: Raw event data
# Primary Key: event_id
```

#### Bước 2: Expand Events thành 30-Minute Slots

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EXPAND LOGIC                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Input: 1 event = { start_time: "08:00", end_time: "22:00" }              │
│                                                                              │
│  Output: 28 slots = {                                                       │
│    08:00, 08:30, 09:00, 09:30, 10:00, ..., 21:30                         │
│  }                                                                           │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  Default Time Handling (00:00-23:59):                                      │
│                                                                              │
│  Many events have placeholder times (00:00-23:59).                          │
│  These are converted to operational hours:                                   │
│                                                                              │
│  │ Event Type    │ Inferred Hours │ Reason                                │
│  ├───────────────┼────────────────┼─────────────────────────────────────  │
│  │ Exhibition    │ 08:00-22:00    │ Standard museum/gallery hours          │
│  │ Festival      │ 08:00-22:00    │ Daytime events with evening extension  │
│  │ Concert       │ (use real)     │ Real times from Ticketbox API         │
│  │ Football      │ (use real)     │ Real kickoff times from VPF/VFF API   │
│  │ Cultural      │ (use real)     │ Real times from VanMieu API           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Bước 3: Merge với Weather

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        WEATHER MERGE                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Join Key: datetime (date + slot_time)                                      │
│                                                                              │
│  Events.datetime           Weather.datetime                                 │
│  2026-08-01 09:00    ←→    2026-08-01 09:00:00                           │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  Weather Data Coverage:                                                     │
│  • Date range: 2026-06-29 → 2026-09-28                                   │
│  • Resolution: 30 minutes (matching event slots)                            │
│  • Geographic: 2 anchor locations (CauGiay, West Hanoi)                  │
│                                                                              │
│  If no weather data:                                                        │
│  • weather_impact = 0.0                                                    │
│  • Other weather fields = NaN                                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Bước 4: Merge với Holiday

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        HOLIDAY MERGE                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Join Key: date (date only, không time)                                    │
│                                                                              │
│  Events.date          Holiday.date                                           │
│  2026-09-02     ←→    2026-09-02 (Vietnam Independence Day)              │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  Holiday Types:                                                             │
│  • National holidays (Quốc khánh, Tết Dương lịch)                         │
│  • Vietnamese holidays (Tết Nguyên đán, Giỗ tổ Hùng Vương)                │
│  • Tet phases: pre_tet, during_tet, post_tet                              │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Schema (36 Trường)

### A. Event Information (9 trường)

| Trường | Kiểu | Mô tả | Nguồn |
|--------|------|--------|--------|
| `event_name` | string | Tên sự kiện đầy đủ | VanMieu, Ticketbox, VPF, VFF |
| `venue` | string | Địa điểm tổ chức | VanMieu, Ticketbox, VPF, VFF |
| `start_date` | date | Ngày bắt đầu (YYYY-MM-DD) | Tất cả sources |
| `start_time` | time | Giờ bắt đầu (HH:MM) | Tất cả sources |
| `end_time` | time | Giờ kết thúc (HH:MM) | Tất cả sources |
| `slot_time` | time | Thời điểm slot 30 phút (HH:MM) | Generated |
| `type` | string | Loại sự kiện | Classification từ config |
| `estimate_attendence` | int | Số người tham dự ước tính | VPF, VFF, Ticketbox |
| `source_url` | string | URL nguồn gốc sự kiện | Tất cả sources |

### B. Geographic Information (6 trường)

| Trường | Kiểu | Mô tả | Nguồn |
|--------|------|--------|--------|
| `latitude` | float | Vĩ độ của venue | Geocoding từ venue name |
| `longitude` | float | Kinh độ của venue | Geocoding từ venue name |
| `h3_index` | string | H3 spatial index (resolution 15) | Computed từ lat/lon |
| `anchor_name` | string | Tên trạm thời tiết gần nhất | Weather API |
| `anchor_lat` | float | Vĩ độ trạm thời tiết | Weather API |
| `anchor_lon` | float | Kinh độ trạm thời tiết | Weather API |

### C. Weather Information (11 trường)

| Trường | Kiểu | Mô tả | Nguồn |
|--------|------|--------|--------|
| `temp_c` | float | Nhiệt độ (Celsius) | VCW API |
| `humidity_pct` | float | Độ ẩm (%) | VCW API |
| `precip` | float | Lượng mưa (mm) | VCW API |
| `precip_prob` | float | Xác suất mưa (%) | VCW API |
| `wind_speed` | float | Tốc độ gió (km/h) | VCW API |
| `weather_conditions` | string | Mô tả thời tiết | VCW API |
| `weather_impact` | float | Tác động thời tiết (0-1) | Computed |
| `precip_impact` | float | Tác động mưa (0-1) | Computed |
| `blended_weather_impact` | float | Tác động thời tiết blend (0-1) | Computed |
| `blended_value` | float | Giá trị blend | Computed |
| `is_monsoon` | int | Có mùa mưa (0/1) | Computed |

### D. Holiday Information (4 trường)

| Trường | Kiểu | Mô tả | Nguồn |
|--------|------|--------|--------|
| `is_holiday` | int | Là ngày lễ (0/1) | Holiday API |
| `holiday_impact` | float | Tác động ngày lễ (0-1) | Computed |
| `holiday_name` | string | Tên ngày lễ | Holiday API |
| `tet_phase` | string | Giai đoạn Tết (normal/pre_tet/tet/post_tet) | Computed |

### E. Time Features (5 trường)

| Trường | Kiểu | Mô tả | Nguồn |
|--------|------|--------|--------|
| `hour` | int | Giờ trong ngày (0-23) | Computed |
| `day_of_week` | int | Ngày trong tuần (0=Mon, 6=Sun) | Computed |
| `is_weekend` | int | Là cuối tuần (0/1) | Computed |
| `is_rush_hour` | int | Là giờ cao điểm (0/1) | Computed |
| `month` | int | Tháng (1-12) | Computed |

---

## Cách sử dụng cho Machine Learning

### Feature Engineering

```python
# Các features có thể sử dụng trực tiếp:
features = [
    'weather_impact',      # Tác động thời tiết
    'precip_impact',       # Tác động mưa
    'is_holiday',          # Ngày lễ
    'holiday_impact',      # Mức độ ảnh hưởng ngày lễ
    'is_weekend',          # Cuối tuần
    'is_rush_hour',        # Giờ cao điểm
    'is_monsoon',          # Mùa mưa
    'temp_c',              # Nhiệt độ
    'humidity_pct',        # Độ ẩm
    'day_of_week',         # Ngày trong tuần
    'month',               # Tháng
]

# Features cần encode:
categorical = [
    'type',                # Loại sự kiện (concert, festival, etc.)
    'weather_conditions',  # Tình trạng thời tiết
    'tet_phase',           # Giai đoạn Tết
]

# Target variable (cần thêm từ demand data):
# - demand_spike (0/1): Có spike trong demand
# - demand_value: Giá trị demand thực tế
```

### Geographic Features

```python
# H3 index có thể dùng để:
# 1. Group các events cùng khu vực
# 2. Tính density của events trong 1 vùng
# 3. Spatial features cho ML

# Anchor information dùng để:
# 1. Map weather data về đúng location
# 2. Tính khoảng cách từ event đến nearest weather station
```

---

## Ví dụ Data

```csv
event_name,start_date,slot_time,type,weather_impact,is_holiday,holiday_impact,temp_c,humidity_pct
"Triển lãm Allusive Panorama",2026-08-01,09:00,exhibition,0.1,0,0.0,29.0,83.89
"Việt Nam vs Campuchia",2026-08-07,19:00,football,0.0,0,0.0,28.0,75.0
"CARROT DAY 2026",2026-08-15,14:00,concert,0.3,0,0.0,31.0,65.0
"Quốc khánh 2/9",2026-09-02,09:00,exhibition,0.0,1,0.8,27.0,80.0
```

---

## Ghi chú quan trọng

### 1. Date Format
- **Events**: `YYYY-MM-DD` (ví dụ: 2026-08-01)
- **Weather**: `YYYY-MM-DD HH:MM:SS` (ví dụ: 2026-08-01 09:00:00)
- **Holiday**: `YYYY-MM-DD` (ví dụ: 2026-09-02)

### 2. Missing Weather Data
- Weather data chỉ có cho date range: 2026-06-29 → 2026-09-28
- Events ngoài range sẽ có `weather_impact = 0.0`

### 3. H3 Index
- Resolution: 15 (H3 cell ~0.7km²)
- Dùng để spatial join với các dataset khác

### 4. Event Classification
| Type | Sources | Keywords |
|------|---------|----------|
| concert | Ticketbox | concert, live show, âm nhạc |
| football | VPF, VFF | football, V-League |
| festival | LeHoiVietnam | lễ hội, festival |
| exhibition | VanMieu | triển lãm, trưng bày |
| cultural_event | VanMieu | workshop, seminar |

---

## Data Quality Notes

| Issue | Handling |
|-------|----------|
| Default times (00:00-23:59) | Converted to 08:00-22:00 |
| Missing attendance | Left as empty |
| Weather gaps | Filled with 0.0 impact |
| Geographic missing | H3 computed from lat/lon |

---

## Next Steps

1. **Flood Data Integration**: Cần fetch và merge thêm flood data
2. **Demand Data**: Cần thêm actual demand data để tạo target variable
3. **Feature Engineering**: Tạo thêm features như event_density, distance_to_flood

---

*Generated: 2026-10-02*
*Pipeline: Demand Spike Detector*
