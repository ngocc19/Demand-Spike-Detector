"""
Weather Ensemble Plugin
====================

Plugin for combining weather data from multiple sources using ensemble methods.
This is the MAIN plugin that integrates all 4 weather sources.

Sources:
1. OWM: OpenWeatherMap API (https://openweathermap.org/)
2. VCW: Visual Crossing Weather API (https://www.visualcrossing.com/)
3. HSDC: Hanoi Drainage Company (https://maps.hsdc.vn/) - Rainfall Ground Truth
4. NCHMF: National Center for Hydro-Meteorological Forecasting (https://nchmf.gov.vn/)

Ensemble Methods:
- Continuous: MAE-based inverse-error weighting
- Classification: F1-score soft-voting
- Common: Time-decay + Circuit breaker
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging

from ..base import BaseFactorPlugin, FactorType, FactorRecord
from ..registry import PluginRegistry
from ..weather_ensemble import (
    WeatherEnsembleAggregator,
    EnsembleConfig,
    SourceStatus,
    VariableType,
)

logger = logging.getLogger(__name__)


@PluginRegistry.register("weather_ensemble")
class WeatherEnsemblePlugin(BaseFactorPlugin):
    """
    Weather Ensemble Plugin - Combines data from multiple weather sources.

    This plugin:
    1. Fetches data from OWM, VCW, HSDC, NCHMF
    2. Applies ensemble aggregation
    3. Outputs unified weather data with confidence scores

    Usage:
        result = plugin.fetch()
        # Returns ensemble data with weights and confidence
    """

    factor_type = FactorType.WEATHER
    factor_name = "weather_ensemble"
    schedule = "0 * * * *"  # Every hour

    # Sources to aggregate
    SOURCES = ['OWM', 'VCW', 'HSDC', 'NCHMF']

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Initialize ensemble aggregator
        ensemble_config = EnsembleConfig(
            lambda_decay=config.get('lambda_decay', 0.1),
            timeout_threshold_hours=config.get('timeout_threshold_hours', 2.0),
        )
        self.ensemble = WeatherEnsembleAggregator(ensemble_config)

        # Source configurations
        self.sources_config = config.get('sources', {})

        # Source instances
        self._source_instances = {}

        # Metrics cache for ensemble weights
        self.mae_cache = {}  # For continuous variables
        self.f1_cache = {}   # For classification variables

    def fetch(self) -> pd.DataFrame:
        """
        Fetch and ensemble weather data from all sources.

        Returns DataFrame with ensemble weather data including:
        - Ensemble values
        - Per-source values
        - Source weights
        - Confidence scores
        """
        results = []

        # Initialize source plugins
        self._init_sources()

        # Fetch data from each source
        source_data = {}
        source_staleness = {}

        for source_name in self.SOURCES:
            try:
                data = self._fetch_source(source_name)
                if not data.empty:
                    source_data[source_name] = data

                    # Get staleness
                    staleness = self._get_source_staleness(source_name, data)
                    source_staleness[source_name] = staleness

            except Exception as e:
                logger.error(f"Failed to fetch from {source_name}: {e}")
                source_staleness[source_name] = 24.0  # Mark as very stale

        if not source_data:
            logger.error("No data from any source!")
            return self._create_empty_result()

        # Ensemble each variable
        ensemble_results = self._ensemble_all_variables(source_data, source_staleness)

        # Combine results
        for variable, result in ensemble_results.items():
            results.append({
                'datetime': datetime.now(),
                'variable': variable,
                'ensemble_value': result.ensemble_value,
                'variable_type': result.variable_type.value,
                'active_sources': result.active_sources_count,
                'total_sources': result.total_sources_count,
                'source_weights': result.source_weights,
                'source_values': result.source_values,
                'source_staleness': result.source_staleness,
                'metadata': {
                    'ensemble_method': 'weighted_average',
                    'sources_used': list(result.source_values.keys()),
                    'timestamp': datetime.now().isoformat(),
                },
            })

        return pd.DataFrame(results)

    def _init_sources(self):
        """Initialize source plugins if not already done."""
        if not self._source_instances:
            # Lazy import to avoid circular dependency
            try:
                from .owm_plugin import OWMFactorPlugin
                from .vcw_plugin import VCWFactorPlugin
                from .hsdc_plugin import HSDCFactorPlugin
                from .nchmf_plugin import NCHMFFactorPlugin

                self._source_instances = {
                    'OWM': OWMFactorPlugin(self.sources_config.get('owm', {})),
                    'VCW': VCWFactorPlugin(self.sources_config.get('vcw', {})),
                    'HSDC': HSDCFactorPlugin(self.sources_config.get('hsdc', {})),
                    'NCHMF': NCHMFFactorPlugin(self.sources_config.get('nchmf', {})),
                }
            except ImportError as e:
                logger.error(f"Failed to import source plugins: {e}")

    def _fetch_source(self, source_name: str) -> pd.DataFrame:
        """Fetch data from a single source."""
        if source_name not in self._source_instances:
            return pd.DataFrame()

        plugin = self._source_instances[source_name]
        data = plugin.fetch()

        if not data.empty:
            data['source_name'] = source_name

        return data

    def _get_source_staleness(self, source_name: str, data: pd.DataFrame) -> float:
        """Get data staleness for a source."""
        if data.empty:
            return 24.0

        # Try to get staleness from data
        if 'update_time' in data.columns:
            last_update = pd.to_datetime(data['update_time']).max()
            staleness = (datetime.now() - last_update).total_seconds() / 3600
            return staleness

        if 'source_update' in data.columns:
            last_update = pd.to_datetime(data['source_update']).max()
            staleness = (datetime.now() - last_update).total_seconds() / 3600
            return staleness

        # Use default staleness based on source type
        default_staleness = {
            'OWM': 0.0,    # Real-time API
            'VCW': 0.0,    # Real-time API
            'HSDC': 0.25,  # 15-minute updates
            'NCHMF': 4.0,  # 3-hour updates
        }

        return default_staleness.get(source_name, 1.0)

    def _ensemble_all_variables(
        self,
        source_data: Dict[str, pd.DataFrame],
        source_staleness: Dict[str, float]
    ) -> Dict[str, Any]:
        """Ensemble all weather variables."""
        results = {}

        # Get latest values for each source
        latest_values = self._extract_latest_values(source_data)

        # Ensemble continuous variables
        for variable in ['temperature', 'humidity', 'precipitation']:
            source_values = latest_values.get(variable, {})

            if source_values:
                # Get ground truth for MAE calculation (HSDC is best)
                y_true, predictions = self._get_mae_data(variable, source_data)

                result = self.ensemble.ensemble_continuous(
                    variable_name=variable,
                    source_values=source_values,
                    y_true=y_true,
                    predictions=predictions,
                )

                results[variable] = result

        # Ensemble classification variables
        for variable in ['storm', 'thunderstorm', 'heavy_rain']:
            source_values = latest_values.get(variable, {})

            if source_values:
                y_true, predictions = self._get_f1_data(variable, source_data)

                result = self.ensemble.ensemble_classification(
                    variable_name=variable,
                    source_values=source_values,
                    y_true=y_true,
                    predictions=predictions,
                )

                results[variable] = result

        return results

    def _extract_latest_values(self, source_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, float]]:
        """Extract latest values for each variable from each source."""
        latest = {
            'temperature': {},
            'humidity': {},
            'precipitation': {},
            'storm': {},
            'thunderstorm': {},
            'heavy_rain': {},
        }

        for source_name, df in source_data.items():
            if df.empty:
                continue

            # Get latest record
            if 'datetime' in df.columns:
                df = df.sort_values('datetime', ascending=False)

            row = df.iloc[0] if not df.empty else pd.Series()

            # Extract temperature
            if 'temp_c' in row.index:
                latest['temperature'][source_name] = float(row['temp_c'])

            # Extract humidity
            if 'humidity_pct' in row.index:
                latest['humidity'][source_name] = float(row['humidity_pct'])

            # Extract precipitation
            precip_cols = ['precip_mm', 'precip', 'rainfall_mm', 'rain_1h', 'rain_3h']
            for col in precip_cols:
                if col in row.index:
                    latest['precipitation'][source_name] = float(row[col])
                    break

            # Extract storm indicators
            if 'weather_code' in row.index:
                weather_code = int(row['weather_code'])
                # OWM codes for storm
                if weather_code >= 200 and weather_code < 300:
                    latest['storm'][source_name] = 1.0
                    latest['thunderstorm'][source_name] = 1.0
                # Heavy rain
                elif weather_code in [502, 503, 504, 522, 531, 63, 65, 82]:
                    latest['heavy_rain'][source_name] = 1.0
                    latest['storm'][source_name] = 0.7

            # Check storm warning flag
            if 'storm_warning' in row.index:
                if row['storm_warning']:
                    latest['storm'][source_name] = 1.0

            # Check severity
            if 'severity' in row.index:
                severity = row['severity']
                if severity == 'SEVERE':
                    latest['storm'][source_name] = 1.0
                elif severity == 'HIGH':
                    latest['storm'][source_name] = latest.get('storm', {}).get(source_name, 0.7)

        return latest

    def _get_mae_data(self, variable: str, source_data: Dict) -> tuple:
        """Get historical data for MAE calculation."""
        # This would typically come from stored historical predictions
        # For now, return None (will use cache)
        return None, None

    def _get_f1_data(self, variable: str, source_data: Dict) -> tuple:
        """Get historical data for F1-score calculation."""
        # This would typically come from stored historical predictions
        # For now, return None (will use cache)
        return None, None

    def _create_empty_result(self) -> pd.DataFrame:
        """Create empty DataFrame."""
        return pd.DataFrame(columns=[
            'datetime', 'variable', 'ensemble_value', 'variable_type',
            'active_sources', 'total_sources', 'source_weights',
            'source_values', 'source_staleness', 'metadata'
        ])

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform ensemble results to standardized format."""
        if df.empty:
            return df

        df = df.copy()

        # Calculate confidence based on active sources and weights
        def calc_confidence(row):
            weights = row.get('source_weights', {})
            if not weights:
                return 0.0

            # Higher confidence when:
            # 1. More sources agree (concentrated weight)
            # 2. Sources are fresh (low staleness)
            active_count = sum(1 for w in weights.values() if w > 0)

            if active_count == 0:
                return 0.0

            # Weight concentration (Herfindahl index)
            weight_sq_sum = sum(w ** 2 for w in weights.values() if w > 0)
            concentration = weight_sq_sum if weight_sq_sum > 0 else 0.5

            # Staleness penalty
            staleness = row.get('source_staleness', {})
            avg_staleness = sum(staleness.values()) / len(staleness) if staleness else 0
            staleness_factor = max(0, 1 - avg_staleness / 24)  # Penalty for data >24h old

            # Combined confidence
            confidence = (active_count / 4) * concentration * staleness_factor
            return min(1.0, confidence)

        df['confidence'] = df.apply(calc_confidence, axis=1)

        # Map to standard severity
        def value_to_severity(row):
            value = row['ensemble_value']

            # For probabilities (storm, thunderstorm)
            if row.get('variable_type') == 'classification':
                if value >= 0.8:
                    return 'SEVERE'
                elif value >= 0.5:
                    return 'HIGH'
                elif value >= 0.2:
                    return 'MEDIUM'
                return 'LOW'

            # For continuous values (temperature, humidity)
            # Use percentile-based severity
            if value >= 0.8:
                return 'SEVERE'
            elif value >= 0.5:
                return 'HIGH'
            elif value >= 0.2:
                return 'MEDIUM'
            return 'LOW'

        df['severity'] = df.apply(value_to_severity, axis=1)

        # Set value for ensemble
        df['value'] = df['ensemble_value']

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map ensemble results to spatial grid."""
        if df.empty:
            return df

        import h3

        df = df.copy()

        # Hanoi center
        center = (21.0285, 105.8542)
        center_hex = h3.latlng_to_cell(center[0], center[1], 8)
        hex_ids = list(h3.grid_disk(center_hex, 20))

        records = []
        for _, row in df.iterrows():
            for hex_id in hex_ids:
                new_row = row.copy()
                new_row['hex_id'] = hex_id
                records.append(new_row)

        return pd.DataFrame(records)

    def get_ensemble_summary(self, df: pd.DataFrame) -> Dict:
        """
        Get summary of ensemble results.

        Useful for monitoring and debugging.
        """
        if df.empty:
            return {}

        summary = {
            'timestamp': datetime.now().isoformat(),
            'variables': df['variable'].unique().tolist(),
            'total_records': len(df),
        }

        for variable in df['variable'].unique():
            var_data = df[df['variable'] == variable]
            if not var_data.empty:
                row = var_data.iloc[0]
                summary[variable] = {
                    'ensemble_value': row['ensemble_value'],
                    'confidence': row.get('confidence', 0),
                    'severity': row.get('severity', 'UNKNOWN'),
                    'active_sources': row['active_sources'],
                    'weights': row.get('source_weights', {}),
                }

        return summary
