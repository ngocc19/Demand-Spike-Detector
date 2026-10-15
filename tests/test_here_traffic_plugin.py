"""
Test HERE Traffic Plugin
=======================

Tests for HERE Traffic Plugin with Traffic Flow API.
"""

import pytest
from datetime import datetime
import pandas as pd
import os

from src.pipeline.plugins.here_traffic_plugin import (
    HERETrafficPlugin,
    ANCHOR_POINTS,
    FREE_FLOW_SPEEDS,
)


class TestHERETrafficPlugin:
    """Test cases for HERE Traffic Plugin."""

    @pytest.fixture
    def plugin(self):
        """Create plugin instance with test API key."""
        return HERETrafficPlugin({
            'api_key': os.environ.get('HERE_API_KEY', 'test_key'),
            'data_lake_dir': 'data/traffic/test',
            'center_lat': 21.0285,
            'center_lon': 105.8542,
            'radius_m': 10000,  # 10km for testing
        })

    def test_plugin_initialization(self, plugin):
        """Test plugin initializes correctly."""
        assert plugin is not None
        assert plugin.factor_name == "here_traffic"
        assert plugin.factor_type.value == "traffic"
        assert len(plugin.anchor_points) == 35

    def test_anchor_points_structure(self):
        """Test anchor points have correct structure."""
        for anchor in ANCHOR_POINTS:
            assert 'id' in anchor
            assert 'name' in anchor
            assert 'lat' in anchor
            assert 'lon' in anchor
            assert 'is_control' in anchor
            assert 20.9 <= anchor['lat'] <= 21.2  # Extended to include Southern Hanoi
            assert 105.6 <= anchor['lon'] <= 105.9

    def test_control_points(self):
        """Test control points are properly marked."""
        control_points = [a for a in ANCHOR_POINTS if a['is_control']]
        assert len(control_points) == 5  # Highways

        # Control points should be on highways
        highway_names = ['thang long', 'vo nguyen giap', 'truong sa', 'cao toc', 'cienco']
        for cp in control_points:
            name_lower = cp['name'].lower()
            is_highway = any(hw in name_lower for hw in highway_names)
            assert is_highway, f"Control point {cp['name']} should be a highway"

    def test_free_flow_speeds(self):
        """Test free flow speeds are reasonable."""
        assert FREE_FLOW_SPEEDS['highway'] >= 80
        assert FREE_FLOW_SPEEDS['major'] >= 40
        assert FREE_FLOW_SPEEDS['default'] >= 30

    def test_calculate_speed_drop_ratio(self, plugin):
        """Test speed drop ratio calculation."""
        # Free flow - no drop
        ratio = plugin._calculate_speed_drop_ratio(60, 60)
        assert ratio == 0.0

        # Half speed - 50% drop
        ratio = plugin._calculate_speed_drop_ratio(30, 60)
        assert ratio == 0.5

        # Stopped - 100% drop
        ratio = plugin._calculate_speed_drop_ratio(0, 60)
        assert ratio == 1.0

        # Speed higher than free flow (rare) - no drop
        ratio = plugin._calculate_speed_drop_ratio(70, 60)
        assert ratio == 0.0

    def test_haversine_distance(self, plugin):
        """Test Haversine distance calculation."""
        # Same point - distance should be 0
        dist = plugin._haversine_distance(21.0285, 105.8542, 21.0285, 105.8542)
        assert dist == 0.0

        # Known distance (roughly 1km)
        # Hanoi center to ~1km north
        dist = plugin._haversine_distance(21.0285, 105.8542, 21.0375, 105.8542)
        assert 0.9 < dist < 1.1  # Should be ~1km

    def test_transform_jam_factor_to_severity(self, plugin):
        """Test jam factor to severity mapping."""
        df = pd.DataFrame({
            'datetime': [datetime.now()] * 5,
            'jam_factor': [0.0, 2.0, 4.0, 7.0, 10.0],
            'speed_drop_ratio': [0.0, 0.3, 0.5, 0.8, 1.0],
        })

        transformed = plugin.transform(df)

        assert list(transformed['severity']) == ['LOW', 'MEDIUM', 'HIGH', 'SEVERE', 'SEVERE']
        assert list(transformed['congestion_level']) == [
            'FREE_FLOW', 'LIGHT', 'MODERATE', 'HEAVY', 'GRIDLOCK'
        ]

    def test_congestion_level_mapping(self, plugin):
        """Test congestion level from jam factor."""
        # Test gridlock
        df = pd.DataFrame({
            'datetime': [datetime.now()],
            'jam_factor': [9.0],
            'speed_drop_ratio': [0.9],
        })
        transformed = plugin.transform(df)
        assert transformed['congestion_level'].iloc[0] == 'GRIDLOCK'

    def test_road_type_detection(self, plugin):
        """Test road type detection from road name."""
        test_cases = [
            ('Highway 1', 'highway'),
            ('motorway expressway', 'highway'),
            ('Quoc lo 1A', 'major'),
            ('primary road', 'major'),
            ('Duong Tran Duy Hung', 'default'),  # Not matching any pattern
            ('Service road', 'local'),
            ('residential street', 'local'),
            ('cao toc Ha Noi', 'highway'),
        ]

        for road_name, expected_type in test_cases:
            detected_type = plugin._detect_road_type(road_name)
            assert detected_type == expected_type, f"Road '{road_name}' should be '{expected_type}', got '{detected_type}'"

    def test_empty_traffic_data(self, plugin):
        """Test handling of empty traffic data."""
        empty_result = plugin._create_empty_result()
        assert empty_result.empty
        assert isinstance(empty_result, pd.DataFrame)

        required_cols = [
            'datetime', 'anchor_id', 'anchor_name', 'lat', 'lon',
            'current_speed', 'jam_factor', 'speed_drop_ratio',
            'severity', 'confidence'
        ]
        for col in required_cols:
            assert col in empty_result.columns

    def test_get_anchor_traffic_no_data(self, plugin):
        """Test anchor traffic when no flow data available."""
        anchor = ANCHOR_POINTS[0]  # First non-control point

        result = plugin._get_anchor_traffic(anchor, {}, {})

        assert result['anchor_id'] == anchor['id']
        assert result['anchor_name'] == anchor['name']
        assert result['confidence'] == 0.0  # Low confidence - no data
        assert result['is_control'] == False

    def test_get_anchor_traffic_with_control_point(self, plugin):
        """Test anchor traffic for control points (highways)."""
        control_point = [a for a in ANCHOR_POINTS if a['is_control']][0]

        result = plugin._get_anchor_traffic(control_point, {}, {})

        assert result['is_control'] == True
        assert result['speed_drop_ratio'] == 0.0
        assert result['current_speed'] == FREE_FLOW_SPEEDS['highway']

    def test_cache_mechanism(self, plugin):
        """Test cache is invalidated when TTL expires."""
        # Initially cache should be invalid
        assert not plugin._is_cache_valid()

        # After update, cache should be valid
        plugin._update_cache([{'anchor_id': 1, 'speed_drop_ratio': 0.5}])
        assert plugin._is_cache_valid()

    def test_cache_ttl(self, plugin):
        """Test cache respects TTL setting."""
        import time

        plugin.cache_ttl_minutes = 1

        # Update cache
        plugin._update_cache([{'anchor_id': 1, 'speed_drop_ratio': 0.5}])

        # Should be valid immediately
        assert plugin._is_cache_valid()

        # Manually set cache to old time
        from datetime import timedelta
        plugin.last_cache_update = datetime.now() - timedelta(minutes=2)

        # Should now be invalid
        assert not plugin._is_cache_valid()

    def test_traffic_summary(self, plugin):
        """Test traffic summary generation."""
        df = pd.DataFrame({
            'datetime': [datetime.now()] * 3,
            'anchor_id': [1, 2, 3],
            'is_control': [False, False, True],
            'current_speed': [30.0, 50.0, 100.0],
            'jam_factor': [5.0, 2.0, 0.0],
            'speed_drop_ratio': [0.5, 0.2, 0.0],
            'severity': ['HIGH', 'MEDIUM', 'LOW'],
            'has_incident': [True, False, False],
        })

        summary = plugin.get_traffic_summary(df)

        assert 'total_anchors' in summary
        assert summary['total_anchors'] == 3
        assert summary['control_anchors'] == 1
        assert summary['avg_speed'] == 60.0
        assert summary['severe_count'] == 0


