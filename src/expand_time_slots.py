"""
Expand events into time slots for spike detection.
==========================================

This script reads event file (CSV or Excel) and expands each event into multiple rows,
one for each time slot (default: 30 minutes).

Usage:
    python expand_time_slots.py                      # Default: 30 min slots
    python expand_time_slots.py --slot 15            # 15 min slots
    python expand_time_slots.py --slot 60            # 60 min slots
    python expand_time_slots.py --input data.xlsx    # Read from Excel

Configuration:
    SLOT_MINUTES: Change this to modify slot duration
"""

import csv
import json
from pathlib import Path
import argparse
import h3
import pandas as pd

# ============================================================
# CONFIGURATION - CHANGE THIS TO MODIFY SLOT DURATION
# ============================================================
# Default slot duration in minutes
# Options: 15, 30, 60, etc.
SLOT_MINUTES = 30  # <-- CHANGE THIS VALUE

# H3 Resolution
H3_RESOLUTION = 8

# Hanoi bounds
HANOI_BOUNDS = {
    'lat_min': 20.85,
    'lat_max': 21.15,
    'lon_min': 105.70,
    'lon_max': 105.95
}

# Hardcoded venue coordinates (Vietnamese venues)
VENUE_COORDINATES = {
    'văn miếu': (21.0369, 105.8351),
    'văn miếu - quốc tử giám': (21.0369, 105.8351),
    'cung thể thao điền kinh mỹ đình': (21.0636, 105.7639),
    'mỹ đình': (21.0636, 105.7639),
    'svđqg mỹ đình': (21.0636, 105.7639),
    'svđ hàng đẫy': (21.0451, 105.7841),
    'nhà hát hồ gươm': (21.0285, 105.8527),
    'trung tâm hội nghị quốc gia': (21.0402, 105.7871),
    'aeon mall hà đông': (20.9828, 105.7854),
    'go! thăng long': (21.0136, 105.7989),
    'phố đi bộ hồ gươm': (21.0285, 105.8527),
    'đại học sư phạm hà nội': (21.0367, 105.8018),
}


def geocode_venue(venue: str) -> tuple:
    """
    Get lat/lon for a venue.

    Args:
        venue: Venue name string

    Returns:
        Tuple of (lat, lon) or (None, None) if not found
    """
    if not venue:
        return None, None

    normalized = venue.lower().strip()

    # Check hardcoded coordinates
    for key, coords in VENUE_COORDINATES.items():
        if key in normalized or normalized in key:
            return coords

    return None, None


def in_hanoi(lat: float, lon: float) -> bool:
    """Check if coordinates are within Hanoi bounds."""
    return (HANOI_BOUNDS['lat_min'] <= lat <= HANOI_BOUNDS['lat_max'] and
            HANOI_BOUNDS['lon_min'] <= lon <= HANOI_BOUNDS['lon_max'])


def parse_time(time_str: str) -> tuple:
    """
    Parse time string HH:MM to (hour, minute).

    Args:
        time_str: Time string in format "HH:MM"

    Returns:
        Tuple of (hour, minute) or (None, None) if invalid
    """
    try:
        parts = time_str.strip().split(':')
        return int(parts[0]), int(parts[1])
    except:
        return None, None


def expand_to_slots(start_time: str, end_time: str, slot_minutes: int = SLOT_MINUTES) -> list:
    """
    Generate list of time slots between start and end time.

    Args:
        start_time: Start time in format "HH:MM"
        end_time: End time in format "HH:MM"
        slot_minutes: Duration of each slot in minutes (default: SLOT_MINUTES)

    Returns:
        List of time slot strings in format "HH:MM"

    Example:
        >>> expand_to_slots("09:00", "11:00", 30)
        ['09:00', '09:30', '10:00', '10:30']

        >>> expand_to_slots("09:00", "10:00", 15)
        ['09:00', '09:15', '09:30', '09:45']
    """
    start_h, start_m = parse_time(start_time)
    end_h, end_m = parse_time(end_time)

    if start_h is None:
        return [start_time]

    # Convert to total minutes from midnight
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    # If end <= start, add slot_minutes to make it valid
    if end_minutes <= start_minutes:
        end_minutes = start_minutes + slot_minutes

    # Generate slots
    slots = []
    current = start_minutes
    while current < end_minutes:
        h = current // 60
        m = current % 60
        slots.append(f'{h:02d}:{m:02d}')
        current += slot_minutes

    return slots


