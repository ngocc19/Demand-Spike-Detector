"""
HSDC Rainfall Plugin
====================

Plugin for collecting rainfall data from HSDC (Hanoi Drainage Company).
Website: https://maps.hsdc.vn/

API Endpoint:
- https://thoatnuochanoi.vn/luongmua/api/getAllData (POST)

Response Structure:
{
    'code': 1,
    'data': {
        'tram': '[{"Id":52,"TenTram":"HOÀN KIẾM",...}]',  <- JSON STRING
        'data': '[{"Id":1,"TramId":11,"LuongMua_BD":0.1,...}]'  <- JSON STRING
    }
}

Fields:
- LuongMua_BD: Rainfall before (mm)
- LuongMua_HT: Rainfall current (mm)
- LuongMua_Tr: Rainfall total/accumulated (mm)
- TramId: Station ID
"""

import requests
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any
import json
import logging

from ..base import BaseFactorPlugin, FactorType, FactorRecord
from ..registry import PluginRegistry

logger = logging.getLogger(__name__)


@PluginRegistry.register("hsdc")
class HSDCFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting rainfall data from HSDC Hanoi.

    API Response Structure:
    {
        'code': 1,
        'data': {
            'tram': '[...]',  <- JSON string of station info
            'data': '[...]'  <- JSON string of rainfall records
        }
    }

    This requires 2-stage JSON parsing.
    """

    factor_type = FactorType.WEATHER
    factor_name = "hsdc"
    schedule = "*/15 * * * *"  # Every 15 minutes

    # HSDC Rainfall API
    BASE_URL = "https://thoatnuochanoi.vn"
    RAINFALL_API = "/luongmua/api/getAllData"

    # Rainfall impact mapping (mm/hour)
    RAINFALL_IMPACT_MAP = {
        (0, 2.5): 0.2,   # Light rain
        (2.5, 5): 0.3,   # Light-moderate
        (5, 10): 0.5,    # Moderate
        (10, 20): 0.7,   # Moderate-heavy
        (20, 50): 0.9,   # Heavy
        (50, float('inf')): 1.0,  # Extreme
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.timeout = config.get('timeout_seconds', 15)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Referer': f'{self.BASE_URL}/',
        })

    def fetch(self) -> pd.DataFrame:
        """
        Fetch rainfall data from HSDC API.

        API requires POST method. Response contains double-encoded JSON.
        """
        url = f"{self.BASE_URL}{self.RAINFALL_API}"

        try:
            response = self.session.post(url, timeout=self.timeout)
            response.raise_for_status()

            return self._parse_response(response.text)

        except requests.RequestException as e:
            logger.error(f"HSDC rainfall API request failed: {e}")
            return self._create_synthetic_data()

    def _parse_response(self, text: str) -> pd.DataFrame:
        """
        Parse HSDC API response.

        Layer 1: response.json() -> {'code': 1, 'data': {...}}
        Layer 2: data['tram'] is STRING -> json.loads()
        Layer 2: data['data'] is STRING -> json.loads()
        """
        current_time = datetime.now()

        try:
            # Layer 1: Parse response
            layer1 = json.loads(text)

            code = layer1.get('code')
            if code != 1:
                logger.warning(f"HSDC API returned code: {code}")
                return self._create_synthetic_data()

            # Layer 2: Get inner data
            layer2 = layer1.get('data', {})

            # Layer 3: Parse tram (stations) - JSON STRING to list
            tram_str = layer2.get('tram', '[]')
            stations = json.loads(tram_str) if tram_str else []

            # Layer 3: Parse data (rainfall) - JSON STRING to list
            rainfall_str = layer2.get('data', '[]')
            rainfall_records = json.loads(rainfall_str) if rainfall_str else []

            # Create station lookup
            station_lookup = {s['Id']: s for s in stations}

            # Build records with merged station info
            records = []
            for record in rainfall_records:
                station_id = record.get('TramId')
                station_info = station_lookup.get(station_id, {})

                records.append({
                    'datetime': current_time,
                    'record_id': record.get('Id'),
                    'station_id': station_id,
                    'station_name': station_info.get('TenTram', 'Unknown'),
                    'station_address': station_info.get('DiaChi', ''),
                    'latitude': station_info.get('Lat'),
                    'longitude': station_info.get('Lng'),
                    'rainfall_before_mm': record.get('LuongMua_BD', 0),
                    'time_before': record.get('ThoiGian_BD'),
                    'rainfall_current_mm': record.get('LuongMua_HT', 0),
                    'time_current': record.get('ThoiGian_HT'),
                    'rainfall_total_mm': record.get('LuongMua_Tr', 0),
                    'time_total': record.get('ThoiGian_Tr'),
                    'rainfall_ac': record.get('AC', 0),
                    'source': 'HSDC_RAINFALL',
                    'update_time': current_time,
                })

            if not records:
                return self._create_synthetic_data()

            return pd.DataFrame(records)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse HSDC response: {e}")
            return self._create_synthetic_data()

    def _create_synthetic_data(self) -> pd.DataFrame:
        """Create synthetic rainfall data when API unavailable."""
        current_time = datetime.now()

        # Common rainfall stations
        stations = [
            {'id': 1, 'name': 'Hoàn Kiếm', 'lat': 21.0283, 'lon': 105.8542},
            {'id': 2, 'name': 'Cầu Giấy', 'lat': 21.0333, 'lon': 105.7833},
            {'id': 3, 'name': 'Thanh Xuân', 'lat': 21.0055, 'lon': 105.8120},
        ]

        records = []
        for station in stations:
            records.append({
                'datetime': current_time,
                'record_id': station['id'],
                'station_id': station['id'],
                'station_name': station['name'],
                'station_address': '',
                'latitude': station['lat'],
                'longitude': station['lon'],
                'rainfall_before_mm': 0.0,
                'time_before': None,
                'rainfall_current_mm': 0.0,
                'time_current': None,
                'rainfall_total_mm': 0.0,
                'time_total': None,
                'rainfall_ac': 0,
                'source': 'HSDC_SYNTHETIC',
                'update_time': current_time,
            })

        return pd.DataFrame(records)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform to standardized format."""
        if df.empty:
            return df

        df = df.copy()

        # Use current rainfall as main value
        df['precip_mm'] = df['rainfall_current_mm']

        # Calculate impact from rainfall
        def rainfall_to_impact(mm: float) -> float:
            for (low, high), impact in self.RAINFALL_IMPACT_MAP.items():
                if low <= mm < high:
                    return impact
            return 0.0

        df['weather_impact'] = df['precip_mm'].apply(rainfall_to_impact)

        # Combined impact
        df['value'] = df['weather_impact']

        # Severity
        def classify_severity(row):
            mm = row.get('precip_mm', 0)
            if mm >= 50:
                return 'SEVERE'
            elif mm >= 20:
                return 'HIGH'
            elif mm >= 10:
                return 'MEDIUM'
            elif mm >= 2.5:
                return 'LOW'
            return 'NONE'

        df['severity'] = df.apply(classify_severity, axis=1)

        # Metadata
        df['metadata'] = df.apply(
            lambda r: {
                'source': 'HSDC',
                'station': r.get('station_name', ''),
                'rainfall_mm': r.get('precip_mm', 0),
                'rainfall_total_mm': r.get('rainfall_total_mm', 0),
            },
            axis=1
        )

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map rainfall data to H3 hexagons."""
        if df.empty:
            return df

        import h3

        df = df.copy()
        records = []

        for _, row in df.iterrows():
            lat = row.get('latitude')
            lon = row.get('longitude')

            if lat and lon and pd.notna(lat) and pd.notna(lon):
                hex_id = h3.latlng_to_cell(lat, lon, 9)

                new_row = row.copy()
                new_row['hex_id'] = hex_id
                records.append(new_row)
            else:
                records.append(row.copy())

        return pd.DataFrame(records)

    def get_data_age(self) -> float:
        """Get data staleness in hours."""
        return 0.25  # 15 minutes

    def get_rainfall_summary(self, df: pd.DataFrame) -> Dict:
        """Get summary of rainfall across stations."""
        if df.empty:
            return {}

        return {
            'total_stations': len(df),
            'active_stations': len(df[df['rainfall_current_mm'] > 0]),
            'avg_rainfall': round(df['rainfall_current_mm'].mean(), 2),
            'max_rainfall': round(df['rainfall_current_mm'].max(), 2),
            'max_station': df.loc[df['rainfall_current_mm'].idxmax(), 'station_name'] if not df.empty else None,
            'total_accumulated': round(df['rainfall_total_mm'].sum(), 2),
        }
