"""
Unit Tests for Demand Spike Weather Pipeline
==========================================
"""

import pytest
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLightGBMDataPrep:
    """Tests for LightGBM feature engineering."""

    def test_time_features(self):
        """Test time-derived features."""
        from src.pipeline.demand_spike_pipeline import LightGBMDataPrep

        prep = LightGBMDataPrep()

        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-09-01', periods=24, freq='H'),
            'h3_index': ['88415cb4e5fffff'] * 24,
            'blended_rainfall': [0] * 24,
            'is_storm_current': [0] * 24,
            'blended_forecast_1h': [0] * 24,
            'latitude': [21.0283] * 24,
            'longitude': [105.8542] * 24,
            'zone': ['NoiThanh'] * 24,
            'district': ['HoanKiem'] * 24,
        })

        result = prep.transform(df)

        assert 'hour_of_day' in result.columns
        assert 'day_of_week' in result.columns
        assert 'is_weekend' in result.columns
        assert 'is_rush_hour' in result.columns

        # Check values for known timestamps
        # 2026-09-01 is Tuesday (day_of_week=1)
        assert result.loc[0, 'day_of_week'] == 1
        # 00:00 is not rush hour
        assert result.loc[0, 'is_rush_hour'] == 0
        # Not weekend
        assert result.loc[0, 'is_weekend'] == 0

    def test_lag_features(self):
        """Test lag features."""
        from src.pipeline.demand_spike_pipeline import LightGBMDataPrep

        prep = LightGBMDataPrep()

        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-09-01', periods=5, freq='15min'),
            'h3_index': ['88415cb4e5fffff'] * 5,
            'blended_rainfall': [0, 5, 10, 15, 20],
            'is_storm_current': [0] * 5,
            'blended_forecast_1h': [0] * 5,
            'latitude': [21.0283] * 5,
            'longitude': [105.8542] * 5,
            'zone': ['NoiThanh'] * 5,
            'district': ['HoanKiem'] * 5,
        })

        result = prep.transform(df)

        # rain_lag_15m should be previous rainfall
        assert result.loc[1, 'rain_lag_15m'] == 0
        assert result.loc[2, 'rain_lag_15m'] == 5
        assert result.loc[3, 'rain_lag_15m'] == 10

        # First row should be NaN (no previous)
        assert pd.isna(result.loc[0, 'rain_lag_15m'])

    def test_rolling_features(self):
        """Test rolling window features."""
        from src.pipeline.demand_spike_pipeline import LightGBMDataPrep

        prep = LightGBMDataPrep()

        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-09-01', periods=5, freq='15min'),
            'h3_index': ['88415cb4e5fffff'] * 5,
            'blended_rainfall': [5, 5, 5, 5, 5],
            'is_storm_current': [0] * 5,
            'blended_forecast_1h': [0] * 5,
            'latitude': [21.0283] * 5,
            'longitude': [105.8542] * 5,
            'zone': ['NoiThanh'] * 5,
            'district': ['HoanKiem'] * 5,
        })

        result = prep.transform(df)

        # Rolling sum of 4 x 15min = 1 hour
        # Sum should be 20 (4 * 5)
        assert result.loc[3, 'rain_sum_last_60m'] == 20

    def test_lead_features(self):
        """Test lead features (forecast rename)."""
        from src.pipeline.demand_spike_pipeline import LightGBMDataPrep

        prep = LightGBMDataPrep()

        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-09-01', periods=3, freq='15min'),
            'h3_index': ['88415cb4e5fffff'] * 3,
            'blended_rainfall': [0, 5, 10],
            'is_storm_current': [0] * 3,
            'blended_forecast_1h': [8, 12, 15],  # Forecast
            'latitude': [21.0283] * 3,
            'longitude': [105.8542] * 3,
            'zone': ['NoiThanh'] * 3,
            'district': ['HoanKiem'] * 3,
        })

        result = prep.transform(df)

        # Lead should be renamed
        assert 'rain_expected_next_1h' in result.columns

        # Is rain expected (>5mm)?
        assert result.loc[0, 'is_rain_expected'] == 1
        assert result.loc[1, 'is_rain_expected'] == 1
        assert result.loc[2, 'is_rain_expected'] == 1

    def test_trend_features(self):
        """Test trend features."""
        from src.pipeline.demand_spike_pipeline import LightGBMDataPrep

        prep = LightGBMDataPrep()

        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-09-01', periods=5, freq='15min'),
            'h3_index': ['88415cb4e5fffff'] * 5,
            'blended_rainfall': [0, 5, 10, 15, 20],
            'is_storm_current': [0] * 5,
            'blended_forecast_1h': [0] * 5,
            'latitude': [21.0283] * 5,
            'longitude': [105.8542] * 5,
            'zone': ['NoiThanh'] * 5,
            'district': ['HoanKiem'] * 5,
        })

        result = prep.transform(df)

        # Rain diff should be current - previous
        assert result.loc[1, 'rain_diff_15m'] == 5
        assert result.loc[2, 'rain_diff_15m'] == 5

        # Intensity should be categorized
        # 0-5: none/light, 5-20: moderate
        assert result.loc[0, 'rain_intensity'] == 'none'
        assert result.loc[2, 'rain_intensity'] == 'moderate'  # 10mm = moderate
        assert result.loc[4, 'rain_intensity'] == 'moderate'  # 20mm = moderate

    def test_category_encoding(self):
        """Test h3_index is encoded as category."""
        from src.pipeline.demand_spike_pipeline import LightGBMDataPrep

        prep = LightGBMDataPrep()

        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-09-01', periods=3, freq='15min'),
            'h3_index': ['88415cb4e5fffff', '88415cb4e6fffff', '88415cb4e7fffff'],
            'blended_rainfall': [0, 5, 10],
            'is_storm_current': [0] * 3,
            'blended_forecast_1h': [0] * 3,
            'latitude': [21.0283] * 3,
            'longitude': [105.8542] * 3,
            'zone': ['NoiThanh'] * 3,
            'district': ['HoanKiem'] * 3,
        })

        result = prep.transform(df)

        # h3_index should be category type (LightGBM native)
        assert result['h3_index'].dtype.name == 'category'

    def test_groupby_no_leakage(self):
        """Test that groupby processes hexagons independently."""
        from src.pipeline.demand_spike_pipeline import LightGBMDataPrep

        prep = LightGBMDataPrep()

        # Two different hexagons with different patterns
        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-09-01', periods=4, freq='15min'),
            'h3_index': ['88415cb4e5fffff', '88415cb4e5fffff', '88415cb4e6fffff', '88415cb4e6fffff'],
            'blended_rainfall': [0, 0, 10, 10],  # Hex 1: 0, Hex 2: 10
            'is_storm_current': [0] * 4,
            'blended_forecast_1h': [0] * 4,
            'latitude': [21.0283] * 4,
            'longitude': [105.8542] * 4,
            'zone': ['NoiThanh'] * 4,
            'district': ['HoanKiem'] * 4,
        })

        result = prep.transform(df)

        # Each hexagon should have independent lag values
        hex1_rows = result[result['h3_index'] == '88415cb4e5fffff']
        hex2_rows = result[result['h3_index'] == '88415cb4e6fffff']

        # Lag of hex1 should NOT affect hex2
        assert hex1_rows.iloc[0]['rain_lag_15m'] == 0 or pd.isna(hex1_rows.iloc[0]['rain_lag_15m'])
        assert hex2_rows.iloc[0]['rain_lag_15m'] == 0 or pd.isna(hex2_rows.iloc[0]['rain_lag_15m'])

    def test_get_feature_columns(self):
        """Test feature column extraction."""
        from src.pipeline.demand_spike_pipeline import LightGBMDataPrep

        prep = LightGBMDataPrep()

        df = pd.DataFrame({
            'timestamp': pd.date_range(start='2026-09-01', periods=3, freq='15min'),
            'h3_index': ['88415cb4e5fffff'] * 3,
            'blended_rainfall': [0, 5, 10],
            'is_storm_current': [0] * 3,
            'blended_forecast_1h': [0] * 3,
            'latitude': [21.0283] * 3,
            'longitude': [105.8542] * 3,
            'zone': ['NoiThanh'] * 3,
            'district': ['HoanKiem'] * 3,
        })

        result = prep.transform(df)
        features = prep.get_feature_columns(result)

        # Should not include identifiers or targets
        assert 'timestamp' not in features
        assert 'h3_index' not in features
        assert 'blended_rainfall' not in features

        # Should include generated features
        assert 'hour_of_day' in features
        assert 'rain_lag_15m' in features
        assert 'rain_sum_last_60m' in features


