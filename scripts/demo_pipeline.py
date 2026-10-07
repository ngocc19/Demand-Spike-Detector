"""
Demo: Running Unified Pipeline with Proxy Data
============================================

Demo này chạy pipeline với dữ liệu proxy thật từ các API:
- VCW (Visual Crossing Weather)
- OWM (OpenWeatherMap)

Nếu API keys không được set, sẽ dùng fallback data.

Usage:
    python scripts/demo_pipeline.py
"""

import sys
import os
from datetime import datetime

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


def check_api_keys():
    """Check which API keys are available."""
    keys = {
        'VISUALCROSSING_API_KEY': bool(os.getenv('VISUALCROSSING_API_KEY')),
        'OPENWEATHERMAP_API_KEY': bool(os.getenv('OPENWEATHERMAP_API_KEY')),
    }

    print("API Key Status:")
    for key, available in keys.items():
        status = "[OK] Available" if available else "[X] Not set"
        print(f"  {key}: {status}")

    return any(keys.values())


def demo_proxy_data_fetch():
    """Demo fetching real proxy data."""
    print("\n" + "="*70)
    print("DEMO 1: FETCHING PROXY DATA FROM APIs")
    print("="*70)

    from src.pipeline.plugins.vcw_plugin import VCWFactorPlugin
    from src.pipeline.plugins.owm_plugin import OWMFactorPlugin
    from scripts.processor import WeatherProcessor

    processor = WeatherProcessor()

    # Try VCW
    print("\n[1] Testing VCW Plugin...")
    try:
        vcw = VCWFactorPlugin({
            'latitude': 21.0285,
            'longitude': 105.8542,
            'radius_km': 30,
        })
        vcw_data = vcw.fetch()
        print(f"    VCW fetched: {len(vcw_data)} records")

        if not vcw_data.empty:
            vcw_transformed = vcw.transform(vcw_data)
            print(f"    Transformed: {len(vcw_transformed)} records")
            print(f"    Columns: {list(vcw_transformed.columns)}")
    except Exception as e:
        print(f"    VCW failed: {e}")
        vcw_transformed = None

    # Try OWM
    print("\n[2] Testing OWM Plugin...")
    try:
        owm = OWMFactorPlugin({
            'latitude': 21.0285,
            'longitude': 105.8542,
            'radius_km': 30,
        })
        owm_data = owm.fetch()
        print(f"    OWM fetched: {len(owm_data)} records")

        if not owm_data.empty:
            owm_transformed = owm.transform(owm_data)
            print(f"    Transformed: {len(owm_transformed)} records")
    except Exception as e:
        print(f"    OWM failed: {e}")
        owm_transformed = None

    # Use available data
    if vcw_transformed is not None and not vcw_transformed.empty:
        print("\n[3] Processing VCW data to 30-min intervals...")
        data = processor.resample_to_30min(vcw_transformed)
        data = processor.add_weather_impact(data)
        data = processor.add_time_features(data)
        print(f"    Processed: {len(data)} records")
        print(f"    Sample row:")
        print(f"    {data.iloc[0].to_dict()}")

        return data
    else:
        print("\n[3] Using fallback data...")
        return None


def demo_pipeline_components():
    """Demo individual pipeline components."""
    print("\n" + "="*70)
    print("DEMO 2: PIPELINE COMPONENTS")
    print("="*70)

    from src.pipeline.demand_spike_pipeline import (
        PipelineConfig,
        WeatherDataFetcher,
        DemandFeaturePipeline,
    )

    config = PipelineConfig()

    # Test fetcher
    print("\n[1] Testing WeatherDataFetcher...")
    fetcher = WeatherDataFetcher(config)
    print(f"    H3 grid size: {len(fetcher.hex_grid)} hexagons")
    print(f"    H3 resolution: {config.h3_resolution}")

    # Test feature pipeline
    print("\n[2] Testing DemandFeaturePipeline...")
    feature_pipeline = DemandFeaturePipeline(config)
    print(f"    Holiday generator: {feature_pipeline.holiday_generator is not None}")

    # Test holiday features
    import pandas as pd
    test_dates = pd.DataFrame({
        'datetime': pd.date_range('2026-09-01', periods=24, freq='h')
    })
    test_with_holidays = feature_pipeline.add_holiday_features(test_dates)
    print(f"    Holiday features added: {list(test_with_holidays.columns)}")

    # Test lag features
    print("\n[3] Testing Lag/Rolling Features...")
    import numpy as np

    # Create test data with time series
    n = 100
    test_data = pd.DataFrame({
        'datetime': pd.date_range('2026-09-01', periods=n, freq='30min'),
        'hex_id': ['88415cb4e5fffff'] * n,
        'precip': np.random.exponential(5, n),
        'weather_impact': np.random.uniform(0, 0.5, n),
    })

    test_lags = feature_pipeline.add_lag_features(test_data)
    lag_cols = [c for c in test_lags.columns if 'lag' in c]
    print(f"    Lag columns: {lag_cols}")

    test_rolling = feature_pipeline.add_rolling_features(test_data)
    rolling_cols = [c for c in test_rolling.columns if 'sum' in c or 'max' in c]
    print(f"    Rolling columns: {rolling_cols}")

    print("\n    Sample with lags:")
    print(test_lags[['datetime', 'precip', 'precip_lag_15m', 'precip_lag_30m']].head(5))


