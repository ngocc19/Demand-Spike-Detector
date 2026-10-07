"""
OSM Batch Fetching Pipeline
==========================

ONE-TIME API CALL -> PARQUET STORAGE -> OFFLINE MULTI-USE

Pipeline Design:
1. Batch Fetching: Call Overpass API once -> Save to Parquet
2. Offline Loading: Load from Parquet for all subsequent training
3. Freeze API: No more API calls needed after initial fetch

Usage:
    # Step 1: Fetch real OSM data (run once - may take 1-2 minutes)
    >>> python scripts/osm_batch_pipeline.py --fetch

    # Step 2: Process to parquet
    >>> python scripts/osm_batch_pipeline.py --process

    # Step 3: Verify coverage
    >>> python scripts/osm_batch_pipeline.py --verify

    # Or run all at once
    >>> python scripts/osm_batch_pipeline.py --full

    # Load for training (run many times)
    >>> python scripts/osm_batch_pipeline.py --load

Output:
    data/h3_osm_capacity.parquet (fast loading, ~4000 rows)
    data/h3_osm_capacity.csv (human readable)
    data/h3_osm_capacity_meta.json (metadata)
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import h3
import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
PARQUET_PATH = Path("data/h3_osm_capacity.parquet")
CSV_PATH = Path("data/h3_osm_capacity.csv")
META_PATH = Path("data/h3_osm_capacity_meta.json")
WEATHER_DATA_PATH = Path("data/weather_anchors_30T_merged.parquet")


# =============================================================================
# LOADER FUNCTIONS (FOR TRAINING)
# =============================================================================

@lru_cache(maxsize=1)
def load_osm_capacity(path: str = str(PARQUET_PATH)) -> pd.DataFrame:
    """
    Load OSM capacity from parquet with caching.
    THIS IS THE MAIN FUNCTION TO USE IN TRAINING CODE.

    Usage:
        from scripts.osm_batch_pipeline import load_osm_capacity
        osm_df = load_osm_capacity()
    """
    if not Path(path).exists():
        raise FileNotFoundError(
            f"Static OSM data not found at {path}.\n"
            f"\n"
            f"Run 'python scripts/osm_batch_pipeline.py --full' to generate it.\n"
        )

    df = pd.read_parquet(path)
    logger.info(f"Loaded {len(df)} hexes from {path}")

    return df


def merge_osm_to_weather(weather_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge OSM capacity to weather DataFrame.
    THIS IS THE MAIN FUNCTION TO USE IN TRAINING PIPELINE.

    Usage:
        from scripts.osm_batch_pipeline import merge_osm_to_weather

        # Load weather
        weather_df = pd.read_parquet('data/weather_anchors_30T_merged.parquet')

        # Add OSM capacity features
        weather_df = merge_osm_to_weather(weather_df)

        # Ready for training!
    """
    osm_df = load_osm_capacity()
    osm_df = osm_df.rename(columns={'hex_id': 'h3_index'})

    merged = weather_df.merge(
        osm_df[['h3_index', 'osm_capacity_index', 'osm_capacity_score',
                'osm_road_score', 'osm_infra_score', 'road_count', 'infra_count']],
        on='h3_index',
        how='left'
    )

    # Fill missing
    merged['osm_capacity_index'] = merged['osm_capacity_index'].fillna(0.01)
    merged['osm_capacity_score'] = merged['osm_capacity_score'].fillna(0)
    merged['osm_road_score'] = merged['osm_road_score'].fillna(0)
    merged['osm_infra_score'] = merged['osm_infra_score'].fillna(0)
    merged['road_count'] = merged['road_count'].fillna(0).astype(int)
    merged['infra_count'] = merged['infra_count'].fillna(0).astype(int)

    return merged


# =============================================================================
# VERIFY COVERAGE
# =============================================================================

def verify_coverage() -> bool:
    """Verify OSM hexes cover all weather data hexes."""
    logger.info("=" * 70)
    logger.info("COVERAGE VERIFICATION")
    logger.info("=" * 70)

    if not WEATHER_DATA_PATH.exists():
        logger.warning(f"Weather data not found: {WEATHER_DATA_PATH}")
        return True

    weather_df = pd.read_parquet(WEATHER_DATA_PATH)
    weather_hexes = set(weather_df['h3_index'].dropna().unique())
    logger.info(f"Weather hexes: {len(weather_hexes)}")

    if not PARQUET_PATH.exists():
        logger.error(f"OSM data not found: {PARQUET_PATH}")
        return False

    osm_df = load_osm_capacity()
    osm_hexes = set(osm_df['hex_id'].unique())
    logger.info(f"OSM hexes: {len(osm_hexes)}")

    missing = weather_hexes - osm_hexes

    if missing:
        logger.warning(f"MISSING: {len(missing)} hexes not covered!")
        for h in missing:
            logger.warning(f"  - {h}")
        return False
    else:
        logger.info("FULL COVERAGE: All weather hexes have OSM data!")
        return True


# =============================================================================
# STATUS & INFO
# =============================================================================

def get_status() -> dict:
    """Get pipeline status."""
    status = {
        'parquet_exists': PARQUET_PATH.exists(),
        'csv_exists': CSV_PATH.exists(),
        'meta_exists': META_PATH.exists(),
        'weather_exists': WEATHER_DATA_PATH.exists(),
    }

    if status['meta_exists']:
        with open(META_PATH, 'r') as f:
            meta = json.load(f)
        status['meta'] = meta

    if status['parquet_exists']:
        osm_df = load_osm_capacity()
        status['total_hexes'] = len(osm_df)
        status['hexes_with_roads'] = int((osm_df['road_count'] > 0).sum())

    if status['weather_exists'] and status['parquet_exists']:
        weather_df = pd.read_parquet(WEATHER_DATA_PATH)
        weather_hexes = set(weather_df['h3_index'].dropna().unique())
        osm_hexes = set(load_osm_capacity()['hex_id'].unique())
        status['weather_hexes'] = len(weather_hexes)
        status['covered_hexes'] = len(weather_hexes & osm_hexes)
        status['coverage_pct'] = len(weather_hexes & osm_hexes) / len(weather_hexes) * 100 if weather_hexes else 100

    return status


