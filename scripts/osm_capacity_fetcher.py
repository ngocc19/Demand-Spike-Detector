"""
OSM Capacity Fetcher
====================

Load pre-computed OSM capacity data for H3 grid cells in Hanoi.
Optimized for fast loading during training.

Usage:
    # Simple load (for training)
    >>> from scripts.osm_capacity_fetcher import load_osm_capacity
    >>> df = load_osm_capacity()

    # Add to weather data (RECOMMENDED for training)
    >>> from scripts.osm_capacity_fetcher import merge_osm_to_weather
    >>> weather_df = merge_osm_to_weather(weather_df)

    # Generate static data (run once if not exists)
    >>> python scripts/osm_batch_pipeline.py --full

Output:
    data/h3_osm_capacity.parquet (fast loading, ~2100 rows)
    data/h3_osm_capacity.csv (human readable)

Pipeline Design:
    1. Batch Fetching: Call Overpass API once -> Save to Parquet
    2. Offline Loading: Load from Parquet for all subsequent training
    3. Freeze API: No more API calls needed after initial fetch
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Static data paths
STATIC_PARQUET: Path = Path("data/h3_osm_capacity.parquet")
STATIC_CSV: Path = Path("data/h3_osm_capacity.csv")


# =============================================================================
# LOADER FUNCTIONS
# =============================================================================

@lru_cache(maxsize=1)
def load_osm_capacity(path: str = str(STATIC_PARQUET)) -> pd.DataFrame:
    """
    Load pre-computed OSM capacity data from parquet file.

    Uses LRU cache for fast repeated access during training.
    Load time: ~10ms (vs minutes with Overpass API).

    Args:
        path: Path to parquet file (default: data/h3_osm_capacity.parquet)

    Returns:
        DataFrame with columns:
        - hex_id: H3 hex ID
        - osm_capacity_index: Normalized capacity (0.01 - 1.0)
        - osm_capacity_score: Raw capacity score
        - osm_road_score: Road-only score
        - osm_infra_score: Infrastructure score
        - road_count: Number of roads in hex
        - infra_count: Number of infrastructure points
        - hex_lat, hex_lon: Hex centroid coordinates

    Raises:
        FileNotFoundError: If parquet file doesn't exist
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Static OSM data not found at {path}.\n"
            f"\n"
            f"To generate OSM data, run:\n"
            f"  python scripts/osm_batch_pipeline.py --full\n"
            f"\n"
            f"This will:\n"
            f"  1. Fetch all roads from Overpass API (one-time)\n"
            f"  2. Calculate capacity for each H3 hex\n"
            f"  3. Save to Parquet for fast loading\n"
            f"\n"
            f"After that, you only need to call merge_osm_to_weather() in training."
        )

    df = pd.read_parquet(path)
    logger.info(f"Loaded OSM capacity: {len(df)} hexes from {path}")
    logger.info(f"Capacity range: [{df['osm_capacity_index'].min():.4f}, {df['osm_capacity_index'].max():.4f}]")

    return df


def get_hex_capacity(hex_id: str, df: Optional[pd.DataFrame] = None) -> float:
    """
    Get capacity index for a specific H3 hex.

    Args:
        hex_id: H3 hex ID
        df: Optional pre-loaded DataFrame (for repeated queries)

    Returns:
        Capacity index (0.01 - 1.0), default 0.01 if not found
    """
    if df is None:
        df = load_osm_capacity()

    row = df[df['hex_id'] == hex_id]

    if len(row) == 0:
        logger.warning(f"Hex {hex_id} not found, returning default 0.01")
        return 0.01

    return float(row['osm_capacity_index'].iloc[0])


