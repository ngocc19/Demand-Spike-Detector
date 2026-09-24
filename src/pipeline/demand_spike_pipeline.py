"""
Demand Spike Detector - Spatial Weather ETL Pipeline
=================================================

Decoupled Architecture:
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEMAND SPIKE DETECTOR                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  PART 1: CORE ETL & DUAL-PASS ENSEMBLE (Immutable)                 │  │
│  │                                                                     │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                │  │
│  │  │  HSDC   │ │  NCHMF  │ │   OWM   │ │   VCW   │                │  │
│  │  │ (T=0)   │ │ (T=0)   │ │ (T=0)   │ │ (T=0)   │                │  │
│  │  │ Rainfall │ │  Storm  │ │ Current  │ │ Current  │                │  │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘                │  │
│  │       │            │            │            │                       │  │
│  │       └────────────┴─────┬──────┴────────────┘                       │  │
│  │                          │                                            │  │
│  │                    ┌─────▼─────┐                                      │  │
│  │                    │  PASS 1   │  Nowcast                          │  │
│  │                    │ (Current)  │ → blended_rainfall,              │  │
│  │                    │            │ → is_storm_current                │  │
│  │                    └─────┬─────┘                                      │  │
│  │                          │                                            │  │
│  │       ┌─────────────────┴─────────────────┐                         │  │
│  │       │                               │                             │  │
│  │  ┌────▼────┐                    ┌──────▼──────┐                     │  │
│  │  │   OWM   │                    │    VCW      │                     │  │
│  │  │Forecast │                    │  Forecast   │                     │  │
│  │  │ (+1h)   │                    │   (+1h)     │                     │  │
│  │  └────┬────┘                    └──────┬──────┘                     │  │
│  │       │                                 │                            │  │
│  │       └─────────────────┬───────────────┘                            │  │
│  │                         │                                              │  │
│  │                   ┌─────▼─────┐                                       │  │
│  │                   │  PASS 2   │  Forecast                           │  │
│  │                   │(+1h lead) │ → blended_forecast_1h              │  │
│  │                   └───────────┘                                       │  │
│  │                                                                     │  │
│  │  OUTPUT: DataFrame[                                                   │  │
│  │    timestamp, h3_index,                                              │  │
│  │    blended_rainfall, is_storm_current,                               │  │
│  │    blended_forecast_1h                                              │  │
│  │  ]                                                                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  PART 2: FEATURE ENGINEERING FOR LIGHTGBM (Variable)                 │  │
│  │                                                                     │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │  .groupby('h3_index').apply() - No data leakage            │  │  │
│  │  │                                                             │  │  │
│  │  │  Time Features:                                             │  │  │
│  │  │    - hour_of_day (0-23)                                    │  │  │
│  │  │    - day_of_week (0-6)                                     │  │  │
│  │  │    - is_weekend                                            │  │  │
│  │  │    - is_rush_hour                                          │  │  │
│  │  │                                                             │  │  │
│  │  │  Lag Features:                                             │  │  │
│  │  │    - rain_lag_15m                                          │  │  │
│  │  │    - rain_lag_30m                                          │  │  │
│  │  │                                                             │  │  │
│  │  │  Rolling Features:                                         │  │  │
│  │  │    - rain_sum_last_2h                                       │  │  │
│  │  │    - rain_max_last_1h                                       │  │  │
│  │  │                                                             │  │  │
│  │  │  Lead Features:                                            │  │  │
│  │  │    - rain_expected_next_1h (renamed)                        │  │  │
│  │  │                                                             │  │  │
│  │  │  Trend Features:                                          │  │  │
│  │  │    - rain_diff_15m                                         │  │  │
│  │  │    - rain_intensity (increasing/decreasing)               │  │  │
│  │  │                                                             │  │  │
│  │  │  Categorical:                                             │  │  │
│  │  │    - h3_index (category type)                             │  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  │                                                                     │  │
│  │  OUTPUT: DataFrame[Features] → LightGBM                           │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import h3
import logging

from src.pipeline.weather_ensemble import WeatherEnsembleAggregator, EnsembleConfig
from src.pipeline.nchmf_spatial_lookup import (
    H3_TO_DISTRICT,
    DISTRICT_TO_ZONE,
    nchmf_zone_cache,
    get_nchmf_for_hex,
)
from src.pipeline.plugins.hsdc_plugin import HSDCFactorPlugin
from src.pipeline.plugins.owm_plugin import OWMFactorPlugin
from src.pipeline.plugins.vcw_plugin import VCWFactorPlugin

logger = logging.getLogger(__name__)


# ============================================================================
# PART 1: CORE ETL & DUAL-PASS ENSEMBLE (Immutable Block)
# ============================================================================

class SpatialWeatherETL:
    """
    Part 1: Core ETL Pipeline - Immutable Block

    Responsibilities:
    1. Fetch data from all weather sources (HSDC, NCHMF, OWM, VCW)
    2. Map to H3 hexagons
    3. Run Dual-Pass Ensemble:
       - Pass 1 (Nowcast): Current conditions → blended_rainfall, is_storm_current
       - Pass 2 (Forecast): +1h forecast → blended_forecast_1h
    4. Output clean DataFrame

    This block is IMMUTABLE - same input always produces same output.
    """

    def __init__(
        self,
        resolution: int = 8,
        ensemble_config: Optional[EnsembleConfig] = None,
    ):
        """
        Args:
            resolution: H3 resolution (default: 8 for demand forecasting)
            ensemble_config: WeatherEnsembleAggregator configuration
        """
        self.resolution = resolution
        self.ensemble_config = ensemble_config or EnsembleConfig(lambda_decay=0.1)
        self.aggregator = WeatherEnsembleAggregator(self.ensemble_config)

        # Initialize plugins
        self.hsdc_plugin = HSDCFactorPlugin({})
        self.owm_plugin = OWMFactorPlugin({})
        self.vcw_plugin = VCWFactorPlugin({})

        # Hanoi hex grid (cached)
        self._hex_grid: Optional[List[str]] = None

    @property
    def hex_grid(self) -> List[str]:
        """Lazy load hex grid."""
        if self._hex_grid is None:
            self._hex_grid = self._create_hanoi_hex_grid()
        return self._hex_grid

    def _create_hanoi_hex_grid(self) -> List[str]:
        """Create H3 hex grid for Hanoi."""
        HANOI_BOUNDS = {
            'min_lat': 20.85,
            'max_lat': 21.15,
            'min_lng': 105.70,
            'max_lng': 105.95,
        }

        hexagons = set()
        lat_step = 0.005
        lng_step = 0.005

        lat = HANOI_BOUNDS['min_lat']
        while lat <= HANOI_BOUNDS['max_lat']:
            lng = HANOI_BOUNDS['min_lng']
            while lng <= HANOI_BOUNDS['max_lng']:
                try:
                    hex_id = h3.latlng_to_cell(lat, lng, self.resolution)
                    hexagons.add(hex_id)
                except:
                    pass
                lng += lng_step
            lat += lat_step

        return list(hexagons)

    def fetch_all_sources(self) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Fetch data from all sources.

        Returns:
            Tuple of (hsdc_data, owm_current, vcw_current)
        """
        # HSDC - rainfall ground truth
        hsdc_data = self.hsdc_plugin.fetch()
        if not hsdc_data.empty:
            hsdc_data = self._map_hsdc_to_hex(hsdc_data)
            hsdc_data = self._aggregate_hsdc_by_hex(hsdc_data)

        # OWM - current weather
        owm_data = self.owm_plugin.fetch()

        # VCW - current weather
        vcw_data = self.vcw_plugin.fetch()

        return hsdc_data, owm_data, vcw_data

    def _map_hsdc_to_hex(self, hsdc_data: pd.DataFrame) -> pd.DataFrame:
        """Map HSDC stations to H3 hexagons."""
        if hsdc_data.empty:
            return hsdc_data

        hsdc_data = hsdc_data.copy()
        hsdc_data['h3_index'] = hsdc_data.apply(
            lambda row: h3.latlng_to_cell(
                row['latitude'],
                row['longitude'],
                self.resolution
            ) if pd.notna(row.get('latitude')) and pd.notna(row.get('longitude')) else None,
            axis=1
        )
        return hsdc_data

    def _aggregate_hsdc_by_hex(self, hsdc_mapped: pd.DataFrame) -> pd.DataFrame:
        """
        Aggregate HSDC data by hexagon using MAX (safe for routing).

        Multiple stations in same hex → MAX rainfall
        """
        if hsdc_mapped.empty:
            return pd.DataFrame()

        valid_data = hsdc_mapped[hsdc_mapped['h3_index'].notna()].copy()
        if valid_data.empty:
            return pd.DataFrame()

        aggregated = valid_data.groupby('h3_index').agg({
            'rainfall_current_mm': 'max',
            'rainfall_total_mm': 'max',
            'station_name': 'first',
        }).reset_index()

        aggregated['has_hsdc'] = True
        return aggregated

    def _get_hsdc_for_hex(self, h3_index: str, hsdc_aggregated: pd.DataFrame) -> float:
        """Get HSDC rainfall for a specific hexagon."""
        if hsdc_aggregated.empty:
            return 0.0

        row = hsdc_aggregated[hsdc_aggregated['h3_index'] == h3_index]
        if row.empty:
            return 0.0

        return float(row.iloc[0].get('rainfall_current_mm', 0))

    def _get_nchmf_for_hex(self, h3_index: str) -> Dict:
        """Get NCHMF storm warning for hexagon using O(1) lookup."""
        return get_nchmf_for_hex(h3_index)

    def _get_owm_for_hex(self, lat: float, lng: float, owm_data: pd.DataFrame) -> Dict:
        """Get OWM data (using first row as representative)."""
        if owm_data.empty:
            return {'rainfall_mm': 0, 'weather_code': 0}

        row = owm_data.iloc[0]
        return {
            'rainfall_mm': float(row.get('rain_mm', 0)),
            'weather_code': int(row.get('weather_code', 0)),
        }

    def _get_vcw_for_hex(self, lat: float, lng: float, vcw_data: pd.DataFrame) -> Dict:
        """Get VCW data."""
        if vcw_data.empty:
            return {'rainfall_mm': 0, 'conditions': ''}

        row = vcw_data.iloc[0]
        return {
            'rainfall_mm': float(row.get('precip_mm', 0)),
            'conditions': str(row.get('weather_conditions', '')),
        }

    def _get_hex_centroid(self, h3_index: str) -> Tuple[float, float]:
        """Get centroid of hexagon."""
        boundary = h3.cell_to_boundary(h3_index)
        lats = [p[0] for p in boundary]
        lngs = [p[1] for p in boundary]
        return (np.mean(lats), np.mean(lngs))

    # -------------------------------------------------------------------------
    # PASS 1: NOWCAST (Current Conditions)
    # -------------------------------------------------------------------------

    def _run_nowcast_ensemble(
        self,
        h3_index: str,
        hsdc_aggregated: pd.DataFrame,
        owm_data: pd.DataFrame,
        vcw_data: pd.DataFrame,
    ) -> Dict:
        """
        Pass 1: Nowcast Ensemble

        Combines:
        - HSDC: Ground truth rainfall (if station exists)
        - NCHMF: Storm warnings (O(1) lookup)
        - OWM: Current rainfall
        - VCW: Current rainfall

        Output:
        - blended_rainfall: Continuous variable (mm)
        - is_storm_current: Classification (0/1)
        """

        lat, lng = self._get_hex_centroid(h3_index)

        # Get source values
        rainfall_values = {
            'OWM': self._get_owm_for_hex(lat, lng, owm_data)['rainfall_mm'],
            'VCW': self._get_vcw_for_hex(lat, lng, vcw_data)['rainfall_mm'],
            'HSDC': self._get_hsdc_for_hex(h3_index, hsdc_aggregated),
            'NCHMF': 0,  # NCHMF doesn't provide direct rainfall
        }

        # HSDC Circuit Breaker
        has_hsdc = h3_index in hsdc_aggregated['h3_index'].values if not hsdc_aggregated.empty else False
        source_status = {
            'OWM': 1,
            'VCW': 1,
            'HSDC': 1 if has_hsdc else 0,  # 0 if no station
            'NCHMF': 1,
        }

        # Run continuous ensemble for rainfall
        rainfall_result = self.aggregator.ensemble_continuous(
            variable_name='rainfall',
            source_values=rainfall_values,
            source_status=source_status,
        )

        # Get storm probability from NCHMF (primary source)
        nchmf = self._get_nchmf_for_hex(h3_index)
        storm_prob = nchmf.get('storm_prob', 0)

        return {
            'blended_rainfall': rainfall_result.ensemble_value,
            'is_storm_current': 1.0 if storm_prob >= 0.5 else 0.0,
            'storm_probability': storm_prob,
            'has_hsdc_station': has_hsdc,
            'active_sources': rainfall_result.active_sources_count,
        }

    # -------------------------------------------------------------------------
    # PASS 2: FORECAST (+1h Lead)
    # -------------------------------------------------------------------------

    def _run_forecast_ensemble(
        self,
        h3_index: str,
        owm_forecast: pd.DataFrame,
        vcw_forecast: pd.DataFrame,
    ) -> float:
        """
        Pass 2: Forecast Ensemble (+1h lead)

        Combines:
        - OWM forecast (+1h)
        - VCW forecast (+1h)

        Output:
        - blended_forecast_1h: Expected rainfall in next hour
        """

        rainfall_values = {
            'OWM': 0,  # Would come from forecast API
            'VCW': 0,  # Would come from forecast API
        }

        # Placeholder - would fetch from forecast endpoints
        forecast_result = self.aggregator.ensemble_continuous(
            variable_name='forecast_1h',
            source_values=rainfall_values,
        )

        return forecast_result.ensemble_value

    # -------------------------------------------------------------------------
    # MAIN RUN METHOD
    # -------------------------------------------------------------------------

    def run(self) -> pd.DataFrame:
        """
        Run complete ETL pipeline.

        Returns DataFrame:
            [timestamp, h3_index, blended_rainfall, is_storm_current, blended_forecast_1h]
        """
        timestamp = datetime.now()
        logger.info(f"Running ETL at {timestamp}")

        # Step 1: Fetch all sources
        logger.info("Fetching weather data...")
        hsdc_data, owm_data, vcw_data = self.fetch_all_sources()

        # Step 2: Run ensemble per hexagon
        logger.info(f"Running ensemble for {len(self.hex_grid)} hexagons...")
        results = []

        for h3_index in self.hex_grid:
            # Pass 1: Nowcast
            nowcast = self._run_nowcast_ensemble(
                h3_index=h3_index,
                hsdc_aggregated=hsdc_data,
                owm_data=owm_data,
                vcw_data=vcw_data,
            )

            # Pass 2: Forecast (placeholder - needs forecast API)
            forecast = self._run_forecast_ensemble(
                h3_index=h3_index,
                owm_forecast=pd.DataFrame(),
                vcw_forecast=pd.DataFrame(),
            )

            lat, lng = self._get_hex_centroid(h3_index)
            nchmf = self._get_nchmf_for_hex(h3_index)

            results.append({
                'timestamp': timestamp,
                'h3_index': h3_index,
                'latitude': lat,
                'longitude': lng,
                'zone': nchmf.get('zone'),
                'district': nchmf.get('district'),
                'blended_rainfall': nowcast['blended_rainfall'],
                'is_storm_current': nowcast['is_storm_current'],
                'storm_probability': nowcast['storm_probability'],
                'blended_forecast_1h': forecast,
                'has_hsdc_station': nowcast['has_hsdc_station'],
                'active_sources': nowcast['active_sources'],
            })

        df = pd.DataFrame(results)
        logger.info(f"ETL complete: {len(df)} rows")

        return df


