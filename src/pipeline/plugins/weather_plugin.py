"""
Weather Factor Plugin
====================

Plugin for collecting weather data from Open-Meteo API.
Open-Meteo is free and does not require an API key.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any
import h3

from ..base import BaseFactorPlugin, FactorType, FactorRecord
from ..registry import PluginRegistry


@PluginRegistry.register("weather")
class WeatherFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting weather data from Open-Meteo API.

    Features:
    - Free API, no API key required
    - Hourly forecasts up to 7 days
    - Historical data with past_days parameter
    """

    factor_type = FactorType.WEATHER
    factor_name = "weather"
    schedule = "0 * * * *"  # Every hour

    # Mapping Open-Meteo weather codes -> impact values
    # Based on demand impact analysis
    WEATHER_IMPACT_MAP = {
        0: 0.0,    # Clear sky
        1: 0.0,    # Mainly clear
        2: 0.0,    # Partly cloudy
        3: 0.0,    # Overcast
        45: 0.2,   # Fog
        48: 0.2,   # Depositing rime fog
        51: 0.3,   # Light drizzle
        53: 0.5,   # Moderate drizzle
        55: 0.7,   # Dense drizzle
        56: 0.5,   # Light freezing drizzle
        57: 0.7,   # Dense freezing drizzle
        61: 0.5,   # Slight rain
        63: 0.7,   # Moderate rain
        65: 0.9,   # Heavy rain
        66: 0.6,   # Light freezing rain
        67: 0.8,   # Heavy freezing rain
        71: 0.4,   # Slight snow
        73: 0.6,   # Moderate snow
        75: 0.8,   # Heavy snow
        77: 0.5,   # Snow grains
        80: 0.7,   # Slight rain showers
        81: 0.85,  # Moderate rain showers
        82: 1.0,   # Violent rain showers
        85: 0.6,   # Slight snow showers
        86: 0.8,   # Heavy snow showers
        95: 0.9,   # Thunderstorm
        96: 1.0,   # Thunderstorm with slight hail
        99: 1.0,   # Thunderstorm with heavy hail
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = "https://api.open-meteo.com/v1/forecast"

        # Default coordinates: Hanoi
        self.latitude = config.get('latitude', 21.0285)
        self.longitude = config.get('longitude', 105.8542)
        self.radius_km = config.get('radius_km', 30)
        self.timezone = config.get('timezone', 'Asia/Ho_Chi_Minh')
        self.forecast_days = config.get('forecast_days', 7)
        self.past_days = config.get('past_days', 0)  # For backfill

    def fetch(self) -> pd.DataFrame:
        """Fetch weather data from Open-Meteo API."""
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
            "forecast_days": self.forecast_days,
            "timezone": self.timezone,
        }

        # Add past_days for backfill (historical data)
        if self.past_days > 0:
            params["past_days"] = self.past_days

        # Handle rate limiting with retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(self.base_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                break
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Weather API failed after {max_retries} attempts: {e}")
                print(f"[Weather] Retry {attempt + 1} after error: {e}")

        # Parse response
        hourly = data['hourly']
        df = pd.DataFrame({
            'datetime': pd.to_datetime(hourly['time']),
            'temp_c': hourly['temperature_2m'],
            'humidity_pct': hourly['relative_humidity_2m'],
            'precip_mm': hourly['precipitation'],
            'weather_code': hourly['weather_code'],
        })

        return df

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform raw weather data -> normalized impact score."""
        df = df.copy()

        # Map weather code -> impact value
        df['weather_impact'] = df['weather_code'].map(self.WEATHER_IMPACT_MAP).fillna(0)

        # Map precipitation -> additional impact (log scale for smoothing)
        df['precip_impact'] = df['precip_mm'].apply(
            lambda x: min(1.0, x / 20) if x > 0 else 0.0
        )

        # Combined weather impact score (use max of weather code or precipitation)
        df['value'] = df[['weather_impact', 'precip_impact']].max(axis=1)

        # Severity classification
        def classify_severity(row):
            if row['value'] >= 0.8:
                return 'SEVERE'
            elif row['value'] >= 0.5:
                return 'HIGH'
            elif row['value'] >= 0.2:
                return 'MEDIUM'
            else:
                return 'LOW'

        df['severity'] = df.apply(classify_severity, axis=1)
        df['metadata'] = df.apply(
            lambda r: {
                'temp_c': r['temp_c'],
                'humidity': r['humidity_pct'],
                'precip_mm': r['precip_mm'],
                'weather_code': r['weather_code']
            },
            axis=1
        )

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Weather affects the entire city.

        Creates H3 hex_id coverage for the configured radius.
        """
        df = df.copy()

        # Get center coordinates
        center = (self.latitude, self.longitude)

        # Calculate H3 coverage (resolution 8 = ~460m hex, resolution 9 = ~230m)
        # Approximate: radius_km / 0.46 km per hex at resolution 8
        hex_count = int(self.radius_km * 1000 / 460)
        center_hex = h3.latlng_to_cell(center[0], center[1], 8)
        hex_ids = list(h3.grid_disk(center_hex, hex_count))

        # Expand df: each datetime has impact for ALL hexes in coverage
        records = []
        for _, row in df.iterrows():
            for hex_id in hex_ids:
                new_row = row.copy()
                new_row['hex_id'] = hex_id
                records.append(new_row)

        return pd.DataFrame(records)

    def get_h3_coverage(self) -> List[str]:
        """Get the H3 hex coverage for this configuration."""
        center = (self.latitude, self.longitude)
        hex_count = int(self.radius_km * 1000 / 460)
        center_hex = h3.latlng_to_cell(center[0], center[1], 8)
        return list(h3.grid_disk(center_hex, hex_count))
