"""
NCHMF API + Scraper Plugin
==========================

Plugin for collecting weather data from NCHMF (National Center for Hydro-Meteorological Forecasting).

Data Sources:
1. NCHMF Weather API (PRIMARY):
   - https://www.khituongvietnam.gov.vn/WeatherApiService/api/Weather?code={2-73}
   - Code 2-73 maps to weather stations across Vietnam
   - Returns: temperature, weather text, humidity, wind, location

2. HTML Scraping (SECONDARY):
   - https://nchmf.gov.vn/Kttvsite/vi-VN/1/ha-noi-w29.html (Hanoi station)
   - https://nchmf.gov.vn/kttvsite/vi-VN/1/bao-ap-thap-nhiet-doi-2049-15.html (Storm warnings)
   - https://nchmf.gov.vn/kttvsite/vi-VN/1/mua-lon-mua-lon-dien-rong-2053-15.html (Heavy rain)
   - https://nchmf.gov.vn/kttvsite/vi-VN/1/dong-to-loc-voi-rong-2052-15.html (Thunderstorm)

Weather Station Codes (2-73):
- 2-15: Northern region (including Hanoi area)
- 16-30: North Central region
- 31-45: Central region
- 46-60: Central Highlands
- 61-73: Southern region

Hanoi Area Codes (for demand spike detection):
- 29: Hà Nội (Hanoi)
- 64: Tân Phong (Lai Châu - near north)
- Other nearby: 26, 27, 28, 30, 31, etc.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
import re
import logging
import time

from ..base import BaseFactorPlugin, FactorType, FactorRecord
from ..registry import PluginRegistry

logger = logging.getLogger(__name__)


@PluginRegistry.register("nchmf_api")
class NCHMFApiPlugin(BaseFactorPlugin):
    """
    NCHMF Plugin with real API + HTML scraping.

    Primary Source: NCHMF Weather API
    Secondary Source: HTML pages for warnings and bulletins

    Features:
    - Fetch all 72 weather stations across Vietnam
    - Get Hanoi-area specific data
    - Scrape weather warnings (storms, heavy rain, thunderstorm)
    - Get 10-day forecasts
    """

    factor_type = FactorType.WEATHER
    factor_name = "nchmf_api"
    schedule = "0 */3 * * *"  # Every 3 hours (matches NCHMF update frequency)

    # NCHMF Weather API
    API_BASE_URL = "https://www.khituongvietnam.gov.vn/WeatherApiService"
    WEATHER_API = "/api/Weather"

    # NCHMF HTML Pages
    HANOI_PAGE = "https://nchmf.gov.vn/Kttvsite/vi-VN/1/ha-noi-w29.html"
    STORM_PAGE = "https://nchmf.gov.vn/kttvsite/vi-VN/1/bao-ap-thap-nhiet-doi-2049-15.html"
    HEAVY_RAIN_PAGE = "https://nchmf.gov.vn/kttvsite/vi-VN/1/mua-lon-mua-lon-dien-rong-2053-15.html"
    THUNDER_PAGE = "https://nchmf.gov.vn/kttvsite/vi-VN/1/dong-to-loc-voi-rong-2052-15.html"
    COLD_PAGE = "https://nchmf.gov.vn/kttvsite/vi-VN/1/khong-khi-lanh-2050-15.html"
    HOT_PAGE = "https://nchmf.gov.vn/kttvsite/vi-VN/1/nang-nong-2051-15.html"

    # Hanoi area station codes (Northern region)
    HANOI_CODES = list(range(2, 16))  # 2-15

    # Weather condition to impact mapping
    WEATHER_IMPACT_MAP = {
        # Clear/Sunny
        'nắng': 0.0, 'trời nắng': 0.0, 'ít mây': 0.0,
        'nắng ráo': 0.0, 'trời quang': 0.0,

        # Cloudy
        'nhiều mây': 0.1, 'âm u': 0.1, 'mây đen': 0.2,
        'mây': 0.1, 'có mây': 0.1,

        # Fog/Mist
        'sương mù': 0.2, 'sương': 0.2, 'mù': 0.2,

        # Light rain
        'mưa nhỏ': 0.3, 'mưa phùn': 0.2, 'mưa rào nhẹ': 0.3,

        # Moderate rain
        'mưa rào': 0.5, 'có mưa': 0.5, 'mưa': 0.5,
        'mưa rào và dông': 0.6,

        # Heavy rain
        'mưa to': 0.7, 'mưa lớn': 0.8, 'mưa nhiều': 0.8,
        'mưa lớn diện rộng': 0.9, 'mưa rất lớn': 1.0,

        # Thunderstorm
        'giông': 0.8, 'dông': 0.8, 'có giông': 0.8,
        'mưa giông': 0.8, 'dông và sét': 0.9,
        'bão': 1.0, 'áp thấp': 0.9,

        # Special
        'nắng nóng': 0.4, 'nhiệt độ cao': 0.3,
        'rét': 0.1, 'lạnh': 0.1,
    }

    # Vietnamese weather descriptions -> WMO codes
    WEATHER_CODE_MAP = {
        'nắng': 0, 'trời nắng': 0, 'ít mây': 1,
        'nhiều mây': 3, 'âm u': 3, 'mây': 2,
        'sương mù': 45, 'sương': 45,
        'mưa nhỏ': 51, 'mưa phùn': 51,
        'mưa rào': 61, 'có mưa': 61, 'mưa': 61,
        'mưa to': 63, 'mưa lớn': 65,
        'giông': 95, 'dông': 95, 'có giông': 95,
        'bão': 99, 'áp thấp': 95,
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.timeout = config.get('timeout_seconds', 30)
        self.station_codes = config.get('station_codes', list(range(2, 74)))  # All 72 stations
        self.hanoi_only = config.get('hanoi_only', False)
        self.rate_limit = config.get('rate_limit', 0.5)  # seconds between API calls
        self.fetch_warnings = config.get('fetch_warnings', True)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/html',
            'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
            'Referer': 'https://www.khituongvietnam.gov.vn/',
        })

    def fetch(self) -> pd.DataFrame:
        """
        Fetch weather data from NCHMF.

        Sources:
        1. Weather API for all stations
        2. HTML scraping for warnings (optional)
        """
        all_records = []

        # 1. Fetch from NCHMF Weather API
        api_records = self._fetch_api_all_stations()
        if not api_records.empty:
            all_records.append(api_records)

        # 2. Fetch Hanoi-specific page data
        hanoi_records = self._fetch_hanoi_page()
        if not hanoi_records.empty:
            all_records.append(hanoi_records)

        # 3. Fetch warnings if enabled
        if self.fetch_warnings:
            warning_records = self._fetch_warnings()
            if not warning_records.empty:
                all_records.append(warning_records)

        if not all_records:
            return self._create_empty_result()

        return pd.concat(all_records, ignore_index=True)

    def _fetch_api_all_stations(self) -> pd.DataFrame:
        """
        Fetch weather data from NCHMF Weather API for all stations.

        API: https://www.khituongvietnam.gov.vn/WeatherApiService/api/Weather?code={2-73}

        Response:
        [{
            "Current_Temp": 26.0,
            "Weather_Text": "Ít mây, trời nắng",
            "Url_Path": "Upload/WeatherSymbol/2008/8/22/340.png",
            "Name": "Tân Phong (Lai Châu)",
            "Humidity": 79.0,
            "Wind": "Gió nam - tốc độ: 2 m/s",
            "DateObservation": "2026-10-04T00:00:00",
            "timeobservation": 10
        }]
        """
        records = []
        codes_to_fetch = self.HANOI_CODES if self.hanoi_only else self.station_codes

        logger.info(f"Fetching NCHMF API for {len(codes_to_fetch)} stations...")

        for code in codes_to_fetch:
            try:
                url = f"{self.API_BASE_URL}{self.WEATHER_API}?code={code}"
                response = self.session.get(url, timeout=self.timeout)

                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        station_data = data[0]
                        records.append(self._parse_api_record(station_data, code))

                time.sleep(self.rate_limit)  # Rate limiting

            except requests.RequestException as e:
                logger.debug(f"NCHMF API code={code} failed: {e}")
                continue
            except Exception as e:
                logger.error(f"Error parsing NCHMF API response for code={code}: {e}")
                continue

        if not records:
            logger.warning("No data from NCHMF API")
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df['source'] = 'NCHMF_API'
        df['update_time'] = datetime.now()

        logger.info(f"NCHMF API: Fetched {len(df)} station records")
        return df

    def _parse_api_record(self, data: Dict, code: int) -> Dict:
        """Parse a single API record."""
        # Parse wind information
        wind_speed = 0
        wind_dir = 'N'
        wind_text = data.get('Wind', '')

        # Extract wind speed: "Gió nam - tốc độ: 2 m/s"
        speed_match = re.search(r'(\d+)\s*m/s', wind_text)
        if speed_match:
            wind_speed = int(speed_match.group(1))

        # Extract wind direction
        dir_map = {
            'bắc': 'N', 'nam': 'S', 'đông': 'E', 'tây': 'W',
            'đông bắc': 'NE', 'tây bắc': 'NW',
            'đông nam': 'SE', 'tây nam': 'SW',
        }
        wind_text_lower = wind_text.lower()
        for keyword, direction in dir_map.items():
            if keyword in wind_text_lower:
                wind_dir = direction
                break

        # Parse temperature
        temp = data.get('Current_Temp')
        if temp is None:
            temp = 30.0

        # Parse weather text for impact
        weather_text = data.get('Weather_Text', '')
        weather_impact = self._get_weather_impact(weather_text)
        weather_code = self._map_text_to_code(weather_text)

        # Parse observation time
        obs_time = data.get('timeobservation', 0)
        obs_date = data.get('DateObservation', '')
        try:
            if obs_date:
                obs_datetime = datetime.strptime(obs_date[:10], '%Y-%m-%d')
                obs_datetime = obs_datetime.replace(hour=obs_time if obs_time < 24 else 0)
            else:
                obs_datetime = datetime.now()
        except:
            obs_datetime = datetime.now()

        return {
            'datetime': obs_datetime,
            'station_code': code,
            'station_name': data.get('Name', f'Station_{code}'),
            'temp_c': float(temp) if temp else 30.0,
            'humidity_pct': float(data.get('Humidity', 75)),
            'wind_speed': float(wind_speed),
            'wind_dir': wind_dir,
            'weather_text': weather_text,
            'weather_code': weather_code,
            'weather_impact': weather_impact,
            'wind_description': wind_text,
            'icon_path': data.get('Url_Path', ''),
            'is_hanoi_area': code in self.HANOI_CODES,
        }

    def _fetch_hanoi_page(self) -> pd.DataFrame:
        """
        Fetch weather data from Hanoi station HTML page.

        Returns forecast data and current conditions.
        """
        records = []

        try:
            response = self.session.get(self.HANOI_PAGE, timeout=self.timeout)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract current conditions
            current = self._parse_hanoi_current(soup)
            if current:
                records.append(current)

            # Extract 10-day forecast
            forecast_records = self._parse_hanoi_forecast(soup)
            records.extend(forecast_records)

        except requests.RequestException as e:
            logger.warning(f"Failed to fetch Hanoi page: {e}")
        except Exception as e:
            logger.error(f"Error parsing Hanoi page: {e}")

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df['source'] = 'NCHMF_HTML'
        df['update_time'] = datetime.now()

        return df

    def _parse_hanoi_current(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Parse current weather conditions from Hanoi page."""
        current_time = datetime.now()

        # Look for weather text
        weather_text = ''
        text_elem = soup.find(string=re.compile(r'Nhiều mây|Có mây|Nắng|Mưa'))
        if text_elem:
            weather_text = text_elem.strip()

        # Look for temperature
        temp = 30.0
        temp_elems = soup.find_all(class_='large-temp')
        for elem in temp_elems:
            try:
                temp = float(re.search(r'(\d+)', elem.get_text()).group(1))
                break
            except:
                continue

        # Look for humidity
        humidity = 75.0
        humidity_elems = soup.find_all(string=re.compile(r'độ ẩm|Độ ẩm'))
        for elem in humidity_elems:
            match = re.search(r'(\d+)\s*%', elem)
            if match:
                humidity = float(match.group(1))
                break

        weather_impact = self._get_weather_impact(weather_text)
        weather_code = self._map_text_to_code(weather_text)

        return {
            'datetime': current_time,
            'station_code': 29,  # Hanoi code
            'station_name': 'Hà Nội',
            'temp_c': temp,
            'humidity_pct': humidity,
            'wind_speed': 0,
            'wind_dir': 'E',
            'weather_text': weather_text,
            'weather_code': weather_code,
            'weather_impact': weather_impact,
            'wind_description': '',
            'is_hanoi_area': True,
        }

    def _parse_hanoi_forecast(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse 10-day forecast from Hanoi page."""
        records = []
        current_time = datetime.now()

        # Find forecast items
        forecast_items = soup.find_all(class_='item-days-wt')

        for i, item in enumerate(forecast_items[:10]):
            try:
                # Extract date
                date_elem = item.find(class_='date-wt')
                date_text = date_elem.get_text() if date_elem else ''
                date_match = re.search(r'(\d{2})/(\d{2})/(\d{4})', date_text)
                if date_match:
                    day, month, year = date_match.groups()
                    forecast_date = datetime(int(year), int(month), int(day))
                else:
                    forecast_date = current_time + timedelta(days=i+1)

                # Extract temperatures
                large_temp = item.find(class_='large-temp')
                temp_high = float(re.search(r'(\d+)', large_temp.get_text()).group(1)) if large_temp else 32

                small_temps = item.find_all(class_='small-temp')
                temp_low = temp_high - 6  # Default if not found
                for st in small_temps:
                    text = st.get_text()
                    if '°' in text and temp_high not in [float(x) for x in re.findall(r'\d+', text)]:
                        try:
                            temp_low = float(re.search(r'(\d+)', text).group(1))
                        except:
                            pass
                        break

                # Extract weather description
                text_elem = item.find(class_='text-temp')
                weather_text = text_elem.get_text().strip() if text_elem else ''

                # Extract wind
                wind_speed = 0
                wind_elems = item.find_all(class_='small-temp')
                for elem in wind_elems:
                    text = elem.get_text()
                    if 'm/s' in text:
                        match = re.search(r'(\d+)m/s', text)
                        if match:
                            wind_speed = float(match.group(1))
                        break

                weather_impact = self._get_weather_impact(weather_text)
                weather_code = self._map_text_to_code(weather_text)

                records.append({
                    'datetime': forecast_date,
                    'station_code': 29,
                    'station_name': 'Hà Nội',
                    'temp_c': (temp_high + temp_low) / 2,
                    'temp_high': temp_high,
                    'temp_low': temp_low,
                    'humidity_pct': 75,
                    'wind_speed': wind_speed,
                    'wind_dir': 'E',
                    'weather_text': weather_text,
                    'weather_code': weather_code,
                    'weather_impact': weather_impact,
                    'is_forecast': True,
                    'is_hanoi_area': True,
                })

            except Exception as e:
                logger.debug(f"Error parsing forecast day {i}: {e}")
                continue

        return records

    def _fetch_warnings(self) -> pd.DataFrame:
        """
        Fetch weather warnings from NCHMF warning pages.

        Pages:
        - Storm/typhoon warnings
        - Heavy rain warnings
        - Thunderstorm warnings
        - Cold spell warnings
        - Heat wave warnings
        """
        records = []
        current_time = datetime.now()

        pages = [
            ('storm', self.STORM_PAGE),
            ('heavy_rain', self.HEAVY_RAIN_PAGE),
            ('thunderstorm', self.THUNDER_PAGE),
            ('cold', self.COLD_PAGE),
            ('heat', self.HOT_PAGE),
        ]

        for warning_type, url in pages:
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                response.encoding = 'utf-8'

                soup = BeautifulSoup(response.text, 'html.parser')

                # Extract warning content
                warning_data = self._parse_warning_page(soup, warning_type)
                if warning_data:
                    warning_data['datetime'] = current_time
                    warning_data['source'] = f'NCHMF_WARNING_{warning_type}'
                    records.append(warning_data)

                time.sleep(0.5)  # Rate limiting

            except Exception as e:
                logger.debug(f"Failed to fetch {warning_type} warnings: {e}")
                continue

        if not records:
            return pd.DataFrame()

        return pd.DataFrame(records)

    def _parse_warning_page(self, soup: BeautifulSoup, warning_type: str) -> Optional[Dict]:
        """Parse warning content from HTML page."""
        # Find main content area
        content = soup.find('div', class_='content-waring') or soup.find('div', class_='content-tt')

        if not content:
            # Try to find any text content
            content = soup.find('body')

        if not content:
            return None

        text = content.get_text(separator=' ', strip=True)

        # Check if there's actual warning content
        has_warning = self._check_warning_exists(text, warning_type)

        # Impact values for warnings
        impact_map = {
            'storm': 1.0,
            'heavy_rain': 0.8,
            'thunderstorm': 0.9,
            'cold': 0.2,
            'heat': 0.3,
        }

        return {
            'warning_type': warning_type,
            'warning_text': text[:500] if len(text) > 500 else text,
            'has_warning': has_warning,
            'warning_impact': impact_map.get(warning_type, 0.5) if has_warning else 0,
            'is_warning': has_warning,
        }

    def _check_warning_exists(self, text: str, warning_type: str) -> bool:
        """Check if warning content exists on the page."""
        text_lower = text.lower()

        # Keywords that indicate an active warning
        warning_keywords = {
            'storm': ['bão', 'áp thấp nhiệt đới', 'cảnh báo bão'],
            'heavy_rain': ['mưa lớn', 'mưa to', 'mưa rất lớn', 'cảnh báo mưa'],
            'thunderstorm': ['dông', 'tố', 'lốc', 'giông', 'cảnh báo giông'],
            'cold': ['không khí lạnh', 'rét đậm', 'cảnh báo rét', 'sự tràn'],
            'heat': ['nắng nóng', 'cảnh báo nắng', 'nhiệt độ cao'],
        }

        keywords = warning_keywords.get(warning_type, [])

        # Count keyword occurrences
        count = sum(1 for kw in keywords if kw in text_lower)

        # Threshold: at least 2 mentions to consider it an active warning
        return count >= 2

    def _get_weather_impact(self, weather_text: str) -> float:
        """Map Vietnamese weather text to impact score."""
        if not weather_text:
            return 0.0

        text_lower = weather_text.lower()

        # Check each pattern
        for pattern, impact in self.WEATHER_IMPACT_MAP.items():
            if pattern in text_lower:
                return impact

        return 0.0

    def _map_text_to_code(self, weather_text: str) -> int:
        """Map Vietnamese weather text to WMO code."""
        if not weather_text:
            return 0

        text_lower = weather_text.lower()

        for pattern, code in self.WEATHER_CODE_MAP.items():
            if pattern in text_lower:
                return code

        return 0

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform to standardized format."""
        if df.empty:
            return df

        df = df.copy()

        # Ensure required columns exist
        if 'weather_impact' not in df.columns:
            df['weather_impact'] = df['weather_text'].apply(self._get_weather_impact)

        if 'weather_code' not in df.columns:
            df['weather_code'] = df['weather_text'].apply(self._map_text_to_code)

        # Calculate precip impact from humidity (proxy)
        df['precip_impact'] = ((100 - df['humidity_pct']) / 100).clip(0, 1)

        # Combined impact
        df['value'] = df[['weather_impact', 'precip_impact']].max(axis=1)

        # Severity classification
        def classify_severity(row):
            value = row.get('value', 0)
            warning_impact = row.get('warning_impact', 0)

            # If there's an active warning, increase severity
            if row.get('is_warning') or warning_impact > 0:
                return 'SEVERE'

            if value >= 0.8:
                return 'SEVERE'
            elif value >= 0.5:
                return 'HIGH'
            elif value >= 0.2:
                return 'MEDIUM'
            return 'LOW'

        df['severity'] = df.apply(classify_severity, axis=1)

        # Metadata
        df['metadata'] = df.apply(
            lambda r: {
                'source': 'NCHMF',
                'station': r.get('station_name', ''),
                'station_code': r.get('station_code', ''),
                'weather_text': r.get('weather_text', ''),
                'temp_c': r.get('temp_c', 0),
                'humidity': r.get('humidity_pct', 0),
                'wind_speed': r.get('wind_speed', 0),
                'is_hanoi': r.get('is_hanoi_area', False),
            },
            axis=1
        )

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map weather data to H3 hexagons."""
        if df.empty:
            return df

        import h3

        df = df.copy()

        # Station coordinates lookup (approximate)
        station_coords = self._get_station_coordinates()

        records = []
        for _, row in df.iterrows():
            station_code = row.get('station_code')

            # Get coordinates for this station
            coords = station_coords.get(station_code, (21.0285, 105.8542))  # Default to Hanoi

            # If we have coordinates, map to hex
            lat, lon = coords
            if lat and lon:
                try:
                    hex_id = h3.latlng_to_cell(lat, lon, 8)
                    row['hex_id'] = hex_id
                    row['latitude'] = lat
                    row['longitude'] = lon
                except:
                    row['hex_id'] = None
                    row['latitude'] = lat
                    row['longitude'] = lon
            else:
                row['hex_id'] = None

            records.append(row)

        return pd.DataFrame(records)

    def _get_station_coordinates(self) -> Dict[int, tuple]:
        """Get approximate coordinates for NCHMF stations."""
        # Based on station codes 2-73
        # This is a simplified mapping - actual coordinates would need verification
        return {
            # Northern region (codes 2-15)
            2: (21.5833, 105.8500),   # Sa Pa, Lào Cai
            3: (22.2500, 103.9000),   # Mường Khong, Điện Biên
            4: (21.4500, 103.9500),   # Tuần Giáo, Điện Biên
            5: (21.8167, 103.0500),   # Lai Châu
            6: (22.8000, 104.9833),   # Hà Giang
            7: (22.3833, 103.4500),   # Bắc Hà, Lào Cai
            8: (21.7167, 105.1000),   # Tuyên Quang
            9: (21.5167, 105.8167),   # Thái Nguyên
            10: (21.8167, 106.2833),  # Bắc Kạn
            11: (21.9667, 106.4167),  # Cao Bằng
            12: (22.1333, 106.9000),  # Lạng Sơn
            13: (22.0500, 105.3000),  # Vĩnh Phúc
            14: (21.3000, 105.5833),  # Phú Thọ
            15: (21.2167, 105.8167),  # Sơn La
            # North Central (codes 16-30)
            16: (19.8667, 105.7833),  # Thanh Hóa
            17: (19.2500, 105.7667),  # Nghệ An
            18: (18.6667, 105.7833),  # Hà Tĩnh
            19: (18.1833, 106.0500),  # Quảng Bình
            20: (17.5833, 106.6000),  # Quảng Trị
            21: (16.4500, 107.5833),  # Thừa Thiên Huế
            22: (16.0667, 108.2167),  # Đà Nẵng
            23: (15.5833, 108.4833),  # Tam Kỳ, Quảng Nam
            24: (15.8833, 108.3333),  # Hội An, Quảng Nam
            25: (15.7333, 108.2500),  # Quảng Ngãi
            26: (18.0333, 106.0167),  # Hà Nội area (alternate)
            27: (21.0285, 105.8542),  # Hà Nội
            28: (20.8667, 106.6833),  # Hải Phòng
            29: (21.0285, 105.8542),  # Hà Nội (main)
            30: (20.9500, 107.0500),  # Quảng Ninh
            31: (21.0500, 105.7500),  # Bắc Ninh
            32: (20.8833, 106.0500),  # Hưng Yên
            33: (20.7500, 106.1500),  # Hải Dương
            34: (20.6167, 106.2833),  # Thái Bình
            35: (20.2500, 106.3333),  # Nam Định
            36: (19.8333, 105.7667),  # Ninh Bình
            37: (19.9667, 105.4500),  # Thanh Hóa (alternate)
            38: (19.8000, 105.7667),  # Thanh Hóa
            39: (19.5000, 105.7667),  # Thanh Hóa
            40: (19.3000, 105.7000),  # Thanh Hóa
        }

    def get_data_age(self) -> float:
        """Get data staleness in hours."""
        return 3.0  # NCHMF updates ~3 times/day

    def get_station_summary(self, df: pd.DataFrame) -> Dict:
        """Get summary of station data."""
        if df.empty:
            return {}

        hanoi_data = df[df.get('is_hanoi_area', pd.Series([False]*len(df))).fillna(False)] if 'is_hanoi_area' in df.columns else pd.DataFrame()

        return {
            'total_stations': df['station_code'].nunique() if 'station_code' in df.columns else len(df),
            'hanoi_stations': len(hanoi_data),
            'avg_temp': round(df['temp_c'].mean(), 1) if 'temp_c' in df.columns else None,
            'avg_humidity': round(df['humidity_pct'].mean(), 1) if 'humidity_pct' in df.columns else None,
            'max_impact': round(df['weather_impact'].max(), 2) if 'weather_impact' in df.columns else 0,
            'warnings': df['is_warning'].sum() if 'is_warning' in df.columns else 0,
        }

    def _create_empty_result(self) -> pd.DataFrame:
        """Create empty DataFrame."""
        return pd.DataFrame(columns=[
            'datetime', 'station_code', 'station_name', 'temp_c', 'humidity_pct',
            'wind_speed', 'wind_dir', 'weather_text', 'weather_code',
            'weather_impact', 'precip_impact', 'value', 'severity',
            'is_hanoi_area', 'source', 'update_time'
        ])
