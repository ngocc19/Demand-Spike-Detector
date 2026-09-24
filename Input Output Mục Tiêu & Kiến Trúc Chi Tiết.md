# Input/Output Muc Tieu & Kien Truc Chi Tiet

---

## 1. INPUT - Du Lieu Dau Vao

### 1.1 Data Sources (≥2 external sources)

#### SOURCE 1: DEMAND DATA (INTERNAL - tu he thong cua ban)

**DAY LA DU LIEU COT LOI - ban phai co**

| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime | Thoi diem (30-min intervals) |
| hex_id | string | H3 hex ID (resolution 8-9) |
| requests | int | So requests trong slot do |
| avg_eta_min | float | Thoi gian cho trung binh |

**Vi du:**

| timestamp | hex_id | requests | avg_eta_min |
|-----------|--------|----------|-------------|
| 2024-09-01 08:00 | 8a2a1008affffff | 45 | 12.3 |
| 2024-09-01 08:30 | 8a2a1008affffff | 52 | 15.1 |
| 2024-09-01 08:00 | 8a2a1009affffff | 28 | 8.7 |
| 2024-09-01 08:30 | 8a2a1009affffff | 31 | 9.2 |

---

#### SOURCE 2: WEATHER DATA (EXTERNAL - mien phi)

Thoi tiet duoc thu thap tu nhieu nguon de dam bao do chinh xac va do tin cay:

##### 2.1 HSDC Rainfall API (Ground Truth)

| Thong tin | Chi tiet |
|-----------|----------|
| API | HSDC Rainfall - thoatnuochanoi.vn |
| URL | `https://thoatnuochanoi.vn/luongmua/api/getAllData` |
| Cost | FREE |
| Stations | 48 trạm đo mưa tự động toàn Hà Nội |
| Active | 16-26 trạm có dữ liệu mưa gần đây |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| TramId | int | Station ID |
| LuongMua_BD | float | Lượng mưa trước đó (mm) |
| LuongMua_HT | float | Lượng mưa hiện tại (mm) |
| LuongMua_Tr | float | Lượng mưa tích lũy (mm) |
| ThoiGian_BD | datetime | Thời gian đo trước |
| ThoiGian_HT | datetime | Thời gian hiện tại |
| ThoiGian_Tr | datetime | Thời gian tích lũy |

##### 2.2 OpenWeatherMap (OWM)

| Thong tin | Chi tiet |
|-----------|----------|
| API | OpenWeatherMap |
| URL | `https://api.openweathermap.org/data/2.5/weather` |
| Cost | FREE (1M calls/month) |
| Forecast | Current + 48h forecast |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| temp_c | float | Nhiệt độ (°C) |
| humidity_pct | int | Độ ẩm (%) |
| wind_speed | float | Tốc độ gió |
| weather_code | int | Mã thời tiết WMO |
| weather_desc | string | Mô tả thời tiết |
| rain_1h | float | Lượng mưa 1h (mm) |

##### 2.3 Visual Crossing (VCW)

| Thong tin | Chi tiet |
|-----------|----------|
| API | Visual Crossing Weather |
| URL | `https://weather.visualcrossing.com/weather-api` |
| Cost | FREE (1,000 records/day) |
| Forecast | Current + 15 days forecast (tốt cho backfill) |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| temp_c | float | Nhiệt độ (°C) |
| humidity_pct | int | Độ ẩm (%) |
| precip | float | Lượng mưa (mm) |
| precip_prob | float | Xác suất mưa (%) |
| wind_speed | float | Tốc độ gió |
| weather_conditions | string | Mô tả thời tiết |

##### 2.4 NCHMF (Storm Warnings)

