"""
HSDC Flood API Plugin
====================

Plugin for collecting flood monitoring data from HSDC (Hanoi Drainage Company).
Website: https://thoatnuochanoi.vn/

Primary API Endpoint:
- https://thoatnuochanoi.vn/ungngap/api/flood/getflood

Returns JSON with list of 45 flood monitoring points.
"""

import requests
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional
import re
import logging

from ..base import BaseFactorPlugin, FactorType, FactorRecord
from ..registry import PluginRegistry

logger = logging.getLogger(__name__)


@PluginRegistry.register("hsdc_flood")
class HSDCFloodPlugin(BaseFactorPlugin):
    """
    Plugin for collecting flood monitoring data from HSDC Hanoi API.

    API Response Structure:
    {
        "Code": 1,
        "Content": [
            {
                "TramId": "3",
                "TenTram": "Cao Bá Quát (cổng Cty Môi trường đô thị)",
                "Lng": "105.839500",
                "Lat": "21.030180",
                "Icon": "202608311105287262087_Flood_level1.png"
            },
            ...
        ]
    }
    """

    factor_type = FactorType.FLOOD
    factor_name = "hsdc_flood"
    schedule = "*/15 * * * *"  # Every 15 minutes

    # HSDC API endpoints
    BASE_URL = "https://thoatnuochanoi.vn"
    FLOOD_API = "/ungngap/api/flood/getflood"

    # Flood level mapping from icon
    FLOOD_LEVEL_MAP = {
        0: {'name': 'Không ngập', 'cm': 0, 'impact': 0.0},
        1: {'name': 'Ngập nhẹ', 'cm': 10, 'impact': 0.2},
        2: {'name': 'Ngập trung bình', 'cm': 25, 'impact': 0.5},
        3: {'name': 'Ngập cao', 'cm': 50, 'impact': 0.8},
        4: {'name': 'Ngập nặng', 'cm': 100, 'impact': 1.0},
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.timeout = config.get('timeout_seconds', 15)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/html, */*',
            'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
            'Referer': f'{self.BASE_URL}/',
        })

    def fetch(self) -> pd.DataFrame:
        """Fetch flood data from HSDC API."""
        url = f"{self.BASE_URL}{self.FLOOD_API}"

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            return self._parse_response(response.text)

        except requests.RequestException as e:
            logger.error(f"HSDC flood API request failed: {e}")
            return self._create_synthetic_data()

    def _parse_response(self, text: str) -> pd.DataFrame:
        """Parse HSDC flood API response."""
        import json

        records = []
        current_time = datetime.now()

        try:
            data = json.loads(text)

            # Check response code
            code = data.get('Code')
            if code != 1:
                logger.warning(f"HSDC API returned code: {code}")
                return self._create_synthetic_data()

            # Extract flood points from Content
            flood_points = data.get('Content', [])

            for point in flood_points:
                if isinstance(point, dict):
                    # Parse icon to get flood level
                    icon = point.get('Icon', '')
                    level = self._parse_level_from_icon(icon)

                    records.append({
                        'datetime': current_time,
                        'station_id': point.get('TramId'),
                        'location_name': point.get('TenTram', 'Unknown'),
                        'flood_level': level,
                        'flood_level_name': self.FLOOD_LEVEL_MAP.get(level, {}).get('name', 'Không rõ'),
                        'flood_depth_cm': self.FLOOD_LEVEL_MAP.get(level, {}).get('cm', 0),
                        'is_flooding': level > 0,
                        'latitude': float(point.get('Lat', 0)),
                        'longitude': float(point.get('Lng', 0)),
                        'icon': icon,
                        'source': 'HSDC_FLOOD_API',
                        'update_time': current_time,
                    })

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse HSDC response: {e}")
            return self._create_synthetic_data()

        if not records:
            return self._create_synthetic_data()

        df = pd.DataFrame(records)
        return df

    def _parse_level_from_icon(self, icon_name: str) -> int:
        """
        Parse flood level from icon filename.

        Patterns:
        - Flood_level0.png = 0 (no flooding)
        - Flood_level1.png = 1 (low)
        - Flood_level2.png = 2 (medium)
        - Flood_level3.png = 3 (high)
        - Flood_level4.png = 4 (severe)
        """
        if not icon_name:
            return 0

        match = re.search(r'level(\d+)', icon_name)
        if match:
            return int(match.group(1))

        return 0

    def _create_synthetic_data(self) -> pd.DataFrame:
        """Create synthetic flood data when API unavailable."""
        current_time = datetime.now()

        # Common flood-prone locations
        locations = [
            {'id': '1', 'name': 'Cầu Giấy', 'lat': 21.0333, 'lon': 105.7833},
            {'id': '2', 'name': 'Thanh Xuân', 'lat': 21.0055, 'lon': 105.8120},
            {'id': '3', 'name': 'Hoàng Mai', 'lat': 20.9833, 'lon': 105.8500},
            {'id': '4', 'name': 'Đống Đa', 'lat': 21.0200, 'lon': 105.8300},
            {'id': '5', 'name': 'Hai Bà Trưng', 'lat': 21.0133, 'lon': 105.8467},
        ]

        records = []
        for loc in locations:
            level = 0  # No flooding in synthetic data
            records.append({
                'datetime': current_time,
                'station_id': loc['id'],
                'location_name': loc['name'],
                'flood_level': level,
                'flood_level_name': self.FLOOD_LEVEL_MAP[level]['name'],
                'flood_depth_cm': 0,
                'is_flooding': False,
                'latitude': loc['lat'],
                'longitude': loc['lon'],
                'icon': f'Flood_level{level}.png',
                'source': 'HSDC_SYNTHETIC',
                'update_time': current_time,
            })

        return pd.DataFrame(records)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform to standardized format."""
        if df.empty:
            return df

        df = df.copy()

        # Calculate impact from flood level
        df['weather_impact'] = df['flood_level'].map(
            lambda x: self.FLOOD_LEVEL_MAP.get(x, {}).get('impact', 0.0)
        )

        # Combined impact
        df['value'] = df['weather_impact']

        # Severity
        def classify_severity(level):
            if level >= 4:
                return 'SEVERE'
            elif level >= 3:
                return 'HIGH'
            elif level >= 2:
                return 'MEDIUM'
            elif level >= 1:
                return 'LOW'
            return 'NONE'

        df['severity'] = df['flood_level'].apply(classify_severity)

        # Metadata
        df['metadata'] = df.apply(
            lambda r: {
                'source': 'HSDC',
                'location': r.get('location_name', ''),
                'flood_level': r.get('flood_level', 0),
                'flood_depth_cm': r.get('flood_depth_cm', 0),
                'is_flooding': r.get('is_flooding', False),
            },
            axis=1
        )

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map flood data to H3 hexagons."""
        if df.empty:
            return df

        import h3

        df = df.copy()
        records = []

        for _, row in df.iterrows():
            lat = row.get('latitude')
            lon = row.get('longitude')

            if lat and lon and lat != 0 and lon != 0:
                hex_id = h3.latlng_to_cell(lat, lon, 9)

                new_row = row.copy()
                new_row['hex_id'] = hex_id
                records.append(new_row)
            else:
                records.append(row.copy())

        return pd.DataFrame(records)

    def get_flood_summary(self, df: pd.DataFrame) -> Dict:
        """Get summary of flood status."""
        if df.empty:
            return {}

        flooding = df[df['is_flooding'] == True]

        return {
            'total_stations': len(df),
            'flooding_stations': len(flooding),
            'flooding_percentage': round(len(flooding) / len(df) * 100, 1) if len(df) > 0 else 0,
            'max_level': int(df['flood_level'].max()) if 'flood_level' in df.columns else 0,
            'max_depth_cm': int(df['flood_depth_cm'].max()) if 'flood_depth_cm' in df.columns else 0,
            'flooding_locations': flooding['location_name'].tolist() if len(flooding) > 0 else [],
        }