class TestSpatialWeatherETL:
    """Tests for ETL pipeline."""

    def test_h3_grid_creation(self):
        """Test H3 grid creation."""
        from src.pipeline.demand_spike_pipeline import SpatialWeatherETL

        etl = SpatialWeatherETL(resolution=8)
        hexagons = etl.hex_grid

        assert len(hexagons) > 0
        assert len(hexagons) < 2000

    def test_hsdc_hex_mapping(self):
        """Test HSDC station to H3 mapping."""
        from src.pipeline.demand_spike_pipeline import SpatialWeatherETL

        etl = SpatialWeatherETL(resolution=8)

        df = pd.DataFrame({
            'latitude': [21.0283, 21.0333],
            'longitude': [105.8542, 105.7833],
            'rainfall_current_mm': [15.0, 22.0],
            'station_name': ['HoanKiem', 'CauGiay'],
        })

        mapped = etl._map_hsdc_to_hex(df)

        assert 'h3_index' in mapped.columns
        assert len(mapped) == 2
        assert mapped.iloc[0]['h3_index'] is not None


class TestPipelineIntegration:
    """Integration tests."""

    def test_full_pipeline_structure(self):
        """Test pipeline has correct structure."""
        from src.pipeline.demand_spike_pipeline import (
            SpatialWeatherETL,
            LightGBMDataPrep,
            DemandSpikeWeatherPipeline,
        )

        # Check ETL exists
        etl = SpatialWeatherETL()
        assert hasattr(etl, 'run')
        assert hasattr(etl, 'fetch_all_sources')

        # Check feature engineering exists
        prep = LightGBMDataPrep()
        assert hasattr(prep, 'transform')
        assert hasattr(prep, 'get_feature_columns')

        # Check orchestrator exists
        pipeline = DemandSpikeWeatherPipeline()
        assert hasattr(pipeline, 'run')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
