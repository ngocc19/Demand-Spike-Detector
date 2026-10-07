# Data Dictionary - Demand Spike Detector

## Overview

This document describes all data files, their schemas, and field definitions used in the Demand Spike Detector project.

## Data Files

### Muc Tieu Ban Dau vs Hien Tai

| Aspect | Ban Dau | Hien Tai |
|--------|---------|----------|
| **Muc tieu** | Du bao demand spike | Du bao tinh trang giao thong |
| **Output** | Alert: spike co/khong | Traffic ratio (0-1) cho moi hex |
| **Data source** | Demand data + Weather | Weather + Event + Holiday + OSM + Traffic |
| **Target variable** | `is_spike` (binary) | `target_traffic_ratio` (0.0-1.0) |

### Output Moi

```python
# Du bao traffic ratio cho ~1,960 hex o Ha Noi
result = {
    'hex_id': '88415cb4e5fffff',
    'predicted_traffic_ratio': 0.75,  # 0.0 = thong thoang, 1.0 = ket nang
    'prediction_timestamp': '2026-10-06 14:30:00',
}
```

### 1. Main Feature Store

#### `data/weather_anchors_30T_merged.parquet`

The primary feature store containing weather data merged from multiple sources.

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `h3_index` | string | H3 hexagon ID (resolution 8) | `88415cb4e5fffff` |
| `datetime` | datetime | Timestamp (30-min intervals) | `2026-06-29 00:00:00` |
| `temp_c` | float | Temperature (°C) | `26.0` |
| `humidity_pct` | int | Humidity (%) | `75` |
| `wind_speed_kmh` | float | Wind speed (km/h) | `15.0` |
| `rain_mm` | float | Rainfall (mm) | `0.0` |
| `weather_code` | int | WMO weather code | `61` |
| `weather_desc` | string | Weather description | `light rain` |
| `vcw_temp_c` | float | VCW temperature (°C) | `25.8` |
| `vcw_rain_mm` | float | VCW rainfall (mm) | `0.2` |
| `ensemble_rain_mm` | float | Blended rainfall (ensemble) | `0.1` |
| `ensemble_storm_prob` | float | Storm probability (0-1) | `0.35` |
| `flood_level` | int | HSDC flood level (0-4) | `0` |
| `nchmf_warning` | bool | NCHMF warning flag | `False` |
| `holiday_impact` | float | Holiday impact score (0-1) | `0.0` |
| `osm_capacity_index` | float | OSM road capacity (0.01-1.0) | `0.457` |
| `osm_capacity_score` | float | OSM raw capacity score | `925.1` |
| `road_count` | int | OSM road count in hex | `593` |

**Statistics:**
- Total rows: 26,479
- Unique hexes: 6 (weather anchors)
- Time range: 2026-06-29 to 2026-09-28 (92 days)

**6 Weather Anchors (with OSM):**
| Anchor | H3-8 | OSM Index | OSM Roads | Khu vực |
|--------|-------|-----------|-----------|----------|
| HoanKiem | `88415cb4e5fffff` | 0.457 | 593 | Trung tâm |
| CauGiay | `884143696dfffff` | 0.307 | 489 | Tây |
| HoangMai | `88415cb687fffff` | 0.348 | 396 | Nam |
| LongBien | `88415cb51bfffff` | 0.263 | 211 | Đông |
| TayHo | `88415ca645fffff` | 0.037 | 65 | Bắc |
| NoiBai | `88415caecdfffff` | 0.010 | 0 | Sân bay |

---

### 2. OSM Capacity Data

#### `data/h3_osm_capacity.parquet`

Road network capacity data from OpenStreetMap.

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `hex_id` | string | H3 hexagon ID | `88415cb4e5fffff` |
| `osm_capacity_index` | float | Normalized capacity (0.01-1.0) | `0.457` |
| `osm_capacity_score` | float | Raw capacity score | `925.1` |
| `osm_road_score` | float | Road network score | `925.1` |
| `road_count` | int | Number of roads | `593` |
| `hex_lat` | float | Hex centroid latitude | `21.0299` |
| `hex_lon` | float | Hex centroid longitude | `105.8514` |
| `osm_infra_score` | float | Infrastructure score | `92.51` |
| `infra_count` | int | Infrastructure count | `118` |

**Statistics:**
- Total hexes: 3,997
- Hexes with roads: 1,806
- Capacity range: [0.01, 1.0]
- Data source: Overpass API (OpenStreetMap)

#### `data/h3_osm_capacity_meta.json`

