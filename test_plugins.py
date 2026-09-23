"""
Test script for all plugins
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Fix UTF-8 output for Windows
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def test_weather_plugin():
    """Test Weather Plugin."""
    print("\n" + "="*60)
    print("TESTING: Weather Plugin (Open-Meteo API)")
    print("="*60)

    from src.pipeline.plugins.weather_plugin import WeatherFactorPlugin

    config = {
        'name': 'weather',
        'latitude': 21.0285,
        'longitude': 105.8542,
        'radius_km': 10,
        'timezone': 'Asia/Ho_Chi_Minh',
        'forecast_days': 2,
    }

    plugin = WeatherFactorPlugin(config)

    # Fetch
    print("\n1. FETCHING data from Open-Meteo API...")
    df = plugin.fetch()
    print(f"   Result: {len(df)} records fetched")
    print("   Sample:")
    for _, row in df.head(3).iterrows():
        print(f"   - {row['datetime']} | code={row['weather_code']} | temp={row['temp_c']}C | precip={row['precip_mm']}mm")

    # Transform
    print("\n2. TRANSFORMING: weather_code -> impact values...")
    df = plugin.transform(df)
    print("   Result:")
    for _, row in df.head(5).iterrows():
        print(f"   - {row['datetime']} | code={row['weather_code']} | impact={row['value']} | {row['severity']}")

    # Map spatial
    print("\n3. MAPPING SPATIAL: location -> H3 hex_id...")
    df = plugin.map_spatial(df)
    print(f"   Result: {len(df)} records")
    print(f"   Unique hexes: {df['hex_id'].nunique()}")
    print(f"   Sample hex_id: {df['hex_id'].iloc[0]}")

    print("\n[OK] Weather Plugin: WORKING")
    return df


def test_flood_plugin():
    """Test Flood Plugin."""
    print("\n" + "="*60)
    print("TESTING: Flood Plugin (VNExpress RSS)")
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
    print("\n1. FETCHING data from VNExpress RSS...")
    df = plugin.fetch()
    print(f"   Result: {len(df)} flood-related news")

    if df.empty:
        print("   [WARN] No flood news found (may be dry season)")
    else:
        print("   Sample titles (showing first 3):")
        for i, (_, row) in enumerate(df.head(3).iterrows()):
            title = row['title'][:70] + "..." if len(row['title']) > 70 else row['title']
            print(f"   [{i+1}] {title}")

        # Transform
        print("\n2. TRANSFORMING: extract severity from keywords...")
        df = plugin.transform(df)
        print("   Result:")
        for _, row in df.head(5).iterrows():
            title = row['title'][:50] + "..." if len(row['title']) > 50 else row['title']
            print(f"   - [{row['severity']}] {title}")

        # Map spatial
        print("\n3. MAPPING SPATIAL: location -> H3 hex_id...")
        df = plugin.map_spatial(df)
        print(f"   Result: {len(df)} records")

        print("\n[OK] Flood Plugin: WORKING")
    return df


def test_event_plugin():
    """Test Event Plugin."""
    print("\n" + "="*60)
    print("TESTING: Event Plugin (Manual CSV)")
    print("="*60)

    from src.pipeline.plugins.event_plugin import EventFactorPlugin

    config = {
        'name': 'event',
        'csv_path': 'data/events.csv',
    }

    plugin = EventFactorPlugin(config)

    # Fetch
    print("\n1. FETCHING data from CSV...")
    df = plugin.fetch()
    print(f"   Result: {len(df)} events")
    print("   Sample:")
    for _, row in df.head(3).iterrows():
        print(f"   - {row['event_name']} | {row['venue']} | {row['event_type']}")

    if df.empty:
        print("   [WARN] No events found in CSV")
    else:
        # Transform
        print("\n2. TRANSFORMING: event_type -> impact values...")
        df = plugin.transform(df)
        print("   Result:")
        for _, row in df.head(5).iterrows():
            print(f"   - {row['event_name']} | type={row['event_type']} | impact={row['value']} | {row['severity']}")

        # Map spatial
        print("\n3. MAPPING SPATIAL: venue -> H3 hex_id...")
        df = plugin.map_spatial(df)
        print(f"   Result: {len(df)} records (time-expanded)")

        print("\n[OK] Event Plugin: WORKING")
    return df


def test_holiday_plugin():
    """Test Holiday Plugin."""
    print("\n" + "="*60)
    print("TESTING: Holiday Plugin (Static Calendar)")
    print("="*60)

    from src.pipeline.plugins.holiday_plugin import HolidayFactorPlugin

    config = {
        'name': 'holiday',
        'holiday_file': 'data/holidays.csv',
    }

    plugin = HolidayFactorPlugin(config)

    # Fetch
    print("\n1. FETCHING data from holidays.csv...")
    df = plugin.fetch()
    print(f"   Result: {len(df)} holidays")
    print("   Sample:")
    for _, row in df.head(5).iterrows():
        print(f"   - {row['date'].strftime('%Y-%m-%d')} | {row['holiday_name']}")

    # Transform
    print("\n2. TRANSFORMING: holidays -> impact values...")
    df = plugin.transform(df)
    print("   Result:")
    for _, row in df.head(5).iterrows():
        print(f"   - {row['date'].strftime('%Y-%m-%d')} | {row['holiday_name']} | phase={row['tet_phase']} | impact={row['value']} | {row['severity']}")

    # Map spatial
    print("\n3. MAPPING SPATIAL: city-wide coverage...")
    df = plugin.map_spatial(df)
    print(f"   Result: {len(df)} records (city-wide for each holiday)")
    print(f"   Unique hexes: {df['hex_id'].nunique()}")

    print("\n[OK] Holiday Plugin: WORKING")
    return df


def test_registry():
    """Test Plugin Registry."""
    print("\n" + "="*60)
    print("TESTING: Plugin Registry")
    print("="*60)

    from src.pipeline.registry import PluginRegistry

    plugins = PluginRegistry.list_plugins()
    print(f"\nRegistered plugins: {plugins}")

    print("\n[OK] Registry: WORKING")


def main():
    print("\n" + "="*60)
    print("  DATA PIPELINE PLUGIN TESTS")
    print("="*60)

    # Test each plugin
    try:
        test_registry()
    except Exception as e:
        print(f"\n[ERROR] Registry Error: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_weather_plugin()
    except Exception as e:
        print(f"\n[ERROR] Weather Plugin Error: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_flood_plugin()
    except Exception as e:
        print(f"\n[ERROR] Flood Plugin Error: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_event_plugin()
    except Exception as e:
        print(f"\n[ERROR] Event Plugin Error: {e}")
        import traceback
        traceback.print_exc()

    try:
        test_holiday_plugin()
    except Exception as e:
        print(f"\n[ERROR] Holiday Plugin Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*60)
    print("  ALL TESTS COMPLETED")
    print("="*60)


if __name__ == '__main__':
    main()