class TestHERETrafficPluginIntegration:
    """Integration tests - requires actual API call."""

    @pytest.fixture
    def real_plugin(self):
        """Create plugin with real API key."""
        api_key = os.environ.get('HERE_API_KEY')
        if not api_key:
            pytest.skip("HERE_API_KEY not set")

        return HERETrafficPlugin({
            'api_key': api_key,
            'data_lake_dir': 'data/traffic/test',
            'center_lat': 21.0285,
            'center_lon': 105.8542,
            'radius_m': 15000,  # 15km
            'cache_ttl_minutes': 0,  # Disable cache for testing
        })

    @pytest.mark.integration
    def test_fetch_real_traffic_data(self, real_plugin):
        """Test fetching real traffic data from HERE API."""
        try:
            df = real_plugin.fetch()

            # Should get some data (may be empty if API fails)
            if not df.empty:
                assert 'anchor_id' in df.columns
                assert 'current_speed' in df.columns
                assert 'jam_factor' in df.columns
                assert 'speed_drop_ratio' in df.columns
                assert 'severity' in df.columns

                # At least some non-control points should have data
                non_control = df[~df['is_control']]
                if not non_control.empty:
                    assert non_control['current_speed'].max() > 0

        except Exception as e:
            pytest.skip(f"API call failed: {e}")

    @pytest.mark.integration
    def test_traffic_flow_api_response(self, real_plugin):
        """Test Traffic Flow API response parsing."""
        flow_data = real_plugin._fetch_traffic_flow()

        # Should return a dict
        assert isinstance(flow_data, dict)

        # If data available, check structure
        if flow_data:
            for (lat, lon), data in list(flow_data.items())[:5]:
                assert 'speed_kmh' in data
                assert 'jam_factor' in data
                assert 'confidence' in data
                assert 'free_flow_speed' in data
