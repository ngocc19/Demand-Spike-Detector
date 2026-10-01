"""
Features Module
===============

Unified feature engineering for Demand Spike Detector.
Ensures Train-Serving consistency between historical and real-time data.

Modules:
- holiday_calendar: Reusable holiday calendar generator
- preprocessor: Main feature extraction pipeline for LightGBM
"""

from .holiday_calendar import HolidayCalendarGenerator
from .preprocessor import build_model_features, ModelFeaturePreprocessor

__all__ = [
    'HolidayCalendarGenerator',
    'build_model_features',
    'ModelFeaturePreprocessor',
]