def demo_full_pipeline():
    """Demo running full pipeline."""
    print("\n" + "="*70)
    print("DEMO 3: FULL PIPELINE RUN")
    print("="*70)

    from src.pipeline.run_pipeline import PipelineRunner

    print("\nInitializing pipeline runner...")
    runner = PipelineRunner()

    print("Running pipeline...")
    print("(This may take a few minutes for data fetching and processing)")

    try:
        results = runner.run(
            fetch_real_data=True,
            train_model=True,
            detect_spikes=True
        )

        print("\n" + "="*70)
        print("PIPELINE RESULTS")
        print("="*70)

        if 'proxy_data' in results:
            print(f"\nProxy Data:")
            print(f"  Source: {results['proxy_data']['source']}")
            print(f"  Records: {results['proxy_data']['rows']:,}")
            print(f"  Date Range: {results['proxy_data']['date_range']}")

        if 'features' in results:
            print(f"\nFeatures:")
            print(f"  Columns: {results['features']['columns']}")
            print(f"  Shape: {results['features']['shape']}")

        if 'model' in results and 'error' not in results['model']:
            print(f"\nModel Performance:")
            print(f"  Validation R²: {results['model']['valid_r2']:.4f}")
            print(f"  Validation RMSE: {results['model']['valid_rmse']:.2f}")

        if 'alerts' in results:
            print(f"\nAlerts:")
            print(f"  Total Alerts: {results['alerts']['total_alerts']}")
            print(f"  Alerts per Day: {results['alerts']['alerts_per_day']:.2f}")
            print(f"  By Severity: {results['alerts']['by_severity']}")
            print(f"  By Cause: {results['alerts']['by_cause']}")

        print("\nOutput files saved to: data/pipeline_output/")

    except Exception as e:
        print(f"\nPipeline error: {e}")
        import traceback
        traceback.print_exc()


def demo_json_alerts():
    """Demo alert JSON format."""
    print("\n" + "="*70)
    print("DEMO 4: ALERT JSON FORMAT")
    print("="*70)

    from src.demand_spike_alerts import Alert, AlertGenerator
    from datetime import datetime

    # Create sample alerts
    alerts = [
        Alert(
            alert_id="ALT-88415cb4-0001",
            hex_id="88415cb4e5fffff",
            lat=21.0285,
            lon=105.8542,
            timestamp=datetime.now(),
            severity="HIGH",
            demand_actual=85.2,
            demand_expected=52.1,
            deviation_pct=63.5,
            cause_weather=0.35,
            cause_flood=0.0,
            cause_event=0.15,
            cause_traffic=0.08,
            is_flooded=False,
            deficit_ratio=1.45,
        ),
        Alert(
            alert_id="ALT-88415cb5-0002",
            hex_id="88415cb5e5fffff",
            lat=21.0350,
            lon=105.8600,
            timestamp=datetime.now(),
            severity="MEDIUM",
            demand_actual=68.0,
            demand_expected=50.0,
            deviation_pct=36.0,
            cause_weather=0.25,
            cause_flood=0.0,
            cause_event=0.0,
            cause_traffic=0.1,
            is_flooded=False,
            deficit_ratio=1.35,
        ),
    ]

    # Generate JSON
    generator = AlertGenerator()
    json_str = generator.to_json(alerts)

    print("\nJSON Alert Output:")
    print(json_str)

    print("\n" + "-"*70)
    print("Alert Fields Explanation:")
    print("-"*70)
    print("""
    alert_id        : Unique alert identifier (ALT-{hex_id[:8]}-{timestamp})
    hex_id          : H3 hexagon code (spatial location)
    location        : lat/lon coordinates
    timestamp       : Detection time
    severity        : LOW, MEDIUM, HIGH, SEVERE
    demand          : actual vs expected with deviation percentage
    cause           : Breakdown of contributing factors:
                      - weather: rain/temperature impact (0.0-1.0)
                      - flood: flood severity impact (0.0-1.0)
                      - event: nearby event impact (0.0-1.0)
                      - traffic: traffic congestion impact (0.0-1.0)
                      - is_flooded: boolean flood indicator
    primary_cause   : Dominant factor from cause breakdown
    deficit_ratio   : Supply/Demand ratio (>1.3 = shortage)
    source_count    : Number of external sources integrated
    """)


def main():
    """Main demo entry point."""
    print("\n" + "="*70)
    print("DEMAND SPIKE DETECTOR - UNIFIED PIPELINE DEMO")
    print("="*70)
    print(f"Start time: {datetime.now()}")

    # Check API keys
    has_keys = check_api_keys()

    if not has_keys:
        print("\n⚠️  No API keys found. Will use fallback/synthetic data.")
        print("    Set API keys in .env file for real data:")
        print("    - VISUALCROSSING_API_KEY")
        print("    - OPENWEATHERMAP_API_KEY")

    # Demo 1: Proxy Data Fetching
    try:
        demo_proxy_data_fetch()
    except Exception as e:
        print(f"\nDemo 1 failed: {e}")

    # Demo 2: Pipeline Components
    try:
        demo_pipeline_components()
    except Exception as e:
        print(f"\nDemo 2 failed: {e}")

    # Demo 3: Full Pipeline
    try:
        demo_full_pipeline()
    except Exception as e:
        print(f"\nDemo 3 failed: {e}")

    # Demo 4: Alert Format
    try:
        demo_json_alerts()
    except Exception as e:
        print(f"\nDemo 4 failed: {e}")

    print("\n" + "="*70)
    print("DEMO COMPLETE")
    print("="*70)
    print(f"End time: {datetime.now()}")


if __name__ == '__main__':
    main()
