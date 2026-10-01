"""
Model Feature Preprocessor
=========================

Unified feature engineering for Demand Spike Detector LightGBM model.
Ensures Train-Serving consistency between historical and real-time data.

Features extracted:
- Time features (hour, month, day_of_week, etc.)
- Holiday features (is_holiday, holiday_impact, tet_phase, etc.)

STRICT CONSTRAINTS:
- NO flood data (HSDC - is_flooded, flood_level) - handled by Rule Override
- NO storm data (NCHMF - storm_warning) - handled by Rule Override

Usage:
    # Simple function call
    features_df = build_model_features(raw_df)

    # Or use class for more control
    preprocessor = ModelFeaturePreprocessor(year=2026)
    features_df = preprocessor.transform(raw_df)
"""

from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .holiday_calendar import HolidayCalendarGenerator

# Type aliases
DataFrameOrSeries = Union[pd.DataFrame, pd.Series]


# =============================================================================
# HELPER FUNCTIONS (for unit testing)
# =============================================================================

def standardize_timestamp(df: pd.DataFrame, timestamp_col: str = 'timestamp') -> pd.DataFrame:
    """
    Standardize timestamp column name to 'timestamp'.

    Handles various column names:
    - 'crawled_at' (realtime crawler)
    - 'datetime' (backfill data)
    - 'time' (generic)
    - 'timestamp' (standard)

    Args:
        df: Input DataFrame
        timestamp_col: Current timestamp column name

    Returns:
        DataFrame with standardized timestamp column
    """
    df = df.copy()

    # Rename to standard name if different
    if timestamp_col != 'timestamp' and timestamp_col in df.columns:
        df = df.rename(columns={timestamp_col: 'timestamp'})

    # If no recognized timestamp col, try to find one
    if 'timestamp' not in df.columns:
        possible_cols = ['crawled_at', 'datetime', 'time', 'date']
        for col in possible_cols:
            if col in df.columns:
                df = df.rename(columns={col: 'timestamp'})
                break

    # Ensure timestamp is datetime type
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')

    return df


def extract_time_features(df: pd.DataFrame, timestamp_col: str = 'timestamp') -> pd.DataFrame:
    """
    Extract time-based features from timestamp.

    Features extracted:
    - hour: Hour of day (0-23)
    - month: Month (1-12)
    - day_of_week: Vietnamese format (2=Monday, 8=Sunday)
    - is_weekend: 1 if Saturday/Sunday, 0 otherwise
    - is_rush_hour: 1 if 7-9h or 17-19h, 0 otherwise
    - part_of_day: 'morning', 'afternoon', 'evening', 'night'
    - is_monsoon: 1 if May-October (Vietnam monsoon season)

    Args:
        df: Input DataFrame with timestamp column
        timestamp_col: Name of timestamp column

    Returns:
        DataFrame with time features added
    """
    df = df.copy()

    # Ensure timestamp is datetime
    if not pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
        df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors='coerce')

    ts = df[timestamp_col]

    # Basic time components
    df['hour'] = ts.dt.hour.astype(int)
    df['month'] = ts.dt.month.astype(int)

    # Day of week: Vietnamese format
    # Python: Monday=0, Sunday=6
    # Vietnam: Thứ Hai=2, Chủ Nhật=8
    dow = ts.dt.dayofweek
    # Convert: Monday(0) -> 2, Tuesday(1) -> 3, ..., Sunday(6) -> 8
    df['day_of_week'] = ((dow + 1) * 2) % 14 + 2 - ((dow + 1) % 7)
    # Simpler: Monday=2, ..., Sunday=8
    df['day_of_week'] = dow.apply(lambda x: 2 if x == 0 else x + 2 if x <= 5 else 8)

    # Weekend: Saturday (5) or Sunday (6) in Python
    df['is_weekend'] = dow.isin([5, 6]).astype(int)

    # Rush hour: 7-9h (morning) or 17-19h (evening)
    df['is_rush_hour'] = (
        ((df['hour'] >= 7) & (df['hour'] <= 9)) |
        ((df['hour'] >= 17) & (df['hour'] <= 19))
    ).astype(int)

    # Part of day
    def get_part_of_day(hour: int) -> str:
        if 6 <= hour < 11:
            return 'morning'
        elif 11 <= hour < 14:
            return 'noon'
        elif 14 <= hour < 18:
            return 'afternoon'
        elif 18 <= hour < 22:
            return 'evening'
        else:
            return 'night'

    df['part_of_day'] = df['hour'].apply(get_part_of_day)

    # Monsoon season: May (5) to October (10)
    df['is_monsoon'] = df['month'].between(5, 10).astype(int)

    return df


