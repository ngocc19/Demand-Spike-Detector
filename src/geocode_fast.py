"""Fast geocoding using cache + hardcoded venues only (no API calls)."""

import csv
import json
from pathlib import Path
import h3

# Hardcoded coordinates - expand this as needed
VENUE_COORDINATES: dict[str, tuple[float, float]] = {
    # Historical/Cultural
    "văn miếu": (21.0369, 105.8351),
    "văn miếu - quốc tử giám": (21.0369, 105.8351),
    "quốc tử giám": (21.0369, 105.8351),
    "sân thái học": (21.0369, 105.8351),
    "hoàng thành thăng long": (21.0380, 105.8348),
    "hoàng diệu": (21.0380, 105.8348),
    "khu di sản hoàng thành": (21.0380, 105.8348),
    "khu di tích hoàng thành": (21.0380, 105.8348),
    "bảo tàng hà nội": (21.0295, 105.8475),
    "sân khấu view hồ nước": (21.0295, 105.8475),
    "chùa cúc": (21.0380, 105.8350),
    "đình làng lệ mật": (21.0150, 105.8800),

    # Sports venues
    "cung thể thao điền kinh mỹ đình": (21.0636, 105.7639),
    "mỹ đình": (21.0636, 105.7639),
    "svđqg mỹ đình": (21.0636, 105.7639),
    "svđ hàng đẫy": (21.0451, 105.7841),
    "hàng đẫy": (21.0451, 105.7841),

    # Theaters & Concert halls
    "nhà hát hồ gươm": (21.0285, 105.8527),
    "nhà hát âu cơ": (21.0285, 105.8527),
    "trung tâm hội nghị quốc gia": (21.0402, 105.7871),
    "nhà hát ca múa nhạc thăng long": (21.0285, 105.8527),
    "1900 le theatre": (21.0285, 105.8527),
    "sân khấu": (21.0285, 105.8527),

    # SOL8 Live Stage
    "sol8": (21.0285, 105.8527),
    "sol 8": (21.0285, 105.8527),

    # Malls & Shopping
    "aeon mall hà đông": (20.9828, 105.7854),
    "go! thăng long": (21.0136, 105.7989),
    "vincom mega mall": (21.0052, 105.8203),
    "vcca": (21.0052, 105.8203),
    "vincom": (21.0052, 105.8203),
    "mipec long biên": (21.0487, 105.8745),
    "long biên art space": (21.0487, 105.8745),

    # Public areas
    "phố đi bộ hồ gươm": (21.0285, 105.8527),
    "hồ gươm": (21.0285, 105.8527),

    # Schools
    "đại học sư phạm hà nội": (21.0367, 105.8018),

    # Cultural venues
    "cung văn hóa hữu nghị": (21.0085, 105.7832),
    "làng văn hóa các dân tộc việt nam": (21.0520, 105.7600),
    "trung tâm triển lãm việt nam": (21.2219, 105.8547),
    "cung triển lãm xây dựng hà nội": (21.0280, 105.7850),
    "cung xuân": (21.0210, 105.8440),
    "nhà triển lãm mỹ thuật": (21.0285, 105.8527),
    "ngô quyền": (21.0285, 105.8527),

    # Cultural venues
    "làng văn hóa": (21.0520, 105.7600),
    "du lịch các dân tộc": (21.0520, 105.7600),

    # Office buildings
    "hàng dầu": (21.0318, 105.8539),  # Sở VHTT HN
    "sở văn hóa": (21.0318, 105.8539),

    # Historical sites
    "phủ chủ tịch": (21.0380, 105.8340),
    "hồ chí minh": (21.0380, 105.8340),

    # Other
    "bắc ninh": (21.1860, 106.0790),  # Outside Hanoi
    "soc sơn": (21.2167, 105.8833),  # Sóc Sơn district
    "sớc sơn": (21.2167, 105.8833),  # Sóc Sơn district
    "đan tảo": (21.2167, 105.8833),  # Đan Tảo village
    "xã sóc sơn": (21.2167, 105.8833),  # Sóc Sơn commune
    "paris": (48.8566, 2.3522),  # Paris
    "unesco": (48.8566, 2.3522),  # Paris
    "benaras": (21.0285, 105.8527),  # Restaurant near Hoan Kiem
    "indian restaurant": (21.0285, 105.8527),
    "1900 le th": (21.0285, 105.8527),  # 1900 Le Théâtre
    "le th": (21.0285, 105.8527),  # Theatre near Hoan Kiem

    # Schools
    "trường thcs trần duy hưng": (21.0375, 105.8320),
    "trần duy hưng": (21.0375, 105.8320),
    "trường tiểu học ngô thì nhậm": (21.0380, 105.8400),
    "ngô thì nhậm": (21.0380, 105.8400),
    "trường thcs hoàng liệt": (21.0460, 105.8500),
    "hoàng liệt": (21.0460, 105.8500),
    "đại học bách khoa hà nội": (21.0060, 105.8433),
    "bách khoa hà nội": (21.0060, 105.8433),
}

