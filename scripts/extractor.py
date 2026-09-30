"""
VCW Data Extractor - Optimized
=============================

Optimized extractor với chiến lược gọi API tối ưu:

Cho mỗi location:
- Call 1 (Key 1): 29/06 → 08/08 (41 days × 24 = 984 records)
- Call 2 (Key 2): 09/08 → 18/09 (41 days × 24 = 984 records)
- Call 3 (Key 3): 19/09 → 28/09 (10 days × 24 = 240 records)

6 locations × 3 calls = 18 calls total ✓

Usage:
    from extractor import VCWExtractor

    extractor = VCWExtractor(api_keys=['key1', 'key2', 'key3'])
    data = extractor.fetch_weather_optimized(
        lat=21.0285,
        lon=105.8542,
        location_name='HoanKiem'
    )
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class VCWExtractor:
    """
    Extracts weather data từ Visual Crossing API với chiến lược tối ưu.

    Chiến lược: Mỗi call < 1000 records, luân phiên keys.
    """

    BASE_URL = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
    QUOTA_PER_KEY = 1000
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    # Date splits cho 92 ngày (29/06 → 28/09)
    DATE_SPLITS = [
        ("2026-06-29", "2026-08-08"),  # 41 days = 984 records
        ("2026-08-09", "2026-09-18"),  # 41 days = 984 records
        ("2026-09-19", "2026-09-28"),  # 10 days = 240 records
    ]

    def __init__(self, api_keys: List[str]):
        """
        Initialize extractor.

        Args:
            api_keys: List of API keys
        """
        if len(api_keys) < 1:
            raise ValueError("Cần ít nhất 1 API key!")

        self.api_keys = api_keys
        self.current_key_index = 0
        self.calls_made = {key: 0 for key in api_keys}

        logger.info(f"VCWExtractor initialized với {len(api_keys)} keys")
        logger.info(f"Date splits: {self.DATE_SPLITS}")

    @property
    def current_key(self) -> str:
        return self.api_keys[self.current_key_index]

    def switch_to_next_key(self):
        """Switch sang key tiếp theo."""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        logger.info(f"Switched to Key {self.current_key_index + 1}")

    def fetch_single_call(
        self,
        lat: float,
        lon: float,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """
        Gọi API 1 lần cho 1 date range.
        Thử TẤT CẢ keys cho đến khi thành công hoặc hết keys.
        """
        location = f"{lat},{lon}"
        url = f"{self.BASE_URL}/{location}/{start_date}/{end_date}"

        # Thử tất cả keys cho đến khi thành công
        keys_tried = []

        while len(keys_tried) < len(self.api_keys):
            # Get next key chưa thử
            available_keys = [k for k in self.api_keys if k not in keys_tried]
            if not available_keys:
                break

            key = available_keys[0]
            key_index = self.api_keys.index(key)

            params = {
                "unitGroup": "metric",
                "include": "hours",
                "key": key,
                "contentType": "json",
            }

            try:
                logger.info(f"  Trying Key {key_index + 1}...")
                response = requests.get(url, params=params, timeout=60)

                if response.status_code == 429:
                    logger.warning(f"  Key {key_index + 1}: 429 Rate Limit")
                    keys_tried.append(key)
                    continue

                response.raise_for_status()
                data = response.json()

                records_count = sum(len(day.get('hours', [])) for day in data.get('days', []))
                self.calls_made[key] = self.calls_made.get(key, 0) + 1

                logger.info(f"  ✓ Key {key_index + 1}: Got {records_count} records")

                return self._parse_response(data)

            except Exception as e:
                logger.warning(f"  Key {key_index + 1}: {e}")
                keys_tried.append(key)

        logger.error(f"  ✗ All keys exhausted ({len(keys_tried)} tried)")
        return None

    def _parse_response(self, data: dict) -> pd.DataFrame:
        """Parse API response thành DataFrame."""
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

        return df

    def fetch_weather_optimized(
        self,
        lat: float,
        lon: float,
        location_name: str
    ) -> Optional[pd.DataFrame]:
        """
        Fetch weather cho 1 location với chiến lược tối ưu.

        3 calls: Mỗi call < 1000 records, luân phiên 3 keys.

        Args:
            lat, lon: Tọa độ
            location_name: Tên location (cho log)

        Returns:
            DataFrame với tất cả data hoặc None nếu thất bại
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Fetching weather for {location_name} ({lat}, {lon})")
        logger.info(f"{'='*60}")

        all_data = []

        for i, (start_date, end_date) in enumerate(self.DATE_SPLITS):
            logger.info(f"  [{i+1}/3] Date range: {start_date} → {end_date}")

            df = self.fetch_single_call(lat, lon, start_date, end_date)

            if df is not None and not df.empty:
                df['anchor_name'] = location_name
                df['anchor_lat'] = lat
                df['anchor_lon'] = lon
                all_data.append(df)
                logger.info(f"  ✓ Got {len(df)} records")
            else:
                logger.error(f"  ✗ No data for {start_date} → {end_date}")
                return None

            # Delay giữa các calls
            time.sleep(1)

        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            logger.info(f"✓ Total: {len(combined)} records for {location_name}")
            return combined

        return None

    def fetch_all_anchors(self, anchors: List[Dict]) -> pd.DataFrame:
        """
        Fetch weather cho tất cả 6 anchor points.

        Args:
            anchors: List of anchor dictionaries

        Returns:
            Combined DataFrame cho tất cả locations
        """
        all_data = []

        for anchor in anchors:
            anchor_name = anchor.get('name', 'Unknown')
            lat = anchor.get('lat')
            lon = anchor.get('lon')

            if lat and lon:
                df = self.fetch_weather_optimized(
                    lat=lat,
                    lon=lon,
                    location_name=anchor_name
                )

                if df is not None:
                    all_data.append(df)

            # Delay giữa các locations
            time.sleep(2)

        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            logger.info(f"\n{'='*60}")
            logger.info(f"TOTAL: {len(combined)} records from {len(all_data)} locations")
            logger.info(f"{'='*60}")
            return combined

        return pd.DataFrame()

    def get_status(self) -> Dict:
        """Get current status."""
        return {
            'current_key': self.current_key_index + 1,
            'total_keys': len(self.api_keys),
            'calls_made': self.calls_made,
        }


def main():
    """Test function."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from dotenv import load_dotenv
    load_dotenv()

    # Lấy keys từ environment
    api_keys = [
        os.getenv('VISUALCROSSING_API_KEY'),
        os.getenv('VISUALCROSSING_API_KEY_2'),
        os.getenv('VISUALCROSSING_API_KEY_3'),
    ]
    api_keys = [k for k in api_keys if k]

    if len(api_keys) < 3:
        print("Cần 3 API keys!")
        return

    # 6 anchors
    anchors = [
        {"name": "HoanKiem", "lat": 21.0285, "lon": 105.8542},
        {"name": "CauGiay", "lat": 21.0306, "lon": 105.7925},
        {"name": "HoangMai", "lat": 20.9723, "lon": 105.8454},
        {"name": "LongBien", "lat": 21.0470, "lon": 105.8920},
        {"name": "TayHo", "lat": 21.0664, "lon": 105.8176},
        {"name": "NoiBai", "lat": 21.2187, "lon": 105.8042},
    ]

    # Test với 1 location trước
    extractor = VCWExtractor(api_keys)
    df = extractor.fetch_weather_optimized(
        lat=21.0285,
        lon=105.8542,
        location_name='HoanKiem_Test'
    )

    if df is not None:
        print(f"\nResult: {len(df)} records")
        print(df.head())


if __name__ == "__main__":
    main()
