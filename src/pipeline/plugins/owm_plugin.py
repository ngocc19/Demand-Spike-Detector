"""
OpenWeatherMap (OWM) Weather Plugin
=================================

Plugin for collecting weather data from OpenWeatherMap API.
Website: https://openweathermap.org/

API Types:
- Current Weather Data: Free tier available
- 5 Day / 3 Hour Forecast: Free tier available

API Key Setup:
1. Copy .env.example to .env
2. Fill in your API key
3. Keys are loaded automatically from .env file
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any
import h3
import logging

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from ..base import BaseFactorPlugin, FactorType, FactorRecord
from ..registry import PluginRegistry

logger = logging.getLogger(__name__)


@PluginRegistry.register("owm")
class OWMFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting weather data from OpenWeatherMap API.

    Features:
    - Current Weather Data API (free)
    - 5 Day / 3 Hour Forecast API (free)
    - Requires API key (free tier: 60 calls/minute)

    API Key: Set OPENWEATHERMAP_API_KEY in environment or config
    """

    factor_type = FactorType.WEATHER
    factor_name = "owm"
    schedule = "0 * * * *"  # Every hour

    BASE_URL = "https://api.openweathermap.org/data/2.5"

    # OWM weather condition codes -> impact values
    # https://openweathermap.org/weather-conditions
    WEATHER_IMPACT_MAP = {
        # Group 2xx: Thunderstorm
        200: 0.9,  # Thunderstorm with light rain
        201: 0.9,  # Thunderstorm with rain
        202: 1.0,  # Thunderstorm with heavy rain
        210: 0.9,  # Light thunderstorm
        211: 0.9,  # Thunderstorm
        212: 1.0,  # Heavy thunderstorm
        221: 1.0,  # Ragged thunderstorm
        230: 0.9,  # Thunderstorm with light drizzle
        231: 0.9,  # Thunderstorm with drizzle
        232: 1.0,  # Thunderstorm with heavy drizzle

        # Group 3xx: Drizzle
        300: 0.3,  # Light intensity drizzle
        301: 0.4,  # Drizzle
        302: 0.5,  # Heavy intensity drizzle
        310: 0.3,  # Light intensity drizzle rain
        311: 0.4,  # Drizzle rain
        312: 0.5,  # Heavy intensity drizzle rain
        313: 0.5,  # Shower rain and drizzle
        314: 0.6,  # Heavy shower rain and drizzle
        321: 0.5,  # Shower drizzle

        # Group 5xx: Rain
        500: 0.3,  # Light rain
        501: 0.5,  # Moderate rain
        502: 0.7,  # Heavy intensity rain
        503: 0.9,  # Very heavy rain
        504: 1.0,  # Extreme rain
        511: 0.8,  # Freezing rain
        520: 0.6,  # Light intensity shower rain
        521: 0.7,  # Shower rain
        522: 0.9,  # Heavy intensity shower rain
        531: 1.0,  # Ragged shower rain

        # Group 6xx: Snow
        600: 0.4,  # Light snow
        601: 0.6,  # Snow
        602: 0.8,  # Heavy snow
        611: 0.5,  # Sleet
        612: 0.6,  # Light shower sleet
        613: 0.7,  # Shower sleet
        615: 0.4,  # Light rain and snow
        616: 0.5,  # Rain and snow
        620: 0.4,  # Light shower snow
        621: 0.6,  # Shower snow
        622: 0.8,  # Heavy shower snow

        # Group 7xx: Atmosphere
        701: 0.2,  # Mist
        711: 0.2,  # Smoke
        721: 0.2,  # Haze
        731: 0.2,  # Sand/ dust whirls
        741: 0.3,  # Fog
        751: 0.2,  # Sand
        761: 0.2,  # Dust
        762: 0.2,  # Volcanic ash
        771: 0.3,  # Squalls
        781: 1.0,  # Tornado

        # Group 800: Clear/Clouds
        800: 0.0,  # Clear sky
        801: 0.0,  # Few clouds
        802: 0.0,  # Scattered clouds
        803: 0.0,  # Broken clouds
        804: 0.0,  # Overcast clouds
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # API key priority: config > environment > .env file
        self.api_key = (
            config.get('api_key') or
            os.getenv('OPENWEATHERMAP_API_KEY')
        )
        if not self.api_key:
            logger.warning("OWM API key not found. Set OPENWEATHERMAP_API_KEY in .env file.")
            self.api_key = "demo"

        # Coordinates
        self.latitude = config.get('latitude', 21.0285)
        self.longitude = config.get('longitude', 105.8542)
        self.city = config.get('city', 'Hanoi,VN')
        self.radius_km = config.get('radius_km', 30)
        self.units = config.get('units', 'metric')  # metric = Celsius

        self.timeout = config.get('timeout_seconds', 10)

    def fetch(self) -> pd.DataFrame:
        """
        Fetch weather data from OpenWeatherMap API.

        Uses both Current Weather and 5 Day/3 Hour Forecast APIs.
        """
        data = []

        # Current weather
        try:
            current = self._fetch_current()
            if not current.empty:
                data.append(current)
        except Exception as e:
            logger.error(f"OWM current weather failed: {e}")

        # 5-day forecast (3-hour intervals)
        try:
            forecast = self._fetch_forecast()
            if not forecast.empty:
                data.append(forecast)
        except Exception as e:
            logger.error(f"OWM forecast failed: {e}")

        if not data:
            return self._create_empty_result()

        return pd.concat(data, ignore_index=True)

    def _fetch_current(self) -> pd.DataFrame:
        """Fetch current weather data."""
        url = f"{self.BASE_URL}/weather"
        params = {
            'q': self.city,
            'appid': self.api_key,
            'units': self.units,
        }

        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        now = datetime.now()

        # Parse current weather
        weather_code = data.get('weather', [{}])[0].get('id', 800)

        return pd.DataFrame([{
            'datetime': now,
            'temp_c': data.get('main', {}).get('temp'),
            'feels_like': data.get('main', {}).get('feels_like'),
            'humidity_pct': data.get('main', {}).get('humidity'),
            'pressure_hpa': data.get('main', {}).get('pressure'),
            'wind_speed': data.get('wind', {}).get('speed', 0),
            'wind_deg': data.get('wind', {}).get('deg', 0),
            'clouds_pct': data.get('clouds', {}).get('all', 0),
            'visibility_m': data.get('visibility', 10000),
            'weather_code': weather_code,
            'weather_main': data.get('weather', [{}])[0].get('main', ''),
            'weather_desc': data.get('weather', [{}])[0].get('description', ''),
            'rain_1h': data.get('rain', {}).get('1h', 0),
            'snow_1h': data.get('snow', {}).get('1h', 0),
            'source': 'OWM_CURRENT',
            'update_time': datetime.fromtimestamp(data.get('dt', 0)),
        }])

    def _fetch_forecast(self) -> pd.DataFrame:
        """Fetch 5-day/3-hour forecast."""
        url = f"{self.BASE_URL}/forecast"
        params = {
            'q': self.city,
            'appid': self.api_key,
            'units': self.units,
        }

        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        records = []
        for item in data.get('list', []):
            weather_code = item.get('weather', [{}])[0].get('id', 800)

            records.append({
                'datetime': datetime.fromtimestamp(item.get('dt', 0)),
                'temp_c': item.get('main', {}).get('temp'),
                'feels_like': item.get('main', {}).get('feels_like'),
                'humidity_pct': item.get('main', {}).get('humidity'),
                'pressure_hpa': item.get('main', {}).get('pressure'),
                'wind_speed': item.get('wind', {}).get('speed', 0),
                'wind_deg': item.get('wind', {}).get('deg', 0),
                'clouds_pct': item.get('clouds', {}).get('all', 0),
                'visibility_m': item.get('visibility', 10000),
                'weather_code': weather_code,
                'weather_main': item.get('weather', [{}])[0].get('main', ''),
                'weather_desc': item.get('weather', [{}])[0].get('description', ''),
                'rain_3h': item.get('rain', {}).get('3h', 0),
                'snow_3h': item.get('snow', {}).get('3h', 0),
                'pop': item.get('pop', 0),  # Probability of precipitation
                'source': 'OWM_FORECAST',
                'update_time': datetime.now(),
            })

        return pd.DataFrame(records)

    def _create_empty_result(self) -> pd.DataFrame:
        """Create empty DataFrame with correct schema."""
        return pd.DataFrame(columns=[
            'datetime', 'temp_c', 'feels_like', 'humidity_pct',
            'pressure_hpa', 'wind_speed', 'wind_deg', 'clouds_pct',
            'visibility_m', 'weather_code', 'weather_main', 'weather_desc',
            'rain_1h', 'rain_3h', 'snow_1h', 'snow_3h', 'pop',
            'source', 'update_time'
        ])

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform to standardized format with impact scores."""
        if df.empty:
            return df

        df = df.copy()

        # Map weather code to impact
        df['weather_impact'] = df['weather_code'].map(
            lambda x: self.WEATHER_IMPACT_MAP.get(x, 0.0)
        )

        # Precipitation impact
        precip_cols = ['rain_1h', 'rain_3h', 'snow_1h', 'snow_3h']
        df['precip_mm'] = df[precip_cols].max(axis=1)
        df['precip_impact'] = df['precip_mm'].apply(
            lambda x: min(1.0, x / 20) if x > 0 else 0.0
        )

        # Combined impact
        df['value'] = df[['weather_impact', 'precip_impact']].max(axis=1)

        # Severity
        def classify_severity(row):
            if row['value'] >= 0.8:
                return 'SEVERE'
            elif row['value'] >= 0.5:
                return 'HIGH'
            elif row['value'] >= 0.2:
                return 'MEDIUM'
            return 'LOW'

        df['severity'] = df.apply(classify_severity, axis=1)

        # Metadata
        df['metadata'] = df.apply(
            lambda r: {
                'source': 'OWM',
                'weather_code': r['weather_code'],
                'weather_desc': r.get('weather_desc', ''),
                'temp_c': r['temp_c'],
                'humidity': r['humidity_pct'],
                'wind_speed': r['wind_speed'],
                'precip_mm': r['precip_mm'],
            },
            axis=1
        )

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """Weather affects the entire region."""
        if df.empty:
            return df

        df = df.copy()

        center = (self.latitude, self.longitude)
        center_hex = h3.latlng_to_cell(center[0], center[1], 8)
        hex_ids = list(h3.grid_disk(center_hex, int(self.radius_km * 1000 / 460)))

        records = []
        for _, row in df.iterrows():
            for hex_id in hex_ids:
                new_row = row.copy()
                new_row['hex_id'] = hex_id
                records.append(new_row)

        return pd.DataFrame(records)

    def get_data_age(self) -> float:
        """Get data staleness in hours for ensemble."""
        return 0.0  # Fresh data from API