def process_events(input_path: Path, slot_minutes: int = SLOT_MINUTES,
                   filter_hanoi: bool = True) -> dict:
    """
    Process event file (CSV or Excel) and expand to time slots.

    Args:
        input_path: Path to event file (CSV or Excel)
        slot_minutes: Slot duration in minutes
        filter_hanoi: Whether to filter events within Hanoi bounds

    Returns:
        Dictionary with processing statistics
    """
    # Determine file type
    is_excel = input_path.suffix.lower() in ['.xlsx', '.xls']

    # Read input file
    if is_excel:
        df = pd.read_excel(input_path)
    else:
        df = pd.read_csv(input_path, encoding='utf-8')

    print(f'Original events: {len(df)}')

    # Step 1: Geocode and filter Hanoi if needed
    if filter_hanoi:
        # Load cache
        cache_path = input_path.parent / '.geocode_cache.json'
        cache = {}
        if cache_path.exists():
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)

        # Merge cache into coordinates
        all_coords = dict(VENUE_COORDINATES)
        all_coords.update(cache)

        # Geocode events
        def get_coords(venue):
            if pd.isna(venue) or venue == '':
                return None, None
            normalized = str(venue).lower().strip()
            if normalized in all_coords:
                return all_coords[normalized]
            return None, None

        coords = df['venue'].apply(get_coords)
        df['latitude'] = coords.apply(lambda x: x[0])
        df['longitude'] = coords.apply(lambda x: x[1])

        # Filter Hanoi
        mask = df.apply(
            lambda row: row['latitude'] is not None and
                       in_hanoi(row['latitude'], row['longitude']),
            axis=1
        )
        df = df[mask].copy()
        print(f'After Hanoi filter: {len(df)} events')

        # Add H3 index
        df['h3_index'] = df.apply(
            lambda row: h3.latlng_to_cell(row['latitude'], row['longitude'], H3_RESOLUTION),
            axis=1
        )

    # Step 2: Expand into time slots
    expanded_rows = []
    for _, row in df.iterrows():
        slots = expand_to_slots(
            str(row['start_time']),
            str(row['end_time']),
            slot_minutes
        )

        for slot in slots:
            new_row = row.to_dict()
            new_row['slot_time'] = slot  # Changed from 'time_slot' to 'slot_time'
            expanded_rows.append(new_row)

    expanded_df = pd.DataFrame(expanded_rows)
    print(f'After {slot_minutes}-min expansion: {len(expanded_df)} rows')

    # Step 3: Save output (same format as input)
    output_path = input_path
    if is_excel:
        expanded_df.to_excel(output_path, index=False)
    else:
        expanded_df.to_csv(output_path, index=False, encoding='utf-8')

    # Calculate statistics
    slot_distribution = {}
    for slot in expanded_df['slot_time']:
        hour = int(slot.split(':')[0])
        slot_distribution[hour] = slot_distribution.get(hour, 0) + 1

    return {
        'original_events': len(df),
        'expanded_rows': len(expanded_df),
        'slot_minutes': slot_minutes,
        'slots_per_event': len(expanded_df) / len(df) if len(df) > 0 else 0,
        'slot_distribution': slot_distribution
    }


def main():
    parser = argparse.ArgumentParser(description='Expand events into time slots')
    parser.add_argument(
        '--slot',
        type=int,
        default=SLOT_MINUTES,
        choices=[15, 30, 60],
        help=f'Slot duration in minutes (default: {SLOT_MINUTES})'
    )
    parser.add_argument(
        '--input', '-i',
        type=str,
        default='data/event.csv',
        help='Path to event file (CSV or Excel). Default: data/event.csv'
    )
    parser.add_argument(
        '--no-filter',
        action='store_true',
        help='Skip Hanoi location filter (use existing lat/lon/h3_index)'
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f'Error: {input_path} not found')
        return

    print('=' * 60)
    print(f'EXPAND TIME SLOTS - {args.slot} MINUTES')
    print(f'Input: {input_path}')
    print('=' * 60)
    print()

    stats = process_events(input_path, args.slot, filter_hanoi=not args.no_filter)

    print()
    print('=' * 60)
    print('SUMMARY')
    print('=' * 60)
    print(f'Slot duration: {args.slot} minutes')
    print(f'Events processed: {stats["original_events"]}')
    print(f'Expanded rows: {stats["expanded_rows"]}')
    print(f'Avg slots/event: {stats["slots_per_event"]:.1f}')
    print()
    print('Hourly distribution:')
    for hour in range(24):
        if hour in stats['slot_distribution']:
            count = stats['slot_distribution'][hour]
            bar = '#' * (count // 10)
            print(f'  {hour:02d}:00 - {count:4d} {bar}')


if __name__ == '__main__':
    main()
