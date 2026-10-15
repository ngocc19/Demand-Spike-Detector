# Input/Output - Mục Tiêu & Kiến Trúc Chi Tiết

---

## 1. INPUT - Dữ Liệu Đầu Vào

### 1.1 Data Sources

#### SOURCE 1: DEMAND DATA (INTERNAL)

| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime | Thời điểm (30-min intervals) |
| hex_id | string | H3 hex ID (resolution 8) |
| requests | int | Số requests trong slot đó |
| avg_eta_min | float | Thời gian chờ trung bình |

---

#### SOURCE 2: WEATHER DATA (EXTERNAL - FREE)

##### 2.1 HSDC Rainfall API (Ground Truth)

| Thông tin | Chi tiết |
|-----------|----------|
| API | HSDC Rainfall - thoatnuochanoi.vn |
| URL | `https://thoatnuochanoi.vn/luongmua/api/getAllData` |
| Cost | FREE |
| Stations | 48 trạm đo mưa tự động toàn Hà Nội |

##### 2.2 OpenWeatherMap (OWM)

| Thông tin | Chi tiết |
|-----------|----------|
| API | OpenWeatherMap |
| URL | `https://api.openweathermap.org/data/2.5/weather` |
| Cost | FREE (60 calls/min) |
| Data | Current + 48h forecast |

##### 2.3 Visual Crossing (VCW)

| Thông tin | Chi tiết |
|-----------|----------|
| API | Visual Crossing Weather |
| URL | `https://weather.visualcrossing.com/weather-api` |
| Cost | FREE (1,000 records/day) |
| Historical | Tốt cho backfill |

##### 2.4 NCHMF (Storm Warnings)

| Thông tin | Chi tiết |
|-----------|----------|
| Source | Trung tâm Khí tượng Thủy văn Quốc gia |
| URL | https://nchmf.gov.vn |
| Data | Cảnh báo bão, giông, lốc |

---

#### SOURCE 3: FLOOD DATA (EXTERNAL - FREE)

| Thông tin | Chi tiết |
|-----------|----------|
| API | HSDC Flood - thoatnuochanoi.vn |
| URL | `https://thoatnuochanoi.vn/ungngap/api/flood/getflood` |
| Stations | 45 trạm theo dõi ngập toàn Hà Nội |

**Flood Level Severity:**

| Level | Name | Depth | Impact |
|-------|------|-------|--------|
| 0 | Không ngập | 0 cm | 0.0 |
| 1 | Ngập nhẹ | 1-10 cm | 0.3 |
| 2 | Ngập vừa | 11-25 cm | 0.6 |
| 3 | Ngập nặng | 26-50 cm | 0.8 |
| 4 | Ngập sâu | >50 cm | 1.0 |

---

#### SOURCE 4: HOLIDAY DATA (INTERNAL - Static)

| Thông tin | Chi tiết |
|-----------|----------|
| Type | Solar + Lunar holidays |
| Source | Viet Nam official calendar |
| Coverage | 2024-2026 |
| Special | Tết phases |

---

#### SOURCE 5: OSM CAPACITY DATA (OpenStreetMap)

| Thông tin | Chi tiết |
|-----------|----------|
| Source | OpenStreetMap via Overpass API |
| URL | https://overpass-api.de/api/interpreter |
| Data | Road network density per hex |
| Update | One-time fetch, cached to parquet |

---

### 1.2 Feature Store (Unified Input Format)

**Primary Key:** (hex_id, datetime_30min)

```
data/weather_anchors_30T_merged.parquet
├── h3_index
├── datetime
├── temp_c, humidity_pct, wind_speed_kmh
├── rain_mm, weather_code, weather_desc
├── vcw_temp_c, vcw_rain_mm
├── ensemble_rain_mm, ensemble_storm_prob
├── flood_level
├── nchmf_warning
└── holiday_impact

data/h3_osm_capacity.parquet
├── hex_id
├── osm_capacity_index (0.01-1.0)
├── road_count
└── hex_lat, hex_lon
```

---

## 2. OUTPUT - Kết Quả Đầu Ra

### 2.1 Spike Alert Output

```json
{
  "alert_id": "SPK-20260925-1400-001",
  "timestamp": "2026-09-25T14:00:00",
  "hex_id": "88415cb4e5fffff",
  "severity": "HIGH",
  "demand_metrics": {
    "actual_requests": 78,
    "baseline_requests": 45,
    "deviation_pct": 73.3
  },
  "suggested_causes": [
    {"cause": "weather", "confidence": 0.85},
    {"cause": "flood", "confidence": 0.72}
  ],
  "primary_cause": "weather"
}
```

---

## 3. Implementation Status

### 3.1 Data Sources Implemented

| # | Source | API | Status |
|---|--------|-----|--------|
| 1 | HSDC Rainfall | thoatnuochanoi.vn | ✅ Implemented |
| 2 | OpenWeatherMap | openweathermap.org | ✅ Implemented |
| 3 | Visual Crossing | visualcrossing.com | ✅ Implemented |
| 4 | NCHMF | nchmf.gov.vn | ✅ Implemented |
| 5 | HSDC Flood | thoatnuochanoi.vn | ✅ Implemented |
| 6 | Holiday | Static Calendar | ✅ Implemented |
| 7 | OSM Capacity | OpenStreetMap | ✅ Implemented |

### 3.2 Pipeline Status

| Component | File | Status |
|-----------|------|--------|
| Weather Ensemble | `weather_ensemble.py` | ✅ |
| HSDC Plugin | `hsdc_plugin.py` | ✅ |
| OWM Plugin | `owm_plugin.py` | ✅ |
| VCW Plugin | `vcw_plugin.py` | ✅ |
| NCHMF Plugin | `nchmf_plugin.py` | ✅ |
| Holiday Plugin | `holiday_plugin.py` | ✅ |
| OSM Batch Pipeline | `osm_batch_pipeline.py` | ✅ |
| Spatial Ensemble | `spatial_ensemble_pipeline.py` | ✅ |

---

## 4. File Structure

```
Demand-Spike-Detector/
├── data/
│   ├── weather_anchors_30T_merged.parquet  # Main feature store
│   ├── h3_osm_capacity.parquet             # OSM capacity
│   └── realtime_lake/                      # Real-time data
│
├── src/pipeline/
│   ├── base.py                    # BaseFactorPlugin
│   ├── registry.py                # Plugin registry
│   ├── orchestrator.py          # Pipeline orchestrator
│   ├── weather_ensemble.py      # Ensemble logic
│   ├── spatial_ensemble_pipeline.py  # H3 mapping
│   └── plugins/
│       ├── owm_plugin.py
│       ├── vcw_plugin.py
│       ├── hsdc_plugin.py
│       ├── hsdc_flood_plugin.py
│       ├── nchmf_plugin.py
│       └── holiday_plugin.py
│
├── scripts/
│   ├── backfill_weather.py
│   ├── realtime_crawler.py
│   ├── osm_batch_pipeline.py
│   └── fetch_osm_retry.py
│
└── docs/
    ├── Architecture_of_weather.md
    ├── spatial_architecture.md
    ├── weather_ensemble_system.md
    └── data_dictionary.md
```
