"""
Expand events into time slots for spike detection.
==========================================

This script reads event.csv and expands each event into multiple rows,
one for each time slot (default: 30 minutes).

Usage:
    python expand_time_slots.py              # Default: 30 min slots
    python expand_time_slots.py --slot 15   # 15 min slots
    python expand_time_slots.py --slot 60   # 60 min slots

Configuration:
    SLOT_MINUTES: Change this to modify slot duration
"""

import csv
import json
from pathlib import Path
import argparse
import h3

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


def process_events(csv_path: Path, slot_minutes: int = SLOT_MINUTES) -> dict:
    """
    Process event CSV and expand to time slots.

    Args:
        csv_path: Path to event.csv
        slot_minutes: Slot duration in minutes

    Returns:
        Dictionary with processing statistics
    """
    # Load cache if exists
    cache_path = csv_path.parent / '.geocode_cache.json'
    cache = {}
    if cache_path.exists():
        with open(cache_path, 'r', encoding='utf-8') as f:
            cache = json.load(f)

    # Merge cache into VENUE_COORDINATES for this run
    all_coords = dict(VENUE_COORDINATES)
    all_coords.update(cache)

    # Read CSV
    rows = []
    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    print(f'Original events: {len(rows)}')

    # Step 1: Geocode and filter Hanoi
    processed_rows = []
    for row in rows:
        lat, lon = geocode_venue(row.get('venue', ''))

        # Try cache first
        if lat is None:
            normalized = row.get('venue', '').lower().strip()
            if normalized in all_coords:
                lat, lon = all_coords[normalized]

        if lat and lon and in_hanoi(lat, lon):
            row['latitude'] = f'{lat:.6f}'
            row['longitude'] = f'{lon:.6f}'
            row['h3_index'] = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
            processed_rows.append(row)

    print(f'After Hanoi filter: {len(processed_rows)} events')

    # Step 2: Expand into time slots
    expanded_rows = []
    for row in processed_rows:
        slots = expand_to_slots(
            row['start_time'],
            row['end_time'],
            slot_minutes
        )

        for slot in slots:
            new_row = row.copy()
            new_row['time_slot'] = slot
            expanded_rows.append(new_row)

    print(f'After {slot_minutes}-min expansion: {len(expanded_rows)} rows')

    # Step 3: Update fieldnames and write CSV
    new_fields = ['latitude', 'longitude', 'h3_index', 'time_slot']
    for field in new_fields:
        if field not in fieldnames:
            fieldnames.append(field)

    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(expanded_rows)

    # Calculate statistics
    slot_distribution = {}
    for row in expanded_rows:
        slot = row['time_slot']
        hour = int(slot.split(':')[0])
        slot_distribution[hour] = slot_distribution.get(hour, 0) + 1

    return {
        'original_events': len(rows),
        'after_hanoi_filter': len(processed_rows),
        'expanded_rows': len(expanded_rows),
        'slot_minutes': slot_minutes,
        'slots_per_event': len(expanded_rows) / len(processed_rows) if processed_rows else 0,
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
        '--csv',
        type=str,
        default='data/event.csv',
        help='Path to event.csv (default: data/event.csv)'
    )

    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f'Error: {csv_path} not found')
        return

    print('=' * 60)
    print(f'EXPAND TIME SLOTS - {args.slot} MINUTES')
    print('=' * 60)
    print()

    stats = process_events(csv_path, args.slot)

    print()
    print('=' * 60)
    print('SUMMARY')
    print('=' * 60)
    print(f'Slot duration: {args.slot} minutes')
    print(f'Original events: {stats["original_events"]}')
    print(f'After Hanoi filter: {stats["after_hanoi_filter"]}')
    print(f'Expanded rows: {stats["expanded_rows"]}')
    print(f'Avg slots/event: {stats["slots_per_event"]:.1f}')
    print()
    print('Hourly distribution:')
    for hour in range(24):
        if hour in stats['slot_distribution']:
            count = stats['slot_distribution'][hour]
            bar = '█' * (count // 10)
            print(f'  {hour:02d}:00 - {count:4d} {bar}')


if __name__ == '__main__':
    main()
