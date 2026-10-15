"""
Phân tích giờ sự kiện trong event.csv
=========================================

Mục tiêu:
1. Đếm số event có giờ THỰC (không phải 00:00-23:59)
2. Phân tích giờ thực theo event_type
3. Đếm số event có giờ DEFAULT và thuộc type nào
"""

import csv
from collections import defaultdict
from datetime import datetime

def parse_time(time_str):
    """Parse time string HH:MM to (hour, minute)"""
    if not time_str:
        return None, None
    try:
        parts = time_str.strip().split(':')
        return int(parts[0]), int(parts[1])
    except:
        return None, None

def is_default_time(start_time, end_time):
    """Check if time is default (00:00 to 23:59)"""
    start_h, start_m = parse_time(start_time)
    end_h, end_m = parse_time(end_time)

    if start_h is None or end_h is None:
        return True

    # Pattern: start=00:00, end=23:59
    if start_h == 0 and start_m == 0:
        if (end_h == 23 and end_m == 59) or (end_h == 0 and end_m == 0):
            return True

    return False

def main():
    input_path = "data/event.csv"

    # Statistics
    total_events = 0
    default_time_events = 0
    real_time_events = 0

    # By event type
    type_stats = defaultdict(lambda: {
        'total': 0,
        'default': 0,
        'real': 0,
        'real_hours': defaultdict(int),  # start_hour -> count
        'real_end_hours': defaultdict(int),  # end_hour -> count
    })

    # Sample real-time events
    real_time_samples = []

    # Read CSV
    with open(input_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total_events = len(rows)

    for row in rows:
        event_type = row.get('type', 'unknown') or 'unknown'
        start_time = row.get('start_time', '')
        end_time = row.get('end_time', '')
        title = row.get('event_name', '')[:50]

        type_stats[event_type]['total'] += 1

        if is_default_time(start_time, end_time):
            default_time_events += 1
            type_stats[event_type]['default'] += 1
        else:
            real_time_events += 1
            type_stats[event_type]['real'] += 1

            # Track real hours
            start_h, _ = parse_time(start_time)
            end_h, end_m = parse_time(end_time)

            if start_h is not None:
                type_stats[event_type]['real_hours'][start_h] += 1
            if end_h is not None:
                type_stats[event_type]['real_end_hours'][end_h] += 1

            # Sample
            if len(real_time_samples) < 100:
                real_time_samples.append({
                    'type': event_type,
                    'title': title,
                    'start': start_time,
                    'end': end_time
                })

    # Print results
    print("=" * 80)
    print("PHÂN TÍCH GIỜ SỰ KIỆN TRONG EVENT.CSV")
    print("=" * 80)

    print(f"\n📊 TỔNG QUAN:")
    print(f"   Tổng số events: {total_events}")
    print(f"   Events có giờ THỰC: {real_time_events} ({real_time_events/total_events*100:.1f}%)")
    print(f"   Events có giờ DEFAULT (00:00-23:59): {default_time_events} ({default_time_events/total_events*100:.1f}%)")

    print(f"\n" + "=" * 80)
    print("THEO TỪNG EVENT TYPE:")
    print("=" * 80)

    # Sort by total count
    sorted_types = sorted(type_stats.items(), key=lambda x: x[1]['total'], reverse=True)

    for event_type, stats in sorted_types:
        pct_default = stats['default'] / stats['total'] * 100 if stats['total'] > 0 else 0
        pct_real = stats['real'] / stats['total'] * 100 if stats['total'] > 0 else 0

        print(f"\n📌 {event_type.upper()}")
        print(f"   Tổng: {stats['total']} events")
        print(f"   - Default time (00:00-23:59): {stats['default']} ({pct_default:.1f}%)")
        print(f"   - Real time: {stats['real']} ({pct_real:.1f}%)")

        if stats['real'] > 0:
            # Start hours distribution
            print(f"   Real START hours:")
            for hour in sorted(stats['real_hours'].keys()):
                count = stats['real_hours'][hour]
                bar = "█" * (count // 2)
                print(f"      {hour:02d}:00 - {count:3d} events {bar}")

            # End hours distribution
            print(f"   Real END hours:")
            for hour in sorted(stats['real_end_hours'].keys()):
                count = stats['real_end_hours'][hour]
                bar = "█" * (count // 2)
                print(f"      {hour:02d}:00 - {count:3d} events {bar}")

    print(f"\n" + "=" * 80)
    print("MẪU EVENTS CÓ GIỜ THỰC:")
    print("=" * 80)

    # Group samples by type
    samples_by_type = defaultdict(list)
    for s in real_time_samples:
        samples_by_type[s['type']].append(s)

    for event_type in ['concert', 'football', 'festival', 'exhibition', 'cultural_event', 'workshop', 'conference_seminar', 'official_or_diplomatic']:
        if event_type in samples_by_type and samples_by_type[event_type]:
            print(f"\n🎭 {event_type} ({len(samples_by_type[event_type])} samples):")
            for s in samples_by_type[event_type][:5]:
                print(f"   {s['start']} → {s['end']} | {s['title']}")

    # Summary statistics
    print(f"\n" + "=" * 80)
    print("KẾT LUẬN:")
    print("=" * 80)

    # Concert analysis
    concert_stats = type_stats.get('concert', {})
    if concert_stats['real'] > 0:
        real_hours = concert_stats['real_hours']
        most_common_start = max(real_hours.keys(), key=lambda h: real_hours[h]) if real_hours else None
        print(f"\n🎸 CONCERT: Peak start hour = {most_common_start}:00")

    # Football analysis
    football_stats = type_stats.get('football', {})
    if football_stats['real'] > 0:
        real_hours = football_stats['real_hours']
        most_common_start = max(real_hours.keys(), key=lambda h: real_hours[h]) if real_hours else None
        print(f"⚽ FOOTBALL: Peak start hour = {most_common_start}:00")

    # Cultural event analysis
    cultural_stats = type_stats.get('cultural_event', {})
    if cultural_stats['real'] > 0:
        real_hours = cultural_stats['real_hours']
        most_common_start = max(real_hours.keys(), key=lambda h: real_hours[h]) if real_hours else None
        print(f"🏛️  CULTURAL_EVENT: Peak start hour = {most_common_start}:00")

    # Festival analysis
    festival_stats = type_stats.get('festival', {})
    print(f"\n🎪 FESTIVAL: {festival_stats['default']}/{festival_stats['total']} events có giờ default")

    # Exhibition analysis
    exhibition_stats = type_stats.get('exhibition', {})
    print(f"📸 EXHIBITION: {exhibition_stats['default']}/{exhibition_stats['total']} events có giờ default")

if __name__ == "__main__":
    main()
