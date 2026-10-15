"""
Feature Engineer Module
=====================

Hợp nhất Weather Ensemble, Events và Traffic Target thành Training Data.

Logic bắt buộc:
1. Weather (15-min) → Tạo Lag Features → 30-min alignment
2. Events: AGGREGATE trước (theo h3_index + datetime) → Safe Left Join
3. Traffic Target: Left Join với bảng đã merge ở trên
4. KHÔNG được để Cartesian explosion (row explosion)

Usage:
    >>> engineer = FeatureEngineer()
    >>> df = engineer.build_training_data(
    ...     weather_df=weather_df,
    ...     events_df=events_df,
    ...     traffic_df=traffic_df
    ... )
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


# =============================================================================
# EVENT TYPE WEIGHTS
# =============================================================================

# Placeholder: Map event type → impact weight
# Thực tế nên điều chỉnh dựa trên domain knowledge
EVENT_TYPE_WEIGHTS: Dict[str, float] = {
    'concert': 1.0,
    'festival': 0.9,
    'sport': 0.8,
    'conference': 0.7,
    'exhibition': 0.6,
    'cultural': 0.7,
    'religious': 0.5,
    'political': 0.6,
    'academic': 0.4,
    'entertainment': 0.6,
    'default': 0.5,
}


# =============================================================================
# FEATURE ENGINEER CLASS
# =============================================================================

class FeatureEngineer:
    """
    Hợp nhất Weather + Events + Traffic → Training Data.

    Pipeline:
        1. Weather: 15-min → 30-min alignment + Lag features
        2. Events: Aggregate (h3_index, datetime) → Safe Left Join
        3. Traffic: Left Join với bảng đã merge
        4. Output: Training-ready DataFrame

    Features tạo ra:
    - Lag features: precip_diff_15m, temp_diff_15m, etc.
    - Rolling features: precip_rolling_mean_30m, etc.
    - Event features: has_event, event_impact_weight, estimate_attendence
    - Traffic target: target_traffic_ratio
    """

    def __init__(self, seed: int = 42):
        """
        Initialize FeatureEngineer.

        Args:
            seed: Random seed for reproducibility
        """
        self.seed = seed
        np.random.seed(seed)

        # Tracking
        self._original_weather_len: int = 0
        self._final_len: int = 0
        self._events_aggregated_len: int = 0

    def build_training_data(
        self,
        weather_df: pd.DataFrame,
        events_df: pd.DataFrame,
        traffic_df: Optional[pd.DataFrame] = None,
        lag_features: bool = True,
    ) -> pd.DataFrame:
        """
        Build complete training dataset.

        Args:
            weather_df: Weather data (30-min intervals)
            events_df: Events data
            traffic_df: Traffic target data (optional)
            lag_features: Whether to create lag features

        Returns:
            Merged DataFrame ready for training
        """
        print("[FeatureEngineer] Starting pipeline...")

        # Step 1: Weather + Lag features
        print("[FeatureEngineer] Step 1: Processing weather data...")
        df = self._process_weather(weather_df, create_lags=lag_features)
        self._original_weather_len = len(df)
        print(f"[FeatureEngineer]   -> Weather records: {len(df)}")

        # Step 2: Safe Event merge
        print("[FeatureEngineer] Step 2: Processing events (safe aggregate + merge)...")
        df = self._merge_events_safe(df, events_df)
        print(f"[FeatureEngineer]   -> Events aggregated: {self._events_aggregated_len}")
        print(f"[FeatureEngineer]   -> After event merge: {len(df)}")

        # Step 3: Traffic target merge
        if traffic_df is not None:
            print("[FeatureEngineer] Step 3: Merging traffic target...")
            df = self._merge_traffic(df, traffic_df)
            print(f"[FeatureEngineer]   -> After traffic merge: {len(df)}")

        # Validation
        self._final_len = len(df)
        assert len(df) == self._original_weather_len, (
            f"Row explosion detected! Original: {self._original_weather_len}, "
            f"Final: {self._final_len}"
        )
        print(f"[FeatureEngineer] [OK] Row count preserved: {self._final_len}")

        # Final cleanup
        df = self._finalize(df)

        return df

    # =========================================================================
    # STEP 1: Weather Processing + Lag Features
    # =========================================================================

    def _process_weather(
        self,
        weather_df: pd.DataFrame,
        create_lags: bool = True
    ) -> pd.DataFrame:
        """
        Process weather data and create lag features.

        Weather data is at 30-min intervals, but source updates every 15 min.
        We create lag features to capture the 15-min change.

        Args:
            weather_df: Weather data
            create_lags: Whether to create lag features

        Returns:
            Processed weather DataFrame
        """
        df = weather_df.copy()

        # Ensure datetime column
        if 'datetime' not in df.columns:
            raise ValueError("weather_df must have 'datetime' column")

        df['datetime'] = pd.to_datetime(df['datetime'])

        # Sort by h3_index and datetime for proper lag calculation
        if 'h3_index' in df.columns:
            df = df.sort_values(['h3_index', 'datetime']).reset_index(drop=True)

        if create_lags:
            # Create lag features for key weather columns
            df = self._create_lag_features(df)

        return df

    def _create_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create lag features for weather data.

        Since weather updates every 15 min but we have 30-min intervals,
        lag features capture the change between consecutive periods.

        Features created:
        - precip_diff_15m: precip(t) - precip(t-15)  [approximation]
        - temp_diff_15m: temp(t) - temp(t-15)
        - humidity_diff_15m: humidity(t) - humidity(t-15)
        - wind_diff_15m: wind_speed(t) - wind_speed(t-15)

        Args:
            df: Weather DataFrame

        Returns:
            DataFrame with lag features added
        """
        df = df.copy()

        # Columns to create lag diffs for
        lag_cols = ['precip', 'temp_c', 'humidity_pct', 'wind_speed',
                    'cloud_cover', 'visibility']

        # Group by h3_index to calculate lag within each cell
        if 'h3_index' in df.columns:
            group_col = 'h3_index'
        else:
            group_col = None

        for col in lag_cols:
            if col not in df.columns:
                continue

            if group_col:
                # Within each H3 cell
                df[f'{col}_lag1'] = df.groupby(group_col)[col].shift(1)
            else:
                df[f'{col}_lag1'] = df[col].shift(1)

            # Difference: current - previous
            df[f'{col}_diff'] = df[col] - df[f'{col}_lag1']

            # Fill NaN with 0 (first record has no lag)
            df[f'{col}_diff'] = df[f'{col}_diff'].fillna(0)

            # Drop intermediate lag column
            df = df.drop(columns=[f'{col}_lag1'])

        # Rolling features (if enough data points)
        if group_col:
            for col in ['precip', 'temp_c', 'humidity_pct']:
                if col not in df.columns:
                    continue

                # Rolling mean over last 2 periods (1 hour)
                df[f'{col}_rolling_mean'] = (
                    df.groupby(group_col)[col]
                    .transform(lambda x: x.rolling(window=2, min_periods=1).mean())
                )

                # Rolling max over last 2 periods
                df[f'{col}_rolling_max'] = (
                    df.groupby(group_col)[col]
                    .transform(lambda x: x.rolling(window=2, min_periods=1).max())
                )

        return df

    # =========================================================================
    # STEP 2: Safe Event Merge (CRUCIAL)
    # =========================================================================

    def _merge_events_safe(
        self,
        weather_df: pd.DataFrame,
        events_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Safely merge events into weather data.

        CRITICAL: Events must be aggregated BEFORE join to avoid row explosion.
        One (h3_index, datetime) might have multiple events simultaneously.

        Pipeline:
        1. Create datetime from start_date + time_slot
        2. Feature engineering on events
        3. Aggregate by (h3_index, datetime)
        4. Safe left join

        Args:
            weather_df: Weather DataFrame
            events_df: Events DataFrame

        Returns:
            Merged DataFrame
        """
        # Step 2a: Preprocess events
        events_processed = self._preprocess_events(events_df)
        self._events_aggregated_len = len(events_processed)

        # Step 2b: Safe left join
        df = weather_df.merge(
            events_processed,
            on=['h3_index', 'datetime'],
            how='left'
        )

        # Step 2c: Fill NaN for non-event rows
        df['has_event'] = df['has_event'].fillna(0).astype(int)
        df['event_impact_weight'] = df['event_impact_weight'].fillna(0.0)
        df['estimate_attendence'] = df['estimate_attendence'].fillna(0)
        df['event_name'] = df['event_name'].fillna('None')
        df['event_type'] = df['event_type'].fillna('None')

        return df

    def _preprocess_events(self, events_df: pd.DataFrame) -> pd.DataFrame:
        """
        Preprocess and aggregate events.

        Steps:
        1. Create datetime from start_date + time_slot
        2. Fill missing attendance
        3. Create event_impact_weight
        4. Aggregate by (h3_index, datetime)

        Args:
            events_df: Raw events DataFrame

        Returns:
            Aggregated events DataFrame (one row per h3_index + datetime)
        """
        df = events_df.copy()

        # =========================================================================
        # Step 1: Time & Spatial Alignment
        # =========================================================================

        # Create datetime from start_date + time_slot
        # start_date format: '01/05/26' (DD/MM/YY)
        # time_slot format: '00:00', '00:30' (HH:MM)
        if 'start_date' in df.columns and 'time_slot' in df.columns:
            # Parse date first (DD/MM/YY format)
            df['_parsed_date'] = pd.to_datetime(
                df['start_date'].astype(str),
                format='%d/%m/%y',
                errors='coerce'
            )

            # Combine with time_slot
            df['datetime'] = pd.to_datetime(
                df['_parsed_date'].dt.strftime('%Y-%m-%d') + ' ' + df['time_slot'].astype(str),
                format='%Y-%m-%d %H:%M',
                errors='coerce'
            )

            # Drop temp column
            df = df.drop(columns=['_parsed_date'])

        elif 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
        else:
            raise ValueError("Events must have either (start_date + time_slot) or datetime")

        # Ensure h3_index exists
        if 'h3_index' not in df.columns:
            raise ValueError("Events must have 'h3_index' column")

        # =========================================================================
        # Step 1b: Filter events by date range (29/06/2026 - 28/09/2026)
        # =========================================================================

        original_len = len(df)
        df = df.dropna(subset=['datetime'])

        # Filter to events within target date range
        min_date = pd.Timestamp('2026-06-29')
        max_date = pd.Timestamp('2026-09-28 23:59:59')

        df = df[(df['datetime'] >= min_date) & (df['datetime'] <= max_date)]

        if len(df) < original_len:
            print(f"[FeatureEngineer]   -> Filtered out {original_len - len(df)} events outside date range")

        if df.empty:
            print("[FeatureEngineer]   -> No events in date range, returning empty DataFrame")
            return pd.DataFrame(columns=['h3_index', 'datetime', 'estimate_attendence',
                                         'event_impact_weight', 'has_event', 'event_name', 'event_type'])

        # =========================================================================
        # Step 2: Feature Engineering on Events
        # =========================================================================

        # Create has_event = 1
        df['has_event'] = 1

        # Fill missing attendance
        # Strategy: Fill with median of same event type
        if 'estimate_attendence' in df.columns and 'type' in df.columns:
            # Fill NaN with median attendance per type
            df['estimate_attendence'] = df.groupby('type')['estimate_attendence'].transform(
                lambda x: x.fillna(x.median())
            )
            # If type still has all NaN, fill with small constant
            df['estimate_attendence'] = df['estimate_attendence'].fillna(100)
        else:
            df['estimate_attendence'] = 0

        # Create event_impact_weight
        if 'type' in df.columns:
            df['type_weight'] = df['type'].map(EVENT_TYPE_WEIGHTS).fillna(EVENT_TYPE_WEIGHTS['default'])
        else:
            df['type_weight'] = EVENT_TYPE_WEIGHTS['default']

        # Log transform attendance and multiply by type weight
        # log(attendance + 1) to handle zeros
        df['event_impact_weight'] = (
            np.log1p(df['estimate_attendence']) * df['type_weight']
        )

        # =========================================================================
        # Step 3: Aggregation (CRUCIAL - prevents row explosion)
        # =========================================================================

        # Aggregate by (h3_index, datetime)
        aggregated = df.groupby(['h3_index', 'datetime']).agg(
            estimate_attendence=('estimate_attendence', 'sum'),
            event_impact_weight=('event_impact_weight', 'sum'),
            has_event=('has_event', 'max'),
            event_name=('event_name', lambda x: ' | '.join(x.dropna().unique())),
            event_type=('type', lambda x: ' | '.join(x.dropna().unique())),
        ).reset_index()

        return aggregated

    # =========================================================================
    # STEP 3: Traffic Target Merge
    # =========================================================================

    def _merge_traffic(
        self,
        weather_df: pd.DataFrame,
        traffic_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Merge traffic target into weather data.

        Args:
            weather_df: Weather DataFrame (after event merge)
            traffic_df: Traffic target DataFrame

        Returns:
            Merged DataFrame with target column
        """
        # Ensure datetime columns are same type
        df_weather = weather_df.copy()
        df_traffic = traffic_df.copy()

        df_weather['datetime'] = pd.to_datetime(df_weather['datetime'])
        df_traffic['datetime'] = pd.to_datetime(df_traffic['datetime'])

        # Rename target column if needed
        if 'target_traffic_ratio' not in df_traffic.columns:
            if 'target' in df_traffic.columns:
                df_traffic = df_traffic.rename(columns={'target': 'target_traffic_ratio'})
            else:
                # Take first numeric column as target
                numeric_cols = df_traffic.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) > 0:
                    target_col = numeric_cols[0]
                    df_traffic = df_traffic.rename(columns={target_col: 'target_traffic_ratio'})

        # Rename h3_index in traffic if needed
        if 'hex_id' in df_traffic.columns and 'h3_index' not in df_traffic.columns:
            df_traffic = df_traffic.rename(columns={'hex_id': 'h3_index'})

        # Safe left join
        df = df_weather.merge(
            df_traffic[['h3_index', 'datetime', 'target_traffic_ratio']],
            on=['h3_index', 'datetime'],
            how='left'
        )

        return df

    # =========================================================================
    # FINALIZATION
    # =========================================================================

    def _finalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Final cleanup and validation.

        Args:
            df: Merged DataFrame

        Returns:
            Cleaned DataFrame
        """
        # Fill any remaining NaN in target
        if 'target_traffic_ratio' in df.columns:
            df['target_traffic_ratio'] = df['target_traffic_ratio'].fillna(0)

        # Ensure correct dtypes
        int_cols = ['has_event', 'is_weekend', 'is_rush_hour', 'is_holiday',
                    'is_working_day', 'hour', 'day_of_week', 'month']
        for col in int_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0).astype(int)

        return df

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def get_summary(self) -> Dict:
        """Get merge summary statistics."""
        return {
            'original_weather_rows': self._original_weather_len,
            'events_aggregated_rows': self._events_aggregated_len,
            'final_rows': self._final_len,
            'row_explosion_check': self._final_len == self._original_weather_len,
        }


# =============================================================================
# STANDALONE FUNCTIONS
# =============================================================================

def build_training_data(
    weather_df: pd.DataFrame,
    events_df: pd.DataFrame,
    traffic_df: Optional[pd.DataFrame] = None,
    seed: int = 42
) -> pd.DataFrame:
    """
    Convenience function to build training data.

    Args:
        weather_df: Weather DataFrame (30-min intervals)
        events_df: Events DataFrame
        traffic_df: Traffic target DataFrame (optional)
        seed: Random seed

    Returns:
        Training-ready DataFrame
    """
    engineer = FeatureEngineer(seed=seed)
    return engineer.build_training_data(
        weather_df=weather_df,
        events_df=events_df,
        traffic_df=traffic_df
    )


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("FeatureEngineer - Standalone Test")
    print("=" * 60)

    # Load data
    print("\n[1] Loading data...")
    weather_df = pd.read_parquet('data/weather_anchors_30T_merged.parquet')
    events_df = pd.read_excel('data/event.xlsx')

    print(f"    Weather: {len(weather_df)} rows")
    print(f"    Events: {len(events_df)} rows")

    # Build training data
    print("\n[2] Building training data...")
    engineer = FeatureEngineer(seed=42)
    df = engineer.build_training_data(
        weather_df=weather_df,
        events_df=events_df,
        traffic_df=None  # Traffic target not available yet
    )

    # Summary
    print("\n[3] Summary:")
    summary = engineer.get_summary()
    for k, v in summary.items():
        print(f"    {k}: {v}")

    print("\n[4] Final columns:")
    print(f"    {df.columns.tolist()}")

    print("\n[5] Sample data:")
    print(df.head(3).to_string())

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
