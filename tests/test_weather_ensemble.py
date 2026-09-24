"""
Unit Tests for Weather Ensemble Aggregator
==========================================

Tests all mathematical steps of the ensemble algorithm.
"""

import pytest
import numpy as np
from datetime import datetime, timedelta
from src.pipeline.weather_ensemble import (
    WeatherEnsembleAggregator,
    EnsembleConfig,
    SourceStatus,
    VariableType,
)


class TestContinuousWeights:
    """Test Branch 1: Continuous Variables (MAE-based inverse-error weighting)."""

    def test_inverse_error_weighting(self):
        """Test that lower MAE gets higher weight."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        # Simulated MAE: NCHMF best, OWM worst
        mae_history = {
            'OWM': [2.5],
            'VCW': [1.8],
            'HSDC': [1.2],  # Best
            'NCHMF': [1.0],  # Best
        }
        aggregator.mae_cache['temperature'] = mae_history.copy()

        weights = aggregator.compute_continuous_weights('temperature')

        # NCHMF should have highest weight (lowest MAE)
        assert weights['NCHMF'] > weights['VCW']
        assert weights['NCHMF'] > weights['HSDC']
        assert weights['HSDC'] > weights['OWM']

        # Sum should be 1.0
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_equal_weights_when_no_history(self):
        """Test equal weights when no MAE history available."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        weights = aggregator.compute_continuous_weights('new_variable')

        # All equal when no history
        n_sources = len(config.sources)
        expected_weight = 1.0 / n_sources

        for source in weights:
            assert abs(weights[source] - expected_weight) < 1e-6


class TestClassificationWeights:
    """Test Branch 2: Binary Classification (F1-score soft-voting)."""

    def test_f1_score_calculation(self):
        """Test precision, recall, F1 calculation."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        y_true = np.array([0, 0, 0, 0, 1, 1, 1, 0, 0, 1])
        y_pred = np.array([0, 0, 0, 0, 1, 1, 0, 0, 0, 1])

        precision, recall, f1 = aggregator.calculate_precision_recall(y_true, y_pred)

        # TP=3, FN=1, FP=0, TN=6
        assert precision == 1.0  # No false positives
        assert recall == 0.75    # 3/4
        expected_f1 = 2 * 1.0 * 0.75 / (1.0 + 0.75)
        assert abs(f1 - expected_f1) < 1e-6

    def test_f1_based_weights(self):
        """Test that higher F1 gets higher weight."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        y_true = np.array([0, 0, 0, 0, 1, 1, 1, 0, 0, 1])

        # NCHMF perfect, others partial
        predictions = {
            'OWM': np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),  # All negative
            'VCW': np.array([0, 0, 0, 0, 1, 1, 0, 0, 0, 1]),  # Moderate
            'NCHMF': np.array([0, 0, 0, 0, 1, 1, 1, 0, 0, 1]),  # Best
        }

        weights = aggregator.compute_classification_weights(
            'storm', y_true=y_true, predictions=predictions
        )

        # NCHMF should have highest weight
        assert weights['NCHMF'] > weights['VCW']
        assert weights['VCW'] > weights['OWM']

        # Sum should be 1.0
        assert abs(sum(weights.values()) - 1.0) < 1e-6


class TestTimeDecay:
    """Test Step 3: Time-Decay Function."""

    def test_time_decay_formula(self):
        """Test exponential decay: w'_i = w_i * e^(-λ * Δt)."""
        config = EnsembleConfig(lambda_decay=0.1)
        aggregator = WeatherEnsembleAggregator(config)

        base_weights = {'A': 0.5, 'B': 0.3, 'C': 0.2}
        staleness = {'A': 0.0, 'B': 5.0, 'C': 10.0}

        decayed = aggregator.apply_time_decay(base_weights, staleness)

        # Check decay factors
        assert decayed['A'] == pytest.approx(0.5 * 1.0, rel=1e-6)
        assert decayed['B'] == pytest.approx(0.3 * np.exp(-0.5), rel=1e-6)
        assert decayed['C'] == pytest.approx(0.2 * np.exp(-1.0), rel=1e-6)

    def test_4_hour_decay_factor(self):
        """Test decay factor for 4-hour delay with λ=0.15."""
        config = EnsembleConfig(lambda_decay=0.15)
        aggregator = WeatherEnsembleAggregator(config)

        base_weights = {'NCHMF': 0.3124}
        staleness = {'NCHMF': 4.0}

        decayed = aggregator.apply_time_decay(base_weights, staleness)

        expected = 0.3124 * np.exp(-0.15 * 4.0)
        assert decayed['NCHMF'] == pytest.approx(expected, rel=1e-4)


