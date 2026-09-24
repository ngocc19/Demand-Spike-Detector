# Weather Ensemble System - Technical Documentation

## Overview

This document describes the Weather Ensemble System implemented for the Demand Spike Detector project. The system aggregates weather data from 4 heterogeneous sources using ensemble methods.

## Data Sources

### 1. OpenWeatherMap (OWM)
- **Type**: Real-time API
- **URL**: https://openweathermap.org/
- **API**: Current Weather + 5 Day/3 Hour Forecast
- **Free Tier**: 60 calls/minute
- **Update Frequency**: Real-time
- **Code**: `src/pipeline/plugins/owm_plugin.py`

### 2. Visual Crossing Weather (VCW)
- **Type**: Real-time API + Historical
- **URL**: https://www.visualcrossing.com/
- **API**: Timeline API
- **Free Tier**: 1,000 records/day
- **Update Frequency**: Real-time
- **Historical Data**: Excellent for Phase 0 backfill
- **Code**: `src/pipeline/plugins/vcw_plugin.py`

### 3. HSDC (Hanoi Drainage Company)
- **Type**: Rainfall + Flood Ground Truth
- **URL**: https://maps.hsdc.vn/ (Rainfall Maps)
- **Flood API**: https://thoatnuochanoi.vn/ungngap/api/flood/getflood
- **Data**: Real-time rainfall and flood monitoring
- **Stations**: 45 flood monitoring points across Hanoi
- **Update Frequency**: Every 15 minutes
- **Code**: `src/pipeline/plugins/hsdc_plugin.py` (Rainfall)
- **Code**: `src/pipeline/plugins/hsdc_flood_plugin.py` (Flood)

### 4. NCHMF (National Center for Hydro-Meteorological Forecasting)
- **Type**: Official Forecast + Warnings
- **URL**: https://nchmf.gov.vn/
- **Hanoi Station**: https://nchmf.gov.vn/Kttvsite/vi-VN/1/ha-noi-w29.html
- **Data**: Official forecasts, storm warnings
- **Update Frequency**: Every 3 hours
- **Code**: `src/pipeline/plugins/nchmf_plugin.py`

## Ensemble Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Weather Ensemble Plugin                         │
│                 (weather_ensemble_plugin.py)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │   OWM   │  │   VCW   │  │  HSDC   │  │  NCHMF  │            │
│  │  Plugin │  │  Plugin │  │  Plugin │  │  Plugin │            │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘            │
│       │            │            │            │                   │
│       └────────────┴────────────┴────────────┘                   │
│                          │                                      │
│                    ┌──────▼──────┐                               │
│                    │   Fetch     │                               │
│                    │   All Data   │                               │
│                    └──────┬──────┘                               │
│                          │                                      │
│                    ┌──────▼──────────────────┐                  │
│                    │ WeatherEnsembleAggregator │                  │
│                    │   (weather_ensemble.py)   │                  │
│                    │                          │                  │
│                    │ Branch 1: Continuous     │                  │
│                    │   - MAE-based weighting   │                  │
│                    │                          │                  │
│                    │ Branch 2: Classification │                  │
│                    │   - F1-score voting      │                  │
│                    │                          │                  │
│                    │ Common:                   │                  │
│                    │   - Time-decay           │                  │
│                    │   - Circuit breaker      │                  │
│                    └──────────────────────────┘                  │
│                               │                                   │
│                    ┌──────────▼──────────┐                       │
│                    │  Ensemble Result    │                       │
│                    │  - Values           │                       │
│                    │  - Weights          │                       │
│                    │  - Confidence       │                       │
│                    └─────────────────────┘                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Mathematical Framework

### Branch 1: Continuous Variables (Temperature, Humidity, Precipitation)

**Step 1**: Calculate MAE for each source in window T days
```
E_i = MAE(y_true, y_i)
```

**Step 2**: Inverse-Error Weighting
```
w_i = E_i^(-1) / Σ(E_j^(-1))
```

### Branch 2: Binary Classification (Storm, Thunderstorm)

**Step 1**: Confusion Matrix → Precision, Recall
```
P_i = TP / (TP + FP)
R_i = TP / (TP + FN)
```