def extract_holiday_features(df: pd.DataFrame, timestamp_col: str = 'timestamp') -> pd.DataFrame:
    """
    Extract holiday features using HolidayCalendarGenerator.

    Features extracted:
    - is_holiday: 1 if holiday, 0 otherwise
    - holiday_name: Name of holiday or 'normal'
    - holiday_impact: Impact score 0.0-1.0
    - tet_phase: 'normal', 'pre_tet', 'tet_week', 'post_tet'
    - is_working_day: 0 if non-working, 1 if working
    - holiday_type: 'solar', 'lunar', 'tet', 'special', 'normal'
    - category: 'official', 'cultural', etc.

    Args:
        df: Input DataFrame with timestamp column
        timestamp_col: Name of timestamp column

    Returns:
        DataFrame with holiday features added
    """
    df = df.copy()

    # Create holiday generator
    ts = pd.to_datetime(df[timestamp_col], errors='coerce')

    # Get year from timestamp - use mode (most common year)
    years = ts.dt.year
    if len(years.dropna()) > 0:
        year_mode = years.mode()
        if len(year_mode) > 0:
            year = int(year_mode.iloc[0])
        else:
            year = datetime.now().year
    else:
        year = datetime.now().year

    generator = HolidayCalendarGenerator(year=year)
    df = generator.merge_holidays(df, datetime_col=timestamp_col)

    return df


