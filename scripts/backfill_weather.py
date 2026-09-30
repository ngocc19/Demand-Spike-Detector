"""
Weather Backfill Script - Incremental với Append After Each Call
=============================================================

Chiến lược:
- 1 location = 3 calls (mỗi call < 1000 records)
- Sau mỗi call thành công → APPEND vào parquet file
- Quota hết → Thêm key mới → Chạy lại → Tiếp tục từ điểm dừng

Date range: 29/06/2026 → 28/09/2026 (92 ngày)

Usage:
    python scripts/backfill_weather.py              # Tiếp tục fetch
    python scripts/backfill_weather.py --reset    # Reset và chạy lại từ đầu
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from extractor import VCWExtractor
from processor import WeatherProcessor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('data/backfill.log', encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger(__name__)

DEFAULT_ANCHORS = [
    {"name": "HoanKiem", "lat": 21.0285, "lon": 105.8542},
    {"name": "CauGiay", "lat": 21.0306, "lon": 105.7925},
    {"name": "HoangMai", "lat": 20.9723, "lon": 105.8454},
    {"name": "LongBien", "lat": 21.0470, "lon": 105.8920},
    {"name": "TayHo", "lat": 21.0664, "lon": 105.8176},
    {"name": "NoiBai", "lat": 21.2187, "lon": 105.8042},
]


def get_api_keys() -> list:
    """Get all API keys from environment."""
    keys = []
    for i in range(1, 11):
        suffix = f"_{i}" if i > 1 else ""
        key = os.getenv(f'VISUALCROSSING_API_KEY{suffix}')
        if key and key.strip():
            keys.append(key)
    if not keys:
        raise ValueError("No API key found!")
    return keys


def add_h3_and_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Add H3 index and metadata."""
    import h3

    df['h3_index'] = df.apply(
        lambda row: h3.latlng_to_cell(row['anchor_lat'], row['anchor_lon'], 8), axis=1
    )

    region_map = {
        'HoanKiem': 'center', 'CauGiay': 'west', 'HoangMai': 'south',
        'LongBien': 'east', 'TayHo': 'north', 'NoiBai': 'airport'
    }
    df['region'] = df['anchor_name'].map(region_map)

    df['fetch_date'] = datetime.now().strftime('%Y-%m-%d')
    df['fetch_timestamp'] = datetime.now().isoformat()
    df['data_version'] = '1.0'
    df['source'] = 'VCW'

    return df


def load_existing(output_path: Path) -> pd.DataFrame:
    """Load existing parquet file."""
    if output_path.exists():
        df = pd.read_parquet(output_path)
        logger.info(f"Loaded existing: {len(df)} records, anchors: {df['anchor_name'].unique().tolist()}")
        return df
    return pd.DataFrame()


def append_and_save(df: pd.DataFrame, output_path: Path, existing_df: pd.DataFrame):
    """Append new data to existing and save."""
    if existing_df.empty:
        combined = df
    else:
        combined = pd.concat([existing_df, df], ignore_index=True)

    combined.to_parquet(output_path, index=False)
    return combined


def get_progress(existing_df: pd.DataFrame) -> tuple:
    """Get current progress: completed anchors and next anchor to fetch."""
    if existing_df.empty:
        return set(), DEFAULT_ANCHORS

    completed = set(existing_df['anchor_name'].unique())
    remaining = [a for a in DEFAULT_ANCHORS if a['name'] not in completed]

    return completed, remaining


def main():
    parser = argparse.ArgumentParser(description='Weather Backfill - Incremental')
    parser.add_argument('--reset', action='store_true', help='Reset all data')
    parser.add_argument('--output', default='data/weather_anchors_30T.parquet')
    args = parser.parse_args()

    os.makedirs('data', exist_ok=True)
    output_path = Path(args.output)

    logger.info("\n" + "="*70)
    logger.info("WEATHER BACKFILL - INCREMENTAL (Append after each call)")
    logger.info("="*70)

    api_keys = get_api_keys()
    logger.info(f"API Keys available: {len(api_keys)}")

    if args.reset:
        logger.info("RESET MODE: Deleting existing data...")
        if output_path.exists():
            os.remove(output_path)
        existing_df = pd.DataFrame()
    else:
        existing_df = load_existing(output_path)

    completed, remaining = get_progress(existing_df)

    if not remaining:
        logger.info("All locations completed!")
        return 0

    logger.info(f"Completed: {sorted(completed)}")
    logger.info(f"Remaining: {[a['name'] for a in remaining]}")

    # Initialize
    extractor = VCWExtractor(api_keys)
    processor = WeatherProcessor()

    # Fetch each remaining anchor
    for anchor in remaining:
        anchor_name = anchor['name']
        lat, lon = anchor['lat'], anchor['lon']

        logger.info(f"\n>>> FETCHING: {anchor_name}")

        # Try each date split
        for i, (start_date, end_date) in enumerate(extractor.DATE_SPLITS):
            logger.info(f"  [{i+1}/3] {start_date} → {end_date}")

            df = extractor.fetch_single_call(lat, lon, start_date, end_date)

            if df is not None and not df.empty:
                df['anchor_name'] = anchor_name
                df['anchor_lat'] = lat
                df['anchor_lon'] = lon

                # Process
                processed = processor.process_pipeline(df, add_owm=True, add_blended=True)
                processed = add_h3_and_metadata(processed)

                # APPEND NGAY SAU CALL THÀNH CÔNG
                combined = append_and_save(processed, output_path, existing_df)
                existing_df = combined

                logger.info(f"  ✓ Appended: Total {len(combined)} records")
            else:
                logger.warning(f"  ✗ Failed - Quota may be exhausted")
                logger.info(f">>> Add more keys and run again to continue")
                return 1

    # Final
    logger.info("\n" + "="*70)
    logger.info("ALL DONE!")
    logger.info("="*70)

    final_df = load_existing(output_path)
    logger.info(f"Total records: {len(final_df)}")
    logger.info(f"Anchors: {final_df['anchor_name'].unique().tolist()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
