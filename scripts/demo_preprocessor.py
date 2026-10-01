"""
Demo Script for Feature Preprocessor
===================================

Shows how to use the unified feature preprocessor for both
historical (training) and realtime (inference) data.

Usage:
    python scripts/demo_preprocessor.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
from src.features.preprocessor import build_model_features, ModelFeaturePreprocessor
from src.features.holiday_calendar import HolidayCalendarGenerator


def demo_simple():
    print()
    print('=' * 60)
    print('DEMO: Simple build_model_features()')
    print('=' * 60)
    
    df = pd.DataFrame({
        'timestamp': pd.date_range('2026-09-01 08:00:00', periods=5, freq='h'),
        'temp_c': [28.0, 28.5, 29.0, 29.5, 30.0],
        'humidity_pct': [85, 84, 83, 82, 81],
        'precip': [0.0, 0.0, 0.5, 1.0, 2.0],
    })
    
    print('Input:', df.shape)
    features = build_model_features(df)
    print('Output:', features.shape)
    print('Columns:', list(features.columns))


def demo_realtime():
    print()
    print('=' * 60)
    print('DEMO: Realtime Data Transformation')
    print('=' * 60)
    
    try:
        df = pd.read_parquet('data/realtime_lake/weather_2026-09-29.parquet')
    except FileNotFoundError:
        print('Realtime data not found. Skipping...')
        return
    
    print('Input:', df.shape)
    features = build_model_features(df, timestamp_col='crawled_at')
    print('Output:', features.shape)
    print('Columns:', list(features.columns))
    
    excluded = ['is_flooded', 'flood_level', 'storm_warning']
    found = [c for c in excluded if c in features.columns]
    if found:
        print('WARNING: Still has excluded columns:', found)
    else:
        print('OK: Flood/storm columns correctly excluded')


def demo_class():
    print()
    print('=' * 60)
    print('DEMO: ModelFeaturePreprocessor Class')
    print('=' * 60)
    
    preprocessor = ModelFeaturePreprocessor(year=2026)
    df = pd.DataFrame({
        'crawled_at': pd.date_range('2026-09-01', periods=10, freq='h'),
        'temp_c': [28.0] * 10,
    })
    
    features = preprocessor.transform(df)
    print('Feature names:', preprocessor.feature_names)


def demo_holidays():
    print()
    print('=' * 60)
    print('DEMO: HolidayCalendarGenerator')
    print('=' * 60)
    
    gen = HolidayCalendarGenerator(year=2026)
    print('Tet 2026:', gen.get_tet_date())
    
    holidays = gen.get_holidays_in_range(
        pd.Timestamp('2026-09-01'),
        pd.Timestamp('2026-09-30')
    )
    print('Holidays in Sep 2026:', len(holidays))
    for _, row in holidays.iterrows():
        print(f'  {row["date"].strftime("%Y-%m-%d")}: {row["holiday_name"]}')


def main():
    print()
    print('=' * 60)
    print('FEATURE PREPROCESSOR DEMO')
    print('=' * 60)
    
    demos = [demo_simple, demo_realtime, demo_class, demo_holidays]
    for d in demos:
        try:
            d()
        except Exception as e:
            print(f'Error in {d.__name__}: {e}')
    
    print()
    print('=' * 60)
    print('ALL DEMOS COMPLETE')
    print('=' * 60)


if __name__ == '__main__':
    main()