```json
{
  "version": "1.0",
  "generated_at": "2026-10-06T16:22:56.025508",
  "source": "Overpass API (OpenStreetMap)",
  "total_hexes": 3997,
  "hexes_with_roads": 1806,
  "capacity_range": {
    "min": 0.01,
    "max": 1.0,
    "mean": 0.0447
  }
}
```

---

### 3. Real-time Data Lake

#### `data/realtime_lake/weather_YYYY-MM-DD.parquet`

Real-time weather data collected by the crawler.

| Field | Type | Description |
|-------|------|-------------|
| `h3_index` | string | H3 hexagon ID |
| `datetime` | datetime | Timestamp |
| `source` | string | Data source name |
| `temp_c` | float | Temperature |
| `humidity_pct` | int | Humidity |
| `rain_mm` | float | Rainfall |
| `weather_code` | int | WMO code |
| `fetched_at` | datetime | Fetch timestamp |

---

## External Data Sources

### 1. OpenWeatherMap (OWM)

| Field | Type | Description |
|-------|------|-------------|
| `temp_c` | float | Temperature (°C) |
| `humidity_pct` | int | Humidity (%) |
| `wind_speed` | float | Wind speed (m/s) |
| `weather_code` | int | WMO weather code |
| `weather_desc` | string | Weather description |
| `rain_1h` | float | Rainfall last 1h (mm) |

### 2. Visual Crossing (VCW)

| Field | Type | Description |
|-------|------|-------------|
| `temp_c` | float | Temperature (°C) |
| `humidity_pct` | int | Humidity (%) |
| `precip` | float | Precipitation (mm) |
| `precip_prob` | float | Precipitation probability (%) |
| `wind_speed` | float | Wind speed (km/h) |

### 3. HSDC Rainfall

| Field | Type | Description |
|-------|------|-------------|
| `TramId` | int | Station ID |
| `TenTram` | string | Station name |
| `LuongMua_BD` | float | Rainfall before (mm) |
| `LuongMua_HT` | float | Rainfall current (mm) |
| `LuongMua_Tr` | float | Rainfall accumulated (mm) |
| `Lat` | float | Station latitude |
| `Lng` | float | Station longitude |

### 4. HSDC Flood

| Field | Type | Description |
|-------|------|-------------|
| `TramId` | int | Station ID |
| `TenTram` | string | Station name |
| `flood_level` | int | Level (0-4) |
| `flood_depth_cm` | int | Flood depth (cm) |
| `is_flooding` | bool | Currently flooding |
| `Lat` | float | Station latitude |
| `Lng` | float | Station longitude |

**Flood Level Severity:**
| Level | Name | Depth | Impact |
|-------|------|-------|--------|
| 0 | Không ngập | 0 cm | 0.0 |
| 1 | Ngập nhẹ | 1-10 cm | 0.3 |
| 2 | Ngập vừa | 11-25 cm | 0.6 |
| 3 | Ngập nặng | 26-50 cm | 0.8 |
| 4 | Ngập sâu | >50 cm | 1.0 |

### 5. NCHMF

| Field | Type | Description |
|-------|------|-------------|
| `temp_c` | float | Temperature (°C) |
| `temp_min` | int | Min temperature |
| `temp_max` | int | Max temperature |
| `humidity_pct` | int | Humidity (%) |
| `wind_speed` | float | Wind speed (km/h) |
| `weather_code` | int | Weather code |
| `storm_warning` | bool | Storm warning |
| `precip_mm` | float | Precipitation (mm) |
| `precip_prob` | float | Precipitation probability (%) |

### 4.7 Temporal Features

| Truong | Mo Ta |
|--------|--------|
| `hour` | Gio trong ngay (0-23) |
| `day_of_week` | Ngay trong tuan (1-7) |
| `is_weekend` | Co phai cuoi tuan khong (0/1) |
| `is_rush_hour` | Gio cao diem (7-9, 17-19) (0/1) |

### 4.8 Lag & Rolling Features

| Truong | Mo Ta |
|--------|--------|
| `rain_lag_1h` | Luong mua 1 gio truoc |
| `rain_lag_2h` | Luong mua 2 gio truoc |
| `rain_rolling_1h` | Luong mua trung binh 1 gio gan nhat |
| `rain_rolling_3h` | Luong mua trung binh 3 gio gan nhat |

### 4.9 Target Variable

| Truong | Mo Ta |
|--------|--------|
| `target_traffic_ratio` | Ty le ket xe (0.0=thong thoang, 1.0=ket nang) |

