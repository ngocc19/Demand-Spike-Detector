# Weather Ensemble System - Technical Documentation

## Overview

This document describes the Weather Ensemble System implemented for the Demand Spike Detector project. The system aggregates weather data from 4 heterogeneous sources using ensemble methods.

## Data Sources

### 1. OpenWeatherMap (OWM)
- **Type**: Real-time API
- **URL**: https://openweathermap.org/
- **API**: Current Weather + 5 Day/3 Hour Forecast
- **Code**: `src/pipeline/plugins/owm_plugin.py`

### 2. Visual Crossing Weather (VCW)
- **Type**: Real-time API + Historical
- **URL**: https://www.visualcrossing.com/
- **API**: Timeline API
- **Code**: `src/pipeline/plugins/vcw_plugin.py`

### 3. HSDC (Hanoi Drainage Company)
- **Type**: Rainfall + Flood Ground Truth
- **URL**: https://thoatnuochanoi.vn/
- **APIs**:
  - Rainfall: `https://thoatnuochanoi.vn/luongmua/api/getAllData`
  - Flood: `https://thoatnuochanoi.vn/ungngap/api/flood/getflood`
- **Code**: `src/pipeline/plugins/hsdc_plugin.py`, `hsdc_flood_plugin.py`

### 4. NCHMF (National Center for Hydro-Meteorological Forecasting)
- **Type**: Official Forecast + Warnings
- **URL**: https://nchmf.gov.vn/
- **Code**: `src/pipeline/plugins/nchmf_plugin.py`, `nchmf_api_plugin.py`

## Ensemble Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Weather Ensemble System                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
│  │   OWM   │  │   VCW   │  │  HSDC   │  │  NCHMF  │          │
│  │  Plugin │  │  Plugin │  │  Plugin │  │  Plugin │          │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘          │
│       │             │            │            │                 │
│       └─────────────┴────────────┴────────────┘                 │
│                            │                                    │
│                            ▼                                    │
│                   ┌─────────────────┐                          │
│                   │    Weather      │                          │
│                   │    Ensemble     │                          │
│                   │   Aggregator    │                          │
│                   └────────┬────────┘                          │
│                            │                                    │
│              ┌─────────────┼─────────────┐                    │
│              │             │             │                       │
│              ▼             ▼             ▼                       │
│      ┌───────────┐ ┌───────────┐ ┌───────────┐              │
│      │ Continuous │ │  Binary   │ │  Time    │              │
│      │ Ensemble   │ │ Ensemble  │ │  Decay   │              │
│      └───────────┘ └───────────┘ └───────────┘              │
│                            │                                    │
│                            ▼                                    │
│                   ┌─────────────────┐                          │
│                   │  Ensemble       │                          │
│                   │  Result         │                          │
│                   │  (Values,       │                          │
│                   │   Weights,       │                          │
│                   │   Confidence)    │                          │
│                   └─────────────────┘                          │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Mathematical Framework

### Continuous Variables (Temperature, Humidity, Precipitation)

**Step 1**: Calculate MAE for each source
```
E_i = MAE(y_true, y_i)
```

**Step 2**: Inverse-Error Weighting
```
w_i = E_i^(-1) / Σ(E_j^(-1))
```

### Binary Classification (Storm, Thunderstorm)

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

### Common Steps

**Time-Decay Function:**
```
w'_i = w_i × e^(-λ × Δt_i)
```
Where:
- λ = decay rate (default: 0.1)
- Δt_i = data staleness in hours

**Circuit Breaker & Normalization:**
```
S_i = 1 if source is HEALTHY or TIMEOUT
S_i = 0 if source is FAILED

w*_i = (S_i × w'_i) / Σ(S_j × w'_j)
```

**Ensemble Output:**
```
Y_final = Σ(w*_i × Y_i)
```

## Source Status Logic

