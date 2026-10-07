"""
Merge weather with events - keeping ALL weather days.
=====================================================

Logic:
1. Start from weather data (full date range: 29/06 - 28/09)
2. For each weather row, check if there's an event at same anchor + date + time_slot
3. If yes, join event info; if no, event columns stay null

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


def merge_weather_events(
    weather_path: str = 'data/weather_anchors_30T_merged.parquet',
    events_path: str = 'data/events_fixed.xlsx',
    output_path: str = 'data/events_with_weather_v2.xlsx'
) -> pd.DataFrame:
    """
    Merge weather with events - keeping ALL weather days.

    Weather is the base table (full date range 29/06 - 28/09).
    Events are LEFT JOINed into weather rows where they match.

    Args:
        weather_path: Path to weather parquet file (base table)
        events_path: Path to expanded events file
        output_path: Output path for merged data

    Returns:
        Merged DataFrame with all weather rows + event info where applicable
    """
    print("Loading data...")

    # Load weather (base table - keep all rows)
    weather = pd.read_parquet(weather_path)
    print(f"  Weather (base): {len(weather)} rows")
    print(f"  Date range: {weather['datetime'].min()} to {weather['datetime'].max()}")

    # Load events
    events = pd.read_excel(events_path)
    print(f"  Events: {len(events)} rows")

    # Step 1: Assign nearest anchor to each event
    print("\nAssigning nearest anchor to each event...")

    def assign_anchor(row):
        if pd.isna(row.get('latitude')) or pd.isna(row.get('longitude')):
            return None, None
        lat = float(row['latitude'])
        lon = float(row['longitude'])
        # Hanoi bounds filter
        if not (20.85 <= lat <= 21.15 and 105.70 <= lon <= 105.95):
            return None, None
        return get_nearest_anchor_fast(lat, lon)

    anchors_assigned = events.apply(assign_anchor, axis=1)
    events['nearest_anchor'] = anchors_assigned.apply(lambda x: x[0] if x else None)
    events['anchor_distance_km'] = anchors_assigned.apply(lambda x: x[1] if x else None)

    # Filter events without anchor
    events_with_anchor = events[events['nearest_anchor'].notna()].copy()
    filtered_count = len(events) - len(events_with_anchor)
    print(f"  Filtered (outside Hanoi): {filtered_count} rows")
    events = events_with_anchor

    # Step 2: Prepare datetime for events
    print("\nPreparing datetime for merge...")

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
    events['event_date'] = events['slot_datetime'].dt.date

    # Step 3: Prepare weather datetime
    weather['weather_date'] = weather['datetime'].dt.date

    # Step 4: Create merge keys
    # Weather key: (anchor_name, date, time_slot)
    weather['merge_key'] = weather.apply(
        lambda row: (
            row['anchor_name'],
            row['weather_date'],
            f"{row['datetime'].hour:02d}:{row['datetime'].minute:02d}"
        ),
        axis=1
    )

    # Event key: (nearest_anchor, date, time_slot)
    events['merge_key'] = events.apply(
        lambda row: (
            row['nearest_anchor'],
            row['event_date'],
            f"{row['slot_hour']:02d}:{row['slot_minute']:02d}"
        ),
        axis=1
    )

    # Step 5: Prepare event columns to merge
    event_cols = [
        'merge_key',
        'event_name', 'venue', 'start_time', 'end_time',
        'type', 'estimate_attendence', 'anchor_distance_km'
    ]
    # Keep only existing columns
    event_cols = [c for c in event_cols if c in events.columns]

    # Deduplicate: if multiple events at same slot, take first (or aggregate)
    events_merge = events[event_cols].drop_duplicates(subset=['merge_key'], keep='first')
    print(f"  Unique event slots: {len(events_merge)}")

    # Step 6: Merge - WEATHER is base, LEFT JOIN events
    print("\nMerging weather with events...")
    merged = weather.merge(
        events_merge,
        on='merge_key',
        how='left'
    )

    # Step 7: Clean up temporary columns
    temp_cols = ['merge_key', 'slot_hour', 'slot_minute', 'weather_date']
    merged = merged.drop(columns=[c for c in temp_cols if c in merged.columns], errors='ignore')

    # Step 8: Calculate rush_hour based on EVENT timing (if event exists)
    print("\nCalculating rush_hour based on event timing...")
    merged = calculate_event_rush_hour_from_merged(merged)

    print(f"\nMerged: {len(merged)} rows")

    # Stats
    events_matched = merged['event_name'].notna().sum()
    print(f"Event slots matched: {events_matched} / {len(merged)} ({events_matched/len(merged)*100:.1f}%)")

    # Anchor distribution
    anchor_counts = merged['anchor_name'].value_counts()
    print("\nAnchor distribution:")
    for anchor, count in anchor_counts.items():
        print(f"  {anchor}: {count} rows")

    # Save
    print(f"\nSaving to {output_path}...")
    merged.to_excel(output_path, index=False)
    print("Done!")

    return merged


def calculate_event_rush_hour_from_merged(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate rush_hour based on event timing for merged data.

    Only affects rows where event info exists.
    """
    df = df.copy()

    def is_rush_for_event(row):
        # If no event, return 0
        if pd.isna(row.get('event_name')):
            return 0

        slot_hour = row['datetime'].hour
        slot_min = row['datetime'].minute
        slot_total_min = slot_hour * 60 + slot_min

        # Event start/end times
        start_hour = int(row['start_time'].split(':')[0])
        start_min = int(row['start_time'].split(':')[1])
        start_total_min = start_hour * 60 + start_min

        end_hour = int(row['end_time'].split(':')[0])
        end_min = int(row['end_time'].split(':')[1])
        end_total_min = end_hour * 60 + end_min

        # 30 min before start INCLUDING start time
        rush_before_start = (slot_total_min >= start_total_min - 30) and (slot_total_min <= start_total_min)

        # 30 min after end INCLUDING end time
        rush_after_end = (slot_total_min >= end_total_min) and (slot_total_min < end_total_min + 30)

        return 1 if (rush_before_start or rush_after_end) else 0

    df['is_rush_hour'] = df.apply(is_rush_for_event, axis=1)

    # Stats
    rush_stats = df['is_rush_hour'].value_counts()
    print(f"Rush hour distribution: {dict(rush_stats)}")

    return df


if __name__ == '__main__':
    merge_weather_events()