| Thong tin | Chi tiet |
|-----------|----------|
| Source | Trung tâm Khí tượng Thủy văn Quốc gia |
| URL | `https://nchmf.gov.vn` |
| Cost | FREE |
| Data | Cảnh báo bão, giông, lốc |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| temp_c | float | Nhiệt độ (°C) |
| temp_min/max | int | Min/Max nhiệt độ |
| humidity_pct | int | Độ ẩm (%) |
| wind_speed | float | Tốc độ gió |
| weather_code | int | Mã thời tiết |
| storm_warning | bool | Cảnh báo bão/giông |
| precip_mm | float | Lượng mưa (mm) |
| precip_prob | float | Xác suất mưa (%) |

**Weather Code -> Impact Mapping:**

| code | description | impact |
|------|-------------|--------|
| 0-3 | Clear/Cloudy | 0.0 |
| 45-48 | Fog | 0.2 |
| 51-55 | Drizzle | 0.4 |
| 61-67 | Rain | 0.6 |
| 80-82 | Rain showers | 0.8 |
| 95-99 | Thunderstorm | 1.0 |

---

#### SOURCE 3: FLOOD DATA (EXTERNAL - mien phi)

##### HSDC Flood API (Real-time Monitoring)

| Thong tin | Chi tiet |
|-----------|----------|
| API | HSDC Flood - thoatnuochanoi.vn |
| URL | `https://thoatnuochanoi.vn/ungngap/api/flood/getflood` |
| Cost | FREE |
| Stations | 45 trạm theo dõi ngập toàn Hà Nội |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| station_id | int | Station ID |
| location_name | string | Tên vị trí |
| flood_level | int | Level 0-4 |
| flood_level_name | string | Ngập nhẹ/nặng... |
| flood_depth_cm | int | Độ sâu ngập (cm) |
| is_flooding | bool | Có đang ngập không |
| latitude | float | Vĩ độ |
| longitude | float | Kinh độ |

**Flood Level Severity:**

| Level | Name | Depth | Impact |
|-------|------|-------|--------|
| 0 | Không ngập | 0 cm | 0.0 |
| 1 | Ngập nhẹ | 1-10 cm | 0.3 |
| 2 | Ngập vừa | 11-25 cm | 0.6 |
| 3 | Ngập nặng | 26-50 cm | 0.8 |
| 4 | Ngập sâu | >50 cm | 1.0 |

---

#### SOURCE 4: EVENT DATA (EXTERNAL - manual/CSV)

**File: events.csv**

| event_name | venue | start_time | end_time | type |
|------------|-------|------------|----------|------|
| Concert Son Tung | SVD My Dinh | 2024-09-01 19:00:00 | 2024-09-01 22:00:00 | concert |
| Football Match | Thong Nhat Stadium | 2024-09-01 17:00:00 | 2024-09-01 19:00:00 | football |
| Tech Conference | ICE Ha Noi | 2024-09-05 08:00:00 | 2024-09-05 17:00:00 | conference |

**Event Type -> Demand Impact:**

| type | description | impact |
|------|-------------|--------|
| concert | Concert/Music | 1.0 |
| football | Sports match | 0.8 |
| festival | Festival/Carnival | 0.9 |
| conference | Business event | 0.5 |

---

#### SOURCE 5: HOLIDAY DATA (INTERNAL - Static)

**File: holidays.csv (generated by holiday_plugin.py)**

| Thong tin | Chi tiet |
|-----------|----------|
| Type | Solar + Lunar holidays |
| Source | Viet Nam official calendar |
| Coverage | 2024-2026 |
| Special | Tết phases (pre_tet, tet_week, post_tet) |

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| date | date | Ngày nghỉ |
| holiday_name | string | Tên ngày lễ |
| category | string | official/cultural/tet |
| is_holiday | bool | Có phải ngày nghỉ |
| value | float | Impact 0-1 |

**Tết Impact Phases:**

| Phase | Days | Impact | Description |
|-------|------|--------|-------------|
| pre_tet | 7 days before | 0.5-0.7 | Peak travel season |
| tet_week | 7 days | 0.8-1.0 | New Year holiday |
| post_tet | 7 days after | 0.5-0.7 | Return to normal |

---

### 1.2 Feature Store (Unified Input Format)

