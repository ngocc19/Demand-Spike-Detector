"""
Merge expanded events with weather data using spatial join.
========================================================

Logic:
1. Với mỗi event row (đã expand 30 min), tìm anchor gần nhất dựa trên h3_index
2. Join với weather data: same anchor + same date + nearest time slot

Usage:
    python scripts/merge_event_weather.py
"""

import pandas as pd
import numpy as np
from pathlib import Path
import h3
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from h3_mapper import H3Mapper

# Weather anchors
ANCHORS = [
    {"name": "HoanKiem", "lat": 21.0285, "lon": 105.8542},
    {"name": "CauGiay", "lat": 21.0306, "lon": 105.7925},
    {"name": "HoangMai", "lat": 20.9723, "lon": 105.8454},
    {"name": "LongBien", "lat": 21.0470, "lon": 105.8920},
    {"name": "TayHo", "lat": 21.0664, "lon": 105.8176},
    {"name": "NoiBai", "lat": 21.2187, "lon": 105.8042},
]


def get_nearest_anchor_fast(lat: float, lon: float) -> str:
    """Tìm anchor gần nhất với tọa độ."""
    from math import radians, cos, sin, asin, sqrt

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371  # km
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        return 2 * R * asin(sqrt(a))

    min_dist = float('inf')
    nearest = None
    for anchor in ANCHORS:
        dist = haversine(lat, lon, anchor['lat'], anchor['lon'])
        if dist < min_dist:
            min_dist = dist
            nearest = anchor['name']

    return nearest, round(min_dist, 2)


def round_time_to_slot(time_str: str, slot_minutes: int = 30) -> str:
    """Round time down to nearest slot boundary."""
    parts = time_str.split(':')
    hour = int(parts[0])
    minute = int(parts[1])

    # Round down to nearest slot
    slot = (minute // slot_minutes) * slot_minutes
    return f'{hour:02d}:{slot:02d}'


def merge_events_weather(
    events_path: str = 'data/events_fixed.xlsx',
    weather_path: str = 'data/weather_anchors_30T_merged.parquet',
    output_path: str = 'data/events_with_weather.xlsx'
) -> pd.DataFrame:
    """
    Merge expanded events with weather data.

    Args:
        events_path: Path to expanded events file
        weather_path: Path to weather parquet file
        output_path: Output path for merged data

    Returns:
        Merged DataFrame
    """
    print("Loading data...")

    # Load events
    events = pd.read_excel(events_path)
    print(f"  Events: {len(events)} rows")

    # Load weather
    weather = pd.read_parquet(weather_path)
    print(f"  Weather: {len(weather)} records")

    # Step 1: Assign nearest anchor to each event
    print("\nAssigning nearest anchor to each event...")

    def assign_anchor(row):
        if pd.isna(row.get('latitude')) or pd.isna(row.get('longitude')):
            return None, None
        lat = float(row['latitude'])
        lon = float(row['longitude'])
        # Hanoi bounds filter - stricter bounds
        if not (20.85 <= lat <= 21.15 and 105.70 <= lon <= 105.95):
            return None, None
        return get_nearest_anchor_fast(lat, lon)

    anchors_assigned = events.apply(assign_anchor, axis=1)
    events['nearest_anchor'] = anchors_assigned.apply(lambda x: x[0] if x else None)
    events['anchor_distance_km'] = anchors_assigned.apply(lambda x: x[1] if x else None)

    # Filter out events without anchor (outside Hanoi)
    events_with_anchor = events[events['nearest_anchor'].notna()].copy()
    filtered_count = len(events) - len(events_with_anchor)
    print(f"  Filtered out (outside Hanoi): {filtered_count} rows")
    events = events_with_anchor

    # Stats
    anchor_counts = events['nearest_anchor'].value_counts()
    print("  Anchor distribution:")
    for anchor, count in anchor_counts.items():
        print(f"    {anchor}: {count} rows")

    # Step 2: Prepare datetime for events
    print("\nPreparing datetime for merge...")

    # Parse slot_time to get hour and minute
    events['slot_hour'] = events['slot_time'].apply(lambda x: int(x.split(':')[0]))
    events['slot_minute'] = events['slot_time'].apply(lambda x: int(x.split(':')[1]))

    # Parse start_date to datetime
    events['slot_datetime'] = pd.to_datetime(events['start_date'], format='%d/%m/%y')
    events['slot_datetime'] = events.apply(
        lambda row: row['slot_datetime'].replace(
            hour=row['slot_hour'],
            minute=row['slot_minute']
        ),
        axis=1
    )

    # Step 3: Prepare weather datetime
    weather['datetime'] = pd.to_datetime(weather['datetime'])
    weather['weather_hour'] = weather['datetime'].dt.hour
    weather['weather_minute'] = weather['datetime'].dt.minute
    weather['weather_date'] = weather['datetime'].dt.date

    # Step 4: Create slot key for merge (anchor + date + time rounded to 30min)
    events['merge_key'] = events.apply(
        lambda row: (
            row['nearest_anchor'],
            row['slot_datetime'].date() if pd.notna(row['slot_datetime']) else None,
            round_time_to_slot(row['slot_time'])
        ),
        axis=1
    )

    weather['merge_key'] = weather.apply(
        lambda row: (
            row['anchor_name'],
            row['weather_date'],
            f"{row['weather_hour']:02d}:{row['weather_minute']:02d}"
        ),
        axis=1
    )

    # Step 5: Select weather columns to merge
    weather_cols = [
        'datetime', 'temp_c', 'feels_like', 'humidity_pct', 'precip',
        'precip_prob', 'wind_speed', 'cloud_cover', 'visibility',
        'pressure', 'weather_conditions', 'weather_icon',
        'weather_impact', 'precip_impact', 'value', 'severity',
        'is_weekend', 'is_rush_hour', 'part_of_day', 'month',
        'is_monsoon', 'blended_temp_c', 'blended_precip',
        'blended_humidity_pct', 'blended_weather_impact', 'blended_value',
        'is_holiday', 'holiday_name', 'holiday_impact',
        'tet_phase', 'is_working_day', 'holiday_type', 'category'
    ]

    # Keep only existing columns
    weather_cols = [c for c in weather_cols if c in weather.columns]

    weather_merge = weather[['merge_key'] + weather_cols].drop_duplicates(subset=['merge_key'])

    # Step 6: Merge
    print("\nMerging events with weather...")
    merged = events.merge(
        weather_merge,
        on='merge_key',
        how='left'
    )

    # Step 7: Clean up temporary columns
    temp_cols = ['merge_key', 'slot_hour', 'slot_minute', 'weather_date']
    merged = merged.drop(columns=[c for c in temp_cols if c in merged.columns], errors='ignore')

    # Rename slot_datetime to slot_datetime
    if 'slot_datetime' in merged.columns:
        merged['slot_datetime'] = merged['slot_datetime'].astype(str)

    print(f"\nMerged: {len(merged)} rows")

    # Stats
    matched = merged['temp_c'].notna().sum()
    print(f"Weather matched: {matched} / {len(merged)} ({matched/len(merged)*100:.1f}%)")

    # Save
    print(f"\nSaving to {output_path}...")
    merged.to_excel(output_path, index=False)
    print("Done!")

    return merged


if __name__ == '__main__':
    merge_events_weather()