# ============================================================================
# PART 2: FEATURE ENGINEERING FOR LIGHTGBM (Variable Block)
# ============================================================================

class LightGBMDataPrep:
    """
    Part 2: Feature Engineering - Variable Block

    This block is VARIABLE - can be swapped for different ML models.

    Responsibilities:
    1. Receive DataFrame from Part 1
    2. Process per h3_index to avoid data leakage
    3. Generate features for LightGBM:
       - Time features
       - Lag features
       - Rolling features
       - Lead features
       - Trend features
    4. Return feature-ready DataFrame

    Design: If switching to Deep Learning (needs 3D tensor),
    simply replace this class without touching Part 1.
    """

    def __init__(self, lags: List[int] = None, rolling_windows: List[int] = None):
        """
        Args:
            lags: List of lag periods in minutes (default: [15, 30])
            rolling_windows: List of rolling windows in minutes (default: [60, 120])
        """
        self.lags = lags or [15, 30]
        self.rolling_windows = rolling_windows or [60, 120]  # 1h, 2h

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform ETL output to LightGBM-ready features.

        Process per h3_index to avoid data leakage.

        Args:
            df: DataFrame from SpatialWeatherETL.run()

        Returns:
            DataFrame with features added
        """
        if df.empty:
            return df

        logger.info("Generating LightGBM features...")

        # Group by hexagon and apply transformations
        feature_dfs = []

        for h3_index, group in df.groupby('h3_index'):
            # Sort by timestamp
            group = group.sort_values('timestamp').reset_index(drop=True)

            # Apply time-based transformations
            group = self._add_time_features(group)
            group = self._add_lag_features(group)
            group = self._add_rolling_features(group)
            group = self._add_lead_features(group)
            group = self._add_trend_features(group)

            feature_dfs.append(group)

        # Combine all hexagons
        result = pd.concat(feature_dfs, ignore_index=True)

        # Encode h3_index as category for LightGBM
        result['h3_index'] = result['h3_index'].astype('category')

        logger.info(f"Feature engineering complete: {len(result)} rows, {len(result.columns)} columns")

        return result

    def _add_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add time-derived features."""
        df = df.copy()

        # Ensure timestamp is datetime
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])

        # Hour of day (affects demand patterns)
        df['hour_of_day'] = df['timestamp'].dt.hour

        # Day of week (weekday vs weekend)
        df['day_of_week'] = df['timestamp'].dt.dayofweek

        # Is weekend
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)

        # Is rush hour (7-9 AM, 5-8 PM)
        df['is_rush_hour'] = (
            ((df['hour_of_day'] >= 7) & (df['hour_of_day'] <= 9)) |
            ((df['hour_of_day'] >= 17) & (df['hour_of_day'] <= 20))
        ).astype(int)

        # Part of day
        df['part_of_day'] = pd.cut(
            df['hour_of_day'],
            bins=[-1, 6, 12, 18, 24],
            labels=['night', 'morning', 'afternoon', 'evening']
        ).astype(str)

        return df

    def _add_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add lag features using .shift().

        Important: Must sort by timestamp before shifting!
        """
        df = df.copy()

        for lag in self.lags:
            lag_col = f'rain_lag_{lag}m'
            df[lag_col] = df['blended_rainfall'].shift(1)  # shift(1) = previous row

        return df

    def _add_rolling_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add rolling window features.

        Rolling sum reflects accumulated demand (congestion).
        """
        df = df.copy()

        for window in self.rolling_windows:
            # Rolling sum
            sum_col = f'rain_sum_last_{window}m'
            df[sum_col] = df['blended_rainfall'].rolling(window=window, min_periods=1).sum()

            # Rolling max
            max_col = f'rain_max_last_{window}m'
            df[max_col] = df['blended_rainfall'].rolling(window=window, min_periods=1).max()

            # Rolling mean
            mean_col = f'rain_mean_last_{window}m'
            df[mean_col] = df['blended_rainfall'].rolling(window=window, min_periods=1).mean()

        return df

    def _add_lead_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add lead features (forecast-based).

        Renames blended_forecast_1h → rain_expected_next_1h
        (Psychological trigger for rain anxiety)
        """
        df = df.copy()

        # Rename forecast to expectation
        df['rain_expected_next_1h'] = df['blended_forecast_1h']

        # Is significant rain expected?
        df['is_rain_expected'] = (df['rain_expected_next_1h'] > 5).astype(int)

        return df

    def _add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add trend features.

        rain_diff: Current - Previous (increasing/decreasing intensity)
        """
        df = df.copy()

        # Calculate diff from lag
        if 'rain_lag_15m' in df.columns:
            df['rain_diff_15m'] = df['blended_rainfall'] - df['rain_lag_15m']

        # Rain intensity category
        df['rain_intensity'] = pd.cut(
            df['blended_rainfall'],
            bins=[-1, 0, 5, 20, 50, float('inf')],
            labels=['none', 'light', 'moderate', 'heavy', 'extreme']
        ).astype(str)

        # Is intensity increasing?
        if 'rain_diff_15m' in df.columns:
            df['is_intensity_increasing'] = (df['rain_diff_15m'] > 0).astype(int)

        return df

    def get_feature_columns(self, df: pd.DataFrame) -> List[str]:
        """
        Get list of feature columns (exclude target and identifiers).

        Usage:
            features = prep.get_feature_columns(df)
            X = df[features]
        """
        exclude = [
            'timestamp', 'h3_index',  # Identifiers
            'blended_rainfall', 'is_storm_current',  # Potential targets
            'latitude', 'longitude', 'zone', 'district',  # Metadata
        ]

        return [col for col in df.columns if col not in exclude]