**Day la OUTPUT cua Data Pipeline, INPUT cua Model**

- **Primary Key:** (hex_id, datetime_30min)
- **Storage:** Parquet file (production) hoac CSV (MVP)

| hex_id | datetime_30min | weather | flood | event | holiday | demand |
|--------|---------------|---------|-------|-------|---------|--------|
| 8a2a1008... | 2024-09-01 08:00 | 0.0 | 0.0 | 0.0 | 0.0 | 45 |
| 8a2a1008... | 2024-09-01 08:30 | 0.0 | 0.0 | 0.0 | 0.0 | 52 |
| 8a2a1008... | 2024-09-01 09:00 | 0.3 | 0.0 | 0.0 | 0.0 | 58 |
| 8a2a1008... | 2024-09-01 09:30 | 0.6 | 0.0 | 0.8 | 0.0 | 78 |
| 8a2a1008... | 2024-09-01 10:00 | 0.8 | 0.0 | 1.0 | 0.0 | 85 |
| 8a2a1009... | 2024-09-01 08:00 | 0.0 | 0.0 | 0.0 | 0.0 | 28 |
| 8a2a100a... | 2024-09-01 08:00 | 0.0 | 0.85 | 0.0 | 0.0 | 15 |

**Ghi chu:**
- weather = 0.0 -> khong mua
- weather = 0.6 -> mua vua (code 61-67)
- flood = 0.85 -> ngap nang (SEVERE)
- event = 1.0 -> concert tai hex nay luc nay
- holiday = 0.0 -> ngay binh thuong
- MOI HANG = 1 time slot cho 1 hex = 1 observation

---

## 2. OUTPUT - Ket Qua Dau Ra

### 2.1 Spike Alert (TC4 Output)

**TC4 Requirement:** "Alert co hex, muc do, nguyen nhan goi y"

```json
{
  "alert_id": "SPK-20240901-0845-001",
  "timestamp": "2024-09-01T08:45:00",
  "detected_at": "2024-09-01T08:45:05",
  "hex_id": "8a2a1008affffff",
  "hex_location": "Quan Cau Giay, Ha Noi",
  "severity": "HIGH",
  "demand_metrics": {
    "actual_requests": 78,
    "baseline_requests": 45,
    "deviation_pct": 73.3,
    "threshold_pct": 30.0
  },
  "suggested_causes": [
    {
      "cause": "weather",
      "confidence": 0.85,
      "description": "Mua vua den lon (code 63)"
    },
    {
      "cause": "event",
      "confidence": 0.72,
      "description": "Football match tai Thong Nhat Stadium"
    }
  ],
  "primary_cause": "weather",
  "action_recommendations": [
    "Tang driver online o khu vuc Cau Giay",
    "Pre-position drivers near stadium truoc match 30 phut"
  ]
}
```

---

### 2.2 TC Metrics Summary

#### TC1: Detection Rate

| Thong tin | Chi tiet |
|-----------|----------|
| Definition | Phat hien ≥80% dot bien ≥30% Requests |
| Formula | TP / (TP + FN) |

**Vi du:**

| Metric | Value |
|--------|-------|
| Ground Truth: spikes thuc su xay ra | 50 |
| Detected: spikes | 43 |
| Missed: spikes | 7 |
| **Detection Rate** | **43 / 50 = 86% ✅ (≥80%)** |

---

#### TC2: False Alert Rate

| Thong tin | Chi tiet |
|-----------|----------|
| Definition | ≤2 false alerts/ngay toan thanh pho |
| Formula | FP / num_days |

**Vi du:**

| Metric | Value |
|--------|-------|
| Alerts tong cong | 156 |
| Actual spikes | 143 |
| False positives | 13 |
| Days in period | 30 |
| **False alerts/day** | **13 / 30 = 0.43 ✅ (≤2)** |

---

#### TC3: External Data Sources

| Thong tin | Chi tiet |
|-----------|----------|
| Definition | ≥2 nguon du lieu ngoai duoc tich hop |

