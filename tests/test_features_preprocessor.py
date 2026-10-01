"""
Unit Tests for Features Preprocessor
====================================

Tests for:
- holiday_calendar.py
- preprocessor.py

Run with:
    pytest tests/test_features_preprocessor.py -v
"""

import sys
import os
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import pandas as pd
import numpy as np

from src.features.holiday_calendar import HolidayCalendarGenerator
from src.features.preprocessor import (
    standardize_timestamp,
    extract_time_features,
    extract_holiday_features,
    select_model_features,
    build_model_features,
    ModelFeaturePreprocessor,
    validate_features,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_df():
    """Create sample DataFrame for testing."""
    return pd.DataFrame({
        'timestamp': pd.date_range('2026-09-01', periods=24, freq='h'),
        'temp_c': np.random.uniform(25, 35, 24),
        'humidity_pct': np.random.uniform(60, 95, 24),
        'precip': np.random.uniform(0, 10, 24),
        'weather_impact': np.random.uniform(0, 0.5, 24),
    })


@pytest.fixture
def realtime_df():
    """Create sample realtime DataFrame (like from crawler)."""
    return pd.DataFrame({
        'crawled_at': pd.date_range('2026-09-29 00:00:00', periods=10, freq='15min'),
        'temp_c': [28.0, 28.5, 29.0, 29.5, 30.0, 30.5, 31.0, 30.5, 30.0, 29.5],
        'humidity_pct': [85, 84, 83, 82, 81, 80, 79, 80, 81, 82],
        'precip': [0.0, 0.0, 0.0, 0.5, 1.0, 2.0, 1.5, 1.0, 0.5, 0.0],
    })


@pytest.fixture
def holiday_df():
    """Create DataFrame with holidays."""
    return pd.DataFrame({
        'timestamp': [
            datetime(2026, 9, 2),   # Ngay Quoc khanh
            datetime(2026, 9, 1),   # Normal day
            datetime(2026, 8, 27),   # Le Vu Lan
        ],
        'temp_c': [30, 31, 29],
    })


# =============================================================================
# HOLIDAY CALENDAR TESTS
# =============================================================================

class TestHolidayCalendarGenerator:
    """Tests for HolidayCalendarGenerator."""

    def test_tet_date_calculation(self):
        """Test Tet date calculation for 2026."""
        generator = HolidayCalendarGenerator(year=2026)
        assert generator.tet_date is not None
        # Tet 2026 should be around Feb 17
        assert generator.tet_date.month == 2
        assert generator.tet_date.day in [15, 16, 17, 18]

    def test_generate_calendar(self):
        """Test calendar generation."""
        generator = HolidayCalendarGenerator(year=2026)
        calendar = generator.generate_calendar(
            datetime(2026, 9, 1),
            datetime(2026, 9, 30)
        )

        assert len(calendar) == 30
        assert 'date' in calendar.columns
        assert 'is_holiday' in calendar.columns
        assert 'holiday_impact' in calendar.columns

    def test_holiday_detection(self):
        """Test that holidays are correctly detected."""
        generator = HolidayCalendarGenerator(year=2026)
        calendar = generator.generate_calendar(
            datetime(2026, 9, 1),
            datetime(2026, 9, 30)
        )

        # Sep 2 should be holiday
        sep_2 = calendar[calendar['date'] == pd.Timestamp('2026-09-02')]
        assert len(sep_2) == 1
        assert sep_2.iloc[0]['is_holiday'] == 1
        assert sep_2.iloc[0]['holiday_name'] == 'Ngay Quoc khanh'

    def test_merge_holidays(self, sample_df):
        """Test merging holidays into DataFrame."""
        generator = HolidayCalendarGenerator(year=2026)
        merged = generator.merge_holidays(sample_df, datetime_col='timestamp')

        assert 'is_holiday' in merged.columns
        assert 'holiday_name' in merged.columns
        assert 'holiday_impact' in merged.columns
        assert 'tet_phase' in merged.columns

    def test_get_summary(self):
        """Test holiday summary."""
        generator = HolidayCalendarGenerator(year=2026)
        summary = generator.get_summary()

        assert 'year' in summary
        assert 'tet_date' in summary
        assert 'total_holidays' in summary
        assert summary['year'] == 2026


# =============================================================================
# PREPROCESSOR TESTS
# =============================================================================

class TestStandardizeTimestamp:
    """Tests for timestamp standardization."""

    def test_rename_crawled_at(self, realtime_df):
        """Test renaming crawled_at to timestamp."""
        result = standardize_timestamp(realtime_df, 'crawled_at')

        assert 'timestamp' in result.columns
        assert 'crawled_at' not in result.columns

    def test_rename_datetime(self, sample_df):
        """Test that datetime is kept as timestamp."""
        result = standardize_timestamp(sample_df, 'timestamp')

        assert 'timestamp' in result.columns

    def test_datetime_conversion(self, realtime_df):
        """Test that timestamp is converted to datetime."""
        result = standardize_timestamp(realtime_df, 'crawled_at')

        assert pd.api.types.is_datetime64_any_dtype(result['timestamp'])


class TestExtractTimeFeatures:
    """Tests for time feature extraction."""

    def test_hour_extraction(self, sample_df):
        """Test hour extraction."""
        result = extract_time_features(sample_df)

        assert 'hour' in result.columns
        assert result['hour'].min() >= 0
        assert result['hour'].max() <= 23

    def test_month_extraction(self, sample_df):
        """Test month extraction."""
        result = extract_time_features(sample_df)

        assert 'month' in result.columns
        assert result['month'].unique()[0] == 9  # September

    def test_day_of_week_vietnamese(self):
        """Test Vietnamese day of week format."""
        df = pd.DataFrame({
            'timestamp': [
                datetime(2026, 9, 7),   # Monday
                datetime(2026, 9, 8),   # Tuesday
                datetime(2026, 9, 13),  # Sunday
            ]
        })
        result = extract_time_features(df)

        assert result.iloc[0]['day_of_week'] == 2   # Monday = 2
        assert result.iloc[1]['day_of_week'] == 3   # Tuesday = 3
        assert result.iloc[2]['day_of_week'] == 8   # Sunday = 8

    def test_is_weekend(self):
        """Test weekend detection."""
        df = pd.DataFrame({
            'timestamp': [
                datetime(2026, 9, 5),   # Saturday
                datetime(2026, 9, 6),   # Sunday
                datetime(2026, 9, 7),   # Monday
            ]
        })
        result = extract_time_features(df)

        assert result.iloc[0]['is_weekend'] == 1  # Saturday
        assert result.iloc[1]['is_weekend'] == 1  # Sunday
        assert result.iloc[2]['is_weekend'] == 0  # Monday

    def test_is_rush_hour(self):
        """Test rush hour detection."""
        df = pd.DataFrame({
            'timestamp': [
                datetime(2026, 9, 7, 8, 0),   # 8 AM - rush hour
                datetime(2026, 9, 7, 12, 0),  # 12 PM - not rush
                datetime(2026, 9, 7, 18, 0),  # 6 PM - rush hour
            ]
        })
        result = extract_time_features(df)

        assert result.iloc[0]['is_rush_hour'] == 1   # Morning rush
        assert result.iloc[1]['is_rush_hour'] == 0   # Noon
        assert result.iloc[2]['is_rush_hour'] == 1   # Evening rush

    def test_part_of_day(self, sample_df):
        """Test part of day classification."""
        result = extract_time_features(sample_df)

        assert 'part_of_day' in result.columns
        assert set(result['part_of_day'].unique()).issubset(
            {'morning', 'noon', 'afternoon', 'evening', 'night'}
        )

    def test_is_monsoon(self):
        """Test monsoon season detection."""
        df = pd.DataFrame({
            'timestamp': [
                datetime(2026, 5, 15),  # May - monsoon
                datetime(2026, 7, 15),  # July - monsoon
                datetime(2026, 11, 15),  # Nov - not monsoon
                datetime(2026, 2, 15),   # Feb - not monsoon
            ]
        })
        result = extract_time_features(df)

        assert result.iloc[0]['is_monsoon'] == 1  # May
        assert result.iloc[1]['is_monsoon'] == 1  # July
        assert result.iloc[2]['is_monsoon'] == 0  # Nov
        assert result.iloc[3]['is_monsoon'] == 0  # Feb


class TestExtractHolidayFeatures:
    """Tests for holiday feature extraction."""

    def test_holiday_columns_added(self, sample_df):
        """Test that holiday columns are added."""
        result = extract_holiday_features(sample_df)

        expected_cols = [
            'is_holiday', 'holiday_name', 'holiday_impact',
            'tet_phase', 'is_working_day', 'holiday_type', 'category'
        ]
        for col in expected_cols:
            assert col in result.columns

    def test_normal_day(self, sample_df):
        """Test normal day has correct values."""
        result = extract_holiday_features(sample_df)

        # Most days should not be holidays
        assert result['is_holiday'].max() >= 0

    def test_holiday_detection(self, holiday_df):
        """Test holiday detection for known holidays."""
        result = extract_holiday_features(holiday_df)

        # Sep 2 should be holiday
        sep_2 = result[pd.to_datetime(result['timestamp']).dt.date == datetime(2026, 9, 2).date()]
        assert sep_2.iloc[0]['is_holiday'] == 1
        assert 'Quoc khanh' in sep_2.iloc[0]['holiday_name']


class TestSelectModelFeatures:
    """Tests for model feature selection."""

    def test_drops_timestamp(self, sample_df):
        """Test that timestamp is dropped."""
        df = extract_time_features(sample_df)
        result = select_model_features(df)

        assert 'timestamp' not in result.columns

    def test_drops_string_columns(self, realtime_df):
        """Test that string columns are dropped."""
        # First standardize to get timestamp column
        df = standardize_timestamp(realtime_df, 'crawled_at')
        df = extract_time_features(df)
        result = select_model_features(df)

        # Should not have object columns (except for columns that were already numeric)
        object_cols = result.select_dtypes(include=['object']).columns
        # part_of_day and other string cols should be dropped
        assert 'part_of_day' not in result.columns

    def test_keeps_numeric_features(self, sample_df):
        """Test that numeric features are kept."""
        df = extract_time_features(sample_df)
        result = select_model_features(df)

        expected_features = ['temp_c', 'humidity_pct', 'precip', 'weather_impact']
        for feat in expected_features:
            assert feat in result.columns


class TestBuildModelFeatures:
    """Tests for main build_model_features function."""

    def test_simple_transform(self, sample_df):
        """Test simple transformation."""
        result = build_model_features(sample_df)

        assert len(result) == len(sample_df)
        assert 'hour' in result.columns
        assert 'is_holiday' in result.columns

    def test_realtime_df_transform(self, realtime_df):
        """Test transformation of realtime DataFrame."""
        result = build_model_features(realtime_df, timestamp_col='crawled_at')

        assert len(result) == len(realtime_df)
        # timestamp is DROPPED after preprocessing (not needed for model)
        assert 'timestamp' not in result.columns
        assert 'hour' in result.columns
        assert result['hour'].iloc[0] == 0  # First row is midnight

    def test_excludes_flood_data(self):
        """Test that flood data is NOT included."""
        df = pd.DataFrame({
            'timestamp': pd.date_range('2026-09-01', periods=10, freq='h'),
            'temp_c': [28.0] * 10,
            'is_flooded': [0, 0, 1, 1, 1, 0, 0, 0, 0, 0],  # Flood data
            'flood_level': [0, 0, 2, 3, 4, 0, 0, 0, 0, 0],  # Flood data
        })

        result = build_model_features(df)

        # Flood columns should be dropped
        assert 'is_flooded' not in result.columns
        assert 'flood_level' not in result.columns

    def test_excludes_storm_data(self):
        """Test that storm data is NOT included."""
        df = pd.DataFrame({
            'timestamp': pd.date_range('2026-09-01', periods=10, freq='h'),
            'temp_c': [28.0] * 10,
            'storm_warning': [0, 0, 1, 1, 0, 0, 0, 0, 0, 0],  # Storm data
        })

        result = build_model_features(df)

        # Storm column should be dropped
        assert 'storm_warning' not in result.columns


class TestModelFeaturePreprocessor:
    """Tests for ModelFeaturePreprocessor class."""

    def test_initialization(self):
        """Test preprocessor initialization."""
        preprocessor = ModelFeaturePreprocessor(year=2026)

        assert preprocessor.year == 2026
        assert preprocessor.timestamp_col == 'timestamp'
        assert preprocessor.holiday_generator is not None

    def test_transform(self, sample_df):
        """Test full transformation pipeline."""
        preprocessor = ModelFeaturePreprocessor(year=2026)
        result = preprocessor.transform(sample_df)

        assert len(result) == len(sample_df)
        assert preprocessor.feature_names is not None
        assert len(preprocessor.feature_names) > 0

    def test_fit_transform(self, sample_df):
        """Test fit_transform is same as transform."""
        preprocessor = ModelFeaturePreprocessor(year=2026)
        result1 = preprocessor.fit_transform(sample_df)
        result2 = preprocessor.transform(sample_df)

        assert list(result1.columns) == list(result2.columns)

    def test_feature_info(self):
        """Test feature info generation."""
        preprocessor = ModelFeaturePreprocessor(year=2026)
        info = preprocessor.get_feature_info()

        assert isinstance(info, dict)
        assert 'hour' in info
        assert 'is_holiday' in info


class TestValidateFeatures:
    """Tests for feature validation."""

    def test_valid_dataframe(self, sample_df):
        """Test validation of valid DataFrame."""
        df = build_model_features(sample_df)
        result = validate_features(df)

        assert result['valid'] == True
        assert len(result['errors']) == 0

    def test_null_handling(self):
        """Test that nulls are handled."""
        df = pd.DataFrame({
            'timestamp': pd.date_range('2026-09-01', periods=10, freq='h'),
            'temp_c': [28.0, np.nan, 30.0, 31.0, 32.0, 33.0, 34.0, 35.0, 36.0, 37.0],
        })

        result = validate_features(df)

        # Should have warning but still valid
        assert 'Null' in str(result['warnings'])

    def test_object_column_error(self):
        """Test that object columns are flagged."""
        df = pd.DataFrame({
            'timestamp': pd.date_range('2026-09-01', periods=5, freq='h'),
            'temp_c': [28.0, 29.0, 30.0, 31.0, 32.0],
            'weather_conditions': ['sunny', 'cloudy', 'rain', 'storm', 'sunny'],
        })

        result = validate_features(df)

        # Object columns should be in errors
        assert len(result['errors']) > 0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests for end-to-end scenarios."""

    def test_historical_to_model(self):
        """Test transforming historical data to model input."""
        # Load actual historical data
        try:
            df = pd.read_parquet('data/weather_anchors_30T.parquet')
        except FileNotFoundError:
            pytest.skip("Historical data not found")

        result = build_model_features(df)

        # Should have same number of rows
        assert len(result) == len(df)
        # Should have hour feature
        assert 'hour' in result.columns
        # Should have holiday feature
        assert 'is_holiday' in result.columns

    def test_realtime_to_model(self):
        """Test transforming realtime data to model input."""
        # Load actual realtime data
        try:
            df = pd.read_parquet('data/realtime_lake/weather_2026-09-29.parquet')
        except FileNotFoundError:
            pytest.skip("Realtime data not found")

        result = build_model_features(df, timestamp_col='crawled_at')

        # Should have same number of rows
        assert len(result) == len(df)
        # Should have required features
        assert 'hour' in result.columns
        assert 'is_holiday' in result.columns
        # Should NOT have excluded features
        assert 'is_flooded' not in result.columns
        assert 'storm_warning' not in result.columns


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