def print_status():
    """Print pipeline status."""
    status = get_status()

    print("=" * 70)
    print("OSM BATCH PIPELINE STATUS")
    print("=" * 70)

    print("\nFiles:")
    print(f"  Parquet: {'OK' if status['parquet_exists'] else 'MISSING'}")
    print(f"  CSV:     {'OK' if status['csv_exists'] else 'MISSING'}")
    print(f"  Meta:    {'OK' if status['meta_exists'] else 'MISSING'}")

    if 'total_hexes' in status:
        print(f"\nOSM Data:")
        print(f"  Total hexes: {status['total_hexes']}")
        print(f"  Hexes with roads: {status['hexes_with_roads']}")

    if 'coverage_pct' in status:
        print(f"\nCoverage:")
        print(f"  Weather hexes: {status['weather_hexes']}")
        print(f"  Covered: {status['covered_hexes']}/{status['weather_hexes']} ({status['coverage_pct']:.1f}%)")

    if 'meta' in status:
        meta = status['meta']
        print(f"\nMetadata:")
        print(f"  Version: {meta.get('version', 'N/A')}")
        print(f"  Source: {meta.get('source', 'N/A')}")
        print(f"  Generated: {meta.get('generated_at', 'N/A')}")

    print("=" * 70)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="OSM Batch Pipeline - One-time fetch, multi-use loading",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline: Fetch + Process + Verify
  python scripts/osm_batch_pipeline.py --full

  # Fetch OSM data from Overpass API
  python scripts/osm_batch_pipeline.py --fetch

  # Process cached OSM data to parquet
  python scripts/osm_batch_pipeline.py --process

  # Verify coverage against weather data
  python scripts/osm_batch_pipeline.py --verify

  # Show status
  python scripts/osm_batch_pipeline.py --status

  # Load and display
  python scripts/osm_batch_pipeline.py --load

  # Demo: merge to weather
  python scripts/osm_batch_pipeline.py --demo
"""
    )

    parser.add_argument('--full', action='store_true', help='Full pipeline')
    parser.add_argument('--fetch', action='store_true', help='Fetch OSM data')
    parser.add_argument('--process', action='store_true', help='Process to parquet')
    parser.add_argument('--verify', action='store_true', help='Verify coverage')
    parser.add_argument('--status', action='store_true', help='Show status')
    parser.add_argument('--load', action='store_true', help='Load OSM data')
    parser.add_argument('--demo', action='store_true', help='Demo merge')

    args = parser.parse_args()

    if not any(vars(args).values()):
        args.status = True

    if args.status:
        print_status()

    elif args.full:
        import subprocess
        import sys

        print("Running full pipeline...")
        print("1. Fetching OSM data...")
        result = subprocess.run([sys.executable, 'scripts/fetch_osm_retry.py'])
        if result.returncode != 0:
            print("Fetch failed. Check if data/osm_with_geometry.json exists.")
            print("If it exists, run: python scripts/osm_batch_pipeline.py --process")

        print("\n2. Processing to parquet...")
        result = subprocess.run([sys.executable, 'scripts/process_osm_h3api.py'])

        if result.returncode == 0:
            print("\n3. Verifying coverage...")
            verify_coverage()

            print("\n" + "=" * 70)
            print("PIPELINE COMPLETE!")
            print("=" * 70)
            print("\nUsage in training:")
            print("-" * 70)
            print("""
from scripts.osm_batch_pipeline import merge_osm_to_weather

weather_df = pd.read_parquet('data/weather_anchors_30T_merged.parquet')
weather_df = merge_osm_to_weather(weather_df)
# Ready for training!
""")

    elif args.fetch:
        import subprocess
        import sys
        result = subprocess.run([sys.executable, 'scripts/fetch_osm_retry.py'])
        if result.returncode == 0:
            print("Fetch complete! Run --process to generate parquet.")

    elif args.process:
        import subprocess
        import sys
        result = subprocess.run([sys.executable, 'scripts/process_osm_h3api.py'])

    elif args.verify:
        verify_coverage()

    elif args.load:
        df = load_osm_capacity()
        print("\nOSM Capacity Data:")
        print(df.head(15).to_string(index=False))
        print(f"\nTotal: {len(df)} hexes")

    elif args.demo:
        if WEATHER_DATA_PATH.exists():
            weather_df = pd.read_parquet(WEATHER_DATA_PATH)
            merged = merge_osm_to_weather(weather_df)

            print("=" * 70)
            print("DEMO: Weather + OSM Merged")
            print("=" * 70)
            print(f"Original rows: {len(weather_df)}")
            print(f"Merged rows: {len(merged)}")
            print(f"\nNew columns:")
            new_cols = [c for c in merged.columns if c not in weather_df.columns]
            for col in new_cols:
                print(f"  - {col}")

            print(f"\nSample with OSM data:")
            sample = merged[['datetime', 'h3_index', 'osm_capacity_index', 'road_count']].drop_duplicates('h3_index')
            print(sample.head(10).to_string(index=False))
        else:
            print(f"Weather data not found: {WEATHER_DATA_PATH}")
