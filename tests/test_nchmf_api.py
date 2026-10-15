"""
Test NCHMF API Plugin
=====================

Tests for the new NCHMF API plugin that fetches real data from:
1. NCHMF Weather API: https://www.khituongvietnam.gov.vn/WeatherApiService/api/Weather?code={2-73}
2. HTML scraping for warnings from NCHMF website
"""

import pytest
from datetime import datetime
import pandas as pd

from src.pipeline.plugins.nchmf_api_plugin import NCHMFApiPlugin


class TestNCHMFApiPlugin:
    """Test cases for NCHMF API plugin."""

    @pytest.fixture
    def plugin(self):
        """Create plugin instance."""
        return NCHMFApiPlugin({
            'hanoi_only': True,
            'fetch_warnings': True,
            'rate_limit': 0.1,
        })

    @pytest.fixture
    def full_plugin(self):
        """Create plugin for all stations."""
        return NCHMFApiPlugin({
            'hanoi_only': False,
            'fetch_warnings': False,
            'rate_limit': 0.1,
        })

    def test_plugin_initialization(self, plugin):
        """Test plugin initializes correctly."""
        assert plugin is not None
        assert plugin.factor_name == "nchmf_api"
        assert len(plugin.HANOI_CODES) == 14  # codes 2-15

    def test_fetch_hanoi_only(self, plugin):
        """Test fetching Hanoi-area stations only."""
        df = plugin.fetch()

        assert not df.empty, "Should fetch some data"
        assert len(df) > 0, "Should have records"

        # Check sources
        assert 'NCHMF_API' in df['source'].values, "Should have API data"

    def test_fetch_all_stations(self, full_plugin):
        """Test fetching all 72 stations."""
        df = full_plugin.fetch()

        assert not df.empty, "Should fetch some data"

        # Should have API records
        api_df = df[df['source'] == 'NCHMF_API']
        assert len(api_df) > 40, "Should fetch at least 40 stations"

    def test_api_data_structure(self, plugin):
        """Test API data has correct structure."""
        df = plugin.fetch()
        api_df = df[df['source'] == 'NCHMF_API']

        required_columns = [
            'datetime', 'station_code', 'station_name', 'temp_c',
            'humidity_pct', 'wind_speed', 'weather_text', 'weather_impact'
        ]

        for col in required_columns:
            assert col in api_df.columns, f"Missing column: {col}"

    def test_warnings_parsing(self, plugin):
        """Test warning pages are fetched."""
        df = plugin.fetch()

        # Should have warning sources
        warning_sources = [s for s in df['source'].unique() if 'WARNING' in s]
        assert len(warning_sources) > 0, "Should have warning data"

    def test_transform(self, plugin):
        """Test data transformation."""
        df = plugin.fetch()
        transformed = plugin.transform(df)

        assert 'severity' in transformed.columns
        assert 'value' in transformed.columns
        assert 'weather_impact' in transformed.columns

        # Severity should be valid
        valid_severities = ['LOW', 'MEDIUM', 'HIGH', 'SEVERE']
        assert all(s in valid_severities for s in transformed['severity'].unique())

    def test_map_spatial(self, plugin):
        """Test H3 spatial mapping."""
        df = plugin.fetch()
        api_df = df[df['source'] == 'NCHMF_API'].head(5)
        mapped = plugin.map_spatial(api_df)

        # Some records should have hex_ids
        hex_records = mapped[mapped['hex_id'].notna()]
        assert len(hex_records) > 0, "Should map some records to hexagons"

    def test_weather_impact_calculation(self, plugin):
        """Test weather text to impact mapping."""
        # Test various weather texts - patterns are checked in order
        test_cases = [
            ("nắng", 0.0),
            ("mưa rào", 0.5),
            ("mưa", 0.5),  # "mưa" matches "mưa" -> 0.5
            ("giông", 0.8),  # "giông" -> 0.8
            ("bão", 1.0),   # "bão" -> 1.0
        ]

        for text, expected_impact in test_cases:
            impact = plugin._get_weather_impact(text)
            assert impact == expected_impact, f"'{text}' should have impact {expected_impact}, got {impact}"

    def test_wmo_code_mapping(self, plugin):
        """Test Vietnamese text to WMO code mapping."""
        test_cases = [
            ("nắng", 0),
            ("mưa", 61),
            ("giông", 95),
        ]

        for text, expected_code in test_cases:
            code = plugin._map_text_to_code(text)
            assert code == expected_code, f"'{text}' should map to WMO code {expected_code}, got {code}"

    def test_station_coordinates(self, plugin):
        """Test station coordinate lookup."""
        coords = plugin._get_station_coordinates()

        # Hanoi station (29)
        assert 29 in coords
        assert len(coords[29]) == 2

        # Should be in Vietnam
        lat, lon = coords[29]
        assert 8 < lat < 24, "Latitude should be in Vietnam range"
        assert 102 < lon < 110, "Longitude should be in Vietnam range"

    def test_empty_result(self, plugin):
        """Test empty result creation."""
        empty_df = plugin._create_empty_result()

        assert empty_df.empty
        assert isinstance(empty_df, pd.DataFrame)
        assert 'datetime' in empty_df.columns
        assert 'station_code' in empty_df.columns

    def test_summary(self, plugin):
        """Test station summary generation."""
        df = plugin.fetch()
        summary = plugin.get_station_summary(df)

        assert 'total_stations' in summary
        assert 'avg_temp' in summary
        assert summary['total_stations'] > 0

    def test_rate_limiting(self, plugin):
        """Test rate limiting between API calls."""
        import time

        # Should respect rate_limit setting
        start = time.time()
        df1 = plugin._fetch_api_all_stations()
        elapsed = time.time() - start

        # With 14 stations and 0.1s rate limit, should take at least 1.3s
        if len(df1) > 5:
            assert elapsed > 1.0, "Should respect rate limiting"


class TestNCHMFIntegration:
    """Integration tests for NCHMF plugin with pipeline."""

    def test_plugin_in_pipeline(self):
        """Test plugin works in pipeline context."""
        from src.pipeline.demand_spike_pipeline import WeatherDataFetcher, PipelineConfig

        config = PipelineConfig()
        config.sources = {'vcw': False, 'owm': False, 'hsdc': False, 'nchmf': True}

        fetcher = WeatherDataFetcher(config)

        # Fetch data
        data = fetcher.fetch_all_sources()

        assert 'nchmf' in data
        assert not data['nchmf'].empty

        # Transform using the correct plugin
        transformed = fetcher.nchmf.transform(data['nchmf'])
        assert 'value' in transformed.columns
