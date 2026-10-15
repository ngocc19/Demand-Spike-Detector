# Demand Spike Detector - Architecture Overview

## 1. Tổng Quan Kiến Trúc

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DEMAND SPIKE DETECTOR ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    EXTERNAL DATA SOURCES                             │   │
│  │                                                                     │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐             │   │
│  │  │   VCW    │ │   OWM    │ │  HSDC    │ │  NCHMF   │             │   │
│  │  │(Weather) │ │(Weather) │ │(Rainfall │ │ (Storm)  │             │   │
│  │  │ Visual    │ │ Open     │ │ Flood)   │ │ National │             │   │
│  │  │Crossing  │ │Weather   │ │Hanoi API │ │Climate   │             │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘             │   │
│  └────────┼────────────┼────────────┼────────────┼─────────────────────┘   │
│            │            │            │            │                          │
│            └────────────┴─────┬──────┴────────────┘                          │
│                               │                                              │
│                               ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    PIPELINE (Orchestrator)                           │   │
│  │                                                                     │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │   Plugin     │  │   Plugin     │  │   Plugin     │              │   │
│  │  │   Registry   │  │   Base      │  │   Weather    │              │   │
│  │  │   (Factory)  │  │   (Interface)│  │   Ensemble   │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  │                                                                     │   │
│  │  Plugins: Weather, HSDC, NCHMF, Holiday, Event, Traffic, OSM     │   │
│  └─────────────────────────────────┬───────────────────────────────────┘   │
│                                    │                                       │
│                                    ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    OUTPUT: Feature Store                           │   │
│  │                                                                     │   │
│  │  ┌──────────────┬──────────────┬──────────────┬──────────────┐    │   │
│  │  │ weather_     │ ensemble_    │ flood_      │ osm_         │    │   │
│  │  │ anchors_30T  │ merged.parquet│ level       │ capacity     │    │   │
│  │  └──────────────┴──────────────┴──────────────┴──────────────┘    │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. Component Overview

### Data Sources (4 External Sources)

| Source | Type | API/URL | Update | Code |
|--------|------|---------|--------|------|
| **VCW** | Weather | Visual Crossing | Real-time | `vcw_plugin.py` |
| **OWM** | Weather | OpenWeatherMap | Real-time | `owm_plugin.py` |
| **HSDC** | Rainfall/Flood | thoatnuochanoi.vn | 15 min | `hsdc_plugin.py`, `hsdc_flood_plugin.py` |
| **NCHMF** | Storm Warning | nchmf.gov.vn | 3 hours | `nchmf_plugin.py`, `nchmf_api_plugin.py` |

### Internal/Static Sources

| Source | Type | Code |
|--------|------|------|
| **Holiday** | Static Calendar | `holiday_plugin.py` |
| **Event** | Manual CSV | `event_plugin.py` |
| **Traffic** | TomTom API | `tomtom_traffic_plugin.py` |
| **OSM** | OpenStreetMap | `osm_batch_pipeline.py` |

## 3. Pipeline Components

### 3.1 Core Pipeline

```
src/pipeline/
├── base.py                    # BaseFactorPlugin - Interface chuẩn cho plugins
├── registry.py                # PluginRegistry - Factory pattern cho plugins
├── orchestrator.py            # PipelineOrchestrator - Điều phối tất cả plugins
├── weather_ensemble.py       # WeatherEnsembleAggregator - Ensemble logic
├── spatial_ensemble_pipeline.py  # H3 spatial mapping
└── nchmf_spatial_lookup.py   # NCHMF O(1) spatial lookup
```

### 3.2 Plugins

```
src/pipeline/plugins/
├── owm_plugin.py             # OpenWeatherMap
├── vcw_plugin.py            # Visual Crossing Weather
├── hsdc_plugin.py           # HSDC Rainfall API
├── hsdc_flood_plugin.py    # HSDC Flood API
├── nchmf_plugin.py          # NCHMF Web Crawler
├── nchmf_api_plugin.py     # NCHMF API (alternative)
├── holiday_plugin.py        # Holiday Calendar
├── event_plugin.py          # Event Data (CSV)
├── tomtom_traffic_plugin.py # TomTom Traffic
└── weather_ensemble_plugin.py # Combined Weather Ensemble
```