class TestCircuitBreaker:
    """Test Step 4: Circuit Breaker & Normalization."""

    def test_failed_source_zero_weight(self):
        """Test that FAILED source gets weight 0."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        decayed_weights = {'OWM': 0.2, 'VCW': 0.3, 'HSDC': 0.5}
        source_status = {
            'OWM': SourceStatus.FAILED,
            'VCW': SourceStatus.HEALTHY,
            'HSDC': SourceStatus.HEALTHY,
        }

        final = aggregator.apply_circuit_breaker(decayed_weights, source_status)

        assert final['OWM'] == 0.0
        assert final['VCW'] > 0
        assert final['HSDC'] > 0
        assert abs(sum(final.values()) - 1.0) < 1e-6

    def test_timeout_keeps_weight(self):
        """Test that TIMEOUT source keeps reduced weight (time-decay already applied)."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        decayed_weights = {'NCHMF': 0.15, 'VCW': 0.45, 'HSDC': 0.40}
        source_status = {
            'NCHMF': SourceStatus.TIMEOUT,  # Stale but usable
            'VCW': SourceStatus.HEALTHY,
            'HSDC': SourceStatus.HEALTHY,
        }

        final = aggregator.apply_circuit_breaker(decayed_weights, source_status)

        # TIMEOUT should keep its weight (S=1)
        assert final['NCHMF'] > 0
        assert abs(sum(final.values()) - 1.0) < 1e-6

    def test_all_sources_failed_emergency_weights(self):
        """Test emergency equal weights when all sources fail."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        decayed_weights = {'OWM': 0.0, 'VCW': 0.0, 'HSDC': 0.0, 'NCHMF': 0.0}
        source_status = {
            'OWM': SourceStatus.FAILED,
            'VCW': SourceStatus.FAILED,
            'HSDC': SourceStatus.FAILED,
            'NCHMF': SourceStatus.FAILED,
        }

        final = aggregator.apply_circuit_breaker(decayed_weights, source_status)

        # Should return equal weights (emergency fallback)
        expected = 1.0 / len(final)
        for w in final.values():
            assert abs(w - expected) < 1e-6


class TestEnsembleOutput:
    """Test Step 5: Ensemble Output."""

    def test_weighted_sum(self):
        """Test Y_final = Σ(w*_i * Y_i)."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        weights = {'A': 0.5, 'B': 0.3, 'C': 0.2}
        values = {'A': 10.0, 'B': 20.0, 'C': 30.0}

        result = aggregator.compute_ensemble_output(weights, values)

        expected = 0.5 * 10.0 + 0.3 * 20.0 + 0.2 * 30.0
        assert result == pytest.approx(expected, rel=1e-6)


class TestFullEnsembleWorkflow:
    """Test complete ensemble workflow with edge cases."""

    def test_owm_failure_circuit_breaker(self):
        """Test full workflow when OWM fails."""
        config = EnsembleConfig(lambda_decay=0.15)
        aggregator = WeatherEnsembleAggregator(config)

        # Mark OWM as failed
        aggregator.update_source_status('OWM', SourceStatus.FAILED)

        # Current predictions
        predictions = {
            'OWM': 0.3,
            'VCW': 0.5,
            'HSDC': 0.7,
            'NCHMF': 0.85,
        }

        result = aggregator.ensemble_classification(
            variable_name='storm',
            source_values=predictions,
        )

        # OWM should have zero weight
        assert result.source_weights['OWM'] == 0.0
        assert result.source_values['OWM'] == 0.3  # Raw value still recorded
        assert result.active_sources_count == 3

    def test_nchmf_delay_time_decay(self):
        """Test full workflow when NCHMF is delayed 4 hours."""
        config = EnsembleConfig(lambda_decay=0.15)
        aggregator = WeatherEnsembleAggregator(config)

        # Simulate 4-hour delay
        aggregator.simulate_staleness('NCHMF', hours_ago=4)

        # Verify staleness
        assert aggregator.source_info['NCHMF'].staleness_hours == pytest.approx(4.0, rel=0.1)

        # Status should still be HEALTHY (not TIMEOUT)
        assert aggregator.source_info['NCHMF'].status == SourceStatus.HEALTHY

    def test_combined_edge_cases(self):
        """Test OWM failure + NCHMF delay combined."""
        config = EnsembleConfig(lambda_decay=0.15)
        aggregator = WeatherEnsembleAggregator(config)

        # Setup edge cases
        aggregator.update_source_status('OWM', SourceStatus.FAILED)
        aggregator.simulate_staleness('NCHMF', hours_ago=4)

        # Historical F1 scores (NCHMF best)
        y_true = np.array([0, 0, 0, 0, 1, 1, 1, 0, 0, 1])
        predictions = {
            'OWM': np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            'VCW': np.array([0, 0, 0, 0, 1, 1, 0, 0, 0, 1]),
            'HSDC': np.array([0, 0, 0, 0, 1, 1, 1, 0, 0, 1]),
            'NCHMF': np.array([0, 0, 0, 0, 1, 1, 1, 0, 0, 1]),
        }

        # Current values
        storm_values = {
            'OWM': 0.3,
            'VCW': 0.5,
            'HSDC': 0.7,
            'NCHMF': 0.85,
        }

        result = aggregator.ensemble_classification(
            variable_name='storm',
            source_values=storm_values,
            y_true=y_true,
            predictions=predictions,
        )

        # OWM should be excluded
        assert result.source_weights['OWM'] == 0.0

        # NCHMF should still have positive weight despite delay
        assert result.source_weights['NCHMF'] > 0

        # Ensemble should be between min and max values
        active_values = [v for s, v in storm_values.items()
                        if result.source_weights[s] > 0]
        assert result.ensemble_value >= min(active_values)
        assert result.ensemble_value <= max(active_values)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_predictions(self):
        """Test handling of empty predictions."""
        config = EnsembleConfig()
        aggregator = WeatherEnsembleAggregator(config)

        result = aggregator.ensemble_continuous(
            variable_name='temperature',
            source_values={},
        )

        # Should return 0 for empty input
        assert result.ensemble_value == 0.0

    def test_single_source(self):
        """Test with only one source available."""
        config = EnsembleConfig(lambda_decay=0.15)
        aggregator = WeatherEnsembleAggregator(config)

        # Fail all but one
        aggregator.update_source_status('OWM', SourceStatus.FAILED)
        aggregator.update_source_status('VCW', SourceStatus.FAILED)
        aggregator.update_source_status('HSDC', SourceStatus.FAILED)

        result = aggregator.ensemble_classification(
            variable_name='storm',
            source_values={'NCHMF': 0.85},
        )

        # NCHMF should get all weight
        assert result.source_weights['NCHMF'] == 1.0
        assert result.ensemble_value == 0.85


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
