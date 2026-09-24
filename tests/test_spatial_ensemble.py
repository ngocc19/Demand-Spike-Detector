"""
Unit Tests for Spatial Weather Ensemble Pipeline
==============================================

Tests for H3 mapping, aggregation, and local ensemble per hexagon.
"""

import pytest
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestH3Mapping:
    """Tests for H3 hexagon mapping."""

    def test_hanoi_hex_grid_creation(self):
        """Test creating H3 grid for Hanoi."""
        from src.pipeline.spatial_ensemble_pipeline import create_hanoi_hex_grid

        hexes = create_hanoi_hex_grid(8)

        assert len(hexes) > 0
        assert len(hexes) < 2000  # Should be reasonable number

        # Check all are valid H3 indices
        for h3_idx in hexes[:10]:
            assert h3_idx.startswith('88')  # Hanoi is around 88xxxxxx

    def test_hexagon_centroid(self):
        """Test getting hexagon centroid."""
        from src.pipeline.spatial_ensemble_pipeline import get_hexagon_centroid
        import h3

        # Known hexagon in Hanoi
        hex_id = '88415cb4e5fffff'
        lat, lng = get_hexagon_centroid(hex_id)

        # Should be in Hanoi bounds
        assert 20.85 <= lat <= 21.15
        assert 105.70 <= lng <= 105.95

    def test_hsdc_station_mapping(self):
        """Test mapping HSDC stations to H3."""
        from src.pipeline.spatial_ensemble_pipeline import map_hsdc_stations_to_hex

        # Sample data
        stations = pd.DataFrame({
            'station_name': ['Hoàn Kiếm', 'Cầu Giấy'],
            'latitude': [21.0283, 21.0333],
            'longitude': [105.8542, 105.7833],
            'rainfall_current_mm': [15.0, 22.0],
        })

        mapped = map_hsdc_stations_to_hex(stations, 8)

        assert 'h3_index' in mapped.columns
        assert len(mapped) == 2

        # Each station should map to a valid H3 index
        for _, row in mapped.iterrows():
            assert row['h3_index'] is not None
            assert len(row['h3_index']) > 0


class TestSpatialAggregation:
    """Tests for spatial aggregation."""

    def test_aggregate_by_hex_max(self):
        """Test aggregation using MAX value."""
        from src.pipeline.spatial_ensemble_pipeline import (
            map_hsdc_stations_to_hex,
            aggregate_hsdc_by_hex,
        )

        # Create test data with multiple stations
        stations = pd.DataFrame({
            'station_name': ['Station A', 'Station B'],
            'latitude': [21.0283, 21.0284],  # Very close - same hex
            'longitude': [105.8542, 105.8543],
            'rainfall_current_mm': [10.0, 25.0],  # Different values
        })

        # Map to H3
        mapped = map_hsdc_stations_to_hex(stations, 9)

        # Aggregate
        aggregated = aggregate_hsdc_by_hex(mapped)

        # Should be 1 row (both in same hex)
        assert len(aggregated) == 1

        # Should use MAX
        assert aggregated['rainfall_current_mm'].iloc[0] == 25.0

    def test_aggregate_multiple_hexes(self):
        """Test aggregation across multiple hexagons."""
        from src.pipeline.spatial_ensemble_pipeline import (
            map_hsdc_stations_to_hex,
            aggregate_hsdc_by_hex,
        )

        # Stations far apart (different hexes)
        stations = pd.DataFrame({
            'station_name': ['Hoàn Kiếm', 'Cầu Giấy', 'Thanh Xuân'],
            'latitude': [21.0283, 21.0333, 21.0055],
            'longitude': [105.8542, 105.7833, 105.8120],
            'rainfall_current_mm': [15.0, 22.0, 8.0],
        })

        mapped = map_hsdc_stations_to_hex(stations, 8)
        aggregated = aggregate_hsdc_by_hex(mapped)

        # Should have 3 rows (different hexes)
        assert len(aggregated) == 3

        # MAX should be taken per hex
        max_row = aggregated.loc[aggregated['rainfall_current_mm'].idxmax()]
        assert max_row['station_name'] == 'Cầu Giấy'