## 4. Feature Store

### 4.1 Main Weather Data

```
data/weather_anchors_30T_merged.parquet
├── h3_index              # H3 hex ID (resolution 8)
├── datetime              # Timestamp (30-min intervals)
├── temp_c               # Temperature (°C)
├── humidity_pct          # Humidity (%)
├── wind_speed_kmh       # Wind speed (km/h)
├── rain_mm              # Rainfall (mm)
├── weather_code          # WMO weather code
├── weather_desc          # Weather description
├── vcw_temp_c           # VCW temperature
├── vcw_rain_mm          # VCW rainfall
├── ensemble_rain_mm     # Blended rainfall
├── ensemble_storm_prob   # Storm probability
├── flood_level          # HSDC flood level (0-4)
├── nchmf_warning        # NCHMF warning flag
└── holiday_impact        # Holiday impact score
```

### 4.2 OSM Capacity Data

```
data/h3_osm_capacity.parquet
├── hex_id                # H3 hex ID
├── osm_capacity_index    # Normalized capacity (0.01-1.0)
├── osm_capacity_score    # Raw capacity score
├── osm_road_score       # Road network score
├── road_count           # Number of roads
├── osm_infra_score      # Infrastructure score
├── infra_count          # Infrastructure count
├── hex_lat              # Hex centroid latitude
└── hex_lon              # Hex centroid longitude
```

## 5. Execution Flow

### 5.1 Batch Pipeline (Offline Training)

```
scripts/
├── backfill_weather.py         # Fetch historical weather data
├── backfill_with_8keys.py      # Bulk backfill với 8 API keys
├── processor.py                # Process raw data → features
├── demo_pipeline.py            # Demo pipeline execution
├── merge_holidays.py          # Merge holiday data
├── osm_batch_pipeline.py      # OSM capacity → parquet
└── fetch_osm_retry.py         # Fetch OSM from Overpass API
```

### 5.2 Real-time Pipeline

```
scripts/
├── realtime_crawler.py          # Real-time data crawler (15 min)
├── run_crawler.ps1             # Windows wrapper
├── run_crawler.sh             # Linux wrapper
├── install_crawler_task.ps1    # Windows Task Scheduler setup
└── check_crawler_status.ps1   # Status checker
```

## 6. Key Features

### 6.1 Weather Ensemble

```python
# 4-source ensemble với:
# - MAE-based weighting cho continuous variables
# - F1-score voting cho classification
# - Time-decay function
# - Circuit breaker pattern (HSDC stations)
```

### 6.2 Spatial Mapping

```python
# H3 resolution 8 (~0.46 km² per hex)
# ~1145 hexes cover Hanoi
# O(1) spatial lookup cho NCHMF warnings
```

### 6.3 OSM Capacity

```python
# One-time fetch từ Overpass API
# Cached to parquet (~168KB)
# Road network density per hex
# Offline multi-use
```

## 7. File Structure

```
Demand-Spike-Detector/
├── data/
│   ├── weather_anchors_30T_merged.parquet  # Main feature store
│   ├── h3_osm_capacity.parquet              # OSM capacity
│   ├── h3_osm_capacity.csv
│   ├── h3_osm_capacity_meta.json
│   └── realtime_lake/                     # Real-time data lake
│       └── weather_YYYY-MM-DD.parquet
├── scripts/
│   ├── backfill_weather.py
│   ├── realtime_crawler.py
│   ├── osm_batch_pipeline.py
│   └── ...
├── src/
│   ├── pipeline/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── orchestrator.py
│   │   ├── weather_ensemble.py
│   │   └── plugins/
│   │       ├── owm_plugin.py
│   │       ├── vcw_plugin.py
│   │       ├── hsdc_plugin.py
│   │       └── ...
│   ├── features/
│   │   ├── preprocessor.py
│   │   ├── feature_engineer.py
│   │   └── holiday_calendar.py
│   └── traffic/
│       └── ...
├── tests/
│   ├── test_weather_ensemble.py
│   ├── test_weather_plugins.py
│   └── ...
└── docs/
    ├── Architecture_of_weather.md
    ├── spatial_architecture.md
    ├── weather_ensemble_system.md
    └── data_dictionary.md
```
