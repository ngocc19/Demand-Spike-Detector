"""
Backfill với 8 API Keys
========================

Script này dùng 8 API keys để crawl dữ liệu quá khứ:
- HoanKiem: Call 2, 3 (2 calls còn lại)
- HoangMai: Call 1, 2, 3 (3 calls)
- LongBien: Call 1, 2, 3 (3 calls)
- TayHo: Call 1, 2, 3 (3 calls)
- NoiBai: Call 1, 2, 3 (3 calls)

Tổng: 14 calls

1 API key (Key 9) được GIỮ LẠI cho realtime crawler.

Usage:
    python scripts/backfill_with_8keys.py

Chiến lược:
- Mỗi call sử dụng 1 API key riêng (1000 records/call)
- Append sau mỗi call thành công
- Resume được nếu bị interrupt
"""

import os
import sys
import time
import requests
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

# Setup path
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from processor import WeatherProcessor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('data/backfill_8keys.log', encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# CẤU HÌNH
# =============================================================================

# 8 API Keys cho backfill (Keys 1-8)
BACKFILL_KEYS = []
for i in range(1, 9):
    key = os.getenv(f'VISUALCROSSING_API_KEY_{i}')
    if key and key.strip():
        BACKFILL_KEYS.append((i, key))

# 1 API Key cho realtime (GIỮ LẠI - Key 9)
REALTIME_KEY = os.getenv('VISUALCROSSING_API_KEY_9', '').strip()

logger.info(f"\n{'='*70}")
logger.info(f"BACKFILL VỚI 8 API KEYS")
logger.info(f"{'='*70}")
logger.info(f"Keys cho backfill (1-8): {len(BACKFILL_KEYS)} keys")
logger.info(f"Key giữ lại cho realtime (Key 9): {'✓ CÓ' if REALTIME_KEY else '✗ KHÔNG CÓ'}")
logger.info(f"{'='*70}\n")

if len(BACKFILL_KEYS) < 7:
    logger.error(f"Cần ít nhất 7 keys cho backfill! Hiện có: {len(BACKFILL_KEYS)}")
    sys.exit(1)
elif len(BACKFILL_KEYS) < 8:
    logger.warning(f"Chỉ có {len(BACKFILL_KEYS)} keys cho backfill. Sẽ round-robin.")

# Date splits cho 92 ngày (29/06 → 28/09)
DATE_SPLITS = [
    ("2026-06-29", "2026-08-08"),  # Call 1: 41 days = 984 records
    ("2026-08-09", "2026-09-18"),  # Call 2: 41 days = 984 records
    ("2026-09-19", "2026-09-28"),  # Call 3: 10 days = 240 records
]

# 6 Anchor Points cho Ha Noi
ANCHORS = [
    {"name": "HoanKiem", "lat": 21.0285, "lon": 105.8542},
    {"name": "CauGiay", "lat": 21.0306, "lon": 105.7925},
    {"name": "HoangMai", "lat": 20.9723, "lon": 105.8454},
    {"name": "LongBien", "lat": 21.0470, "lon": 105.8920},
    {"name": "TayHo", "lat": 21.0664, "lon": 105.8176},
    {"name": "NoiBai", "lat": 21.2187, "lon": 105.8042},
]

BASE_URL = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
OUTPUT_PATH = Path("data/weather_anchors_30T.parquet")

# =============================================================================
# LOAD DỮ LIỆU HIỆN CÓ
# =============================================================================

def load_existing() -> Tuple[pd.DataFrame, set]:
    """Load existing parquet và trả về completed anchors."""
    if OUTPUT_PATH.exists():
        df = pd.read_parquet(OUTPUT_PATH)
        completed = set(df['anchor_name'].unique())
        logger.info(f"Loaded existing: {len(df)} records, anchors: {sorted(completed)}")
        return df, completed
    return pd.DataFrame(), set()


def get_remaining_calls(anchor_name: str, existing_df: pd.DataFrame) -> List[int]:
    """
    Xác định các call còn cần fetch cho 1 anchor.
    """
    if anchor_name not in existing_df['anchor_name'].values:
        # Chưa có data -> cần fetch tất cả 3 calls
        return [0, 1, 2]

    # Đếm số records hiện có cho anchor này
    anchor_records = existing_df[existing_df['anchor_name'] == anchor_name]
    record_count = len(anchor_records)

    # Rough estimate: mỗi call ~1000 records
    calls_completed = record_count // 1000

    if calls_completed >= 3:
        return []  # Hoàn thành
    else:
        return list(range(calls_completed, 3))  # Cần fetch từ call tiếp theo


# =============================================================================
# API CALL
# =============================================================================

def fetch_single_call(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    initial_key_index: int,
    initial_key_value: str
) -> Optional[pd.DataFrame]:
    """
    Gọi API với retry logic - thử tất cả keys khác nếu bị rate limit.
    """
    # Thử tất cả keys, bắt đầu từ key được chỉ định
    keys_to_try = []

    # Thêm key ban đầu
    keys_to_try.append((initial_key_index, initial_key_value))

    # Thêm các keys còn lại
    for idx, (k_idx, k_val) in enumerate(BACKFILL_KEYS):
        if k_idx != initial_key_index:
            keys_to_try.append((k_idx, k_val))

    for key_index, key_value in keys_to_try:
        location = f"{lat},{lon}"
        url = f"{BASE_URL}/{location}/{start_date}/{end_date}"

        params = {
            "unitGroup": "metric",
            "include": "hours",
            "key": key_value,
            "contentType": "json",
        }

        try:
            logger.info(f"  [Key {key_index}] Calling API: {start_date} → {end_date}")
            response = requests.get(url, params=params, timeout=60)

            if response.status_code == 429:
                logger.warning(f"  [Key {key_index}] 429 Rate Limit - thu key khac...")
                time.sleep(1)  # Đợi 1 giây trước khi thử key khác
                continue

            response.raise_for_status()
            data = response.json()

            # Parse response
            records = []
            for day in data.get('days', []):
                day_date = day.get('datetime', '')
                for hour_data in day.get('hours', []):
                    hour_str = hour_data.get('datetime', '')
                    try:
                        if 'T' in str(hour_str):
                            dt = pd.to_datetime(hour_str)
                        else:
                            dt = pd.to_datetime(f"{day_date} {hour_str}")
                    except:
                        dt = pd.to_datetime(day_date)

                    records.append({
                        'datetime': dt,
                        'date': day_date,
                        'hour': dt.hour,
                        'temp_c': hour_data.get('temp'),
                        'feels_like': hour_data.get('feelslike'),
                        'humidity_pct': hour_data.get('humidity'),
                        'precip': hour_data.get('precip', 0),
                        'precip_prob': hour_data.get('precipprob', 0),
                        'wind_speed': hour_data.get('windspeed'),
                        'wind_dir': hour_data.get('winddir'),
                        'pressure': hour_data.get('pressure'),
                        'cloud_cover': hour_data.get('cloudcover'),
                        'visibility': hour_data.get('visibility'),
                        'weather_conditions': hour_data.get('conditions', ''),
                        'weather_icon': hour_data.get('icon', ''),
                    })

            df = pd.DataFrame(records)
            if not df.empty:
                df = df.sort_values('datetime').reset_index(drop=True)
                logger.info(f"  [Key {key_index}] ✓ Got {len(df)} records")
                return df

        except Exception as e:
            logger.warning(f"  [Key {key_index}] Error: {e}")
            time.sleep(1)
            continue

    logger.error(f"  ✗ All keys failed for {start_date} → {end_date}")
    return None


# =============================================================================
# PROCESSING
# =============================================================================

def add_h3_and_metadata(df: pd.DataFrame, anchor_name: str, lat: float, lon: float) -> pd.DataFrame:
    """Add H3 index và metadata."""
    import h3

    df['anchor_name'] = anchor_name
    df['anchor_lat'] = lat
    df['anchor_lon'] = lon
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


def process_and_append(
    df: pd.DataFrame,
    anchor_name: str,
    lat: float,
    lon: float,
    existing_df: pd.DataFrame
) -> pd.DataFrame:
    """Process data và append vào parquet file."""
    processor = WeatherProcessor()

    # Add metadata
    df = add_h3_and_metadata(df, anchor_name, lat, lon)

    # Process pipeline
    processed = processor.process_pipeline(df, add_owm=True, add_blended=True)

    # Append
    if existing_df.empty:
        combined = processed
    else:
        combined = pd.concat([existing_df, processed], ignore_index=True)

    combined.to_parquet(OUTPUT_PATH, index=False)
    logger.info(f"  ✓ Appended. Total: {len(combined)} records")

    return combined


# =============================================================================
# MAIN BACKFILL LOGIC
# =============================================================================

def run_backfill():
    """Run backfill với 8 keys."""
    logger.info(f"\n{'='*70}")
    logger.info(f"BẮT ĐẦU BACKFILL VỚI 8 API KEYS")
    logger.info(f"{'='*70}")

    # Load existing data
    existing_df, completed = load_existing()

    # Xác định anchors cần fetch
    anchors_to_fetch = [a for a in ANCHORS if a['name'] not in completed]

    if not anchors_to_fetch:
        logger.info("Tất cả anchors đã hoàn thành!")
        return

    logger.info(f"Anchors đã hoàn thành: {sorted(completed)}")
    logger.info(f"Anchors cần fetch: {[a['name'] for a in anchors_to_fetch]}")
    logger.info(f"\n{'='*70}\n")

    # Key index cho việc gán
    key_idx = 0

    for anchor in anchors_to_fetch:
        anchor_name = anchor['name']
        lat, lon = anchor['lat'], anchor['lon']

        logger.info(f"\n{'='*60}")
        logger.info(f"FETCHING: {anchor_name} ({lat}, {lon})")
        logger.info(f"{'='*60}")

        # Xác định các call còn cần fetch
        remaining_calls = get_remaining_calls(anchor_name, existing_df)

        if not remaining_calls:
            logger.info(f"  ✓ {anchor_name} đã hoàn thành!")
            continue

        logger.info(f"  Cần fetch {len(remaining_calls)} calls: {[i+1 for i in remaining_calls]}")

        for call_idx in remaining_calls:
            start_date, end_date = DATE_SPLITS[call_idx]

            # Lấy key cho call này
            key_num, key_val = BACKFILL_KEYS[key_idx]
            key_idx = (key_idx + 1) % len(BACKFILL_KEYS)  # Round-robin

            logger.info(f"\n  [{call_idx+1}/3] {start_date} → {end_date}")
            logger.info(f"  Sử dụng Key {key_num} (Index {key_idx}/{len(BACKFILL_KEYS)})")

            # Fetch
            df = fetch_single_call(lat, lon, start_date, end_date, key_num, key_val)

            if df is not None and not df.empty:
                # Process và append
                existing_df = process_and_append(df, anchor_name, lat, lon, existing_df)
            else:
                logger.error(f"  ✗ Failed - Key {key_num} bị rate limit")
                logger.error(f"  → Thử chạy lại script sau khi quota reset (0:00 UTC)")
                return 1

            # Delay giữa các calls
            time.sleep(1)

        logger.info(f"\n  ✓ {anchor_name} hoàn thành!")

    # Final summary
    final_df = pd.read_parquet(OUTPUT_PATH)
    logger.info(f"\n{'='*70}")
    logger.info(f"BACKFILL HOÀN THÀNH!")
    logger.info(f"{'='*70}")
    logger.info(f"Tổng records: {len(final_df)}")
    logger.info(f"Anchors: {sorted(final_df['anchor_name'].unique())}")

    return 0


def continue_from_checkpoint():
    """
    Tiếp tục từ điểm dở.

    Trường hợp: HoanKiem đã fetch call 1, cần fetch call 2, 3
    """
    logger.info(f"\n{'='*70}")
    logger.info(f"CONTINUE FROM CHECKPOINT")
    logger.info(f"{'='*70}")

    # Load existing
    existing_df, completed = load_existing()

    if 'HoanKiem' not in completed:
        logger.info("HoanKiem chưa bắt đầu, chạy backfill thông thường")
        return run_backfill()

    # Kiểm tra HoanKiem đã hoàn thành bao nhiêu calls
    hoankiem_records = len(existing_df[existing_df['anchor_name'] == 'HoanKiem'])
    calls_done = hoankiem_records // 1000

    logger.info(f"HoanKiem: {hoankiem_records} records, ~{calls_done} calls done")

    # Key index bắt đầu từ 0 (Key 1)
    key_idx = calls_done % len(BACKFILL_KEYS)

    anchor = next(a for a in ANCHORS if a['name'] == 'HoanKiem')
    lat, lon = anchor['lat'], anchor['lon']
    anchor_name = anchor['name']

    # Fetch các call còn lại
    for call_idx in range(calls_done, 3):
        start_date, end_date = DATE_SPLITS[call_idx]

        key_num, key_val = BACKFILL_KEYS[key_idx]
        key_idx = (key_idx + 1) % len(BACKFILL_KEYS)

        logger.info(f"\n[{call_idx+1}/3] {start_date} → {end_date} (Key {key_num})")

        df = fetch_single_call(lat, lon, start_date, end_date, key_num, key_val)

        if df is not None and not df.empty:
            existing_df = process_and_append(df, anchor_name, lat, lon, existing_df)
        else:
            logger.error(f"  ✗ Failed")
            return 1

        time.sleep(1)

    # Tiếp tục với các anchors khác
    anchors_to_fetch = [a for a in ANCHORS if a['name'] not in completed and a['name'] != 'HoanKiem']

    for anchor in anchors_to_fetch:
        anchor_name = anchor['name']
        lat, lon = anchor['lat'], anchor['lon']

        logger.info(f"\n{'='*60}")
        logger.info(f"FETCHING: {anchor_name}")
        logger.info(f"{'='*60}")

        for call_idx in range(3):
            start_date, end_date = DATE_SPLITS[call_idx]

            key_num, key_val = BACKFILL_KEYS[key_idx]
            key_idx = (key_idx + 1) % len(BACKFILL_KEYS)

            logger.info(f"\n[{call_idx+1}/3] {start_date} → {end_date} (Key {key_num})")

            df = fetch_single_call(lat, lon, start_date, end_date, key_num, key_val)

            if df is not None and not df.empty:
                existing_df = process_and_append(df, anchor_name, lat, lon, existing_df)
            else:
                logger.error(f"  ✗ Failed")
                return 1

            time.sleep(1)

    # Final
    final_df = pd.read_parquet(OUTPUT_PATH)
    logger.info(f"\n{'='*70}")
    logger.info(f"HOÀN THÀNH!")
    logger.info(f"{'='*70}")
    logger.info(f"Tổng records: {len(final_df)}")
    logger.info(f"Anchors: {sorted(final_df['anchor_name'].unique())}")

    return 0


if __name__ == "__main__":
    # Check trạng thái trước khi chạy
    existing_df, completed = load_existing()

    if 'HoanKiem' in completed:
        # HoanKiem đã bắt đầu, kiểm tra có cần continue không
        hoankiem_records = len(existing_df[existing_df['anchor_name'] == 'HoanKiem'])
        if hoankiem_records < 3000:  # Chưa hoàn thành đủ 3 calls
            sys.exit(continue_from_checkpoint())

    sys.exit(run_backfill())
