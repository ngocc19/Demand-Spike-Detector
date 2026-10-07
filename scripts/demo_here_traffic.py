"""
Demo: HERE Traffic Plugin with Traffic Flow API
==============================================

Demo này test plugin HERE Traffic với Traffic Flow API thực sự.

Usage:
    python scripts/demo_here_traffic.py

Requirements:
    - HERE_API_KEY in .env
    - Internet connection to HERE API
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()


def check_api_key():
    """Check if HERE API key is available."""
    api_key = os.environ.get('HERE_API_KEY', '')

    if not api_key:
        print("❌ HERE_API_KEY not found in .env")
        print("   Get key at: https://developer.here.com/")
        return False

    print(f"✅ HERE_API_KEY found: {api_key[:10]}...")
    return True


def demo_plugin_initialization():
    """Demo plugin initialization."""
    print("\n" + "=" * 70)
    print("DEMO 1: PLUGIN INITIALIZATION")
    print("=" * 70)

    from src.pipeline.plugins.here_traffic_plugin import HERETrafficPlugin

    plugin = HERETrafficPlugin({
        'api_key': os.environ.get('HERE_API_KEY'),
        'data_lake_dir': 'data/traffic',
        'center_lat': 21.0285,
        'center_lon': 105.8542,
        'radius_m': 20000,  # 20km radius
    })

    print(f"✅ Plugin created: {plugin.factor_name}")
    print(f"   Factor type: {plugin.factor_type.value}")
    print(f"   Schedule: {plugin.schedule}")
    print(f"   Anchor points: {len(plugin.anchor_points)}")
    print(f"   Center: ({plugin.center_lat}, {plugin.center_lon})")
    print(f"   Radius: {plugin.radius_m}m")

    return plugin


def demo_fetch_traffic_flow():
    """Demo fetching real traffic flow data."""
    print("\n" + "=" * 70)
    print("DEMO 2: FETCH REAL-TIME TRAFFIC FLOW DATA")
    print("=" * 70)

    from src.pipeline.plugins.here_traffic_plugin import HERETrafficPlugin

    plugin = HERETrafficPlugin({
        'api_key': os.environ.get('HERE_API_KEY'),
        'data_lake_dir': 'data/traffic',
        'center_lat': 21.0285,
        'center_lon': 105.8542,
        'radius_m': 25000,
        'cache_ttl_minutes': 0,  # Disable cache for demo
    })

    print("\nFetching traffic flow data from HERE Traffic Flow API...")
    print("(This may take a few seconds)")

    try:
        # Fetch anchor-level data
        anchor_df = plugin.fetch()
        print(f"\n✅ Fetched data for {len(anchor_df)} anchor points")

        if not anchor_df.empty:
            print(f"\n📊 Traffic Summary:")
            summary = plugin.get_traffic_summary(anchor_df)
            for key, value in summary.items():
                print(f"   {key}: {value}")

            print(f"\n📋 Sample Data (first 5 anchors):")
            sample_cols = ['anchor_id', 'anchor_name', 'current_speed',
                          'jam_factor', 'speed_drop_ratio', 'severity']
            print(anchor_df[sample_cols].head().to_string(index=False))
        else:
            print("⚠️  No traffic data returned (possible API issues)")

    except Exception as e:
        print(f"❌ Error fetching traffic data: {e}")
        import traceback
        traceback.print_exc()


def demo_transform_data():
    """Demo data transformation."""
    print("\n" + "=" * 70)
    print("DEMO 3: TRANSFORM TRAFFIC DATA")
    print("=" * 70)

    from src.pipeline.plugins.here_traffic_plugin import HERETrafficPlugin
    import pandas as pd

    plugin = HERETrafficPlugin({
        'api_key': os.environ.get('HERE_API_KEY'),
        'data_lake_dir': 'data/traffic',
    })

    # Create sample data
    sample_data = pd.DataFrame({
        'datetime': [datetime.now()] * 5,
        'anchor_id': [1, 2, 3, 4, 5],
        'anchor_name': ['Point A', 'Point B', 'Point C', 'Point D', 'Point E'],
        'lat': [21.0278, 21.0065, 21.0285, 21.0341, 21.0234],
        'lon': [105.8022, 105.8196, 105.8232, 105.7877, 105.8123],
        'current_speed': [30.0, 50.0, 10.0, 60.0, 45.0],
        'free_flow_speed': [60.0, 60.0, 60.0, 60.0, 60.0],
        'jam_factor': [5.0, 2.0, 8.0, 0.0, 2.5],
        'speed_drop_ratio': [0.5, 0.17, 0.83, 0.0, 0.25],
        'confidence': [0.9, 0.8, 0.95, 0.7, 0.85],
        'is_control': [False, False, False, False, False],
        'road_name': ['De La Thanh', 'Thai Ha', 'Kim Ma', 'Nguyen Chi Thanh', 'Lang Ha'],
        'road_type': ['major', 'major', 'major', 'major', 'secondary'],
        'has_incident': [False, True, False, False, False],
        'incident_type': ['', 'ACCIDENT', '', '', ''],
    })

    print("Sample input data:")
    print(sample_data[['anchor_name', 'current_speed', 'jam_factor', 'speed_drop_ratio']].to_string(index=False))

    # Transform
    transformed = plugin.transform(sample_data)

    print("\n✅ Transformed data:")
    print(transformed[['anchor_name', 'current_speed', 'jam_factor',
                       'severity', 'congestion_level', 'value']].to_string(index=False))


def demo_spatial_mapping():
    """Demo spatial mapping to H3 hexes."""
    print("\n" + "=" * 70)
    print("DEMO 4: SPATIAL MAPPING (H3 HEXAGONS)")
    print("=" * 70)

    from src.pipeline.plugins.here_traffic_plugin import HERETrafficPlugin
    import pandas as pd

    plugin = HERETrafficPlugin({
        'api_key': os.environ.get('HERE_API_KEY'),
        'data_lake_dir': 'data/traffic',
    })

    # Create sample anchor data
    sample_df = pd.DataFrame({
        'datetime': [datetime.now()] * 35,
        'anchor_id': list(range(1, 36)),
        'anchor_name': [f"Point {i}" for i in range(1, 36)],
        'lat': [21.0278, 21.0065, 21.0285, 21.0341, 21.0234,
                21.0342, 21.0186, 21.0138, 21.0085, 21.0052,
                20.9723, 20.9512, 21.0324, 21.0067, 21.0423,
                21.0178, 21.0567, 21.0654, 21.0432, 21.0523,
                21.0198, 21.0765, 21.0123, 20.9678, 21.0389,
                20.9689, 21.0145, 21.0034, 21.0234, 21.0489,
                21.0123, 21.0789, 21.0923, 20.9656, 20.9345],
        'lon': [105.8022, 105.8196, 105.8232, 105.7877, 105.8123,
                105.8356, 105.7502, 105.7824, 105.7856, 105.8467,
                105.8745, 105.8923, 105.8645, 105.7889, 105.7545,
                105.7895, 105.7856, 105.7623, 105.7956, 105.8023,
                105.7634, 105.8324, 105.7945, 105.7523, 105.7445,
                105.7324, 105.8556, 105.8723, 105.8845, 105.8645,
                105.6845, 105.8123, 105.8234, 105.8567, 105.7456],
        'current_speed': [30.0] * 35,
        'free_flow_speed': [60.0] * 35,
        'jam_factor': [3.0] * 35,
        'speed_drop_ratio': [0.5] * 35,
        'confidence': [0.9] * 35,
        'is_control': [False] * 30 + [True] * 5,  # Last 5 are highways
    })

    # Map to H3
    hex_df = plugin.map_spatial(sample_df)

    print(f"✅ Mapped {len(sample_df)} anchor points to {len(hex_df)} H3 hexagons")
    print(f"\nSample H3 hex data:")
    print(hex_df[['hex_id', 'lat', 'lon', 'speed_drop_ratio', 'severity']].head(10).to_string(index=False))


def demo_save_to_data_lake():
    """Demo saving to data lake."""
    print("\n" + "=" * 70)
    print("DEMO 5: SAVE TO DATA LAKE")
    print("=" * 70)

    from src.pipeline.plugins.here_traffic_plugin import HERETrafficPlugin
    import pandas as pd

    plugin = HERETrafficPlugin({
        'api_key': os.environ.get('HERE_API_KEY'),
        'data_lake_dir': 'data/traffic/demo',
    })

    # Create sample data
    sample_df = pd.DataFrame({
        'datetime': [datetime.now()] * 10,
        'anchor_id': list(range(1, 11)),
        'anchor_name': [f"Point {i}" for i in range(1, 11)],
        'lat': [21.0278 + i * 0.001 for i in range(10)],
        'lon': [105.8022 + i * 0.001 for i in range(10)],
        'current_speed': [50.0 - i * 3 for i in range(10)],
        'free_flow_speed': [60.0] * 10,
        'jam_factor': [i * 0.5 for i in range(10)],
        'speed_drop_ratio': [i * 0.1 for i in range(10)],
        'confidence': [0.9] * 10,
        'is_control': [False] * 10,
        'severity': ['LOW', 'LOW', 'MEDIUM', 'MEDIUM', 'MEDIUM',
                     'HIGH', 'HIGH', 'HIGH', 'HIGH', 'SEVERE'],
        'congestion_level': ['FREE_FLOW', 'FREE_FLOW', 'LIGHT', 'LIGHT', 'LIGHT',
                            'MODERATE', 'MODERATE', 'MODERATE', 'MODERATE', 'HEAVY'],
    })

    # Save
    output_path = plugin.save_to_data_lake(sample_df, 'anchor')

    if output_path:
        print(f"✅ Saved to: {output_path}")
        print(f"   File size: {output_path.stat().st_size} bytes")

        # Verify
        loaded_df = pd.read_parquet(output_path)
        print(f"   Records: {len(loaded_df)}")


def demo_full_pipeline():
    """Demo running full pipeline."""
    print("\n" + "=" * 70)
    print("DEMO 6: FULL PIPELINE (fetch -> transform -> map -> save)")
    print("=" * 70)

    from src.pipeline.plugins.here_traffic_plugin import HERETrafficPlugin

    plugin = HERETrafficPlugin({
        'api_key': os.environ.get('HERE_API_KEY'),
        'data_lake_dir': 'data/traffic/demo',
        'center_lat': 21.0285,
        'center_lon': 105.8542,
        'radius_m': 20000,
        'cache_ttl_minutes': 0,
    })

    print("\n⏳ Running full pipeline...")

    try:
        # Step 1: Fetch
        print("   Step 1: Fetching traffic data...")
        anchor_df = plugin.fetch()

        if not anchor_df.empty:
            print(f"   ✅ Fetched: {len(anchor_df)} records")

            # Step 2: Transform
            print("   Step 2: Transforming data...")
            transformed_df = plugin.transform(anchor_df)
            print(f"   ✅ Transformed: {len(transformed_df)} records")

            # Step 3: Map spatial
            print("   Step 3: Mapping to H3 hexes...")
            hex_df = plugin.map_spatial(transformed_df)
            print(f"   ✅ Mapped: {len(hex_df)} H3 cells")

            # Step 4: Save
            print("   Step 4: Saving to data lake...")
            anchor_path = plugin.save_to_data_lake(transformed_df, 'anchor')
            hex_path = plugin.save_to_data_lake(hex_df, 'hex')
            print(f"   ✅ Saved: {anchor_path}")
            print(f"   ✅ Saved: {hex_path}")

            # Summary
            print("\n📊 Traffic Summary:")
            summary = plugin.get_traffic_summary(transformed_df)
            for key, value in summary.items():
                print(f"   {key}: {value}")

            print("\n🔴 Severity Distribution:")
            severity_counts = transformed_df['severity'].value_counts()
            for severity, count in severity_counts.items():
                print(f"   {severity}: {count} anchors")

        else:
            print("⚠️  No data fetched (check API key and network)")

    except Exception as e:
        print(f"❌ Pipeline error: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main demo entry point."""
    print("\n" + "=" * 70)
    print("HERE TRAFFIC PLUGIN - TRAFFIC FLOW API DEMO")
    print("=" * 70)
    print(f"Start time: {datetime.now()}")

    # Check API key
    if not check_api_key():
        print("\n⚠️  Cannot run full demo without HERE_API_KEY")
        print("   Running limited demos only...")

    # Demo 1: Plugin initialization
    try:
        demo_plugin_initialization()
    except Exception as e:
        print(f"Demo 1 failed: {e}")

    # Demo 2: Transform data
    try:
        demo_transform_data()
    except Exception as e:
        print(f"Demo 2 failed: {e}")

    # Demo 3: Spatial mapping
    try:
        demo_spatial_mapping()
    except Exception as e:
        print(f"Demo 3 failed: {e}")

    # Demo 4: Save to data lake
    try:
        demo_save_to_data_lake()
    except Exception as e:
        print(f"Demo 4 failed: {e}")

    # Demo 5: Full pipeline (only if API key available)
    if check_api_key():
        try:
            demo_full_pipeline()
        except Exception as e:
            print(f"Demo 5 failed: {e}")

    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)
    print(f"End time: {datetime.now()}")


if __name__ == '__main__':
    main()
