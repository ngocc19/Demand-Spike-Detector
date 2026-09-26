"""
Spatial Weather Ensemble Pipeline
================================

Architecture:
1. Divide Hanoi into H3 hexagons (Resolution 8/9)
2. Map HSDC stations to H3 indices
3. Query OWM/VCW/NCHMF for each hexagon
4. Run local ensemble per hexagon
5. Handle missing HSDC data via Circuit Breaker

H3 Resolution Guide:
- Res 8: ~460m edge, ~5.9km² area (good for neighborhood)
- Res 9: ~165m edge, ~0.65km² area (good for street-level)
"""

import pandas as pd
import numpy as np
import h3
from datetime import datetime
from typing import Dict, List, Tuple
import json
import requests


# ============================================================================
# SECTION 1: SPATIAL SETUP - Divide Hanoi into H3 Hexagons
# ============================================================================

def create_hanoi_hex_grid(resolution: int = 8) -> List[str]:
    """
    Create H3 hexagon grid covering Hanoi city.

    Resolution 8: ~460m edge, good for demand forecasting
    Resolution 9: ~165m edge, good for traffic routing
    """
    # Hanoi bounding box
    HANOI_BOUNDS = {
        'min_lat': 20.85,
        'max_lat': 21.15,
        'min_lng': 105.70,
        'max_lng': 105.95,
    }

    hexagons = set()

    # Generate grid of points
    lat_step = 0.005  # ~500m
    lng_step = 0.005

    lat = HANOI_BOUNDS['min_lat']
    while lat <= HANOI_BOUNDS['max_lat']:
        lng = HANOI_BOUNDS['min_lng']
        while lng <= HANOI_BOUNDS['max_lng']:
            # Create hexagon at this point
            try:
                hex_id = h3.latlng_to_cell(lat, lng, resolution)
                hexagons.add(hex_id)
            except:
                pass
            lng += lng_step
        lat += lat_step

    return list(hexagons)


def get_hexagon_centroid(h3_index: str) -> Tuple[float, float]:
    """Get centroid coordinates of a hexagon."""
    boundary = h3.cell_to_boundary(h3_index)
    lats = [p[0] for p in boundary]
    lngs = [p[1] for p in boundary]
    return (np.mean(lats), np.mean(lngs))


# ============================================================================
# SECTION 2: HSDC STATION MAPPING
# ============================================================================

def map_hsdc_stations_to_hex(hsdc_data: pd.DataFrame, resolution: int = 8) -> pd.DataFrame:
    """
    Map HSDC rainfall stations to H3 hexagons.

    Input: HSDC data with 'latitude' and 'longitude' columns
    Output: DataFrame with added 'h3_index' column
    """
    if hsdc_data.empty:
        return hsdc_data

    hsdc_data = hsdc_data.copy()

    # Convert each station to H3 index
    hsdc_data['h3_index'] = hsdc_data.apply(
        lambda row: h3.latlng_to_cell(
            row['latitude'],
            row['longitude'],
            resolution
        ) if pd.notna(row.get('latitude')) and pd.notna(row.get('longitude')) else None,
        axis=1
    )

    return hsdc_data