---

## Feature Engineering

### Impact Overview

Impacts are **normalized scores (0.0 - 1.0)** measuring how external factors affect traffic demand. They are used as features for the traffic prediction model and for Alert cause attribution.

**Formula:**
```
Alert.cause_X = impact_X / (impact_weather + impact_flood + impact_event + impact_traffic)
```

---

### 1. Weather Impact (`weather_impact`)

**Source:** VCW, OWM, NCHMF API

**Definition:** Measures how weather conditions affect traffic demand.

| Weather Condition | Impact | Description |
|-------------------|--------|-------------|
| Trời nắng (Clear) | 0.0 | Không ảnh hưởng |
| Ít mây (Few clouds) | 0.0 | Không ảnh hưởng |
| Nhiều mây (Cloudy) | 0.1 | Ít ảnh hưởng |
| Sương mù (Fog) | 0.2 | Giảm tầm nhìn |
| Mưa nhỏ (Light rain) | 0.3 | Hơi giảm |
| Mưa rào nhẹ (Light shower) | 0.3 | Giảm nhẹ |
| Mưa rào (Rain shower) | 0.5 | Giảm đáng kể |
| Mưa (Rain) | 0.5 | Giảm đáng kể |
| Mưa to (Heavy rain) | 0.7 | Giảm nhiều |
| Mưa lớn (Heavy rain) | 0.8 | Giảm rất nhiều |
| Giông (Thunderstorm) | 0.8 | Giảm nhiều |
| Mưa giông (Thunder rain) | 0.8 | Giảm nhiều |
| Bão (Typhoon) | 1.0 | Tác động tối đa |
| Nắng nóng (Hot) | 0.4 | Tăng nhu cầu điều hòa |

**WMO Code Mapping:**
| Code Range | Description | Impact |
|------------|-------------|--------|
| 0-3 | Clear/Cloudy | 0.0 |
| 45-48 | Fog | 0.2 |
| 51-55 | Drizzle | 0.4 |
| 61-67 | Rain | 0.6 |
| 80-82 | Rain showers | 0.8 |
| 95-99 | Thunderstorm | 1.0 |

---

### 2. Precip Impact (`precip_impact`)

**Source:** HSDC, VCW, OWM

**Definition:** Specific rainfall impact based on precipitation amount (mm).

| Rainfall (mm) | Impact | Description |
|---------------|--------|-------------|
| 0 | 0.0 | Không mưa |
| 0-1 | 0.1 | Mưa rất nhẹ |
| 1-5 | 0.2 | Mưa nhẹ |
| 5-10 | 0.3 | Mưa vừa nhẹ |
| 10-20 | 0.5 | Mưa vừa |
| 20-50 | 0.8 | Mưa to |
| ≥50 | 1.0 | Mưa rất lớn |

**Formula:**
```python
precip_impact = min(rain_mm / 50, 1.0)  # Cap at 1.0
```

---

### 3. Event Impact (`event_impact_weight`)

**Source:** Manual CSV, Ticketbox API

**Definition:** Impact of mass events (concerts, sports, festivals) on nearby traffic.

**Event Type Weights:**
| Event Type | Weight | Example |
|------------|--------|---------|
| Concert | 1.0 | Ca nhạc, nhạc hội |
| Festival | 0.9 | Lễ hội, carnival |
| Sport | 0.8 | Bóng đá, marathon |
| Conference | 0.7 | Hội nghị, workshop |
| Exhibition | 0.6 | Triển lãm, expo |
| Cultural | 0.7 | Văn hóa, nghệ thuật |
| Political | 0.6 | Chính trị, biểu tình |
| Entertainment | 0.6 | Giải trí, gameshow |
| Religious | 0.5 | Tôn giáo, lễ hội |
| Academic | 0.4 | Học thuật, hội thảo |
| Default | 0.5 | Không xác định |

**Formula:**
```python
event_impact_weight = log(1 + estimate_attendence) * type_weight
```

**Example:**
- Concert 5000 người: `log(5001) * 1.0 = 8.52`
- Festival 10000 người: `log(10001) * 0.9 = 9.20`

---

### 4. Holiday Impact (`holiday_impact`)

**Source:** Static holiday calendar

**Definition:** Impact of public holidays and Tet on traffic demand.

