"""
Features Module
===============

Unified feature engineering for Demand Spike Detector.
Ensures Train-Serving consistency between historical and real-time data.

Modules:
- holiday_calendar: Reusable holiday calendar generator
- preprocessor: Main feature extraction pipeline for LightGBM
- feature_engineer: Merge Weather + Events + Traffic Target
"""

from .holiday_calendar import HolidayCalendarGenerator
from .preprocessor import build_model_features, ModelFeaturePreprocessor
from .feature_engineer import FeatureEngineer, build_training_data

__all__ = [
    'HolidayCalendarGenerator',
    'build_model_features',
    'ModelFeaturePreprocessor',
    'FeatureEngineer',
    'build_training_data',
]