def aggregate_hsdc_by_hex(hsdc_mapped: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate HSDC data by hexagon using MAX value.

    Multiple stations in same hexagon -> use MAX (safe for routing)
    Missing stations -> hexagon gets NaN (Circuit Breaker handles this)
    """
    if hsdc_mapped.empty:
        return pd.DataFrame()

    # Filter valid hexagons
    valid_data = hsdc_mapped[hsdc_mapped['h3_index'].notna()].copy()

    if valid_data.empty:
        return pd.DataFrame()

    # Build aggregation dict dynamically based on available columns
    agg_dict = {
        'rainfall_current_mm': 'max',  # MAX for safety
        'station_name': 'first',  # Keep one station name
    }

    # Add rainfall_total_mm if it exists
    if 'rainfall_total_mm' in valid_data.columns:
        agg_dict['rainfall_total_mm'] = 'max'

    # Aggregate by hexagon
    aggregated = valid_data.groupby('h3_index').agg(agg_dict).reset_index()

    aggregated['has_hsdc_data'] = True

    return aggregated


# ============================================================================
# SECTION 3: H3 LOOKUP TABLE - Station -> Hexagon
# ============================================================================

def create_hex_station_lookup(aggregated_hsdc: pd.DataFrame) -> Dict[str, str]:
    """
    Create lookup: h3_index -> station_name
    Used for Circuit Breaker logic.
    """
    if aggregated_hsdc.empty:
        return {}

    return dict(zip(
        aggregated_hsdc['h3_index'],
        aggregated_hsdc['station_name']
    ))


# ============================================================================
# SECTION 4: LOCAL ENSEMBLE PER HEXAGON
# ============================================================================

def query_owm_for_hex(lat: float, lng: float, api_key: str = None) -> Dict:
    """Query OpenWeatherMap for a specific location."""
    # This is a simplified version - implement actual API call
    return {
        'temp_c': 30.0,  # Placeholder
        'rainfall_mm': 0.0,
        'humidity': 75.0,
    }


def query_vcw_for_hex(lat: float, lng: float, api_key: str = None) -> Dict:
    """Query Visual Crossing for a specific location."""
    return {
        'temp_c': 30.0,
        'rainfall_mm': 0.0,
        'humidity': 75.0,
    }


def get_nchmf_for_hex(h3_index: str) -> Dict:
    """
    Get NCHMF data for a hexagon using O(1) lookup.

    Uses pre-computed static mappings:
    - h3_index → district (from nchmf_spatial_lookup)
    - district → zone (from nchmf_spatial_lookup)
    - zone → NCHMF warning (from cache)

    Returns:
        {
            'zone': 'NoiThanh',
            'district': 'CauGiay',
            'storm_prob': 0.9,
            'heavy_rain_prob': 0.5,
            'flood_prob': 0.3,
            'has_nchmf_data': True,
        }
    """
    # Lazy import to avoid circular dependency
    from src.pipeline.nchmf_spatial_lookup import get_nchmf_for_hex as get_nchmf_lookup

    return get_nchmf_lookup(h3_index)


def run_local_ensemble(
    h3_index: str,
    hsdc_lookup: Dict[str, str],
    config: 'EnsembleConfig',
) -> Dict:
    """
    Run WeatherEnsembleAggregator for ONE hexagon.

    This is the core function that:
    1. Gets data from all sources for this hexagon
    2. Runs local ensemble (not global!)
    3. Returns ensemble results

    Returns dict with:
    - h3_index, lat, lng
    - ensemble_rainfall (continuous)
    - ensemble_storm_prob (classification)
    - source_weights
    - metadata
    """
    from src.pipeline.weather_ensemble import WeatherEnsembleAggregator, EnsembleConfig

    lat, lng = get_hexagon_centroid(h3_index)

    # Get data from each source (placeholders - implement actual API calls)

    # OWM - query at centroid
    owm_data = query_owm_for_hex(lat, lng)

    # VCW - query at centroid
    vcw_data = query_vcw_for_hex(lat, lng)

    # HSDC - check if this hex has HSDC station
    has_hsdc = h3_index in hsdc_lookup
    if has_hsdc:
        # In real implementation, get from aggregated HSDC data
        hsdc_rainfall = 0.0  # From hsdc_aggregated lookup
    else:
        hsdc_rainfall = None  # No data - Circuit Breaker

    # NCHMF - O(1) lookup using pre-computed mappings
    nchmf_data = get_nchmf_for_hex(h3_index)

    # ============================================================
    # CONTINUOUS ENSEMBLE: Rainfall
    # ============================================================

    rainfall_values = {
        'OWM': owm_data.get('rainfall_mm', 0.0) or 0.0,
        'VCW': vcw_data.get('rainfall_mm', 0.0) or 0.0,
        'HSDC': hsdc_rainfall if has_hsdc else 0.0,
        'NCHMF': nchmf_data.get('heavy_rain_prob', 0.0) * 50,  # Scale to mm
    }

    source_status = {
        'OWM': 1,  # Always available
        'VCW': 1,  # Always available
        'HSDC': 1 if has_hsdc else 0,  # Circuit Breaker!
        'NCHMF': 1,
    }

    aggregator = WeatherEnsembleAggregator(config)

    rainfall_result = aggregator.ensemble_continuous(
        variable_name='rainfall',
        source_values=rainfall_values,
        source_status=source_status,
    )

    # ============================================================
    # CLASSIFICATION ENSEMBLE: Storm/Extreme Weather
    # ============================================================

    # NCHMF is the primary source for storm warnings
    storm_values = {
        'OWM': 1.0 if owm_data.get('weather_code', 0) >= 200 else 0.0,
        'VCW': 1.0 if 'thunderstorm' in vcw_data.get('conditions', '').lower() else 0.0,
        'HSDC': 0.0,  # HSDC doesn't have storm data
        'NCHMF': nchmf_data.get('storm_prob', 0.0),
    }

    storm_status = {
        'OWM': 1,
        'VCW': 1,
        'HSDC': 1,  # No storm data = 0 contribution anyway
        'NCHMF': 1,
    }

    storm_result = aggregator.ensemble_classification(
        variable_name='storm',
        source_values=storm_values,
        source_status=storm_status,
    )

    # ============================================================
    # BUILD RESULT
    # ============================================================

    return {
        'h3_index': h3_index,
        'latitude': lat,
        'longitude': lng,
        'zone': nchmf_data.get('zone'),
        'district': nchmf_data.get('district'),
        'ensemble_rainfall': rainfall_result.ensemble_value,
        'ensemble_storm_prob': storm_result.ensemble_value,
        'has_hsdc_station': has_hsdc,
        'hsdc_station': hsdc_lookup.get(h3_index),
        'source_weights_rainfall': rainfall_result.source_weights,
        'source_weights_storm': storm_result.source_weights,
        'active_sources_rainfall': rainfall_result.active_sources_count,
        'active_sources_storm': storm_result.active_sources_count,
    }


# ============================================================================
# SECTION 5: MAIN PIPELINE - Spatial Ensemble
# ============================================================================

def run_spatial_weather_ensemble(
    hsdc_data: pd.DataFrame,
    resolution: int = 8,
    config = None
) -> pd.DataFrame:
    """
    Main pipeline for spatial weather ensemble.

    Steps:
    1. Create H3 hex grid for Hanoi
    2. Map HSDC stations to hexagons
    3. Aggregate HSDC by hexagon (MAX)
    4. For each hexagon, run local ensemble
    5. Return DataFrame with results per hexagon
    """
    from src.pipeline.weather_ensemble import EnsembleConfig

    if config is None:
        config = EnsembleConfig(lambda_decay=0.1)

    print(f"Step 1: Creating H3 hex grid (resolution {resolution})...")
    hexagons = create_hanoi_hex_grid(resolution)
    print(f"  Generated {len(hexagons)} hexagons")

    print(f"Step 2: Mapping HSDC stations to hexagons...")
    hsdc_mapped = map_hsdc_stations_to_hex(hsdc_data, resolution)
    print(f"  Mapped {len(hsdc_mapped)} stations")

    print(f"Step 3: Aggregating HSDC by hexagon (MAX)...")
    hsdc_aggregated = aggregate_hsdc_by_hex(hsdc_mapped)
    print(f"  {len(hsdc_aggregated)} hexagons have HSDC data")

    # Create lookup for quick HSDC availability check
    hsdc_lookup = create_hex_station_lookup(hsdc_aggregated)
    print(f"  HSDC lookup table created")

    print(f"Step 4: Running local ensemble per hexagon...")
    results = []

    for i, h3_index in enumerate(hexagons):
        if i % 50 == 0:
            print(f"  Processing hexagon {i+1}/{len(hexagons)}...")

        result = run_local_ensemble(
            h3_index=h3_index,
            hsdc_lookup=hsdc_lookup,
            config=config,
            district_mapping={},  # Would need proper district mapping
        )
        results.append(result)

    print(f"Step 5: Compiling results...")
    results_df = pd.DataFrame(results)

    # Add metadata
    results_df['pipeline_timestamp'] = datetime.now()

    return results_df


# ============================================================================
# SECTION 6: DEMONSTRATION
# ============================================================================

def demo_spatial_ensemble():
    """
    Demo: Show spatial mapping of HSDC stations to H3 hexagons.
    """
    print("=" * 70)
    print("SPATIAL WEATHER ENSEMBLE DEMO")
    print("=" * 70)
    print()

    # Simulate HSDC data
    hsdc_stations = [
        {'name': 'Hoàn Kiếm', 'lat': 21.0283, 'lng': 105.8542, 'rainfall': 15.0},
        {'name': 'Cầu Giấy', 'lat': 21.0333, 'lng': 105.7833, 'rainfall': 22.0},
        {'name': 'Thanh Xuân', 'lat': 21.0055, 'lng': 105.8120, 'rainfall': 8.0},
        {'name': 'Tây Hồ', 'lat': 21.0533, 'lng': 105.7833, 'rainfall': 30.0},
        {'name': 'Hoàng Mai', 'lat': 20.9833, 'lng': 105.8500, 'rainfall': 5.0},
    ]

    hsdc_df = pd.DataFrame(hsdc_stations)
    hsdc_df.columns = ['station_name', 'latitude', 'longitude', 'rainfall_current_mm']

    print("HSDC Stations Input:")
    print(hsdc_df)
    print()

    # Map to H3
    resolution = 8
    hsdc_mapped = map_hsdc_stations_to_hex(hsdc_df, resolution)

    print(f"HSDC Stations Mapped to H3 (Resolution {resolution}):")
    for _, row in hsdc_mapped.iterrows():
        lat, lng = get_hexagon_centroid(row['h3_index'])
        print(f"  {row['station_name']}: ({row['latitude']:.4f}, {row['longitude']:.4f})")
        print(f"    → H3 Index: {row['h3_index']}")
        print(f"    → Centroid: ({lat:.4f}, {lng:.4f})")
        print(f"    → Rainfall: {row['rainfall_current_mm']}mm")
        print()

    # Aggregate by hex
    hsdc_aggregated = aggregate_hsdc_by_hex(hsdc_mapped)

    print("Aggregated by Hexagon (MAX rainfall):")
    print(hsdc_aggregated)
    print()

    # Create lookup
    hsdc_lookup = create_hex_station_lookup(hsdc_aggregated)

    print("HSDC Lookup Table (hex → station):")
    for h3_idx, station in hsdc_lookup.items():
        print(f"  {h3_idx} → {station}")
    print()

    # Demo: Check a few hexagons
    print("Circuit Breaker Demo:")
    test_hexes = list(hsdc_lookup.keys())[:2] + ['8928308280fffff']  # One with, one without HSDC

    for h3_idx in test_hexes:
        has_hsdc = h3_idx in hsdc_lookup
        status = 1 if has_hsdc else 0
        print(f"  {h3_idx}: S_HSDC = {status} ({'✓ Has station' if has_hsdc else '✗ No station - Circuit Breaker'})")
    print()

    # Show complete flow
    print("=" * 70)
    print("COMPLETE DATA FLOW")
    print("=" * 70)
    print("""
    ┌─────────────────────────────────────────────────────────────────┐
    │                    SPATIAL ENSEMBLE PIPELINE                    │
    ├─────────────────────────────────────────────────────────────────┤
    │                                                                  │
    │  1. HSDC API (48 stations)                                       │
    │     ↓                                                            │
    │  2. Map stations → H3 Index (Res 8)                             │
    │     ↓                                                            │
    │  3. groupby('h3_index').max() → Aggregated rainfall             │
    │     ↓                                                            │
    │  4. Create lookup: h3_index → has_HSDC_data                     │
    │     ↓                                                            │
    │  5. FOR EACH hexagon in Hanoi grid:                             │
    │     ├── Get OWM data (centroid)                                │
    │     ├── Get VCW data (centroid)                                │
    │     ├── Get HSDC data (if has station) else None               │
    │     ├── Get NCHMF data (district)                              │
    │     │                                                            │
    │     └── WeatherEnsembleAggregator:                              │
    │         ├── Calculate weights (MAE/F1)                          │
    │         ├── Apply Time-Decay                                   │
    │         ├── Circuit Breaker (S_HSDC = 0 if no station)          │
    │         └── Output: Y_final per hexagon                        │
    │     ↓                                                            │
    │  6. DataFrame: h3_index, Y_final, weights, metadata             │
    │     ↓                                                            │
    │  7. Input to Demand Spike Detector Model                        │
    │                                                                  │
    └─────────────────────────────────────────────────────────────────┘
    """)


if __name__ == '__main__':
    demo_spatial_ensemble()