**Step 2**: F1-Score
```
F1_i = 2 × P_i × R_i / (P_i + R_i)
```

**Step 3**: Soft-voting Weight
```
w_i = F1_i / Σ(F1_j)
```

### Common Steps (Applied to Both Branches)

**Step 3**: Time-Decay Function
```
w'_i = w_i × e^(-λ × Δt_i)
```
Where:
- λ = decay rate (default: 0.1)
- Δt_i = data staleness in hours

**Step 4**: Circuit Breaker & Normalization
```
S_i = 1 if source is HEALTHY or TIMEOUT
S_i = 0 if source is FAILED

w*_i = (S_i × w'_i) / Σ(S_j × w'_j)
```

**Step 5**: Ensemble Output
```
Y_final = Σ(w*_i × Y_i)
```

## Source Status Logic

| Status | S_i Value | Description | Action |
|--------|-----------|-------------|--------|
| HEALTHY | 1 | Normal operation | Use normally |
| TIMEOUT | 1 | Data is stale | Use with time-decay reduced weight |
| FAILED | 0 | API down/error | Exclude from ensemble |

## Usage

### 1. Using Individual Plugins

```python
from src.pipeline.plugins.owm_plugin import OWMFactorPlugin
from src.pipeline.plugins.nchmf_plugin import NCHMFFactorPlugin
from src.pipeline.plugins.hsdc_plugin import HSDCFactorPlugin

# OWM data
owm = OWMFactorPlugin({'api_key': 'YOUR_KEY'})
owm_data = owm.fetch()

# NCHMF data
nchmf = NCHMFFactorPlugin({})
nchmf_data = nchmf.fetch()

# HSDC rainfall (ground truth)
hsdc = HSDCFactorPlugin({})
hsdc_data = hsdc.fetch()
```

### 2. Using Ensemble Plugin

```python
from src.pipeline.plugins.weather_ensemble_plugin import WeatherEnsemblePlugin

# Configure ensemble
config = {
    'lambda_decay': 0.15,
    'timeout_threshold_hours': 2.0,
    'sources': {
        'owm': {'api_key': 'YOUR_KEY'},
        'vcw': {'api_key': 'YOUR_KEY'},
    }
}

ensemble = WeatherEnsemblePlugin(config)
result = ensemble.fetch()

print(result)
# Returns ensemble values with confidence scores
```

### 3. Using Ensemble Aggregator Directly

```python
from src.pipeline.weather_ensemble import WeatherEnsembleAggregator, EnsembleConfig

config = EnsembleConfig(lambda_decay=0.15)
aggregator = WeatherEnsembleAggregator(config)

# Continuous variable ensemble
result = aggregator.ensemble_continuous(
    variable_name='temperature',
    source_values={'OWM': 30.5, 'VCW': 31.0, 'NCHMF': 29.5}
)

# Classification variable ensemble
result = aggregator.ensemble_classification(
    variable_name='storm',
    source_values={'OWM': 0.3, 'VCW': 0.5, 'NCHMF': 0.85}
)

print(f"Ensemble Value: {result.ensemble_value}")
print(f"Active Sources: {result.active_sources_count}/4")
print(f"Weights: {result.source_weights}")
```

## Configuration

### factors.yaml

```yaml
factors:
  - name: weather_ensemble
    enabled: true
    schedule: "0 * * * *"
    config:
      lambda_decay: 0.15
      timeout_threshold_hours: 2.0
      sources:
        owm:
          api_key: ${OPENWEATHERMAP_API_KEY}
          city: Hanoi,VN
        vcw:
          api_key: ${VISUALCROSSING_API_KEY}
          location: Hanoi,Vietnam
        hsdc:
          timeout_seconds: 15
        nchmf:
          timeout_seconds: 20
```

### Environment Variables

```bash
# API Keys
export OPENWEATHERMAP_API_KEY=your_key_here
export VISUALCROSSING_API_KEY=your_key_here
```

## HSDC Maps - Finding API Endpoints

### Flood Data API (CONFIRMED WORKING)
```
Endpoint: https://thoatnuochanoi.vn/ungngap/api/flood/getflood
Method: GET
Response: JSON
```

