"""
Data Processor
=============

Processes weather data with:
- 30-minute resampling from hourly data
- Linear interpolation for continuous variables
- Forward-fill for categorical variables
- OWM synthetic data generation from VCW patterns

Usage:
    from processor import WeatherProcessor

    processor = WeatherProcessor()

    # Resample 1H -> 30T
    df_30min = processor.resample_to_30min(df)

    # Generate OWM synthetic data
    df_with_owm = processor.generate_owm_synthetic(df_30min)

    # Add weather impact
    df_final = processor.add_weather_impact(df_30min)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class WeatherProcessor:
    """
    Processes weather data for backfill and training.

    Features:
    - Resample from hourly to 30-minute
    - Interpolate continuous variables
    - Forward-fill categorical variables
    - Generate OWM synthetic data
    - Calculate weather impact
    """

    # Weather conditions -> impact values
    WEATHER_IMPACT_MAP = {
        'clear': 0.0,
        'mostly clear': 0.0,
        'partly cloudy': 0.0,
        'partly sunny': 0.0,
        'mostly cloudy': 0.1,
        'overcast': 0.1,
        'cloudy': 0.1,
        'fog': 0.2,
        'mist': 0.2,
        'haze': 0.1,
        'light rain': 0.3,
        'rain': 0.5,
        'moderate rain': 0.5,
        'heavy rain': 0.9,
        'thunderstorm': 0.9,
        'heavy rain and fog': 0.9,
        'light rain with thunder': 0.8,
    }

    # OWM weather codes -> impact values
    OWM_IMPACT_MAP = {
        200: 0.9, 201: 0.9, 202: 1.0, 210: 0.9, 211: 0.9,
        212: 1.0, 221: 1.0, 230: 0.9, 231: 0.9, 232: 1.0,
        300: 0.3, 301: 0.4, 302: 0.5, 310: 0.3, 311: 0.4,
        312: 0.5, 313: 0.5, 314: 0.6, 321: 0.5,
        500: 0.3, 501: 0.5, 502: 0.8, 503: 0.9, 504: 1.0,
        511: 1.0, 520: 0.6, 521: 0.7, 522: 0.9, 531: 1.0,
        600: 0.2, 601: 0.4, 602: 0.6, 611: 0.3, 612: 0.5,
        613: 0.5, 615: 0.4, 616: 0.5, 620: 0.3, 621: 0.5,
        622: 0.7, 701: 0.2, 711: 0.2, 721: 0.1, 731: 0.1,
        741: 0.2, 751: 0.1, 761: 0.1, 762: 0.2, 771: 0.3,
        781: 0.9, 800: 0.0, 801: 0.0, 802: 0.0, 803: 0.1,
        804: 0.1,
    }

    def __init__(self):
        """Initialize processor."""
        logger.info("WeatherProcessor initialized")

    def resample_to_30min(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Resample weather data from hourly to 30-minute resolution.
        Processes each anchor separately to handle duplicate timestamps.

        Args:
            df: DataFrame with datetime column and hourly data

        Returns:
            DataFrame resampled to 30-minute intervals
        """
        if df.empty:
            return df

        # Ensure datetime column exists
        df = df.copy()
        if 'datetime' not in df.columns:
            raise ValueError("DataFrame must have 'datetime' column")

        df['datetime'] = pd.to_datetime(df['datetime'])

        # Define column groups
        continuous_cols = ['temp_c', 'feels_like', 'humidity_pct', 'precip',
                          'precip_prob', 'wind_speed', 'cloud_cover', 'visibility',
                          'pressure']

        categorical_cols = ['weather_conditions', 'weather_icon', 'weather_code']

        # Keep only columns that exist
        continuous_cols = [c for c in continuous_cols if c in df.columns]
        categorical_cols = [c for c in categorical_cols if c in df.columns]

        # Group by anchor if exists
        has_anchor = 'anchor_name' in df.columns
        groups = [df] if not has_anchor else [group for _, group in df.groupby('anchor_name')]

        all_results = []

        for group_df in groups:
            group_df = group_df.sort_values('datetime').reset_index(drop=True)

            # Set datetime as index
            df_indexed = group_df.set_index('datetime')

            # Resample continuous variables (interpolate)
            continuous_result = df_indexed[continuous_cols].resample('30min').mean().interpolate(method='linear')

            # Resample categorical variables (forward fill)
            if categorical_cols:
                categorical_result = df_indexed[categorical_cols].resample('30min').ffill()
            else:
                categorical_result = pd.DataFrame(index=continuous_result.index)

            # Keep anchor columns (forward fill)
            anchor_cols = ['anchor_lat', 'anchor_lon', 'source']
            anchor_cols = [c for c in anchor_cols if c in df_indexed.columns]
            if anchor_cols:
                anchor_result = df_indexed[anchor_cols].resample('30min').ffill()
            else:
                anchor_result = pd.DataFrame(index=continuous_result.index)

            # Combine results
            result = pd.concat([continuous_result, categorical_result, anchor_result], axis=1)

            # Add anchor name if exists
            if has_anchor:
                anchor_name = group_df['anchor_name'].iloc[0]
                result['anchor_name'] = anchor_name

            all_results.append(result)

        # Combine all groups
        combined = pd.concat(all_results)

        # Reset index
        combined = combined.reset_index().rename(columns={'index': 'datetime'})

        # Remove rows with all NaN (gaps)
        combined = combined.dropna(how='all')

        logger.info(f"Resampled from {len(df)} hourly records to {len(combined)} 30-min records")

        return combined

    def generate_owm_synthetic(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate OWM synthetic data from VCW patterns.

        OWM and VCW have similar weather patterns but slightly different:
        - Temperature: ±1°C difference
        - Rain values: correlated but not identical
        - Weather conditions: mapped differently

        Args:
            df: DataFrame with VCW weather data

        Returns:
            DataFrame with added OWM synthetic columns
        """
        df = df.copy()

        # Seed for reproducibility
        np.random.seed(42)

        # Generate OWM synthetic columns with realistic variations
        # Temperature: ±1.5°C from VCW (typical difference)
        df['owm_temp_c'] = df['temp_c'] + np.random.uniform(-1.5, 1.5, len(df))
        df['owm_temp_c'] = df['owm_temp_c'].round(1)

        # Feels like: similar offset
        if 'feels_like' in df.columns:
            df['owm_feels_like'] = df['feels_like'] + np.random.uniform(-1.5, 1.5, len(df))
            df['owm_feels_like'] = df['owm_feels_like'].round(1)

        # Humidity: ±5% variation
        if 'humidity_pct' in df.columns:
            df['owm_humidity_pct'] = df['humidity_pct'] + np.random.uniform(-5, 5, len(df))
            df['owm_humidity_pct'] = df['owm_humidity_pct'].clip(0, 100).round(0)

        # Precipitation: correlated but with noise
        if 'precip' in df.columns:
            # 85% correlation with VCW, 15% noise
            correlation = 0.85
            noise = np.random.uniform(0, 0.3, len(df))
            df['owm_precip'] = (df['precip'] * correlation + noise * df['precip'].std())
            df['owm_precip'] = df['owm_precip'].clip(lower=0).round(1)

        # Wind speed: ±2 m/s variation
        if 'wind_speed' in df.columns:
            df['owm_wind_speed'] = df['wind_speed'] + np.random.uniform(-2, 2, len(df))
            df['owm_wind_speed'] = df['owm_wind_speed'].clip(lower=0).round(1)

        # Cloud cover: correlated
        if 'cloud_cover' in df.columns:
            df['owm_cloud_cover'] = df['cloud_cover'] + np.random.uniform(-10, 10, len(df))
            df['owm_cloud_cover'] = df['owm_cloud_cover'].clip(0, 100).round(0)

        # Weather code: map from conditions to OWM codes
        df['owm_weather_code'] = df['weather_conditions'].apply(self._conditions_to_owm_code)

        # OWM impact from code
        df['owm_weather_impact'] = df['owm_weather_code'].map(self.OWM_IMPACT_MAP).fillna(0.0)

        df['source'] = 'VCW+OWM_Synthetic'

        logger.info(f"Generated OWM synthetic columns for {len(df)} records")

        return df

    def _conditions_to_owm_code(self, conditions: str) -> int:
        """Map VCW conditions to OWM weather codes."""
        conditions_lower = str(conditions).lower()

        if 'thunder' in conditions_lower or 'storm' in conditions_lower:
            return 202  # Thunderstorm with heavy rain
        elif 'heavy rain' in conditions_lower:
            return 502  # Heavy intensity rain
        elif 'rain' in conditions_lower and 'light' in conditions_lower:
            return 300  # Light rain
        elif 'rain' in conditions_lower:
            return 501  # Moderate rain
        elif 'overcast' in conditions_lower or 'cloudy' in conditions_lower:
            return 804  # Overcast clouds
        elif 'partly' in conditions_lower or 'mostly' in conditions_lower:
            return 801  # Few clouds
        elif 'fog' in conditions_lower or 'mist' in conditions_lower:
            return 741  # Fog
        else:
            return 800  # Clear sky

    def add_weather_impact(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add weather impact score based on conditions.

        Args:
            df: DataFrame with weather_conditions column

        Returns:
            DataFrame with weather_impact column
        """
        df = df.copy()

        # Map conditions to impact
        def get_impact(conditions):
            conditions_lower = str(conditions).lower()
            for key, value in self.WEATHER_IMPACT_MAP.items():
                if key in conditions_lower:
                    return value
            return 0.0

        df['weather_impact'] = df['weather_conditions'].apply(get_impact)

        # Precipitation impact (independent of conditions)
        if 'precip' in df.columns:
            df['precip_impact'] = df['precip'].apply(
                lambda x: min(1.0, x / 20) if pd.notna(x) and x > 0 else 0.0
            )

            # Combined impact (max of conditions and precip)
            df['value'] = df[['weather_impact', 'precip_impact']].max(axis=1)
        else:
            df['value'] = df['weather_impact']

        # Severity classification
        def classify_severity(value):
            if value >= 0.8:
                return 'SEVERE'
            elif value >= 0.5:
                return 'HIGH'
            elif value >= 0.3:
                return 'MEDIUM'
            return 'LOW'

        df['severity'] = df['value'].apply(classify_severity)

        return df

    def add_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add time-based features.

        Args:
            df: DataFrame with datetime column

        Returns:
            DataFrame with time features
        """
        df = df.copy()

        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df['hour'] = df['datetime'].dt.hour
            df['day_of_week'] = df['datetime'].dt.dayofweek
            df['is_weekend'] = df['day_of_week'].isin([5, 6]).astype(int)

            # Rush hour: 7-9 AM and 5-8 PM
            df['is_rush_hour'] = (
                ((df['hour'] >= 7) & (df['hour'] <= 9)) |
                ((df['hour'] >= 17) & (df['hour'] <= 20))
            ).astype(int)

            # Part of day
            def get_part_of_day(hour):
                if 0 <= hour < 6:
                    return 'night'
                elif 6 <= hour < 12:
                    return 'morning'
                elif 12 <= hour < 18:
                    return 'afternoon'
                return 'evening'

            df['part_of_day'] = df['hour'].apply(get_part_of_day)

            # Month and season
            df['month'] = df['datetime'].dt.month
            df['is_monsoon'] = df['month'].isin([4, 5, 6, 7, 8, 9]).astype(int)

        return df

    def add_blended_weather(self, df: pd.DataFrame, w1: float = 0.5, w2: float = 0.5) -> pd.DataFrame:
        """
        Create blended weather feature from VCW and OWM.

        Args:
            df: DataFrame with vcw and owm columns
            w1: Weight for VCW (default 0.5)
            w2: Weight for OWM (default 0.5)

        Returns:
            DataFrame with blended columns
        """
        df = df.copy()

        # Normalize weights
        total = w1 + w2
        w1, w2 = w1 / total, w2 / total

        # Blend temperature
        if 'temp_c' in df.columns and 'owm_temp_c' in df.columns:
            df['blended_temp_c'] = w1 * df['temp_c'] + w2 * df['owm_temp_c']

        # Blend precipitation
        if 'precip' in df.columns and 'owm_precip' in df.columns:
            df['blended_precip'] = w1 * df['precip'] + w2 * df['owm_precip']

        # Blend humidity
        if 'humidity_pct' in df.columns and 'owm_humidity_pct' in df.columns:
            df['blended_humidity_pct'] = w1 * df['humidity_pct'] + w2 * df['owm_humidity_pct']

        # Blend impact (average of both)
        if 'weather_impact' in df.columns and 'owm_weather_impact' in df.columns:
            df['blended_weather_impact'] = (df['weather_impact'] + df['owm_weather_impact']) / 2
            df['blended_value'] = (df['value'] + df.get('owm_value', df['weather_impact'])) / 2

        logger.info(f"Created blended weather features with w_vcw={w1:.2f}, w_owm={w2:.2f}")

        return df

    def process_pipeline(self, df: pd.DataFrame, add_owm: bool = True,
                        add_blended: bool = True) -> pd.DataFrame:
        """
        Run full processing pipeline.

        Args:
            df: Raw weather DataFrame
            add_owm: Generate OWM synthetic data
            add_blended: Create blended features

        Returns:
            Processed DataFrame
        """
        logger.info(f"Starting processing pipeline for {len(df)} records...")

        # Step 1: Resample to 30-minute
        df = self.resample_to_30min(df)

        # Step 2: Add weather impact
        df = self.add_weather_impact(df)

        # Step 3: Add time features
        df = self.add_time_features(df)

        # Step 4: Generate OWM synthetic
        if add_owm:
            df = self.generate_owm_synthetic(df)

        # Step 5: Add blended weather
        if add_blended and add_owm:
            df = self.add_blended_weather(df)

        # Step 6: Sort by datetime
        df = df.sort_values('datetime').reset_index(drop=True)

        logger.info(f"Processing complete. Final records: {len(df)}")

        return df

    def get_summary_stats(self, df: pd.DataFrame) -> Dict:
        """Get summary statistics of processed data."""
        stats = {
            'total_records': len(df),
            'date_range': f"{df['datetime'].min()} to {df['datetime'].max()}" if not df.empty else "N/A",
            'anchors': df['anchor_name'].unique().tolist() if 'anchor_name' in df.columns else [],
            'severity_distribution': df['severity'].value_counts().to_dict() if 'severity' in df.columns else {},
            'avg_weather_impact': df['weather_impact'].mean() if 'weather_impact' in df.columns else None,
            'rainy_records': (df['precip'] > 0).sum() if 'precip' in df.columns else 0,
            'rainy_pct': 100 * (df['precip'] > 0).mean() if 'precip' in df.columns else 0,
        }
        return stats

    def __repr__(self):
        return "WeatherProcessor()"