def merge_osm_to_weather(weather_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge OSM capacity data to weather DataFrame.

    This is the MAIN FUNCTION to use in training pipeline.
    Adds static road infrastructure features to each H3 cell.

    Args:
        weather_df: Weather DataFrame with 'h3_index' column

    Returns:
        DataFrame with OSM capacity features added:
        - osm_capacity_index: Normalized capacity (0.01 - 1.0)
        - osm_capacity_score: Raw capacity score
        - osm_road_score: Road contribution
        - osm_infra_score: Infrastructure contribution
        - road_count: Number of roads
        - infra_count: Number of infrastructure points
    """
    osm_df = load_osm_capacity()

    # Rename for merge
    osm_df = osm_df.rename(columns={'hex_id': 'h3_index'})

    # Merge on h3_index
    merged = weather_df.merge(
        osm_df[['h3_index', 'osm_capacity_index', 'osm_capacity_score',
                'osm_road_score', 'osm_infra_score', 'road_count', 'infra_count']],
        on='h3_index',
        how='left'
    )

    # Fill missing with defaults
    merged['osm_capacity_index'] = merged['osm_capacity_index'].fillna(0.01)
    merged['osm_capacity_score'] = merged['osm_capacity_score'].fillna(0)
    merged['osm_road_score'] = merged['osm_road_score'].fillna(0)
    merged['osm_infra_score'] = merged['osm_infra_score'].fillna(0)
    merged['road_count'] = merged['road_count'].fillna(0).astype(int)
    merged['infra_count'] = merged['infra_count'].fillna(0).astype(int)

    logger.info(f"Merged OSM capacity: {len(merged)} rows")

    return merged


def get_osm_features_summary() -> dict:
    """
    Get summary of OSM capacity features.

    Returns:
        Dictionary with feature descriptions and statistics
    """
    df = load_osm_capacity()

    return {
        'total_hexes': len(df),
        'capacity_stats': {
            'min': float(df['osm_capacity_index'].min()),
            'max': float(df['osm_capacity_index'].max()),
            'mean': float(df['osm_capacity_index'].mean()),
            'median': float(df['osm_capacity_index'].median()),
        },
        'road_stats': {
            'total_roads': int(df['road_count'].sum()),
            'avg_per_hex': float(df['road_count'].mean()),
        },
        'columns': list(df.columns),
    }


def verify_coverage(weather_df: pd.DataFrame) -> dict:
    """
    Verify OSM coverage against weather data.

    Args:
        weather_df: Weather DataFrame with 'h3_index' column

    Returns:
        Dictionary with coverage statistics
    """
    osm_df = load_osm_capacity()

    weather_hexes = set(weather_df['h3_index'].unique())
    osm_hexes = set(osm_df['hex_id'].unique())

    missing = weather_hexes - osm_hexes

    return {
        'weather_hexes': len(weather_hexes),
        'osm_hexes': len(osm_hexes),
        'missing_hexes': len(missing),
        'coverage_pct': (len(weather_hexes) - len(missing)) / len(weather_hexes) * 100 if weather_hexes else 100,
        'missing_list': list(missing)[:10] if missing else [],
    }


# =============================================================================
# STANDALONE FUNCTION
# =============================================================================

def fetch_osm_capacity(use_static: bool = True) -> pd.DataFrame:
    """
    Convenience function to load OSM capacity data.

    Args:
        use_static: Use static data (default: True)

    Returns:
        DataFrame with hex_id and osm_capacity_index
    """
    return load_osm_capacity()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Load OSM capacity data for Hanoi H3 grid"
    )
    parser.add_argument(
        '--csv',
        action='store_true',
        help='Load from CSV instead of parquet'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Show feature summary'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify coverage against weather data'
    )

    args = parser.parse_args()

    if args.csv:
        path = STATIC_CSV
    else:
        path = STATIC_PARQUET

    if args.summary:
        summary = get_osm_features_summary()
        print("=" * 60)
        print("OSM CAPACITY FEATURES SUMMARY")
        print("=" * 60)
        print(f"Total H3 hexes: {summary['total_hexes']}")
        print(f"\nCapacity Index:")
        for k, v in summary['capacity_stats'].items():
            print(f"  {k}: {v:.4f}")
        print(f"\nRoad Statistics:")
        for k, v in summary['road_stats'].items():
            print(f"  {k}: {v}")
        print(f"\nColumns: {summary['columns']}")

    elif args.verify:
        from pathlib import Path
        weather_path = Path("data/weather_anchors_30T_merged.parquet")

        if weather_path.exists():
            weather_df = pd.read_parquet(weather_path)
            coverage = verify_coverage(weather_df)

            print("=" * 60)
            print("COVERAGE VERIFICATION")
            print("=" * 60)
            print(f"Weather hexes: {coverage['weather_hexes']}")
            print(f"OSM hexes: {coverage['osm_hexes']}")
            print(f"Missing hexes: {coverage['missing_hexes']}")
            print(f"Coverage: {coverage['coverage_pct']:.1f}%")

            if coverage['missing_list']:
                print("\nFirst 10 missing hexes:")
                for hex_id in coverage['missing_list']:
                    print(f"  - {hex_id}")
        else:
            print(f"Weather data not found: {weather_path}")

    else:
        try:
            df = load_osm_capacity(str(path))
            print("\n" + "=" * 60)
            print("OSM CAPACITY DATA")
            print("=" * 60)
            print(df.head(10).to_string(index=False))
            print(f"\nTotal: {len(df)} hexes")

            print("\n" + "=" * 60)
            print("USAGE IN TRAINING:")
            print("=" * 60)
            print("""
from scripts.osm_capacity_fetcher import merge_osm_to_weather

# Load weather data
weather_df = pd.read_parquet('data/weather_anchors_30T_merged.parquet')

# Add OSM capacity features
weather_df = merge_osm_to_weather(weather_df)

# Now weather_df has new columns:
# - osm_capacity_index (0.01 - 1.0)
# - osm_capacity_score
# - osm_road_score
# - osm_infra_score
# - road_count
# - infra_count
""")

        except FileNotFoundError as e:
            print(f"\nError: {e}")
            print("\nTo generate static data, run:")
            print("  python scripts/osm_batch_pipeline.py --full")
