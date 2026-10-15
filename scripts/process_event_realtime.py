"""
Process Event Realtime Data - Xử lý data sau khi crawl
=======================================================

Áp dụng cùng logic với backfill:
1. Load từ event_realtime.csv (12 cột theo plan)
2. Geocode venues (sử dụng VenueGeocoder)
3. Assign nearest anchor (Haversine)
4. Calculate time slots (30-min slots)
5. Output event_realtime_fixed.xlsx

Input: 12 cột từ event_realtime.csv (theo PLAN_event_realtime.md):
- event_name, venue, start_date, start_time, end_time
- type, estimate_attendence, source_url
- attendance_source_url, latitude, longitude, h3_index

Output: 16 cột (12 cột input + 4 cột phụ):
- 12 cột gốc (không có end_date)
- nearest_anchor, anchor_distance_km, is_rush_hour, time_slot
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Import từ backfill modules
from geocode_venues import VenueGeocoder, lat_lon_to_h3

# Weather anchors (same as backfill)
ANCHORS = [
    {"name": "HoanKiem", "lat": 21.0285, "lon": 105.8542},
    {"name": "CauGiay", "lat": 21.0306, "lon": 105.7925},
    {"name": "HoangMai", "lat": 20.9723, "lon": 105.8454},
    {"name": "LongBien", "lat": 21.0470, "lon": 105.8920},
    {"name": "TayHo", "lat": 21.0664, "lon": 105.8176},
    {"name": "NoiBai", "lat": 21.2187, "lon": 105.8042},
]

# H3 Resolution
DEFAULT_H3_RESOLUTION = 8


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Tính khoảng cách Haversine (km)."""
    from math import radians, cos, sin, asin, sqrt

    R = 6371  # Earth radius in km
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return 2 * asin(sqrt(a)) * R


def get_nearest_anchor(lat: float, lon: float) -> tuple:
    """Tìm anchor gần nhất với tọa độ."""
    min_dist = float('inf')
    nearest = None

    for anchor in ANCHORS:
        dist = haversine_distance(lat, lon, anchor['lat'], anchor['lon'])
        if dist < min_dist:
            min_dist = dist
            nearest = anchor['name']

    return nearest, round(min_dist, 2)


def is_hanoi(lat: float, lon: float) -> bool:
    """Kiểm tra tọa độ có trong Hà Nội không."""
    # Hanoi approximate bounds
    return 20.85 <= lat <= 21.15 and 105.70 <= lon <= 105.95


def is_rush_hour(time_str: str) -> int:
    """Rush hour: 07:00-09:00 và 17:00-19:00"""
    if pd.isna(time_str) or not time_str:
        return 0
    try:
        parts = str(time_str).split(':')
        hour = int(parts[0])
        if (7 <= hour <= 8) or (17 <= hour <= 18):
            return 1
    except:
        pass
    return 0