| Source | API | Status | Backfill Method |
|--------|-----|--------|-----------------|
| **HSDC Rainfall** | thoatnuochanoi.vn | ✅ | Historical API |
| **OpenWeatherMap** | openweathermap.org | ✅ | `past_days` parameter |
| **Visual Crossing** | visualcrossing.com | ✅ | Historical endpoint |
| **NCHMF** | nchmf.gov.vn | ✅ | Archive |
| **HSDC Flood** | thoatnuochanoi.vn | ✅ | Historical API |
| **Holiday** | Static calendar | ✅ | Pre-known dates |
| **Events** | Manual CSV | ✅ | Manual collection |
| **Total** | **6 external sources** | ✅ **(≥2)** | |

> **Note:** Tat ca sources deu duoc backfill day du cho Phase 0 va hoat dong real-time cho Phase 1. Khong co data mismatch giua training va inference.

---

#### TC4: Alert Completeness

| Thong tin | Chi tiet |
|-----------|----------|
| Definition | Alert co hex, muc do, nguyen nhan goi y |

| Metric | Value |
|--------|-------|
| Total alerts | 143 |
| Alerts with hex_id | 143/143 = 100% ✅ |
| Alerts with severity | 143/143 = 100% ✅ |
| Alerts with suggested_causes | 143/143 = **100%** ✅ |

---

## 3. WEATHER ENSEMBLE ARCHITECTURE

### 3.1 Multi-Source Ensemble

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WEATHER ENSEMBLE PIPELINE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DATA SOURCES:                                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                        │
│  │   OWM   │ │   VCW   │ │  HSDC   │ │  NCHMF  │                        │
│  │(Weather) │ │(Weather) │ │(Rainfall)│ │(Storm)  │                        │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘                        │
│       │           │           │           │                               │
│       └───────────┴───────────┴───────────┘                               │
│                            │                                              │
│                            ▼                                              │
│                   ┌────────────────┐                                       │
│                   │   Ensemble     │                                       │
│                   │ Aggregator    │                                       │
│                   │               │                                       │
│                   │ • Soft-voting │                                       │
│                   │ • Circuit     │                                       │
│                   │   Breaker     │                                       │
│                   │ • Time Decay  │                                       │
│                   └───────┬───────┘                                       │
│                           │                                               │
│                           ▼                                               │
│                   ┌────────────────┐                                       │
│                   │  Output:       │                                       │
│                   │ blended_rainfall│                                       │
│                   │ storm_probability│                                       │
│                   └────────────────┘                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Dual-Pass Ensemble

```
PASS 1: NOWCAST (Current)
==========================
Sources:
- HSDC (rainfall ground truth)
- NCHMF (storm warnings - O(1) lookup)
- OWM (current weather)
- VCW (current weather)

Output:
- blended_rainfall (mm)
- is_storm_current (0/1)

PASS 2: FORECAST (+1h)
========================
Sources:
- OWM (forecast +1h)
- VCW (forecast +1h)

Output:
- blended_forecast_1h (mm)
```

### 3.3 Circuit Breaker Pattern

```python
# HSDC stations: 48 trạm, không phủ hết Hà Nội
# Hex không có trạm HSDC -> Circuit Breaker = S=0

source_status = {
    'OWM': 1,      # Luôn có (query anywhere)
    'VCW': 1,      # Luôn có (query anywhere)
    'HSDC': 1 if has_station else 0,  # Circuit Breaker!
    'NCHMF': 1,    # Luôn có (district-level)
}

# Weight calculation:
# S=0 -> weight=0 (không contribute vào ensemble)
```

### 3.4 NCHMF O(1) Spatial Lookup

```python
# Pre-computed lookup (không geometry at runtime!)
# H3 → District → Zone → NCHMF Warning

┌────────────────────────────────────────────────────┐
│  h3_index → district → zone → warning             │
│  (3 dict lookups = microseconds)                 │
└────────────────────────────────────────────────────┘

ZONES = {
    'NoiThanh': ['HoanKiem', 'HaiBaTrung', 'DongDa', ...],
    'PhiaTay': ['ThanhXuan', 'HoangMai', ...],
    'PhiaBac': ['LongBien', 'GiaLam', ...],
    ...
}
```