| Category | Impact | Description |
|----------|--------|-------------|
| Tết Nguyên Đán (Tet week) | 0.9 | Giảm mạnh - người về quê |
| Pre-Tet (7 days before) | 0.6 | Giảm dần - người bắt đầu về |
| Post-Tet (7 days after) | 0.4 | Tăng dần - người trở lại |
| Official holiday | 1.0 | Nghỉ lễ toàn quốc |
| Pre-holiday (1-2 days) | 0.5 | Giảm nhẹ |
| Post-holiday (1-2 days) | 0.3 | Tăng nhẹ |
| Normal day | 0.0 | Không ảnh hưởng |

**Vietnam Holidays 2026:**
| Holiday | Date | Impact |
|---------|------|--------|
| Tết Dương lịch | 2026-01-01 | 0.3 |
| Tết Nguyên Đán | 2026-02-17-23 | 0.9 |
| Giỗ Tổ Hùng Vương | 2026-04-09 | 0.6 |
| Ngày Giải phóng | 2026-04-30 | 0.4 |
| Quốc tế Lao động | 2026-05-01 | 0.4 |
| Quốc khánh | 2026-09-02 | 0.5 |

---

### 5. Flood Impact (`flood_impact`)

**Source:** HSDC Flood API

**Definition:** Impact of flooding on road accessibility and traffic demand.

**Flood Level Severity:**
| Level | Name | Depth (cm) | Impact |
|-------|------|------------|--------|
| 0 | Không ngập | 0 | 0.0 |
| 1 | Ngập nhẹ | 1-10 | 0.3 |
| 2 | Ngập vừa | 11-25 | 0.6 |
| 3 | Ngập nặng | 26-50 | 0.8 |
| 4 | Ngập sâu | >50 | 1.0 |

**Formula:**
```python
flood_impact = flood_level / 4
```

---

### 6. Traffic Impact (`traffic_impact`)

**Source:** HERE Traffic API

**Definition:** Real-time traffic congestion level from HERE Routing API.

**Jam Factor Severity:**
| Jam Factor | Severity | Description |
|------------|----------|-------------|
| 0-2 | LOW | Thông thoáng |
| 2-4 | MEDIUM | Ùn ứ nhẹ |
| 4-7 | HIGH | Kẹt xe |
| 7-10 | SEVERE | Kẹt cứng |

**Impact Formula:**
```python
traffic_impact = jam_factor / 10  # Normalize to 0-1
```

---

### 7. Severity Classification

All impact types map to a common severity scale for unified alerting:

| Severity | Range | Alert Level | Action |
|----------|-------|-------------|--------|
| `LOW` | 0.0 - 0.2 | ✅ Normal | Bình thường |
| `MEDIUM` | 0.2 - 0.5 | ⚠️ Warning | Theo dõi |
| `HIGH` | 0.5 - 0.8 | 🔶 Alert | Hành động |
| `SEVERE` | 0.8 - 1.0 | 🔴 Critical | Khẩn cấp |

---

### 8. Combined Value (`value`)

**Definition:** Final impact score combining multiple sources.

```python
# Ensemble: Take maximum impact from all sources
value = max(weather_impact, precip_impact)
```

**Purpose:**
- Represents worst-case impact scenario
- Used for model training feature
- Triggers alerts when threshold exceeded

---

### 9. OSM Capacity Index

**Source:** OpenStreetMap Overpass API

**Definition:** Normalized road network capacity (inverse of traffic density).

| Range | Description | Traffic Expectation |
|-------|-------------|---------------------|
| 0.01-0.2 | Low capacity | Suburban, rural areas |
| 0.2-0.5 | Medium capacity | Residential areas |
| 0.5-0.8 | High capacity | Commercial areas |
| 0.8-1.0 | Very high capacity | City center |

**Note:** Higher capacity = better road infrastructure = lower traffic impact

---

## Usage Examples

### Loading Data

```python
import pandas as pd

# Load main feature store
weather_df = pd.read_parquet('data/weather_anchors_30T_merged.parquet')

# Load OSM capacity
osm_df = pd.read_parquet('data/h3_osm_capacity.parquet')

# Merge OSM to weather
weather_df = weather_df.merge(
    osm_df[['hex_id', 'osm_capacity_index', 'road_count']],
    on='hex_id',
    how='left'
)
```

### Key Metrics

| Metric | Description |
|--------|-------------|
| `h3_index` | Primary key - H3 hexagon ID |
| `datetime` | Primary key - Timestamp |
| `ensemble_rain_mm` | Blended rainfall from 4 sources |
| `ensemble_storm_prob` | Storm probability (0-1) |
| `flood_level` | HSDC flood severity (0-4) |
| `osm_capacity_index` | Normalized road capacity (0.01-1.0) |
