# Spatial Architecture Documentation

## Overview

This document describes the spatial architecture for mapping weather and infrastructure data to H3 hexagons for demand forecasting and routing optimization.

## H3 Grid System

### Resolution Selection

| Resolution | Area/Hex | Total Hexes (Hanoi) | Use Case |
|-----------|----------|---------------------|----------|
| Res 7 | ~1.65 km² | ~183 | Regional planning |
| **Res 8** | **~0.46 km²** | **~1,145** | **Demand forecasting** |
| Res 9 | ~0.10 km² | ~3,111 | Street-level routing |

### Hanoi Coverage

```python
HANOI_CENTER = (21.0285, 105.8542)
H3_RES = 8

# Generate hex grid covering Hanoi
center_hex = h3.latlng_to_cell(HANOI_CENTER[0], HANOI_CENTER[1], H3_RES)
hexes = list(h3.grid_disk(center_hex, radius))
# ~1145 hexes covering Hanoi metro area
```

## Spatial Pipeline Components

### 1. Weather Anchors

Weather data is mapped to H3 hexagons using centroid-based assignment:

```
┌─────────────────────────────────────────────────────────────────────┐
│  WEATHER DATA FLOW                                                   │
│                                                                      │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐                     │
│  │   OWM   │     │   VCW   │     │  HSDC   │                     │
│  │   API   │     │   API   │     │ Stations│                     │
│  └────┬────┘     └────┬────┘     └────┬────┘                     │
│       │                │                │                           │
│       │  lat/lon      │  lat/lon       │  station → hex           │
│       └───────┬───────┘                │                           │
│               │                        │                           │
│               ▼                        ▼                           │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │           H3 LAT/LNG → CELL MAPPING                    │        │
│  │                                                         │        │
│  │   h3.latlng_to_cell(lat, lon, 8) → hex_id             │        │
│  │                                                         │        │
│  └─────────────────────────────────────────────────────────┘        │
│                              │                                     │
│                              ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │           WEATHER ANCHOR ASSIGNMENT                      │        │
│  │                                                         │        │
│  │   hex_id: 88415cb4e5fffff                              │        │
│  │   weather data: {temp_c, rain_mm, humidity_pct, ...}  │        │
│  │                                                         │        │
│  └─────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. NCHMF Spatial Lookup (O(1))

NCHMF warnings are mapped to zones using pre-computed lookup tables:

```python
# Pre-computed at startup (O(1) at runtime)
H3_TO_DISTRICT = {
    '88415cb4e5fffff': 'HoanKiem',
    '8841436961fffff': 'CauGiay',
    ...
}

DISTRICT_TO_ZONE = {
    'HoanKiem': 'NoiThanh',
    'CauGiay': 'NoiThanh',
    'ThanhXuan': 'PhiaTay',
    ...
}

# Runtime lookup: h3_index → district → zone → warning (3 dict lookups)
def get_nchmf_warning(h3_index: str) -> Dict:
    district = H3_TO_DISTRICT.get(h3_index)
    zone = DISTRICT_TO_ZONE.get(district)
    warning = nchmf_zone_cache.get(zone, default_warning)
    return warning