---

## 4. Phase 0: OFFLINE (Training)

### Step 1: Thu Thap Du Lieu (Backfill)

```
+-------------------------------------------------------------------------+
|                   PHASE 0: OFFLINE (BACKFILL)                          |
+-------------------------------------------------------------------------+
|                                                                          |
|  Step 1: BACKFILL - Thu thap du lieu LICH SU                           |
|  ===================================================================     |
|                                                                          |
|  +-----------+  +-----------+  +-----------+  +-----------+  +---------+ |
|  |  Demand   |  |  Weather  |  |   Event   |  |   Flood   |  | Holiday | |
|  |   Data    |  | HSDC/OWM |  |    CSV    |  |   HSDC   |  |Calendar | |
|  | (Internal)|  |   /VCW   |  | (Manual)  |  |   API    |  | (Static)| |
|  |           |  | Backfill |  |           |  | Backfill |  |         | |
|  | requests  |  | past_days|  | event,    |  | historical|  | holiday | |
|  | + eta     |  | = 60    |  | venue,    |  | data     |  | dates,  | |
|  |           |  |          |  | time      |  |          |  | tet_    | |
|  | INTERNAL  |  | Backfill |  |  Manual   |  | Backfill |  | phase   | |
|  +-----+-----+  +-----+-----+  +-----+-----+  +-----+-----+  +-----+---+
|        |             |              |             |              |       |
|        +-------------+--------------+-------------+--------------+       |
|                                  |                                       |
|                                  v                                       |
|                     +----------------------------+                       |
|                     |       FEATURE STORE        |                       |
|                     |     (8 tuan BACKFILL)      |                       |
|                     +----------------------------+                       |
|                                  |                                       |
|                                  v                                       |
|                     +----------------------------+                       |
|                     |      MANUAL LABELING       |                       |
|                     |      (is_spike, cause)     |                       |
|                     +-------------+--------------+                       |
|                                   |                                     |
|                                   v                                     |
|                     +----------------------------+                       |
|                     |       TRAIN LIGHTGBM       |                       |
|                     |     spike_predictor.pkl    |                       |
|                     +----------------------------+                       |
|                                                                          |
+-------------------------------------------------------------------------+
```

### Backfill Chi Tiet Tung Data Source

| Data Source | Backfill Method | API/URL | Status |
|------------|----------------|---------|--------|
| **Weather (HSDC)** | HSDC Historical API | thoatnuochanoi.vn | ✅ Có thể |
| **Weather (OWM)** | `past_days` parameter | openweathermap.org | ✅ Có thể |
| **Weather (VCW)** | Historical endpoint | visualcrossing.com | ✅ Có thể |
| **Flood (HSDC)** | HSDC Historical API | thoatnuochanoi.vn | ✅ Có thể |
| **Holiday** | Static Calendar | 2024-2026 | ✅ Đã xong |
| **Events** | Manual CSV | Ticketbox/manual | ⚠️ Cần thu thập |
| **Demand** | Internal Database | He thong cua ban | ⚠️ Cần export |

---

## 5. Phase 1: ONLINE (Real-time Inference)

### Schedule

| Plugin | Schedule | Data Source | API |
|--------|----------|-------------|-----|
| Weather (HSDC) | Every 15 min | thoatnuochanoi.vn | ✅ Real-time |
| Weather (OWM) | Every hour | openweathermap.org | ✅ Real-time |
| Weather (VCW) | Every hour | visualcrossing.com | ✅ Real-time |
| NCHMF | Every 30 min | nchmf.gov.vn | ✅ Real-time |
| Flood (HSDC) | Every 15 min | thoatnuochanoi.vn | ✅ Real-time |
| Event | Daily at 23:00 | Manual CSV | ⚠️ Manual |
| Holiday | On-demand | Static Calendar | ✅ Lookup |