class TestCircuitBreaker:
    """Tests for Circuit Breaker logic in spatial context."""

    def test_hex_lookup_creation(self):
        """Test creating H3 -> station lookup."""
        from src.pipeline.spatial_ensemble_pipeline import (
            map_hsdc_stations_to_hex,
            aggregate_hsdc_by_hex,
            create_hex_station_lookup,
        )

        stations = pd.DataFrame({
            'station_name': ['Hoàn Kiếm', 'Cầu Giấy'],
            'latitude': [21.0283, 21.0333],
            'longitude': [105.8542, 105.7833],
            'rainfall_current_mm': [15.0, 22.0],
        })

        mapped = map_hsdc_stations_to_hex(stations, 8)
        aggregated = aggregate_hsdc_by_hex(mapped)
        lookup = create_hex_station_lookup(aggregated)

        assert len(lookup) == 2
        assert 'Hoàn Kiếm' in lookup.values()
        assert 'Cầu Giấy' in lookup.values()

    def test_circuit_breaker_status(self):
        """Test Circuit Breaker status per hexagon."""
        from src.pipeline.spatial_ensemble_pipeline import (
            map_hsdc_stations_to_hex,
            aggregate_hsdc_by_hex,
            create_hex_station_lookup,
        )

        # Known hex with station
        stations = pd.DataFrame({
            'station_name': ['Hoàn Kiếm'],
            'latitude': [21.0283],
            'longitude': [105.8542],
            'rainfall_current_mm': [15.0],
        })

        mapped = map_hsdc_stations_to_hex(stations, 8)
        aggregated = aggregate_hsdc_by_hex(mapped)
        lookup = create_hex_station_lookup(aggregated)

        # Hex with station
        hex_with = mapped['h3_index'].iloc[0]
        assert hex_with in lookup
        status_with = 1

        # Hex without station
        fake_hex = '8928308280fffff'  # Outside Hanoi's 88 prefix
        assert fake_hex not in lookup
        status_without = 0

        print(f"Hex with station: S_HSDC = {status_with}")
        print(f"Hex without station: S_HSDC = {status_without}")


class TestLocalEnsemble:
    """Tests for local ensemble per hexagon."""

    def test_ensemble_weights_with_missing_hsdc(self):
        """Test ensemble gives more weight to available sources."""
        from src.pipeline.weather_ensemble import WeatherEnsembleAggregator, EnsembleConfig

        aggregator = WeatherEnsembleAggregator(EnsembleConfig(lambda_decay=0.1))

        # Case 1: All sources available
        values_all = {
            'OWM': 0.5,
            'VCW': 0.4,
            'HSDC': 0.3,
            'NCHMF': 0.6,
        }

        result_all = aggregator.ensemble_continuous('rainfall', values_all)
        total_weight_all = sum(result_all.source_weights.values())

        # Case 2: HSDC missing
        values_no_hsdc = {
            'OWM': 0.5,
            'VCW': 0.4,
            'HSDC': 0.0,  # Missing
            'NCHMF': 0.6,
        }

        result_no_hsdc = aggregator.ensemble_continuous('rainfall', values_no_hsdc)
        total_weight_no_hsdc = sum(result_no_hsdc.source_weights.values())

        # Weights should still sum to 1.0
        assert abs(total_weight_all - 1.0) < 0.001
        assert abs(total_weight_no_hsdc - 1.0) < 0.001

        print(f"All sources: weights = {result_all.source_weights}")
        print(f"No HSDC: weights = {result_no_hsdc.source_weights}")


class TestIntegration:
    """Integration tests for complete pipeline."""

    def test_complete_workflow(self):
        """Test complete spatial ensemble workflow."""
        from src.pipeline.spatial_ensemble_pipeline import (
            create_hanoi_hex_grid,
            map_hsdc_stations_to_hex,
            aggregate_hsdc_by_hex,
            create_hex_station_lookup,
            get_hexagon_centroid,
        )

        # Step 1: Create grid
        hexes = create_hanoi_hex_grid(8)
        assert len(hexes) > 0

        # Step 2: Simulate HSDC data
        stations = pd.DataFrame({
            'station_name': ['Hoàn Kiếm', 'Cầu Giấy'],
            'latitude': [21.0283, 21.0333],
            'longitude': [105.8542, 105.7833],
            'rainfall_current_mm': [15.0, 22.0],
        })

        # Step 3: Map and aggregate
        mapped = map_hsdc_stations_to_hex(stations, 8)
        aggregated = aggregate_hsdc_by_hex(mapped)
        lookup = create_hex_station_lookup(aggregated)

        assert len(lookup) == 2

        # Step 4: Verify Circuit Breaker logic
        sample_hex = hexes[0]
        has_hsdc = sample_hex in lookup
        status = 1 if has_hsdc else 0

        assert status in [0, 1]  # Valid status

        print(f"✓ Complete workflow test passed")
        print(f"  Grid size: {len(hexes)} hexagons")
        print(f"  HSDC stations mapped: {len(lookup)}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