# ============================================================================
# MAIN PIPELINE ORCHESTRATOR
# ============================================================================

class DemandSpikeWeatherPipeline:
    """
    Orchestrates Part 1 + Part 2 into a single pipeline.

    Usage:
        pipeline = DemandSpikeWeatherPipeline()
        features = pipeline.run()

        # Use with LightGBM
        X = features[features.columns]  # Already filtered
    """

    def __init__(self, resolution: int = 8):
        self.etl = SpatialWeatherETL(resolution=resolution)
        self.feature_engineering = LightGBMDataPrep()

    def run(self) -> pd.DataFrame:
        """
        Run complete pipeline: ETL → Feature Engineering

        Returns:
            DataFrame ready for LightGBM training/prediction
        """
        # Part 1: ETL
        etl_output = self.etl.run()

        # Part 2: Feature Engineering
        features = self.feature_engineering.transform(etl_output)

        return features


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == '__main__':
    """
    Example Usage:

    # Initialize pipeline
    pipeline = DemandSpikeWeatherPipeline(resolution=8)

    # Run pipeline
    df = pipeline.run()

    print(df.head())
    print(f"\nFeature columns: {pipeline.feature_engineering.get_feature_columns(df)}")

    # Prepare for LightGBM
    features = pipeline.feature_engineering.get_feature_columns(df)
    X = df[features]
    y = df['is_storm_current']  # Example target
    """

    print("=" * 70)
    print("DEMAND SPIKE DETECTOR - WEATHER ETL PIPELINE")
    print("=" * 70)
    print()

    # Demo with synthetic data
    demo_df = pd.DataFrame({
        'timestamp': pd.date_range(start='2026-09-01 00:00', periods=10, freq='15min'),
        'h3_index': ['88415cb4e5fffff'] * 10,
        'blended_rainfall': [0, 0, 2, 5, 8, 12, 15, 10, 5, 2],
        'is_storm_current': [0, 0, 0, 0, 0, 1, 1, 0, 0, 0],
        'blended_forecast_1h': [2, 5, 8, 10, 12, 8, 5, 2, 0, 0],
        'latitude': [21.0283] * 10,
        'longitude': [105.8542] * 10,
        'zone': ['NoiThanh'] * 10,
        'district': ['HoanKiem'] * 10,
    })

    print("Input DataFrame:")
    print(demo_df)
    print()

    # Apply feature engineering
    prep = LightGBMDataPrep()
    result = prep.transform(demo_df)

    print("Output DataFrame with Features:")
    print(result)
    print()

    print("Feature Columns:")
    print(prep.get_feature_columns(result))