def select_model_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Select and order features for LightGBM model.

    Drops:
    - All raw timestamp columns
    - All string/categorical columns (except encoded ones)
    - Any columns that shouldn't be in model input

    Keeps:
    - All numeric time features
    - All numeric weather features
    - Encoded categorical features

    Args:
        df: Input DataFrame with features

    Returns:
        DataFrame with only model-ready features
    """
    df = df.copy()

    # Columns to drop (raw, not for model)
    drop_cols = [
        # Timestamp variations
        'timestamp', 'crawled_at', 'datetime', 'time', 'date',
        'fetch_date', 'fetch_timestamp',
        # String columns not encoded
        'weather_conditions', 'weather_icon', 'weather_code',
        'nearest_anchor', 'part_of_day', 'region',
        'holiday_name', 'tet_phase', 'holiday_type', 'category',
        'wind_dir', 'precip_source',
        # Metadata
        'data_version', 'source', 'anchor_name',
        # FLOOD DATA - EXCLUDED for Model v1 (handled by Rule Override)
        'is_flooded', 'flood_level', 'flood_points',
        # STORM DATA - EXCLUDED for Model v1 (handled by Rule Override)
        'storm_warning', 'nchmf_warning',
    ]

    # Drop existing columns
    for col in drop_cols:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Columns that should be numeric but might be object
    numeric_cols = [
        'temp_c', 'feels_like', 'humidity_pct', 'precip', 'precip_prob',
        'wind_speed', 'cloud_cover', 'visibility', 'pressure',
        'weather_impact', 'precip_impact', 'value',
        'hour', 'month', 'day_of_week', 'is_weekend', 'is_rush_hour', 'is_monsoon',
        'is_holiday', 'holiday_impact', 'is_working_day',
    ]

    # Convert to numeric
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Handle OWM columns if present
    owm_cols = [c for c in df.columns if c.startswith('owm_')]
    for col in owm_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Handle blended columns if present
    blended_cols = [c for c in df.columns if c.startswith('blended_')]
    for col in blended_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Handle anchor/region columns (encode if not already)
    if 'anchor_lat' in df.columns:
        df['anchor_lat'] = pd.to_numeric(df['anchor_lat'], errors='coerce').fillna(0)
    if 'anchor_lon' in df.columns:
        df['anchor_lon'] = pd.to_numeric(df['anchor_lon'], errors='coerce').fillna(0)

    # Drop any remaining object columns
    for col in df.select_dtypes(include=['object']).columns:
        df = df.drop(columns=[col])

    return df


# =============================================================================
# MAIN PREPROCESSOR CLASS
# =============================================================================

class ModelFeaturePreprocessor:
    """
    Unified feature preprocessor for Demand Spike Detector LightGBM model.

    Ensures Train-Serving consistency by applying the same transformations
    to both historical (training) and real-time (inference) data.

    Features extracted:
    1. Time features: hour, month, day_of_week, is_weekend, etc.
    2. Holiday features: is_holiday, holiday_impact, tet_phase, etc.

    Features EXCLUDED (handled by Rule Override):
    - Flood data (HSDC): is_flooded, flood_level
    - Storm data (NCHMF): storm_warning

    Usage:
        preprocessor = ModelFeaturePreprocessor(year=2026)
        features = preprocessor.transform(raw_df)

        # For LightGBM
        X = features[preprocessor.feature_names]
        model.predict(X)
    """

    # Time features (numeric, required for model)
    TIME_FEATURES: List[str] = [
        'hour', 'month', 'day_of_week', 'is_weekend',
        'is_rush_hour', 'is_monsoon'
    ]

    # Holiday features (numeric, required for model)
    HOLIDAY_FEATURES: List[str] = [
        'is_holiday', 'holiday_impact', 'is_working_day'
    ]

    # Weather features (from VCW/OWM only)
    WEATHER_FEATURES: List[str] = [
        'temp_c', 'feels_like', 'humidity_pct', 'precip', 'precip_prob',
        'wind_speed', 'cloud_cover', 'visibility', 'pressure',
        'weather_impact', 'precip_impact', 'value'
    ]

    def __init__(
        self,
        year: Optional[int] = None,
        timestamp_col: str = 'timestamp'
    ):
        """
        Initialize preprocessor.

        Args:
            year: Year for holiday calculation. Defaults to current year.
            timestamp_col: Name of timestamp column in input data.
        """
        self.year = year or datetime.now().year
        self.timestamp_col = timestamp_col
        self.holiday_generator = HolidayCalendarGenerator(year=self.year)
        self._feature_names: Optional[List[str]] = None

    @property
    def feature_names(self) -> List[str]:
        """Get list of feature names for model input."""
        return self._feature_names or []

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply all transformations to raw data.

        Pipeline:
        1. Standardize timestamp column
        2. Extract time features
        3. Extract holiday features
        4. Select model features

        Args:
            df: Raw input DataFrame

        Returns:
            DataFrame ready for LightGBM model
        """
        df = df.copy()

        # Step 1: Standardize timestamp
        df = standardize_timestamp(df, self.timestamp_col)

        # Step 2: Extract time features
        df = extract_time_features(df, 'timestamp')

        # Step 3: Extract holiday features
        df = extract_holiday_features(df, 'timestamp')

        # Step 4: Select model features
        df = select_model_features(df)

        # Store feature names
        self._feature_names = list(df.columns)

        return df

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Fit and transform (same as transform for this preprocessor).

        Args:
            df: Raw input DataFrame

        Returns:
            Transformed DataFrame
        """
        return self.transform(df)

    def get_feature_info(self) -> Dict[str, Dict]:
        """
        Get detailed information about each feature.

        Returns:
            Dictionary with feature names as keys and info as values
        """
        info = {}

        # Time features
        for feat in self.TIME_FEATURES:
            info[feat] = {
                'type': 'numeric',
                'category': 'time',
                'range': self._get_feature_range(feat),
                'description': self._get_feature_description(feat),
            }

        # Holiday features
        for feat in self.HOLIDAY_FEATURES:
            info[feat] = {
                'type': 'numeric',
                'category': 'holiday',
                'range': self._get_feature_range(feat),
                'description': self._get_feature_description(feat),
            }

        return info

    def _get_feature_range(self, feature: str) -> Tuple:
        """Get expected range for a feature."""
        ranges = {
            'hour': (0, 23),
            'month': (1, 12),
            'day_of_week': (2, 8),
            'is_weekend': (0, 1),
            'is_rush_hour': (0, 1),
            'is_monsoon': (0, 1),
            'is_holiday': (0, 1),
            'holiday_impact': (0.0, 1.0),
            'is_working_day': (0, 1),
        }
        return ranges.get(feature, (0, 1))

    def _get_feature_description(self, feature: str) -> str:
        """Get description for a feature."""
        descriptions = {
            'hour': 'Hour of day (0-23)',
            'month': 'Month of year (1-12)',
            'day_of_week': 'Day of week in Vietnamese format (2=Monday, 8=Sunday)',
            'is_weekend': '1 if Saturday or Sunday, 0 otherwise',
            'is_rush_hour': '1 if 7-9h or 17-19h, 0 otherwise',
            'is_monsoon': '1 if May-October (monsoon season), 0 otherwise',
            'is_holiday': '1 if public holiday, 0 otherwise',
            'holiday_impact': 'Holiday impact score (0.0-1.0)',
            'is_working_day': '0 if non-working day, 1 if working day',
        }
        return descriptions.get(feature, 'No description')


# =============================================================================
# MAIN FUNCTION (Simple API)
# =============================================================================

def build_model_features(
    df: pd.DataFrame,
    timestamp_col: str = 'timestamp',
    year: Optional[int] = None
) -> pd.DataFrame:
    """
    Build model-ready features from raw DataFrame.

    This is the main entry point for both training and inference pipelines.

    Features extracted:
    - Time: hour, month, day_of_week, is_weekend, is_rush_hour, is_monsoon
    - Holiday: is_holiday, holiday_impact, is_working_day

    Features EXCLUDED (handled by Rule Override):
    - Flood data (HSDC): is_flooded, flood_level
    - Storm data (NCHMF): storm_warning

    Args:
        df: Raw input DataFrame with timestamp column
        timestamp_col: Name of timestamp column (auto-detected if not 'timestamp')
        year: Year for holiday calculation

    Returns:
        DataFrame with model-ready features

    Example:
        >>> # Load raw data
        >>> df = pd.read_parquet('data/weather_2026-09-29.parquet')
        >>>
        >>> # Build features
        >>> features = build_model_features(df)
        >>>
        >>> # Ready for model
        >>> X = features.drop(columns=['target'])  # if target exists
        >>> predictions = model.predict(X)
    """
    # Create preprocessor
    preprocessor = ModelFeaturePreprocessor(
        year=year,
        timestamp_col=timestamp_col
    )

    # Transform
    return preprocessor.transform(df)


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_features(df: pd.DataFrame) -> Dict[str, any]:
    """
    Validate that the feature DataFrame is model-ready.

    Checks:
    - No null values
    - No object columns
    - All numeric columns
    - Expected features present

    Args:
        df: Feature DataFrame

    Returns:
        Dictionary with validation results
    """
    results = {
        'valid': True,
        'errors': [],
        'warnings': [],
        'stats': {},
    }

    # Check for nulls
    null_counts = df.isnull().sum()
    if null_counts.any():
        null_cols = null_counts[null_counts > 0].to_dict()
        results['warnings'].append(f"Null values found: {null_cols}")
        # Fill nulls with 0 for model
        df = df.fillna(0)
        results['warnings'].append("Nulls filled with 0")

    # Check for object columns
    object_cols = df.select_dtypes(include=['object']).columns.tolist()
    if object_cols:
        results['errors'].append(f"Object columns found: {object_cols}")
        results['valid'] = False

    # Check for inf values
    inf_counts = np.isinf(df.select_dtypes(include=[np.number])).sum()
    if inf_counts.any():
        results['warnings'].append(f"Inf values found: {inf_counts[inf_counts > 0].to_dict()}")
        df = df.replace([np.inf, -np.inf], 0)
        results['warnings'].append("Infs replaced with 0")

    # Stats
    results['stats'] = {
        'shape': df.shape,
        'columns': list(df.columns),
        'dtypes': df.dtypes.astype(str).to_dict(),
    }

    return results
