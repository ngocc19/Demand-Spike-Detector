"""
Demand Spike Detector
====================

A real-time demand spike detection system for urban ride-hailing platforms.
Based on NYC Taxi/Uber research (Correa & Moyano, 2023).

Components:
- pipeline: Factor plugin architecture for data ingestion
- traffic: Traffic prediction with LightGBM
- features: Feature engineering
"""

__version__ = "2.0.0"

# Import main classes for easy access
from .pipeline.plugins.weather_ensemble_plugin import WeatherEnsemblePlugin
from .pipeline.plugins.here_traffic_plugin import HERETrafficPlugin
from .traffic import (
    TrafficDataGenerator,
    TrafficPredictor,
    TrafficPredictionPipeline,
)
from .features import (
    FeatureEngineer,
    build_training_data,
)

__all__ = [
    # Plugins
    'WeatherEnsemblePlugin',
    'HERETrafficPlugin',
    # Traffic
    'TrafficDataGenerator',
    'TrafficPredictor',
    'TrafficPredictionPipeline',
    # Features
    'FeatureEngineer',
    'build_training_data',
]