def round_time_to_slot(time_str: str, slot_minutes: int = 30) -> str:
    """Round time down to nearest slot boundary."""
    parts = str(time_str).split(':')
    hour = int(parts[0])
    minute = int(parts[1])

    # Round down to nearest slot
    slot = (minute // slot_minutes) * slot_minutes
    return f'{hour:02d}:{slot:02d}'


def fix_event_times(df: pd.DataFrame) -> pd.DataFrame:
    """
    Xử lý thời gian sự kiện theo spec:

    Multi-day KHÔNG có thời gian thực (00:00-23:59):
        - Tất cả các ngày: 08:00 - 22:00

    Multi-day CÓ thời gian thực:
        - Ngày đầu:   start = crawl, end = 22:00
        - Ngày giữa:  start = 08:00, end = 22:00
        - Ngày cuối:  start = 08:00, end = crawl (nếu crawl có giờ thật)
                     hoặc end = 22:00 (nếu crawl không có giờ kết thúc thật)

    Single-day CÓ đủ start + end từ crawl: giữ nguyên.

    Single-day chỉ thiếu 1 trong 2 (start hoặc end):
        - start = crawl nếu có, ngược lại 08:00
        - end   = crawl nếu có, ngược lại 22:00
    """
    print("  [Step 1] Fixing event times (multi-day handling)...")

    # Parse dates - chỉ dùng start_date (12 cột format)
    df['start_date_dt'] = pd.to_datetime(df['start_date'], format='%d/%m/%y', errors='coerce')

    # Sắp xếp theo event_name và start_date
    df = df.sort_values(['event_name', 'start_date_dt']).reset_index(drop=True)

    # Xác định ngày đầu và ngày cuối cho mỗi sự kiện
    event_dates = df.groupby('event_name')['start_date_dt'].agg(['min', 'max'])
    event_dates.columns = ['first_date', 'last_date']

    # Merge thông tin ngày vào dataframe
    df = df.merge(event_dates, on='event_name', how='left')

    # Đếm số ngày của mỗi event (1 = single-day, >1 = multi-day)
    day_counts = df.groupby('event_name')['start_date_dt'].transform('count')
    df['day_count'] = day_counts

    # Xác định loại ngày
    df['is_first_day'] = df['start_date_dt'] == df['first_date']
    df['is_last_day'] = df['start_date_dt'] == df['last_date']
    df['is_middle_day'] = (~df['is_first_day']) & (~df['is_last_day']) & (df['day_count'] > 1)

    # Hằng số fallback
    DEFAULT_DAY_START = '08:00'
    DEFAULT_DAY_END = '22:00'
    DEFAULT_TIME_MARKER_START = '00:00'
    DEFAULT_TIME_MARKER_END = '23:59'

    def _is_real_time(s: str, e: str) -> bool:
        """Source cho thời gian thật khi KHÔNG phải marker 00:00-23:59."""
        return not (s == DEFAULT_TIME_MARKER_START and e == DEFAULT_TIME_MARKER_END)

    def _is_real_end(e: str) -> bool:
        """End thật khi KHÔNG phải 23:59 mặc định (23:59 = source không có giờ kết thúc)."""
        return e != DEFAULT_TIME_MARKER_END

    # Xử lý thời gian theo loại ngày
    for idx, row in df.iterrows():
        event_name = row['event_name']
        first_day_row = df[(df['event_name'] == event_name) & (df['is_first_day'])]

        if len(first_day_row) > 0:
            orig_start = str(first_day_row.iloc[0]['start_time']).strip()
            orig_end = str(first_day_row.iloc[0]['end_time']).strip()
        else:
            orig_start = str(row['start_time']).strip()
            orig_end = str(row['end_time']).strip()

        day_count = int(row['day_count'])
        is_multi_day = day_count > 1

        if not _is_real_time(orig_start, orig_end):
            # ---- Trường hợp 1: Multi-day không có giờ thực ----
            # Tất cả các ngày: 08:00 - 22:00
            df.at[idx, 'start_time'] = DEFAULT_DAY_START
            df.at[idx, 'end_time'] = DEFAULT_DAY_END

        elif not is_multi_day:
            # ---- Trường hợp 5+6: Single-day ----
            # Có giờ thật; nếu thiếu 1 trong 2 thì fallback
            if orig_start == DEFAULT_TIME_MARKER_START:
                df.at[idx, 'start_time'] = DEFAULT_DAY_START
            if orig_end == DEFAULT_TIME_MARKER_END:
                df.at[idx, 'end_time'] = DEFAULT_DAY_END

        elif row['is_first_day']:
            # ---- Trường hợp 2: Multi-day, ngày đầu ----
            # start = crawl, end = 22:00
            if orig_start == DEFAULT_TIME_MARKER_START:
                df.at[idx, 'start_time'] = DEFAULT_DAY_START
            df.at[idx, 'end_time'] = DEFAULT_DAY_END

        elif row['is_middle_day']:
            # ---- Trường hợp 3: Multi-day, ngày giữa ----
            df.at[idx, 'start_time'] = DEFAULT_DAY_START
            df.at[idx, 'end_time'] = DEFAULT_DAY_END

        elif row['is_last_day']:
            # ---- Trường hợp 4: Multi-day, ngày cuối ----
            # start = 08:00; end = crawl nếu có, ngược lại 22:00
            df.at[idx, 'start_time'] = DEFAULT_DAY_START
            if _is_real_end(orig_end):
                df.at[idx, 'end_time'] = orig_end
            else:
                df.at[idx, 'end_time'] = DEFAULT_DAY_END

    # Vứt các cột tạm
    temp_cols = ['first_date', 'last_date', 'is_first_day', 'is_last_day', 'is_middle_day',
                 'day_count', 'start_date_dt']
    df = df.drop(columns=[c for c in temp_cols if c in df.columns])

    return df


def geocode_venues(df: pd.DataFrame, cache_path: str = 'data/.geocode_cache.json') -> pd.DataFrame:
    """Geocode venues sử dụng VenueGeocoder (từ geocode_venues.py)."""
    print("  [Step 2] Geocoding venues...")

    geocoder = VenueGeocoder(Path(cache_path))

    # Ensure h3_index column is string type (H3 hex IDs are strings)
    if 'h3_index' in df.columns:
        df['h3_index'] = df['h3_index'].astype(str).replace('nan', '').replace('None', '')

    geocoded_count = 0
    for idx, row in df.iterrows():
        venue = row.get('venue', '')
        # Check NaN, None, empty
        if pd.isna(venue):
            continue
        venue = str(venue)
        if not venue.strip():
            continue

        try:
            lat, lon = geocoder.geocode(venue)
            if lat is not None and lon is not None:
                df.at[idx, 'latitude'] = lat
                df.at[idx, 'longitude'] = lon
                # H3 index is a hex string, not float
                h3 = lat_lon_to_h3(lat, lon, DEFAULT_H3_RESOLUTION)
                df.at[idx, 'h3_index'] = str(h3) if h3 else ''
                geocoded_count += 1
        except Exception as e:
            # Silent skip - just log count
            continue

    geocoder.close()
    print(f"    Geocoded: {geocoded_count}/{len(df)} venues")

    return df


def assign_anchors(df: pd.DataFrame) -> pd.DataFrame:
    """Assign nearest anchor cho mỗi event."""
    print("  [Step 3] Assigning nearest anchors...")

    for idx, row in df.iterrows():
        lat_str = row.get('latitude')
        lon_str = row.get('longitude')

        if pd.isna(lat_str) or pd.isna(lon_str) or not lat_str or not lon_str:
            continue

        try:
            lat = float(lat_str)
            lon = float(lon_str)

            # Always assign the nearest anchor — even if the venue sits
            # outside the old hard-coded Hanoi bounds (e.g. NoiBai at
            # ~21.22 lat, which has its own dedicated anchor). The
            # bounds check was incorrectly filtering those out.
            anchor, dist = get_nearest_anchor(lat, lon)
            df.at[idx, 'nearest_anchor'] = anchor
            df.at[idx, 'anchor_distance_km'] = dist
        except (ValueError, TypeError):
            continue

    anchored_count = df['nearest_anchor'].notna().sum()
    print(f"    Anchored: {anchored_count}/{len(df)} events")

    # Show anchor distribution
    if anchored_count > 0:
        print("    Anchor distribution:")
        for anchor, count in df[df['nearest_anchor'].notna()]['nearest_anchor'].value_counts().items():
            print(f"      {anchor}: {count}")

    return df


def fix_durations(df: pd.DataFrame) -> pd.DataFrame:
    """Fix event durations based on type.

    Rules:
    - Education (hanoi.edu.vn): start 7h, end 10h (duration 3h)
    - Football: start 19h15 → end 21h15, start 20h00 → end 22h00
    """
    print("  [Fix] Adjusting event durations...")

    for idx, row in df.iterrows():
        event_type = str(row.get('type', '')).lower()
        start_time = str(row.get('start_time', ''))

        # Education events (from hanoi.edu.vn) - khai giảng
        if 'hanoi.edu.vn' in str(row.get('source_url', '')):
            df.at[idx, 'start_time'] = '07:00'
            df.at[idx, 'end_time'] = '10:00'
            continue

        # Football events
        if event_type == 'football':
            if '19:15' in start_time:
                df.at[idx, 'end_time'] = '21:15'
            elif '20:00' in start_time:
                df.at[idx, 'end_time'] = '22:00'

    return df


def expand_to_time_slots(df: pd.DataFrame) -> pd.DataFrame:
    """Expand each event into multiple rows, one per 30-minute slot.

    Example:
      Event: 19:00-22:00
      Becomes: 19:00, 19:30, 20:00, 20:30, 21:00, 21:30 (6 rows)
    """
    print("  [Step 5] Expanding to 30-min time slots...")

    rows = []
    slot_minutes = 30

    for _, event in df.iterrows():
        start = event['start_time']
        end = event['end_time']

        # Parse times
        try:
            start_h, start_m = map(int, start.split(':'))
            end_h, end_m = map(int, end.split(':'))
        except:
            continue

        # Convert to minutes
        start_total = start_h * 60 + start_m
        end_total = end_h * 60 + end_m

        # Generate slots
        current = start_total
        while current < end_total:
            slot_h = current // 60
            slot_m = current % 60
            slot_str = f"{slot_h:02d}:{slot_m:02d}"

            # Create new row with this slot
            new_row = event.copy()
            new_row['time_slot'] = slot_str
            rows.append(new_row)

            current += slot_minutes

    result = pd.DataFrame(rows)
    # Avoid non-ASCII arrow on Windows consoles (cp1252) which would
    # crash the print with "'charmap' codec can't encode character".
    print(f"    Expanded: {len(df)} events -> {len(result)} time slots")
    return result


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate rush_hour và time_slot."""
    print("  [Step 4] Calculating features...")

    # Rush hour
    df['is_rush_hour'] = df['start_time'].apply(is_rush_hour)
    rush_count = df['is_rush_hour'].sum()
    print(f"    Rush hour events: {rush_count}/{len(df)}")

    # Time slot (30-min) - placeholder, will be expanded later
    df['time_slot'] = df['start_time'].apply(lambda x: round_time_to_slot(x, 30))
    print(f"    Time slots calculated")

    return df


def process_event_realtime(
    input_path: str = 'data/event_realtime.csv',
    output_path: str = 'data/event_realtime_fixed.xlsx'
) -> pd.DataFrame:
    """
    Process event realtime data.

    Steps (same as backfill):
    1. Load data
    2. Fix event times (multi-day)
    3. Geocode venues (VenueGeocoder)
    4. Assign nearest anchor
    5. Calculate features (rush_hour, time_slot)
    6. Save to Excel

    Args:
        input_path: Path to event_realtime.csv
        output_path: Path to output Excel file

    Returns:
        Processed DataFrame
    """
    import os
    os.chdir(Path(__file__).parent.parent)  # Go to project root

    print(f"\nProcessing event realtime data...")
    print(f"  Input: {input_path}")
    print(f"  Output: {output_path}")

    # Step 1: Load data
    print(f"\n[Step 1] Loading data...")
    df = pd.read_csv(input_path)
    print(f"  Loaded: {len(df)} rows, {df['event_name'].nunique()} unique events")

    # Step 2: Fix event times
    df = fix_event_times(df)

    # Step 3: Geocode venues
    df = geocode_venues(df)

    # Step 4: Assign anchors
    df = assign_anchors(df)

    # Step 5: Calculate features
    df = calculate_features(df)

    # Step 6: Fix durations based on event type
    df = fix_durations(df)

    # Step 7: Expand to 30-min time slots (1 event = N rows)
    df = expand_to_time_slots(df)

    # Step 8: Prepare output
    print(f"\n[Saving] Output: {output_path}")

    # Ensure h3_index is string (not float) for Excel
    if 'h3_index' in df.columns:
        df['h3_index'] = df['h3_index'].astype(str).replace('nan', '').replace('None', '')

    # Reorder columns (12 cột theo plan + 4 cột phụ cho fixed.xlsx)
    final_cols = [
        'event_name', 'venue', 'start_date',
        'start_time', 'end_time', 'type',
        'estimate_attendence', 'source_url',
        'attendance_source_url',
        'latitude', 'longitude', 'h3_index',
        'nearest_anchor', 'anchor_distance_km', 'is_rush_hour', 'time_slot'
    ]
    final_cols = [c for c in final_cols if c in df.columns]
    df = df[final_cols]

    # Save to Excel atomically so a running Task Scheduler run does not
    # collide with a previous run whose file is still open in Excel.
    output_path = Path(output_path)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        df.to_excel(tmp_path, index=False)
        if output_path.exists():
            output_path.unlink()
        tmp_path.rename(output_path)
        print(f"  Saved: {output_path}")
    except PermissionError as e:
        # File is likely open in Excel. Keep the old file and surface a
        # warning so the cron log shows the failure, but don't crash.
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        print(f"  WARNING: Could not replace {output_path} (file locked?): {e}")
        import logging
        logging.warning(f"Could not update xlsx (file locked): {e}")

    # Stats
    print(f"\n[Stats]")
    print(f"  Total rows: {len(df)}")
    print(f"  Unique events: {df['event_name'].nunique()}")
    print(f"  Events with coordinates: {df['latitude'].notna().sum()}")
    print(f"  Events with anchors: {df['nearest_anchor'].notna().sum()}")
    print(f"  Rush hour events: {df['is_rush_hour'].sum()}")

    # By category
    print(f"\n[By Category]")
    cat_counts = df.groupby('type').size()
    for cat, count in cat_counts.items():
        print(f"  {cat}: {count}")

    print("\nDone!")

    return df


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Process Event Realtime Data')
    parser.add_argument('--input', default='data/event_realtime.csv', help='Input CSV file')
    parser.add_argument('--output', default='data/event_realtime_fixed.xlsx', help='Output Excel file')

    args = parser.parse_args()

    df = process_event_realtime(args.input, args.output)
