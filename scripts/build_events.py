"""
Build events.csv and events.xlsx with required columns:
- event_name, venue, start_date, end_date, start_time, end_time
- event_type, attendence_estimate, source_url, source_attendence
- latitude, longitude, h3_index

Uses geocode_venues.py for lat/long/h3 coordinates.
Only fills attendence_estimate when there's actual source evidence.
"""

import csv
import json
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Import from geocode_venues
from src.geocode_venues import VenueGeocoder, lat_lon_to_h3, VENUE_COORDINATES

# Output columns in required order
CSV_COLUMNS = [
    "event_name",
    "venue",
    "start_date",
    "end_date",
    "start_time",
    "end_time",
    "event_type",
    "attendence_estimate",
    "source_url",
    "source_attendence",
    "latitude",
    "longitude",
    "h3_index",
]

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DATA_DIR = Path("data")
CURATED_DIR = DATA_DIR / "curated" / "events_current"
CACHE_PATH = DATA_DIR / ".geocode_cache.json"


def parse_hanoi_datetime(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(TZ)


def main():
    geocoder = VenueGeocoder(CACHE_PATH)

    # Read all curated events
    records_by_id = {}
    for path in sorted(CURATED_DIR.glob("source=*/events.jsonl")):
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                event_id = record.get("event_id")
                if event_id:
                    records_by_id[event_id] = record

    print(f"Loaded {len(records_by_id)} curated events")

    # Deduplicate by source_url + start_at_utc
    groups: dict[tuple, list] = {}
    for record in records_by_id.values():
        key = (record.get("source_url"), record.get("start_at_utc"), record.get("title"))
        if all(isinstance(v, str) and v for v in key):
            groups.setdefault(key, []).append(record)
        else:
            groups[key] = [record]

    rows = []
    for group in groups.values():
        # Pick winner: festival > has attendance > earliest event_id
        winner = min(group, key=lambda r: (
            0 if r.get("primary_category") == "festival" else 1,
            0 if r.get("estimated_attendees") is not None else 1,
            str(r.get("event_id") or ""),
        ))

        # Get attendance evidence from any group member
        attendance_record = next(
            (r for r in group if r.get("estimated_attendees") is not None and r.get("attendance_source_url")),
            None
        )

        start = parse_hanoi_datetime(winner.get("start_at_utc"))
        end = parse_hanoi_datetime(winner.get("end_at_utc")) or start
        if not start:
            continue

        final_date = max(start.date(), end.date())

        # Expand multi-day events
        for day_offset in range((final_date - start.date()).days + 1):
            current_date = start.date() + timedelta(days=day_offset)

            row = {
                "event_name": str(winner.get("title") or ""),
                "venue": str(winner.get("venue_raw") or ""),
                "start_date": current_date.strftime("%d/%m/%y"),
                "end_date": final_date.strftime("%d/%m/%y"),
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M"),
                "event_type": str(winner.get("primary_category") or "other"),
                "attendence_estimate": "",
                "source_url": str(winner.get("source_url") or ""),
                "source_attendence": "",
                "latitude": "",
                "longitude": "",
                "h3_index": "",
            }

            # Only fill attendance if there's actual evidence
            if attendance_record:
                row["attendence_estimate"] = int(attendance_record["estimated_attendees"])
                row["source_attendence"] = str(attendance_record.get("attendance_source_url") or "")

            # Geocode venue
            venue = row["venue"]
            if venue:
                lat, lon = geocoder.geocode(venue)
                if lat is not None and lon is not None:
                    row["latitude"] = f"{lat:.6f}"
                    row["longitude"] = f"{lon:.6f}"
                    row["h3_index"] = lat_lon_to_h3(lat, lon)

            rows.append(row)

    # Sort by date, time, name
    rows.sort(key=lambda r: (r["start_date"], r["start_time"], r["event_name"], r["venue"]))

    # Save CSV
    csv_path = DATA_DIR / "events.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} rows to {csv_path}")

    # Save XLSX
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Events"

        # Write header
        for col_idx, header in enumerate(CSV_COLUMNS, 1):
            ws.cell(row=1, column=col_idx, value=header)

        # Write data
        for row_idx, row in enumerate(rows, 2):
            for col_idx, header in enumerate(CSV_COLUMNS, 1):
                ws.cell(row=row_idx, column=col_idx, value=row[header])

        # Auto-adjust column widths
        for col_idx, header in enumerate(CSV_COLUMNS, 1):
            max_len = len(header)
            for row_idx in range(2, len(rows) + 2):
                v = ws.cell(row=row_idx, column=col_idx).value
                if v:
                    max_len = max(max_len, len(str(v)))
            col_letter = chr(64 + col_idx) if col_idx <= 26 else f"A{col_idx - 25}"
            ws.column_dimensions[col_letter].width = min(max_len + 2, 50)

        xlsx_path = DATA_DIR / "events.xlsx"
        wb.save(xlsx_path)
        print(f"Saved {len(rows)} rows to {xlsx_path}")
    except ImportError:
        print("openpyxl not installed, skipping xlsx export")

    # Save geocode cache
    geocoder.close()

    # Stats
    with_attendance = sum(1 for r in rows if r["attendence_estimate"])
    with_coords = sum(1 for r in rows if r["latitude"])
    print(f"\nStats: {with_attendance}/{len(rows)} with attendance, {with_coords}/{len(rows)} with coordinates")


if __name__ == "__main__":
    main()
