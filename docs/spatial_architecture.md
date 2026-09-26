# Spatial Weather Ensemble Architecture

## Overview

Complete spatial ensemble architecture that maps weather data to H3 hexagons for demand forecasting and routing optimization, with optimized NCHMF integration.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SPATIAL WEATHER ENSEMBLE PIPELINE                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  STARTUP (once)                                                       │  │
│  │                                                                       │  │
│  │  Static Lookups (O(1) lookup, no geometry at runtime):               │  │
│  │  ├── H3 → District: {hex: district, ...}  (~237 entries)            │  │
│  │  └── District → Zone: {district: zone, ...}  (~30 entries)          │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  NORMALIZATION LAYER (on NCHMF crawl - every 3 hours)               │  │
│  │                                                                       │  │
│  │  NCHMF Text → Zone Warnings:                                         │  │
│  │                                                                       │  │
│  │  "Cảnh báo giông lốc khu vực nội thành"                            │  │
│  │       ↓                                                              │  │
│  │  nchmf_zone_warnings = {                                            │  │
│  │      'NoiThanh': {'storm': 1.0, 'heavy_rain': 0.8, 'flood': 0.5}  │  │
│  │      'PhiaTay': {'storm': 0.5, 'heavy_rain': 0.3, 'flood': 0.2}    │  │
│  │  }                                                                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  RUNTIME PER HEXAGON (O(1) - 3 dictionary lookups)                   │  │
│  │                                                                       │  │
│  │  h3_index                                                           │  │
│  │      │                                                               │  │
│  │      ├──→ district = h3_to_district.get(h3_index)      # O(1)      │  │
│  │      │                                                               │  │
│  │      ├──→ zone = district_to_zone.get(district)      # O(1)        │  │
│  │      │                                                               │  │
│  │      └──→ nchmf_warning = zone_cache.get(zone)      # O(1)         │  │
│  │                                                                       │  │
│  │  Total: 3 dictionary lookups = Microseconds                          │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  DATA SOURCES                                                        │  │
│  │                                                                       │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                  │  │
│  │  │   OWM   │ │   VCW   │ │  HSDC   │ │  NCHMF  │                  │  │
│  │  │ Res 8   │ │ Res 8   │ │ Stations │ │ Zone    │                  │  │
│  │  │(Centroid)│(Centroid)│ │  → Hex   │ │ (O(1))  │                  │  │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘                  │  │
│  │       └───────────┴───────────┴───────────┘                        │  │
│  │                           │                                          │  │
│  │                    ┌──────▼──────┐                                   │  │
│  │                    │  Weather    │                                   │  │
│  │                    │ Ensemble    │                                   │  │
│  │                    │ Aggregator  │                                   │  │
│  │                    └──────┬──────┘                                   │  │
│  │                           │                                          │  │
│  └───────────────────────────┼──────────────────────────────────────────┘  │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  OUTPUT: DataFrame per hexagon                                      │  │
│  │                                                                       │  │
│  │  ├── h3_index          (H3 ID)                                      │  │
│  │  ├── latitude/longitude (centroid)                                  │  │
│  │  ├── zone/district     (from lookup)                                │  │
│  │  ├── ensemble_rainfall (continuous)                                │  │
│  │  ├── ensemble_storm_prob (classification - for Prophet/CUSUM)       │  │
│  │  ├── source_weights_*  (per variable)                              │  │
│  │  └── has_hsdc_station  (Circuit Breaker flag)                       │  │
│  │                                                                       │  │
│  │  → Input to Demand Spike Detector Model                             │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Zone Definitions

NCHMF warning zones align with geographic regions:

| Zone | Districts | Priority | Description |
|------|-----------|----------|-------------|
| **NoiThanh** | HoanKiem, HaiBaTrung, DongDa, BaDinh, TayHo, CauGiay | 1 | 6 quận trung tâm |
| **PhiaTay** | ThanhXuan, HoangMai, NamTuLiem, BacTuLiem | 2 | Phía Tây - đồi núi |
| **PhiaBac** | LongBien, GiaLam, SocSon, DongAnh | 3 | Phía Bắc - sông Hồng |
| **PhiaNam** | ThanhTri, HoaiDuc, TuLiEm, SonTay | 4 | Phía Nam |
| **NgoaiThanh** | BaVi, PhuTho, HungYen, VinhPhuc, BacNinh | 5 | Ngoại thành |

## Key Components

### 1. Static Lookup Tables (Pre-computed)

```python
# src/pipeline/nchmf_spatial_lookup.py

# H3 → District mapping (generated once at startup)
H3_TO_DISTRICT: Dict[str, str] = {
    '88415cb4e5fffff': 'HoanKiem',
    '8841436961fffff': 'CauGiay',
    ...
}

# District → Zone mapping (static)
DISTRICT_TO_ZONE: Dict[str, str] = {
    'HoanKiem': 'NoiThanh',
    'CauGiay': 'NoiThanh',
    'ThanhXuan': 'PhiaTay',
    ...
}
```

### 2. NCHMF Zone Cache (Dynamic)

```python
class NCHMFZoneWarningCache:
    """Cache for NCHMF zone warnings - updated on crawl."""

    _cache = {
        'NoiThanh': {'storm': 1.0, 'heavy_rain': 0.8, 'flood': 0.5},
        'PhiaTay': {'storm': 0.5, 'heavy_rain': 0.3, 'flood': 0.2},
        ...
    }

    def update(self, zone_warnings: Dict[str, Dict]):
        """Called when NCHMF is crawled."""
        ...

    def get_zone_warning(self, zone: str) -> Dict:
        """O(1) lookup."""
        return self._cache.get(zone, default_warning)
```

### 3. O(1) Lookup Chain

```python
def get_nchmf_for_hex(h3_index: str) -> Dict:
    """
    O(1) lookup chain for NCHMF data.

    h3_index → district → zone → warning
    """
    # Step 1: H3 → District (static lookup)
    district = H3_TO_DISTRICT.get(h3_index)

    # Step 2: District → Zone (static lookup)
    zone = DISTRICT_TO_ZONE.get(district)

    # Step 3: Zone → Warning (dynamic cache)
    warning = nchmf_zone_cache.get_zone_warning(zone)

    return warning
```

### 4. Local Ensemble Per Hexagon