H3_RESOLUTION = 8

def normalize(text: str) -> str:
    """Normalize venue name."""
    return text.lower().strip()

def find_venue_coords(venue: str, cache: dict, hardcoded: dict) -> tuple:
    """Find coordinates using cache first, then hardcoded."""
    if not venue:
        return None, None

    norm = normalize(venue)

    # Check cache
    if norm in cache:
        return cache[norm][0], cache[norm][1]

    # Check hardcoded (partial match)
    for key, coords in hardcoded.items():
        if key in norm or norm in key:
            return coords[0], coords[1]

    # Try to extract from "tại X" pattern
    if " tại " in norm:
        location = norm.split(" tại ")[-1].strip()
        # Remove trailing punctuation
        location = location.rstrip('.,;')
        for key, coords in hardcoded.items():
            if key in location or location in key:
                return coords[0], coords[1]

    return None, None

def geocode_fast(csv_path: str, cache_path: str) -> dict:
    """Fast geocode using cache + hardcoded only."""

    # Load cache
    cache = {}
    if Path(cache_path).exists():
        with open(cache_path, 'r', encoding='utf-8') as f:
            cache = json.load(f)

    print(f"Loaded {len(cache)} cached venues")
    print(f"Hardcoded venues: {len(VENUE_COORDINATES)}")

    # Read CSV
    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print(f"Total rows: {len(rows)}")

    # Ensure columns exist
    for col in ['latitude', 'longitude', 'h3_index']:
        if col not in fieldnames:
            fieldnames.append(col)

    geocoded = 0
    missing = 0
    missing_venues = []

    # Geocode each row
    for row in rows:
        lat, lon = find_venue_coords(row.get('venue', ''), cache, VENUE_COORDINATES)

        if lat is not None and lon is not None:
            row['latitude'] = f"{lat:.6f}"
            row['longitude'] = f"{lon:.6f}"
            row['h3_index'] = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
            geocoded += 1
        else:
            row['latitude'] = ''
            row['longitude'] = ''
            row['h3_index'] = ''
            missing += 1
            venue = row.get('venue', '')
            if venue and venue not in missing_venues:
                missing_venues.append(venue)

    print(f"\nResults: {geocoded} geocoded, {missing} missing")

    # Write back
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    # Save updated cache
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    # Save missing venues
    if missing_venues:
        with open('missing_venues.txt', 'w', encoding='utf-8') as f:
            for v in missing_venues:
                f.write(v + '\n')
        print(f"Missing venues saved to missing_venues.txt ({len(missing_venues)} unique)")

    return {'geocoded': geocoded, 'missing': missing, 'missing_venues': missing_venues}

if __name__ == '__main__':
    csv_path = 'data/event.csv'
    cache_path = 'data/.geocode_cache.json'

    result = geocode_fast(csv_path, cache_path)
    print(f"\nDone! {result['geocoded']} venues geocoded.")
