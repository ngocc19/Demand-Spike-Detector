"""
Unit Tests for Weather Source Plugins
=====================================

Tests for OWM, VCW, HSDC, and NCHMF plugins.
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOWMFactorPlugin:
    """Tests for OpenWeatherMap plugin."""

    def test_plugin_initialization(self):
        """Test OWM plugin can be initialized."""
        from src.pipeline.plugins.owm_plugin import OWMFactorPlugin

        config = {'api_key': 'test_key', 'city': 'Hanoi,VN'}
        plugin = OWMFactorPlugin(config)

        assert plugin.api_key == 'test_key'
        assert plugin.city == 'Hanoi,VN'
        assert plugin.factor_name == 'owm'

    def test_empty_result_schema(self):
        """Test empty result has correct schema."""
        from src.pipeline.plugins.owm_plugin import OWMFactorPlugin

        plugin = OWMFactorPlugin({})
        result = plugin._create_empty_result()

        expected_cols = [
            'datetime', 'temp_c', 'feels_like', 'humidity_pct',
            'pressure_hpa', 'wind_speed', 'wind_deg', 'clouds_pct',
            'visibility_m', 'weather_code', 'weather_main', 'weather_desc',
            'rain_1h', 'rain_3h', 'snow_1h', 'snow_3h', 'pop',
            'source', 'update_time'
        ]

        assert list(result.columns) == expected_cols

    def test_weather_impact_mapping(self):
        """Test weather impact mapping."""
        from src.pipeline.plugins.owm_plugin import OWMFactorPlugin

        plugin = OWMFactorPlugin({})

        # Thunderstorm should have high impact
        assert plugin.WEATHER_IMPACT_MAP[200] >= 0.9
        assert plugin.WEATHER_IMPACT_MAP[502] >= 0.7  # Heavy rain
        assert plugin.WEATHER_IMPACT_MAP[800] == 0.0  # Clear sky


class TestVCWFactorPlugin:
    """Tests for Visual Crossing Weather plugin."""

    def test_plugin_initialization(self):
        """Test VCW plugin can be initialized."""
        from src.pipeline.plugins.vcw_plugin import VCWFactorPlugin

        config = {'api_key': 'test_key', 'location': 'Hanoi,Vietnam'}
        plugin = VCWFactorPlugin(config)

        assert plugin.api_key == 'test_key'
        assert plugin.location == 'Hanoi,Vietnam'
        assert plugin.factor_name == 'vcw'

    def test_synthetic_data_generation(self):
        """Test synthetic data generation for demo mode."""
        from src.pipeline.plugins.vcw_plugin import VCWFactorPlugin

        plugin = VCWFactorPlugin({'api_key': 'demo'})
        result = plugin._create_synthetic_data()

        assert not result.empty
        assert 'temp_c' in result.columns
        assert 'humidity_pct' in result.columns
        assert 'weather_conditions' in result.columns

    def test_weather_impact_mapping(self):
        """Test weather conditions impact mapping."""
        from src.pipeline.plugins.vcw_plugin import VCWFactorPlugin

        plugin = VCWFactorPlugin({})

        assert plugin.WEATHER_IMPACT_MAP.get('clear', -1) == 0.0
        assert plugin.WEATHER_IMPACT_MAP.get('thunderstorm', -1) >= 0.9
        assert plugin.WEATHER_IMPACT_MAP.get('rain', -1) >= 0.5


class TestNCHMFFactorPlugin:
    """Tests for NCHMF plugin."""

    def test_plugin_initialization(self):
        """Test NCHMF plugin can be initialized."""
        from src.pipeline.plugins.nchmf_plugin import NCHMFFactorPlugin

        plugin = NCHMFFactorPlugin({})

        assert plugin.factor_name == 'nchmf'
        assert plugin.schedule == "0 */3 * * *"

    def test_vietnamese_weather_mapping(self):
        """Test Vietnamese weather description mapping."""
        from src.pipeline.plugins.nchmf_plugin import NCHMFFactorPlugin

        plugin = NCHMFFactorPlugin({})

        # Test mapping function
        assert plugin._map_vietnamese_to_code('nắng') == 0
        assert plugin._map_vietnamese_to_code('mưa') == 61
        assert plugin._map_vietnamese_to_code('giông') == 95

    def test_storm_warning_detection(self):
        """Test storm warning detection."""
        from src.pipeline.plugins.nchmf_plugin import NCHMFFactorPlugin

        plugin = NCHMFFactorPlugin({})

        # Should detect warnings
        assert plugin._check_storm_warning('Cảnh báo giông lốc') == True
        assert plugin._check_storm_warning('Không có cảnh báo') == False

    def test_temperature_extraction(self):
        """Test temperature extraction from text."""
        from src.pipeline.plugins.nchmf_plugin import NCHMFFactorPlugin

        plugin = NCHMFFactorPlugin({})

        temps = plugin._extract_temperatures('Nhiệt độ 25-33°C')
        assert temps['min'] == 25
        assert temps['max'] == 33

    def test_empty_result_schema(self):
        """Test empty result has correct schema."""
        from src.pipeline.plugins.nchmf_plugin import NCHMFFactorPlugin

        plugin = NCHMFFactorPlugin({})
        result = plugin._create_empty_result()

        expected_cols = [
            'datetime', 'temp_c', 'temp_min', 'temp_max',
            'humidity_pct', 'wind_speed', 'wind_dir',
            'weather_code', 'weather_desc', 'precip_mm', 'precip_prob',
            'storm_warning', 'source', 'url', 'metadata'
        ]

        assert list(result.columns) == expected_cols


class TestHSDCFactorPlugin:
    """Tests for HSDC Rainfall plugin."""

    def test_plugin_initialization(self):
        """Test HSDC plugin can be initialized."""
        from src.pipeline.plugins.hsdc_plugin import HSDCFactorPlugin

        plugin = HSDCFactorPlugin({})

        assert plugin.factor_name == 'hsdc'
        assert plugin.schedule == "*/15 * * * *"

    def test_rainfall_api_endpoint(self):
        """Test HSDC rainfall API endpoint is defined."""
        from src.pipeline.plugins.hsdc_plugin import HSDCFactorPlugin

        plugin = HSDCFactorPlugin({})

        assert 'luongmua' in plugin.RAINFALL_API
        assert 'thoatnuochanoi.vn' in plugin.BASE_URL

    def test_rainfall_impact_mapping(self):
        """Test rainfall impact mapping."""
        from src.pipeline.plugins.hsdc_plugin import HSDCFactorPlugin

        plugin = HSDCFactorPlugin({})

        # Test impact function
        impact_func = lambda x: next(
            (impact for (low, high), impact in plugin.RAINFALL_IMPACT_MAP.items() if low <= x < high),
            0.0
        )

        assert impact_func(1.0) == 0.2   # Light rain
        assert impact_func(15.0) == 0.7  # Moderate-heavy rain
        assert impact_func(60.0) == 1.0  # Extreme rain

    def test_synthetic_data_generation(self):
        """Test synthetic HSDC data generation."""
        from src.pipeline.plugins.hsdc_plugin import HSDCFactorPlugin

        plugin = HSDCFactorPlugin({})
        result = plugin._create_synthetic_data()

        assert not result.empty
        assert 'station_name' in result.columns
        assert 'rainfall_current_mm' in result.columns
        assert 'latitude' in result.columns
        assert 'longitude' in result.columns

    def test_rainfall_summary(self):
        """Test rainfall summary function."""
        from src.pipeline.plugins.hsdc_plugin import HSDCFactorPlugin

        plugin = HSDCFactorPlugin({})

        # Create test data
        test_data = pd.DataFrame({
            'station_name': ['Hoàn Kiếm', 'Cầu Giấy', 'Thanh Xuân'],
            'rainfall_current_mm': [5.0, 10.0, 15.0],
            'rainfall_total_mm': [10.0, 20.0, 30.0],
        })

        summary = plugin.get_rainfall_summary(test_data)

        assert summary['total_stations'] == 3
        assert summary['max_rainfall'] == 15.0
        assert summary['max_station'] == 'Thanh Xuân'
        assert summary['total_accumulated'] == 60.0


class TestWeatherEnsemblePlugin:
    """Tests for Weather Ensemble Plugin."""

    def test_plugin_initialization(self):
        """Test ensemble plugin can be initialized."""
        from src.pipeline.plugins.weather_ensemble_plugin import WeatherEnsemblePlugin

        config = {
            'lambda_decay': 0.15,
            'timeout_threshold_hours': 2.0,
        }
        plugin = WeatherEnsemblePlugin(config)

        assert plugin.factor_name == 'weather_ensemble'
        assert plugin.ensemble is not None

    def test_source_list(self):
        """Test all sources are defined."""
        from src.pipeline.plugins.weather_ensemble_plugin import WeatherEnsemblePlugin

        plugin = WeatherEnsemblePlugin({})

        expected_sources = ['OWM', 'VCW', 'HSDC', 'NCHMF']
        assert plugin.SOURCES == expected_sources

    def test_empty_result_schema(self):
        """Test empty result has correct schema."""
        from src.pipeline.plugins.weather_ensemble_plugin import WeatherEnsemblePlugin

        plugin = WeatherEnsemblePlugin({})
        result = plugin._create_empty_result()

        expected_cols = [
            'datetime', 'variable', 'ensemble_value', 'variable_type',
            'active_sources', 'total_sources', 'source_weights',
            'source_values', 'source_staleness', 'metadata'
        ]

        assert list(result.columns) == expected_cols

    def test_ensemble_summary(self):
        """Test ensemble summary generation."""
        from src.pipeline.plugins.weather_ensemble_plugin import WeatherEnsemblePlugin

        plugin = WeatherEnsemblePlugin({})

        # Create test data
        test_data = pd.DataFrame({
            'datetime': [datetime.now()],
            'variable': ['temperature'],
            'ensemble_value': [30.0],
            'variable_type': ['continuous'],
            'active_sources': [3],
            'total_sources': [4],
            'source_weights': [{'OWM': 0.3, 'VCW': 0.3, 'NCHMF': 0.4}],
            'source_values': [{'OWM': 30, 'VCW': 31, 'NCHMF': 29}],
            'source_staleness': [{'OWM': 0.0, 'VCW': 0.0, 'NCHMF': 4.0}],
        })

        summary = plugin.get_ensemble_summary(test_data)

        assert 'temperature' in summary
        assert summary['temperature']['ensemble_value'] == 30.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
