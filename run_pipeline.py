"""
Quick Test Script for Data Pipeline
====================================

Run this to test individual plugins or the full pipeline.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))


def test_weather_plugin():
    """Test Weather Plugin."""
    print("\n" + "="*60)
    print("TESTING: Weather Plugin")
    print("="*60)

    from src.pipeline.plugins.weather_plugin import WeatherFactorPlugin

    config = {
        'name': 'weather',
        'latitude': 21.0285,  # Hanoi
        'longitude': 105.8542,
        'radius_km': 10,
        'timezone': 'Asia/Ho_Chi_Minh',
        'forecast_days': 2,
    }

    plugin = WeatherFactorPlugin(config)

    # Fetch
    df = plugin.fetch()
    print(f"\nFetched {len(df)} weather records")
    print(df.head())

    # Transform
    df = plugin.transform(df)
    print(f"\nAfter transform:")
    print(df[['datetime', 'weather_code', 'weather_impact', 'value', 'severity']].head())

    # Map spatial
    df = plugin.map_spatial(df)
    print(f"\nAfter spatial mapping: {len(df)} records")
    print(f"Unique hex_ids: {df['hex_id'].nunique()}")

    return df


def test_flood_plugin():
    """Test Flood Plugin."""
    print("\n" + "="*60)
    print("TESTING: Flood Plugin")
    print("="*60)

    from src.pipeline.plugins.flood_plugin import FloodFactorPlugin

    config = {
        'name': 'flood',
        'rss_sources': ['https://vnexpress.net/rss/thoi-su.rss'],
        'latitude': 21.0285,
        'longitude': 105.8542,
    }

    plugin = FloodFactorPlugin(config)

    # Fetch
    df = plugin.fetch()
    print(f"\nFetched {len(df)} flood news")

    if not df.empty:
        print("\nSample entries:")
        print(df[['title', 'published']].head())

        # Transform
        df = plugin.transform(df)
        print(f"\nAfter transform:")
        print(df[['title', 'severity', 'value']].head())

    return df


def test_event_plugin():
    """Test Event Plugin."""
    print("\n" + "="*60)
    print("TESTING: Event Plugin")
    print("="*60)

    from src.pipeline.plugins.event_plugin import EventFactorPlugin

    config = {
        'name': 'event',
        'csv_path': 'data/events.csv',
    }

    plugin = EventFactorPlugin(config)

    # Fetch
    df = plugin.fetch()
    print(f"\nFetched {len(df)} events")
    print(df.head())

    # Transform
    df = plugin.transform(df)
    print(f"\nAfter transform:")
    print(df[['event_name', 'event_type', 'value', 'severity']].head())

    # Map spatial
    df = plugin.map_spatial(df)
    print(f"\nAfter spatial mapping: {len(df)} records")

    return df


def test_holiday_plugin():
    """Test Holiday Plugin."""
    print("\n" + "="*60)
    print("TESTING: Holiday Plugin")
    print("="*60)

    from src.pipeline.plugins.holiday_plugin import HolidayFactorPlugin

    config = {
        'name': 'holiday',
        'holiday_file': 'data/holidays.csv',
    }

    plugin = HolidayFactorPlugin(config)

    # Fetch
    df = plugin.fetch()
    print(f"\nFetched {len(df)} holidays")
    print(df.head())

    # Transform
    df = plugin.transform(df)
    print(f"\nAfter transform:")
    print(df[['date', 'holiday_name', 'tet_phase', 'value', 'severity']].head())

    # Map spatial
    df = plugin.map_spatial(df)
    print(f"\nAfter spatial mapping: {len(df)} records")
    print(f"Unique hex_ids: {df['hex_id'].nunique()}")

    return df


def test_registry():
    """Test Plugin Registry."""
    print("\n" + "="*60)
    print("TESTING: Plugin Registry")
    print("="*60)

    from src.pipeline.registry import PluginRegistry

    print(f"\nRegistered plugins: {PluginRegistry.list_plugins()}")


def test_full_pipeline():
    """Test full pipeline with Orchestrator."""
    print("\n" + "="*60)
    print("TESTING: Full Pipeline")
    print("="*60)

    from src.pipeline.orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator(
        config_path='config/factors.yaml',
        feature_store_path='data/feature_store.csv'
    )

    print(f"\nLoaded plugins: {list(orchestrator.plugins.keys())}")

    # Run all plugins
    df = orchestrator.run_all_plugins()

    print(f"\n{'='*60}")
    print("RESULT: Feature Store")
    print("="*60)
    print(f"Total records: {len(df)}")
    print(f"Columns: {list(df.columns)}")

    if not df.empty:
        print("\nSample data:")
        print(df.head())

        # Summary
        print("\nFactor statistics:")
        for col in df.columns:
            if col not in ['hex_id', 'datetime_30min']:
                non_zero = (df[col] > 0).sum()
                print(f"  {col}: {non_zero} non-zero records ({non_zero/len(df)*100:.1f}%)")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Test Data Pipeline')
    parser.add_argument(
        '--plugin',
        choices=['weather', 'flood', 'event', 'holiday', 'all'],
        default='all',
        help='Which plugin to test'
    )
    parser.add_argument(
        '--registry',
        action='store_true',
        help='Test plugin registry'
    )

    args = parser.parse_args()

    if args.registry:
        test_registry()
        return

    if args.plugin in ['weather', 'all']:
        test_weather_plugin()

    if args.plugin in ['flood', 'all']:
        test_flood_plugin()

    if args.plugin in ['event', 'all']:
        test_event_plugin()

    if args.plugin in ['holiday', 'all']:
        test_holiday_plugin()

    if args.plugin == 'all':
        test_registry()
        test_full_pipeline()

    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)


if __name__ == '__main__':
    main()
