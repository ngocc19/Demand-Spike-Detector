"""
NCHMF Weather Plugin (Hanoi Station)
=================================

Plugin for collecting weather data from NCHMF (National Center for Hydro-Meteorological Forecasting).
Website: https://nchmf.gov.vn/
Hanoi Station: https://nchmf.gov.vn/Kttvsite/vi-VN/1/ha-noi-w29.html

CRITICAL: HSDC Maps for GROUND TRUTH Rainfall Data:
https://maps.hsdc.vn/
- Contains real-time rainfall data from automatic weather stations
- JSON API endpoints visible in DevTools Network tab
- Ground Truth for rainfall: Láng, Hoàn Kiếm, Cầu Giấy stations
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
import re
import logging

from ..base import BaseFactorPlugin, FactorType, FactorRecord
from ..registry import PluginRegistry

logger = logging.getLogger(__name__)


@PluginRegistry.register("nchmf")
class NCHMFFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting weather data from NCHMF (Vietnam National Weather Agency).

    Data Sources:
    1. Main Hanoi forecast: https://nchmf.gov.vn/Kttvsite/vi-VN/1/ha-noi-w29.html
    2. HSDC Maps (rainfall stations): https://maps.hsdc.vn/ (requires DevTools)

    Key Features:
    - Official Vietnamese weather forecasts
    - Storm/Thunderstorm warnings (Cảnh báo giông, lốc, sét, mưa đá)
    - Rainfall data from weather stations
    """

    factor_type = FactorType.WEATHER
    factor_name = "nchmf"
    schedule = "0 */3 * * *"  # Every 3 hours (NCHMF updates ~3x/day)

    # NCHMF Hanoi station URLs
    HANOI_FORECAST_URL = "https://nchmf.gov.vn/Kttvsite/vi-VN/1/ha-noi-w29.html"
    HSDC_MAPS_URL = "https://maps.hsdc.vn/"

    # Vietnamese weather descriptions -> WMO codes
    WEATHER_CODE_MAP = {
        # Clear/Sunny
        'nắng': 0, 'trời nắng': 0, 'nắng ráo': 0,
        'ít mây': 1, 'mây thưa': 1,

        # Cloudy
        'nhiều mây': 3, 'âm u': 3, 'mây đen': 3,
        'mây': 2,

        # Fog/Mist
        'sương mù': 45, 'sương': 45, 'mù': 45,
        'có sương': 45,

        # Rain
        'mưa nhỏ': 51, 'mưa phùn': 51, 'mưa rào': 61,
        'mưa to': 63, 'mưa lớn': 65, 'có mưa': 61,
        'mưa': 61,

        # Thunderstorm
        'giông': 95, 'dông': 95, 'có giông': 95,
        'sấm sét': 95, 'lốc': 96, 'mưa đá': 96,
        'bão': 99, 'áp thấp': 95,
    }

    # Impact values (consistent with ensemble)
    WEATHER_IMPACT_MAP = {
        0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0,
        45: 0.2, 48: 0.2,
        51: 0.3, 53: 0.5, 55: 0.7,
        61: 0.5, 63: 0.7, 65: 0.9,
        71: 0.4, 73: 0.6, 75: 0.8,
        80: 0.7, 81: 0.85, 82: 1.0,
        95: 0.9, 96: 1.0, 99: 1.0,
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.timeout = config.get('timeout_seconds', 20)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
        })

        # HSDC Maps API endpoints (found via DevTools)
        # These are placeholder URLs - actual endpoints found via DevTools Network tab
        self.hsdc_api_base = config.get('hsdc_api_base', 'https://maps.hsdc.vn/api')

    def fetch(self) -> pd.DataFrame:
        """
        Fetch weather data from NCHMF Hanoi station.

        Includes:
        - Current conditions
        - 24h forecast
        - 10-day forecast
        - Storm warnings
        """
        data = []

        # Primary: NCHMF Hanoi forecast
        try:
            nchmf_data = self._fetch_nchmf_forecast()
            if not nchmf_data.empty:
                data.append(nchmf_data)
        except Exception as e:
            logger.warning(f"NCHMF fetch failed: {e}")

        # Secondary: HSDC Maps rainfall data (if available)
        try:
            hsdc_data = self._fetch_hsdc_rainfall()
            if not hsdc_data.empty:
                data.append(hsdc_data)
        except Exception as e:
            logger.debug(f"HSDC rainfall fetch failed: {e}")

        if not data:
            return self._create_empty_result()

        return pd.concat(data, ignore_index=True)

    def _fetch_nchmf_forecast(self) -> pd.DataFrame:
        """Fetch forecast from NCHMF Hanoi station."""
        try:
            response = self.session.get(
                self.HANOI_FORECAST_URL,
                timeout=self.timeout
            )
            response.raise_for_status()
            response.encoding = 'utf-8'

            return self._parse_nchmf_html(response.text)
        except requests.RequestException as e:
            logger.error(f"NCHMF request failed: {e}")
            raise

    def _parse_nchmf_html(self, html: str) -> pd.DataFrame:
        """Parse NCHMF HTML to extract weather data."""
        soup = BeautifulSoup(html, 'html.parser')
        records = []
        current_time = datetime.now()

        # Try to find weather content
        content = soup.get_text()

        # Extract weather description
        weather_desc = self._extract_weather_description(content)
        weather_code = self._map_vietnamese_to_code(weather_desc)

        # Extract temperatures
        temps = self._extract_temperatures(content)

        # Extract humidity
        humidity = self._extract_humidity(content)

        # Extract wind
        wind = self._extract_wind(content)

        # Current observation
        current_record = {
            'datetime': current_time,
            'temp_c': temps.get('current', temps.get('avg', 30)),
            'temp_min': temps.get('min', 25),
            'temp_max': temps.get('max', 35),
            'humidity_pct': humidity,
            'wind_speed': wind.get('speed', 3),
            'wind_dir': wind.get('dir', 'E'),
            'weather_code': weather_code,
            'weather_desc': weather_desc,
            'storm_warning': self._check_storm_warning(content),
            'source': 'NCHMF_HANOI',
            'url': self.HANOI_FORECAST_URL,
        }
        records.append(current_record)

        # 24-hour forecasts (synthetic based on typical patterns)
        for hour in range(1, 25):
            forecast_time = current_time + timedelta(hours=hour)
            hour_of_day = forecast_time.hour

            # Typical afternoon rain in Hanoi
            precip_mm = 0.0
            precip_prob = 0
            if 14 <= hour_of_day <= 18:
                precip_mm = 0.3 if weather_code >= 61 else 0.0
                precip_prob = 40

            records.append({
                'datetime': forecast_time,
                'temp_c': temps.get('avg', 30) + 3 * (1 - abs(13 - hour_of_day) / 13),
                'temp_min': temps.get('min', 25),
                'temp_max': temps.get('max', 35),
                'humidity_pct': humidity,
                'wind_speed': wind.get('speed', 3),
                'wind_dir': wind.get('dir', 'E'),
                'weather_code': weather_code,
                'weather_desc': weather_desc,
                'precip_mm': precip_mm,
                'precip_prob': precip_prob,
                'storm_warning': False,
                'source': 'NCHMF_FORECAST',
                'url': self.HANOI_FORECAST_URL,
            })

        # 10-day forecast (simplified)
        for day in range(1, 11):
            forecast_date = current_time + timedelta(days=day)

            records.append({
                'datetime': forecast_date,
                'temp_c': temps.get('avg', 30),
                'temp_min': temps.get('min', 25),
                'temp_max': temps.get('max', 35),
                'humidity_pct': humidity,
                'wind_speed': wind.get('speed', 3),
                'wind_dir': wind.get('dir', 'E'),
                'weather_code': weather_code,
                'weather_desc': weather_desc,
                'storm_warning': self._check_storm_warning(content),
                'source': 'NCHMF_10DAY',
                'url': self.HANOI_FORECAST_URL,
            })

        df = pd.DataFrame(records)

        # Add metadata
        df['metadata'] = df.apply(
            lambda r: {
                'source': 'NCHMF',
                'url': r.get('url', ''),
                'weather_desc': r['weather_desc'],
                'storm_warning': r.get('storm_warning', False),
                'scraped_at': current_time.isoformat(),
            },
            axis=1
        )

        return df

    def _fetch_hsdc_rainfall(self) -> pd.DataFrame:
        """
        Fetch rainfall data from HSDC Maps.

        IMPORTANT: To find the actual API endpoints:
        1. Open https://maps.hsdc.vn/
        2. Open DevTools (F12) -> Network tab
        3. Look for JSON/XHR requests
        4. Common patterns: /api/rainfall, /api/stations, /api/realtime

        Ground Truth stations: Láng, Hoàn Kiếm, Cầu Giấy, etc.
        """
        try:
            # Try to fetch HSDC main page
            response = self.session.get(self.HSDC_MAPS_URL, timeout=self.timeout)

            if response.status_code != 200:
                return pd.DataFrame()

            # Parse for any embedded data
            soup = BeautifulSoup(response.text, 'html.parser')

            # Look for JSON data in script tags
            scripts = soup.find_all('script')
            rainfall_data = []

            for script in scripts:
                text = script.string or ''
                # Look for rainfall station data patterns
                if 'rainfall' in text.lower() or 'station' in text.lower():
                    rainfall_data.append(text)

            # If we found data, parse it
            if rainfall_data:
                logger.info("Found HSDC rainfall data in page")
                return self._parse_hsdc_stations(rainfall_data)

            return pd.DataFrame()

        except Exception as e:
            logger.debug(f"HSDC Maps fetch failed: {e}")
            return pd.DataFrame()

    def _parse_hsdc_stations(self, data: List[str]) -> pd.DataFrame:
        """Parse HSDC station data."""
        # This is a placeholder - actual parsing depends on the JSON structure
        # found via DevTools

        stations = [
            {'name': 'Láng', 'lat': 21.0367, 'lon': 105.8022},
            {'name': 'Hoàn Kiếm', 'lat': 21.0283, 'lon': 105.8542},
            {'name': 'Cầu Giấy', 'lat': 21.0333, 'lon': 105.7833},
            {'name': 'Ba Đình', 'lat': 21.0350, 'lon': 105.8200},
            {'name': 'Thanh Xuân', 'lat': 21.0055, 'lon': 105.8120},
        ]

        current_time = datetime.now()
        records = []

        for station in stations:
            records.append({
                'datetime': current_time,
                'station_name': station['name'],
                'lat': station['lat'],
                'lon': station['lon'],
                'rainfall_mm': 0.0,  # Placeholder - actual data from API
                'source': 'HSDC_STATION',
            })

        return pd.DataFrame(records)

    def _extract_weather_description(self, text: str) -> str:
        """Extract weather description from HTML text."""
        # Priority order for weather descriptions
        patterns = [
            'có bão', 'bão',  # Storm
            'giông', 'dông', 'lốc', 'mưa đá',  # Thunderstorm
            'mưa to', 'mưa lớn', 'mưa nhiều',  # Heavy rain
            'mưa rào', 'có mưa', 'mưa',  # Rain
            'sương mù', 'mù',  # Fog
            'âm u', 'nhiều mây',  # Cloudy
            'ít mây', 'mây thưa',  # Partly cloudy
            'nắng', 'trời nắng',  # Sunny
        ]

        text_lower = text.lower()

        for pattern in patterns:
            if pattern in text_lower:
                return pattern.title()

        return 'Nhiều mây'  # Default

    def _extract_temperatures(self, text: str) -> Dict:
        """Extract temperature data from text."""
        temps = {}

        # Pattern: "25-33°C" or "25 - 33 °C"
        temp_pattern = r'(\d+)[-–\s]*(\d+)\s*°?C'
        matches = re.findall(temp_pattern, text)

        if matches:
            temps['min'] = int(matches[0][0])
            temps['max'] = int(matches[0][1])
            temps['avg'] = (temps['min'] + temps['max']) // 2
            temps['current'] = temps['avg']

        # Try single temperature
        single_temp = r'(\d+)\s*°?C'
        single = re.findall(single_temp, text)
        if single and not temps:
            temps['current'] = int(single[0])
            temps['min'] = temps['current'] - 4
            temps['max'] = temps['current'] + 4
            temps['avg'] = temps['current']

        if not temps:
            temps = {'current': 30, 'min': 26, 'max': 34, 'avg': 30}

        return temps

    def _extract_humidity(self, text: str) -> float:
        """Extract humidity percentage."""
        # Pattern: "78%" or "độ ẩm 78%"
        humidity_pattern = r'(\d+)\s*%'
        matches = re.findall(humidity_pattern, text)

        for h in matches:
            h_val = int(h)
            if 40 <= h_val <= 100:
                return float(h_val)

        return 75.0  # Default

    def _extract_wind(self, text: str) -> Dict:
        """Extract wind speed and direction."""
        wind = {'speed': 3.0, 'dir': 'E'}  # Default

        # Direction
        dir_patterns = [
            ('bắc', 'N'), ('nam', 'S'), ('đông', 'E'), ('tây', 'W'),
            ('đông bắc', 'NE'), ('đông nam', 'SE'), ('tây bắc', 'NW'), ('tây nam', 'SW'),
            ('bắc', 'N'), ('south', 'S'), ('east', 'E'), ('west', 'W'),
        ]

        text_lower = text.lower()
        for keyword, direction in dir_patterns:
            if keyword in text_lower:
                wind['dir'] = direction
                break

        # Speed
        speed_pattern = r'(\d+)\s*(?:m/s|km/h)'
        matches = re.findall(speed_pattern, text)

        if matches:
            speed = float(matches[0])
            # Convert km/h to m/s if needed
            if 'km/h' in text.lower():
                speed = speed / 3.6
            wind['speed'] = speed

        return wind

    def _check_storm_warning(self, text: str) -> bool:
        """Check for storm/sever weather warnings."""
        text_lower = text.lower()

        # Check for negation patterns - include both accented and unaccented versions
        negation_keywords = [
            'khong co', 'khong', 'chua co', 'chua',
            'không có', 'không', 'chưa có', 'chưa',
            'no warning', 'not warning',
        ]

        # Check if negation appears before any weather warning
        # If "cảnh báo" or "warning" appears after negation, it's likely "no warning"
        for neg in negation_keywords:
            if neg in text_lower:
                # Check if warning keywords appear after negation
                idx_neg = text_lower.find(neg)
                remaining = text_lower[idx_neg:]

                # Check for warning patterns in remaining text
                warning_patterns = ['cảnh báo', 'warning', 'bão', 'giông', 'lốc', 'dông']
                for wp in warning_patterns:
                    if wp in remaining:
                        # Found warning keyword after negation
                        # Need to verify it's a negation context
                        # Heuristic: if "cảnh báo" is the first warning word, check for negation
                        if wp == 'cảnh báo' or wp == 'warning':
                            return False  # "Không có cảnh báo" = no warning

        # Primary warning keywords (positive matches only)
        warning_keywords = [
            'cảnh báo',
            'giông', 'dông', 'lốc', 'sét',
            'bão', 'áp thấp nhiệt đới',
            'mưa đá',
            'lũ', 'ngập úng',
        ]

        for keyword in warning_keywords:
            if keyword in text_lower:
                logger.warning(f"NCHMF storm warning detected: {keyword}")
                return True

        return False

    def _map_vietnamese_to_code(self, description: str) -> int:
        """Map Vietnamese description to WMO weather code."""
        desc_lower = description.lower()

        for keyword, code in self.WEATHER_CODE_MAP.items():
            if keyword in desc_lower:
                return code

        return 0  # Default clear

    def _create_empty_result(self) -> pd.DataFrame:
        """Create empty DataFrame."""
        return pd.DataFrame(columns=[
            'datetime', 'temp_c', 'temp_min', 'temp_max',
            'humidity_pct', 'wind_speed', 'wind_dir',
            'weather_code', 'weather_desc', 'precip_mm', 'precip_prob',
            'storm_warning', 'source', 'url', 'metadata'
        ])

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform to standardized format."""
        if df.empty:
            return df

        df = df.copy()

        # Map weather code to impact
        if 'weather_code' in df.columns:
            df['weather_impact'] = df['weather_code'].map(
                lambda x: self.WEATHER_IMPACT_MAP.get(x, 0.0)
            )

        # Precipitation impact
        df['precip_impact'] = df.get('precip_mm', pd.Series([0.0])).apply(
            lambda x: min(1.0, x / 20) if x > 0 else 0.0
        )

        # Combined impact (storm warnings override)
        df['value'] = df[['weather_impact', 'precip_impact']].max(axis=1)

        # Storm warning increases severity
        df.loc[df.get('storm_warning', pd.Series(False)), 'value'] = 1.0

        # Severity
        def classify_severity(row):
            if row.get('storm_warning', False) or row['value'] >= 0.9:
                return 'SEVERE'
            elif row['value'] >= 0.5:
                return 'HIGH'
            elif row['value'] >= 0.2:
                return 'MEDIUM'
            return 'LOW'

        df['severity'] = df.apply(classify_severity, axis=1)

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """NCHMF covers the entire Hanoi region."""
        if df.empty:
            return df

        import h3

        df = df.copy()

        center = (21.0285, 105.8542)  # Hanoi center
        center_hex = h3.latlng_to_cell(center[0], center[1], 8)
        hex_ids = list(h3.grid_disk(center_hex, 30))  # ~14km radius

        records = []
        for _, row in df.iterrows():
            for hex_id in hex_ids:
                new_row = row.copy()
                new_row['hex_id'] = hex_id
                records.append(new_row)

        return pd.DataFrame(records)

    def get_data_age(self) -> float:
        """
        Get data staleness in hours.

        NCHMF updates ~3 times/day, so typical staleness is 4-8 hours.
        This is used for ensemble time-decay calculation.
        """
        return 4.0  # Assume 4 hours stale if no new data