```python
def run_local_ensemble(h3_index: str, config: EnsembleConfig) -> Dict:
    """Run WeatherEnsembleAggregator for ONE hexagon."""

    # Get data from sources
    rainfall_values = {
        'OWM': query_owm(lat, lng),
        'VCW': query_vcw(lat, lng),
        'HSDC': hsdc_rainfall if has_hsdc_station else 0,
        'NCHMF': nchmf_warning['heavy_rain'] * 50,  # Scale to mm
    }

    storm_values = {
        'OWM': is_thunderstorm(weather_code),
        'VCW': 'thunderstorm' in conditions,
        'HSDC': 0,  # No storm data
        'NCHMF': nchmf_warning['storm'],
    }

    # Circuit Breaker
    source_status = {
        'OWM': 1,
        'VCW': 1,
        'HSDC': 1 if has_hsdc else 0,  # Key: 0 if no station!
        'NCHMF': 1,
    }

    # Run ensembles
    rainfall_result = aggregator.ensemble_continuous('rainfall', rainfall_values)
    storm_result = aggregator.ensemble_classification('storm', storm_values)

    return {
        'h3_index': h3_index,
        'ensemble_rainfall': rainfall_result.ensemble_value,
        'ensemble_storm_prob': storm_result.ensemble_value,  # For Prophet/CUSUM
        ...
    }
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 0: Startup (once)                                           │
│                                                                     │
│  1. Generate H3 → District mapping                                 │
│  2. Load District → Zone mapping                                    │
│  3. Initialize NCHMF zone cache                                     │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 1: NCHMF Crawl (every 3 hours)                             │
│                                                                     │
│  1. Crawl NCHMF website                                            │
│  2. Parse warning text → Zone warnings                              │
│  3. Update nchmf_zone_cache                                        │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 2: HSDC Fetch (every 15 minutes)                           │
│                                                                     │
│  1. Fetch HSDC API                                                 │
│  2. Map stations → H3 indices                                      │
│  3. Aggregate by hex (MAX)                                         │
│  4. Create hsdc_lookup table                                       │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 3: OWM/VCW Fetch (hourly)                                  │
│                                                                     │
│  For each hexagon:                                                  │
│    Query OWM at centroid                                           │
│    Query VCW at centroid                                           │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PHASE 4: Local Ensemble (per hexagon)                             │
│                                                                     │
│  For each hexagon (1145 total):                                   │
│    1. Get OWM/VCW data (already fetched)                         │
│    2. Get HSDC data (from lookup) or 0 if no station             │
│    3. Get NCHMF warning (O(1) lookup)                            │
│    4. Run WeatherEnsembleAggregator                               │
│    5. Store result                                                │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OUTPUT: Spatial Weather DataFrame                                 │
│                                                                     │
│  Ready for:                                                         │
│  - Demand Spike Detector Model                                     │
│  - Prophet/CUSUM with storm_prob as exogenous feature             │
│  - Routing optimization (avoid flood zones)                        │
└─────────────────────────────────────────────────────────────────────┘
```

## Resolution Guide

| Resolution | Area/Hex | Total Hexes | Use Case |
|------------|----------|-------------|----------|
| Res 7 | ~1.65 km² | 183 | Regional planning |
| **Res 8** | **~0.46 km²** | **1,145** | **Demand forecasting** |
| Res 9 | ~0.10 km² | 3,111 | Street-level routing |

## Output Schema

```python
result_df = pd.DataFrame({
    'h3_index': ['88415cb4e5fffff', ...],
    'latitude': [21.0299, ...],
    'longitude': [105.8514, ...],
    'zone': ['NoiThanh', ...],
    'district': ['CauGiay', ...],

    # Continuous variable
    'ensemble_rainfall': [12.5, ...],  # mm

    # Classification variable (for Prophet/CUSUM)
    'ensemble_storm_prob': [0.85, ...],  # 0-1 probability

    # Source metadata
    'has_hsdc_station': [True, ...],
    'hsdc_station': ['HoanKiem', ...],
    'source_weights_rainfall': [{'OWM': 0.25, 'VCW': 0.25, ...}, ...],
    'source_weights_storm': [{'OWM': 0.2, 'VCW': 0.2, 'NCHMF': 0.6}, ...],
    'active_sources_rainfall': [4, ...],
    'active_sources_storm': [3, ...],
})
```

## Files

```
src/pipeline/
├── spatial_ensemble_pipeline.py     # Main pipeline
├── weather_ensemble.py              # Core ensemble logic
├── nchmf_spatial_lookup.py         # NCHMF O(1) lookups
└── plugins/
    ├── hsdc_plugin.py              # HSDC rainfall API
    ├── owm_plugin.py               # OpenWeatherMap
    ├── vcw_plugin.py               # Visual Crossing
    └── nchmf_plugin.py             # NCHMF crawler

tests/
├── test_spatial_ensemble.py        # Spatial pipeline tests
└── test_weather_ensemble.py        # Ensemble tests
```

## Performance

- **Lookup time**: ~1-5 microseconds per hexagon (3 dict lookups)
- **Total lookup time**: ~5-10ms for all 1,145 hexagons
- **API calls needed**: 2 (OWM, VCW) × 1,145 = 2,290 calls
  - Can be batched/parallelized
- **NCHMF**: 0 API calls at runtime (pre-computed + cached)