### Data Flow

```
                           EXTERNAL SOURCES
                           ==================
+------------+                                                   |
| HSDC Rain  | ----(15 min)---->                                 |
| thoatnuoch...|                                                    |
+------------+                                                      |
                                      +-------------+              |
| OWM Weather| ----(hourly)---->     |             |              |
| openweather...                      |  WEATHER    |              |
+------------+                       |  ENSEMBLE   |  ---->  FEATURE
                                      |             |              |    STORE
+------------+                       |             |              |
| VCW Weather| ----(hourly)---->     | • Soft-vote |              |
| visualcross...                      | • Circuit   |              |
+------------+                       |   Breaker   |              |
                                      | • Time Decay|              |
+------------+                       +------+------+              |
| NCHMF      | ----(30 min)---->           |                     |
| nchmf.gov  |                              |                     |
+------------+                                                      |
                                      +------+------+              |
+------------+                       |             |              |
| HSDC Flood | ----(15 min)---->     |   FLOOD     |              |
| thoatnuoch...|                      |   DATA      |              |
+------------+                       +------+------+              |
                                            |                     |
+------------+                               |                     |
| Holiday    | ----(static)---->        +-----+-----+               |
| Calendar   |                         |  FEATURE  |               |
+------------+                         |  STORE    |  ---->  ALERTS
                                      +-----+-----+               |
+------------+                               |                     |
| Events     | ----(daily)------>         |                     |
| CSV file   |                             |                     |
+------------+                             |                     |
                                            v                     |
                                   +---------------+              |
                                   | LIGHTGBM      |              |
                                   | spike_predict |              |
                                   | .pkl          |              |
                                   +-------+-------+              |
                                           |                      |
                                           v                      |
                                   +---------------+              |
                                   | CUSUM         | ---------------
                                   | FILTER        |
                                   | (reduce FPs) |
                                   +---------------+
```

---

## 6. Tom Tat

### Data Sources Implemented

| # | Source | API | Type | Real-time |
|---|--------|-----|------|-----------|
| 1 | HSDC Rainfall | thoatnuochanoi.vn | Ground Truth | ✅ |
| 2 | OpenWeatherMap | openweathermap.org | Weather | ✅ |
| 3 | Visual Crossing | visualcrossing.com | Weather | ✅ |
| 4 | NCHMF | nchmf.gov.vn | Storm | ✅ |
| 5 | HSDC Flood | thoatnuochanoi.vn | Flood | ✅ |
| 6 | Holiday | Static Calendar | Calendar | ✅ |
| 7 | Events | Manual CSV | Calendar | ⚠️ |

### TC Metrics Summary

| TC | Metric | Target | Status |
|----|--------|--------|--------|
| TC1 | Detection Rate | ≥80% | Pending |
| TC2 | False Alerts | ≤2/day | Pending |
| TC3 | Data Sources | ≥2 | ✅ 6+ sources |
| TC4 | Alert Completeness | hex, severity, causes | Pending |

### Files Structure

```
src/pipeline/
├── base.py                    # BaseFactorPlugin
├── registry.py                # Plugin registry
├── weather_ensemble.py        # WeatherEnsembleAggregator
├── spatial_ensemble_pipeline.py  # H3 spatial mapping
├── nchmf_spatial_lookup.py    # NCHMF O(1) lookup
├── demand_spike_pipeline.py    # LightGBM features
└── plugins/
    ├── hsdc_plugin.py         # HSDC Rainfall API
    ├── hsdc_flood_plugin.py  # HSDC Flood API
    ├── owm_plugin.py          # OpenWeatherMap
    ├── vcw_plugin.py          # Visual Crossing
    ├── nchmf_plugin.py        # NCHMF storm warnings
    ├── event_plugin.py       # Events (manual CSV)
    └── holiday_plugin.py      # Holidays (solar + lunar)
```