| Status | S_i Value | Description | Action |
|--------|-----------|-------------|--------|
| HEALTHY | 1 | Normal operation | Use normally |
| TIMEOUT | 1 | Data is stale | Use with time-decay reduced weight |
| FAILED | 0 | API down/error | Exclude from ensemble |

## Weather Code Impact Mapping

| Code Range | Description | Impact |
|------------|-------------|--------|
| 0-3 | Clear/Cloudy | 0.0 |
| 45-48 | Fog | 0.2 |
| 51-55 | Drizzle | 0.4 |
| 61-67 | Rain | 0.6 |
| 80-82 | Rain showers | 0.8 |
| 95-99 | Thunderstorm | 1.0 |

## HSDC API Details

### Rainfall API

**Endpoint:** `https://thoatnuochanoi.vn/luongmua/api/getAllData`

**Note:** Response is double-encoded JSON - requires 2 levels of parsing.

```python
# Response structure
layer1 = json.loads(response.text)          # Parse response
layer2 = layer1.get('data', {})             # Get inner data
tram = json.loads(layer2['tram'])           # Parse stations (JSON string)
rainfall = json.loads(layer2['data'])       # Parse rainfall (JSON string)
```

### Flood API

**Endpoint:** `https://thoatnuochanoi.vn/ungngap/api/flood/getflood`

**Flood Level from Icon:**
- `Flood_level0.png` = No flooding (level 0)
- `Flood_level1.png` = Low (10cm)
- `Flood_level2.png` = Medium (25cm)
- `Flood_level3.png` = High (50cm)
- `Flood_level4.png` = Severe (100cm)

## Usage

### Using Individual Plugins

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

### Using Ensemble Plugin

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
```

### Using Ensemble Aggregator Directly

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
```

## Output Schema

The ensemble produces data with the following fields:

```python
result = {
    'h3_index': '88415cb4e5fffff',
    'datetime': '2026-09-25 14:00:00',
    'temp_c': 32.5,
    'humidity_pct': 75,
    'wind_speed_kmh': 15.0,
    'rain_mm': 5.2,
    'weather_code': 61,
    'weather_desc': 'light rain',
    'vcw_temp_c': 32.8,
    'vcw_rain_mm': 4.8,
    'ensemble_rain_mm': 5.0,
    'ensemble_storm_prob': 0.35,
    'flood_level': 1,
    'nchmf_warning': False,
    'has_hsdc_station': True,
}
```

## Files Structure

```
src/pipeline/
├── weather_ensemble.py          # Core ensemble logic
├── weather_ensemble_plugin.py    # Main ensemble plugin
└── plugins/
    ├── owm_plugin.py            # OpenWeatherMap
    ├── vcw_plugin.py            # Visual Crossing
    ├── nchmf_plugin.py          # NCHMF Web Crawler
    ├── nchmf_api_plugin.py     # NCHMF API
    ├── hsdc_plugin.py          # HSDC Rainfall
    └── hsdc_flood_plugin.py    # HSDC Flood

tests/
├── test_weather_ensemble.py      # Ensemble tests
└── test_weather_plugins.py      # Plugin tests
```

## Phase 0 (Backfill) vs Phase 1 (Real-time)

### Phase 0: Backfill
- Use VCW historical API for bulk historical data
- Use HSDC for rainfall ground truth
- NCHMF may have limited historical data
- OWM supports `past_days` parameter

### Phase 1: Real-time
- All 4 sources provide real-time data
- WeatherEnsemblePlugin aggregates every hour
- Time-decay handles data with different update frequencies
- Circuit breaker handles API failures

## Notes

1. **HSDC API**: Response is double-encoded JSON - requires special parsing logic.

2. **HSDC Circuit Breaker**: Not all hexagons have HSDC stations. Hexes without stations get S=0 for HSDC source.

3. **NCHMF**: Official Vietnamese weather agency. Contains storm warnings (Cảnh báo giông, lốc, sét, mưa đá).

4. **Ensemble Weights**: Weights are recalculated based on historical accuracy. First run uses equal weights.