```

### 3. Zone Definitions

| Zone | Districts | Description |
|------|-----------|-------------|
| **NoiThanh** | HoanKiem, HaiBaTrung, DongDa, BaDinh, TayHo, CauGiay | 6 central districts |
| **PhiaTay** | ThanhXuan, HoangMai, NamTuLiem, BacTuLiem | Western Hanoi |
| **PhiaBac** | LongBien, GiaLam, SocSon, DongAnh | Northern Hanoi |
| **PhiaNam** | ThanhTri, HoaiDuc, TuLiEm, SonTay | Southern Hanoi |
| **NgoaiThanh** | BaVi, PhuTho, HungYen, VinhPhuc, BacNinh | Suburban |

## OSM Capacity Mapping

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  OSM DATA PIPELINE                                                │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Step 1: Fetch (one-time)                                   │    │
│  │                                                             │    │
│  │  Overpass API → osm_with_geometry.json                      │    │
│  │  Query: way["highway"](bounds)                              │    │
│  │  Output: 141,956 ways with geometry                         │    │
│  │                                                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                     │
│                              ▼                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Step 2: Process to Parquet                                  │    │
│  │                                                             │    │
│  │  For each way:                                              │    │
│  │    For each point in way.geometry:                          │    │
│  │      hex_id = h3.latlng_to_cell(lat, lon, 8)              │    │
│  │      score += road_weight                                   │    │
│  │                                                             │    │
│  │  Normalize: score → osm_capacity_index (0.01-1.0)        │    │
│  │                                                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                              │                                     │
│                              ▼                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Output: h3_osm_capacity.parquet                          │    │
│  │                                                             │    │
│  │  hex_id | osm_capacity_index | road_count | hex_lat/lon   │    │
│  │  88415cb4e5fffff | 0.457 | 593 | 21.0299, 105.8514     │    │
│  │  ...                                                        │    │
│  │                                                             │    │
│  │  Total: 3,997 hexes                                        │    │
│  │  Hexes with roads: 1,806                                   │    │
│  │                                                             │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### Road Weights

| Highway Type | Weight | Description |
|--------------|--------|-------------|
| motorway | 10.0 | Highway |
| motorway_link | 8.0 | Highway ramp |
| trunk | 8.0 | Major road |
| trunk_link | 6.0 | Major road ramp |
| primary | 5.0 | Primary road |
| primary_link | 4.0 | Primary road ramp |
| secondary | 3.0 | Secondary road |
| secondary_link | 2.5 | Secondary ramp |
| tertiary | 2.0 | Tertiary road |
| tertiary_link | 1.5 | Tertiary ramp |
| residential | 1.0 | Residential street |
| unclassified | 0.8 | Minor road |
| service | 0.5 | Service road |

## Code Reference

### Key Scripts

```bash
# Fetch OSM data (one-time)
python scripts/fetch_osm_retry.py

# Process to parquet (after fetch)
python scripts/process_osm_h3api.py

# Generate grid + capacity
python scripts/osm_batch_pipeline.py --full

# Verify coverage
python scripts/osm_batch_pipeline.py --verify
```

### Key Functions

```python
# src/pipeline/spatial_ensemble_pipeline.py
def generate_weather_anchors(resolution: int = 8) -> pd.DataFrame:
    """Generate H3 grid for Hanoi."""

def map_weather_to_hex(df: pd.DataFrame, resolution: int = 8) -> pd.DataFrame:
    """Map weather data to H3 hexagons."""

# src/pipeline/nchmf_spatial_lookup.py
def get_h3_to_district_mapping() -> Dict[str, str]:
    """Generate H3 → District mapping."""

def get_district_to_zone_mapping() -> Dict[str, str]:
    """Get District → Zone mapping."""

# scripts/osm_batch_pipeline.py
def load_osm_capacity(path: str = "data/h3_osm_capacity.parquet") -> pd.DataFrame:
    """Load OSM capacity from parquet."""

def merge_osm_to_weather(weather_df: pd.DataFrame) -> pd.DataFrame:
    """Merge OSM capacity to weather DataFrame."""
```

## Performance

| Operation | Time | Notes |
|-----------|------|-------|
| H3 lookup | ~1-5 µs | Per hex |
| Full grid (1145 hexes) | ~5-10 ms | |
| OSM processing (142K ways) | ~30-60s | One-time |
| OSM parquet load | ~50 ms | Cached |
| NCHMF lookup | ~1-5 µs | 3 dict lookups |

## Files

```
scripts/
├── osm_batch_pipeline.py     # OSM batch processing pipeline
├── fetch_osm_retry.py       # Overpass API fetcher
├── process_osm_h3api.py     # H3 API processor

src/pipeline/
├── spatial_ensemble_pipeline.py  # Weather → H3 mapping
└── nchmf_spatial_lookup.py     # NCHMF O(1) lookup

data/
├── h3_osm_capacity.parquet    # OSM capacity (168 KB)
├── h3_osm_capacity.csv        # Human readable
└── h3_osm_capacity_meta.json # Metadata
```