**Response Structure:**
```json
{
    "Code": 1,
    "Content": [
        {
            "TramId": "3",
            "TenTram": "Cao Bá Quát (cổng Cty Môi trường đô thị)",
            "Lng": "105.839500",
            "Lat": "21.030180",
            "Icon": "202608311105287262087_Flood_level1.png"
        },
        ...
    ]
}
```

**Flood Level from Icon:**
- `Flood_level0.png` = No flooding (level 0)
- `Flood_level1.png` = Low (10cm)
- `Flood_level2.png` = Medium (25cm)
- `Flood_level3.png` = High (50cm)
- `Flood_level4.png` = Severe (100cm)

**45 Monitoring Stations include:**
- Cầu Giấy, Thanh Xuân, Hoàng Mai
- Đống Đa, Hai Bà Trưng
- Tây Hồ, Ngọc Hồi
- And 38 more locations

### Other HSDC Endpoints

#### Rainfall API (CONFIRMED WORKING)
```
Endpoint: https://thoatnuochanoi.vn/luongmua/api/getAllData
Method: POST
Response: JSON (double-encoded)
```

**Response Structure (3 layers):**
```json
Layer 1: {"code": 1, "data": {...}}
Layer 2: {"tram": "[{...}]", "data": "[{...}]"}  <- JSON strings
Layer 3: tram = [{station objects}]
Layer 3: data = [{rainfall records}]
```

**Station fields:**
```json
{"Id": 52, "TenTram": "HOÀN KIẾM", "DiaChi": "167 Phùng Hưng"}
```

**Rainfall fields:**
```json
{
    "Id": 1,
    "TramId": 11,
    "LuongMua_BD": 0.1,      // Before (mm)
    "ThoiGian_BD": "2026-09-24T03:13:20",
    "LuongMua_HT": 0.1,      // Current (mm)
    "ThoiGian_HT": "2026-09-24T03:13:20",
    "LuongMua_Tr": 0.1,      // Total accumulated (mm)
    "ThoiGian_Tr": "2026-09-24T03:13:20",
    "AC": 0
}
```

**Processing Logic:**
```python
# Double JSON parse required
layer1 = json.loads(response.text)          # Parse response
layer2 = layer1.get('data', {})             # Get inner data
tram = json.loads(layer2['tram'])           # Parse stations (JSON string)
rainfall = json.loads(layer2['data'])       # Parse rainfall (JSON string)
```

**48 Stations available** including:
- Hoàn Kiếm, Thái Hà, Phạm Ngọc Thạch
- Nguyễn Trãi, Cầu Giấy, Keangnam
- And more...

## Testing

Run all weather tests:
```bash
pytest tests/test_weather_ensemble.py tests/test_weather_plugins.py -v
```

## Files Structure

```
src/pipeline/
├── weather_ensemble.py          # Core ensemble logic
└── plugins/
    ├── owm_plugin.py            # OpenWeatherMap plugin
    ├── vcw_plugin.py            # Visual Crossing plugin
    ├── nchmf_plugin.py          # NCHMF Hanoi plugin
    ├── hsdc_plugin.py           # HSDC rainfall plugin
    └── weather_ensemble_plugin.py # Main ensemble plugin

tests/
├── test_weather_ensemble.py      # Ensemble unit tests
└── test_weather_plugins.py      # Plugin unit tests
```

## Phase 0 (Backfill) vs Phase 1 (Real-time)

### Phase 0: Backfill
- Use VCW historical API for bulk historical data
- Use HSDC for rainfall ground truth (if historical available)
- NCHMF may have limited historical data
- OWM supports `past_days` parameter

### Phase 1: Real-time
- All 4 sources provide real-time data
- WeatherEnsemblePlugin aggregates every hour
- Time-decay handles data with different update frequencies
- Circuit breaker handles API failures

## Notes

1. **API Keys**: Get free API keys from:
   - OWM: https://openweathermap.org/api
   - VCW: https://www.visualcrossing.com/weather-api

2. **HSDC Maps**: The actual API endpoints must be discovered via DevTools as they may change.

3. **NCHMF**: Official Vietnamese weather agency. Contains storm warnings (Cảnh báo giông, lốc, sét, mưa đá).

4. **Ensemble Weights**: Weights are recalculated based on historical accuracy. First run uses equal weights.
