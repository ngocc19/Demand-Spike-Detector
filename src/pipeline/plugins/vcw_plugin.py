"""
Visual Crossing Weather (VCW) Plugin
=================================

Plugin for collecting weather data from Visual Crossing Weather API.
Website: https://www.visualcrossing.com/
API Docs: https://www.visualcrossing.com/weather-api

Features:
- Free tier: 1,000 records per day
- Historical data available (great for Phase 0 backfill)
- Both forecast and historical data

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


@PluginRegistry.register("vcw")
class VCWFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting weather data from Visual Crossing Weather API.

    Features:
    - Free tier: 1,000 records/day
    - Historical weather data (excellent for Phase 0 backfill!)
    - 15-day forecast
    - Multiple data fields

    API Key: Set VISUALCROSSING_API_KEY in environment or config
    """

    factor_type = FactorType.WEATHER
    factor_name = "vcw"
    schedule = "0 * * * *"  # Every hour

    BASE_URL = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"

    # VCW weather conditions -> impact values
    WEATHER_IMPACT_MAP = {
        # Clear
        'clear': 0.0,
        'mostly clear': 0.0,
        'partly cloudy': 0.0,
        'partly sunny': 0.0,

        # Cloudy
        'mostly cloudy': 0.0,
        'overcast': 0.0,
        'cloudy': 0.0,

        # Fog/Mist
        'fog': 0.2,
        'mist': 0.2,
        'haze': 0.1,

        # Rain
        'light rain': 0.3,
        'rain': 0.5,
        'moderate rain': 0.5,
        'heavy rain': 0.9,
        'drizzle': 0.3,
        'light drizzle': 0.3,
        'heavy drizzle': 0.5,

        # Thunderstorm
        'thunderstorm': 0.9,
        'thunderstorms': 0.9,
        'thunderstorms possible': 0.85,
        'isolated thunderstorms': 0.8,
        'scattered thunderstorms': 0.85,

        # Snow (not common in Hanoi but included)
        'light snow': 0.4,
        'snow': 0.6,
        'heavy snow': 0.8,
        'flurries': 0.3,

        # Special
        'blowing dust': 0.2,
        'wind': 0.1,
        'breezy': 0.1,
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # API key priority: config > environment > .env file
        self.api_key = (
            config.get('api_key') or
            os.getenv('VISUALCROSSING_API_KEY')
        )
        if not self.api_key:
            logger.warning("VCW API key not found. Set VISUALCROSSING_API_KEY in .env file.")
            self.api_key = "demo"

        # Location
        self.location = config.get('location', 'Hanoi,Vietnam')
        self.latitude = config.get('latitude', 21.0285)
        self.longitude = config.get('longitude', 105.8542)
        self.radius_km = config.get('radius_km', 30)
        self.units = config.get('units', 'metric')

        self.timeout = config.get('timeout_seconds', 15)
        self.forecast_days = config.get('forecast_days', 7)
        self.past_days = config.get('past_days', 0)  # For backfill

    def fetch(self) -> pd.DataFrame:
        """
        Fetch weather data from Visual Crossing API.

        Supports both forecast and historical data.
        """
        data = []

        # Current + Forecast
        try:
            forecast = self._fetch_forecast()
            if not forecast.empty:
                data.append(forecast)
        except Exception as e:
            logger.error(f"VCW forecast failed: {e}")

        # Historical data (for backfill)
        if self.past_days > 0:
            try:
                historical = self._fetch_historical()
                if not historical.empty:
                    data.append(historical)
            except Exception as e:
                logger.error(f"VCW historical failed: {e}")

        if not data:
            return self._create_empty_result()

        return pd.concat(data, ignore_index=True)

    def _fetch_forecast(self) -> pd.DataFrame:
        """Fetch current + forecast weather data."""
        if self.past_days > 0:
            date_range = f"past{self.past_days}days"
        else:
            date_range = f"next{self.forecast_days}days"

        url = f"{self.BASE_URL}/{self.location}/{date_range}"

        params = {
            'unitGroup': self.units,
            'include': 'hours,current',
            'key': self.api_key,
            'contentType': 'json',
        }

        response = requests.get(url, params=params, timeout=self.timeout)

        # Handle demo mode
        if self.api_key == "demo" or response.status_code == 401:
            logger.warning("VCW demo mode - returning synthetic data")
            return self._create_synthetic_data()

        response.raise_for_status()
        data = response.json()

        return self._parse_vcw_response(data)

    def _fetch_historical(self) -> pd.DataFrame:
        """Fetch historical weather data."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.past_days)

        url = f"{self.BASE_URL}/{self.location}/{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"

        params = {
            'unitGroup': self.units,
            'include': 'hours',
            'key': self.api_key,
            'contentType': 'json',
        }

        response = requests.get(url, params=params, timeout=self.timeout)

        if response.status_code == 401:
            return pd.DataFrame()

        response.raise_for_status()
        data = response.json()

        return self._parse_vcw_response(data)

    def _parse_vcw_response(self, data: Dict) -> pd.DataFrame:
        """Parse Visual Crossing JSON response to DataFrame."""
        records = []

        # Current conditions
        if 'currentConditions' in data:
            current = data['currentConditions']
            records.append(self._parse_record(current, datetime.now()))

        # Forecast hours
        for day in data.get('days', []):
            day_date_str = day['datetime']
            day_date = datetime.strptime(day_date_str, '%Y-%m-%d')

            for hour_data in day.get('hours', []):
                # Handle different datetime formats
                hour_str = hour_data.get('datetime', '')
                try:
                    # Try full format first
                    hour_time = datetime.strptime(hour_str, '%Y-%m-%dT%H:%M:%S')
                except ValueError:
                    try:
                        # Try just time format (e.g., '00:00:00')
                        if ':' in hour_str and len(hour_str) == 8:
                            hour_time = day_date.replace(
                                hour=int(hour_str.split(':')[0]),
                                minute=int(hour_str.split(':')[1])
                            )
                        else:
                            # Use day date as fallback
                            hour_time = day_date
                    except:
                        hour_time = day_date

                records.append(self._parse_record(hour_data, hour_time))

        df = pd.DataFrame(records)
        if not df.empty:
            df['source'] = 'VCW'
            df['update_time'] = datetime.now()

        return df

    def _parse_record(self, data: Dict, timestamp: datetime) -> Dict:
        """Parse a single VCW record."""
        conditions = data.get('conditions', '').lower()

        return {
            'datetime': timestamp,
            'temp_c': data.get('temp'),
            'feels_like': data.get('feelslike'),
            'humidity_pct': data.get('humidity'),
            'precip': data.get('precip', 0),
            'precip_prob': data.get('precipprob', 0),
            'wind_speed': data.get('windspeed', 0),
            'wind_dir': data.get('winddir', ''),
            'pressure': data.get('pressure'),
            'cloud_cover': data.get('cloudcover'),
            'visibility': data.get('visibility'),
            'uv_index': data.get('uvindex', 0),
            'weather_code': conditions,
            'weather_conditions': data.get('conditions', ''),
            'source': 'VCW',
        }

    def _create_synthetic_data(self) -> pd.DataFrame:
        """Create synthetic data for demo mode."""
        now = datetime.now()
        records = []

        # Current
        records.append({
            'datetime': now,
            'temp_c': 30.0,
            'feels_like': 33.0,
            'humidity_pct': 75.0,
            'precip': 0.0,
            'precip_prob': 0,
            'wind_speed': 3.0,
            'wind_dir': 'SE',
            'pressure': 1013.0,
            'cloud_cover': 20,
            'visibility': 10.0,
            'uv_index': 7.0,
            'weather_code': 'clear',
            'weather_conditions': 'Clear',
            'source': 'VCW_DEMO',
            'update_time': now,
        })

        # 24-hour forecast
        for hour in range(1, 25):
            forecast_time = now + timedelta(hours=hour)
            hour_of_day = forecast_time.hour

            # Temperature variation
            temp = 30 + 4 * (1 - abs(13 - hour_of_day) / 13)

            # Rain chance in afternoon
            precip = 0.0
            precip_prob = 0
            if 14 <= hour_of_day <= 18:
                precip = 0.5
                precip_prob = 40

            records.append({
                'datetime': forecast_time,
                'temp_c': temp,
                'feels_like': temp + 2,
                'humidity_pct': 75 - (temp - 30),
                'precip': precip,
                'precip_prob': precip_prob,
                'wind_speed': 3.0,
                'wind_dir': 'SE',
                'pressure': 1013.0,
                'cloud_cover': 30 if precip > 0 else 20,
                'visibility': 10.0,
                'uv_index': 7.0 if hour_of_day in range(10, 15) else 3,
                'weather_code': 'rain' if precip > 0 else 'clear',
                'weather_conditions': 'Rain' if precip > 0 else 'Clear',
                'source': 'VCW_DEMO',
                'update_time': now,
            })

        df = pd.DataFrame(records)
        return df

    def _create_empty_result(self) -> pd.DataFrame:
        """Create empty DataFrame."""
        return pd.DataFrame(columns=[
            'datetime', 'temp_c', 'feels_like', 'humidity_pct',
            'precip', 'precip_prob', 'wind_speed', 'wind_dir',
            'pressure', 'cloud_cover', 'visibility', 'uv_index',
            'weather_code', 'weather_conditions', 'source', 'update_time'
        ])

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform to standardized format."""
        if df.empty:
            return df

        df = df.copy()

        # Map conditions to impact
        def get_impact(conditions: str) -> float:
            conditions_lower = conditions.lower()

            # Try exact match first
            if conditions_lower in self.WEATHER_IMPACT_MAP:
                return self.WEATHER_IMPACT_MAP[conditions_lower]

            # Try partial match
            for key, value in self.WEATHER_IMPACT_MAP.items():
                if key in conditions_lower or conditions_lower in key:
                    return value

            # Check for keywords
            if 'thunder' in conditions_lower or 'storm' in conditions_lower:
                return 0.9
            if 'rain' in conditions_lower:
                if 'light' in conditions_lower:
                    return 0.3
                if 'heavy' in conditions_lower:
                    return 0.9
                return 0.5
            if 'snow' in conditions_lower:
                return 0.6
            if 'fog' in conditions_lower or 'mist' in conditions_lower:
                return 0.2

            return 0.0

        df['weather_impact'] = df['weather_conditions'].apply(get_impact)

        # Precipitation impact
        df['precip_mm'] = df['precip'].fillna(0)
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
                'source': 'VCW',
                'weather': r.get('weather_conditions', ''),
                'temp_c': r['temp_c'],
                'humidity': r['humidity_pct'],
                'precip_mm': r.get('precip_mm', 0),
                'wind_speed': r.get('wind_speed', 0),
                'precip_prob': r.get('precip_prob', 0),
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
        return 0.0  # Fresh API data
