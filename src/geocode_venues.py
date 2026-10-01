"""Geocode venues from event.csv to add latitude/longitude coordinates and H3 index.

Uses Nominatim (OpenStreetMap) geocoding with caching to avoid redundant API calls.
H3 indexing follows Uber's hexagonal hierarchical spatial indexing approach.

Requires geopy and h3 packages.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Optional

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import h3

# Hardcoded coordinates for well-known Hanoi venues to avoid API rate limits
VENUE_COORDINATES: dict[str, tuple[float, float]] = {
    # Historical/Cultural sites
    "văn miếu": (21.0369, 105.8351),
    "văn miếu - quốc tử giám": (21.0369, 105.8351),
    "quốc tử giám": (21.0369, 105.8351),
    "sân thái học": (21.0369, 105.8351),
    "không gian hồ văn": (21.0369, 105.8351),
    "vườn giám": (21.0369, 105.8351),
    "tiền đường": (21.0369, 105.8351),
    "nhà thái học": (21.0369, 105.8351),

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
    "việt thương concert hall": (21.0276, 105.8529),
    "aplus hanoi": (21.0285, 105.8527),

    # Cultural centers & Museums
    "cung văn hóa lao động hữu nghị việt xô": (21.0085, 105.7832),
    "cung văn hóa lao động hữu nghị việt - xô": (21.0085, 105.7832),
    "bảo tàng hưng yên": (20.6465, 106.0515),
    "bảo tàng khánh hoà": (12.2388, 109.1967),

    # Malls & Shopping
    "aeon mall hà đông": (20.9828, 105.7854),
    "go! thăng long": (21.0136, 105.7989),
    "đại siêu thị go! thăng long": (21.0136, 105.7989),

    # Public areas
    "phố đi bộ hồ gươm": (21.0285, 105.8527),
    "hồ gươm": (21.0285, 105.8527),
    "công viên yên sở": (20.9821, 105.8734),
    "vườn hoa yên sở": (20.9821, 105.8734),

    # Exhibition centers
    "vietnam exposition center": (21.2219, 105.8547),
    "trung tâm triển lãm việt nam": (21.2219, 105.8547),
    "trung tâm triển lãm việt nam (vec)": (21.2219, 105.8547),

    # Schools (approximate)
    "trường thcs trần duy hưng": (21.0058, 105.7989),
    "trường tiểu học ngô thì nhậm": (21.0189, 105.8256),
    "trường thcs hoàng liệt": (20.9867, 105.8356),
    "đại học sư phạm hà nội": (21.0367, 105.8018),
    "đh sư phạm hà nội": (21.0367, 105.8018),
    "xuân thủy": (21.0367, 105.8018),
    "cầu giấy": (21.0288, 105.8022),

    # Other venues
    "khu vui chơi nhà chen - ước mơ xanh": (21.0378, 105.8321),
    "nhà chen": (21.0378, 105.8321),
}


# H3 Resolution Guide (Uber's approach):
# - Resolution 7: ~254 km² per hex (country/regional level)
# - Resolution 8: ~33.9 km² per hex (metro area level) ← CURRENT
# - Resolution 9: ~4.9 km² per hex (city/district level)
# - Resolution 10: ~0.71 km² per hex (neighborhood level)
# - Resolution 11: ~0.10 km² per hex (block level)
# - Resolution 12: ~0.73 km² per hex (very fine grain)
DEFAULT_H3_RESOLUTION = 8  # Metro area level for Vietnam


def lat_lon_to_h3(lat: float, lon: float, resolution: int = DEFAULT_H3_RESOLUTION) -> str:
    """
    Convert latitude/longitude to H3 index (Uber's hexagonal spatial index).

    Args:
        lat: Latitude
        lon: Longitude
        resolution: H3 resolution (0-15), default 9 for city-level analysis

    Returns:
        H3 index as hex string

    Example:
        >>> lat_lon_to_h3(21.0285, 105.8527, 9)
        '8928308280fffff'
    """
    if lat is None or lon is None:
        return ""
    return h3.latlng_to_cell(lat, lon, resolution)


def get_h3_boundary(lat: float, lon: float, resolution: int = DEFAULT_H3_RESOLUTION) -> list:
    """
    Get the boundary coordinates of an H3 cell.

    Returns list of [lat, lon] pairs forming the hexagon boundary.

    Example:
        >>> boundary = get_h3_boundary(21.0285, 105.8527, 9)
        >>> # Returns 7 points (6 vertices + closing point)
    """
    if lat is None or lon is None:
        return []
    h3_index = h3.latlng_to_cell(lat, lon, resolution)
    return h3.cell_to_boundary(h3_index)


def get_h3_center(lat: float, lon: float, resolution: int = DEFAULT_H3_RESOLUTION) -> tuple:
    """
    Get the center coordinates of an H3 cell.

    Returns:
        Tuple of (lat, lon) for the hex center
    """
    if lat is None or lon is None:
        return (None, None)
    h3_index = h3.latlng_to_cell(lat, lon, resolution)
    center = h3.cell_to_latlng(h3_index)
    return (center[0], center[1])


def h3_to_lat_lon(h3_index: str) -> tuple:
    """
    Convert H3 index back to center lat/lon coordinates.

    Returns:
        Tuple of (lat, lon)
    """
    if not h3_index:
        return (None, None)
    center = h3.cell_to_latlng(h3_index)
    return (center[0], center[1])


class VenueGeocoder:
    """Geocode venue names to lat/long coordinates with caching."""

    def __init__(self, cache_path: Optional[Path] = None):
        self.geolocator = Nominatim(user_agent="demand-spike-detector-v0")
        self.cache: dict[str, tuple[float, float]] = {}
        self.cache_path = cache_path
        self.request_count = 0

        if cache_path and cache_path.exists():
            self._load_cache()

    def _load_cache(self) -> None:
        """Load geocoding cache from file."""
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                self.cache = json.load(f)
            print(f"Loaded {len(self.cache)} cached coordinates")
        except (json.JSONDecodeError, IOError):
            self.cache = {}

    def _save_cache(self) -> None:
        """Save geocoding cache to file."""
        if self.cache_path:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
            print(f"Saved {len(self.cache)} coordinates to cache")

    def _normalize(self, text: str) -> str:
        """Normalize venue name for matching."""
        return text.lower().strip()

    def geocode(self, venue: str) -> tuple[Optional[float], Optional[float]]:
        """
        Geocode a venue name to lat/long.

        Returns:
            Tuple of (latitude, longitude) or (None, None) if not found.
        """
        if not venue or not venue.strip():
            return None, None

        normalized = self._normalize(venue)
        original_venue = venue.strip()

        # Check cache first
        if normalized in self.cache:
            return tuple(self.cache[normalized])

        # Check hardcoded coordinates (exact match first, then partial match)
        for key, coords in VENUE_COORDINATES.items():
            if key in normalized or normalized in key:
                self.cache[normalized] = coords
                return coords

        # Handle "tại" prefix - common in Vietnamese event descriptions
        if original_venue.lower().startswith("tại "):
            venue_without_prefix = original_venue[4:].strip()  # Remove "tại " prefix
            normalized_no_prefix = self._normalize(venue_without_prefix)

            # Check cache with no prefix
            if normalized_no_prefix in self.cache:
                return tuple(self.cache[normalized_no_prefix])

            # Check hardcoded with no prefix
            for key, coords in VENUE_COORDINATES.items():
                if key in normalized_no_prefix or normalized_no_prefix in key:
                    self.cache[normalized] = coords
                    return coords

            # Try to geocode with no prefix
            lat, lon = self._geocode_api(venue_without_prefix)
            if lat is not None:
                self.cache[normalized] = (lat, lon)
                return lat, lon

        # Try Nominatim geocoding with retries
        lat, lon = self._geocode_api(venue)
        if lat is not None:
            return lat, lon

        return None, None

    def _geocode_api(self, search_term: str) -> tuple[Optional[float], Optional[float]]:
        """Call Nominatim API to geocode a search term."""
        for attempt in range(3):
            try:
                self.request_count += 1
                # Add "Hanoi, Vietnam" to improve accuracy for Vietnamese venues
                location = self.geolocator.geocode(f"{search_term}, Hanoi, Vietnam")

                if location:
                    return (location.latitude, location.longitude)

                # Try without Hanoi suffix
                location = self.geolocator.geocode(search_term)
                if location:
                    return (location.latitude, location.longitude)

                return None, None

            except (GeocoderTimedOut, GeocoderServiceError) as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)  # Exponential backoff
                continue
            except Exception:
                break

        return None, None

    def close(self) -> None:
        """Save cache and close geolocator."""
        self._save_cache()


def geocode_csv(
    input_path: Path,
    output_path: Path,
    cache_path: Optional[Path] = None,
    h3_resolution: int = DEFAULT_H3_RESOLUTION,
) -> dict:
    """
    Geocode venues in CSV and save with lat/long columns and H3 index.

    Args:
        input_path: Path to input event.csv
        output_path: Path to output file
        cache_path: Optional path for geocoding cache
        h3_resolution: H3 resolution (0-15), default 9 for city-level analysis

    Returns:
        Statistics about geocoding results
    """
    geocoder = VenueGeocoder(cache_path)

    results = {
        "total": 0,
        "geocoded": 0,
        "missing": 0,
        "unique_venues": set(),
        "failed_venues": set(),
        "h3_resolution": h3_resolution,
        "h3_stats": {},  # Count events per H3 cell
    }

    rows = []

    # Read CSV
    with open(input_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    results["total"] = len(rows)

    # Geocode each row and compute H3 index
    for row in rows:
        venue = row.get("venue", "").strip()

        if venue:
            results["unique_venues"].add(venue)
            lat, lon = geocoder.geocode(venue)

            if lat is not None and lon is not None:
                row["latitude"] = f"{lat:.6f}"
                row["longitude"] = f"{lon:.6f}"
                # Compute H3 index (Uber's hexagonal spatial indexing)
                row["h3_index"] = lat_lon_to_h3(lat, lon, h3_resolution)
                # Track H3 cell distribution
                h3_cell = row["h3_index"]
                results["h3_stats"][h3_cell] = results["h3_stats"].get(h3_cell, 0) + 1
                results["geocoded"] += 1
            else:
                row["latitude"] = ""
                row["longitude"] = ""
                row["h3_index"] = ""
                results["failed_venues"].add(venue)
                results["missing"] += 1
        else:
            row["latitude"] = ""
            row["longitude"] = ""
            row["h3_index"] = ""

    # Write output CSV
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Save cache
    geocoder.close()

    # Print summary
    print(f"\n{'='*50}")
    print("GEOCODING SUMMARY")
    print(f"{'='*50}")
    print(f"Total rows processed: {results['total']}")
    print(f"Successfully geocoded: {results['geocoded']}")
    print(f"Missing coordinates: {results['missing']}")
    print(f"Unique venues found: {len(results['unique_venues'])}")

    if results["failed_venues"]:
        print(f"\nVenues that couldn't be geocoded:")
        for venue in sorted(results["failed_venues"]):
            print(f"  - {venue}")

    return results


def geocode_xlsx(
    input_path: Path,
    output_path: Path,
    cache_path: Optional[Path] = None,
    h3_resolution: int = DEFAULT_H3_RESOLUTION,
) -> dict:
    """
    Geocode venues in Excel file and save with lat/long columns and H3 index.

    Args:
        input_path: Path to input event.xlsx
        output_path: Path to output file
        cache_path: Optional path for geocoding cache
        h3_resolution: H3 resolution (0-15), default 9 for city-level analysis

    Returns:
        Statistics about geocoding results
    """
    from openpyxl import load_workbook

    geocoder = VenueGeocoder(cache_path)

    results = {
        "total": 0,
        "geocoded": 0,
        "missing": 0,
        "unique_venues": set(),
        "failed_venues": set(),
        "h3_resolution": h3_resolution,
        "h3_stats": {},
    }

    # Load workbook - process all sheets
    wb = load_workbook(input_path)

    for ws in wb.worksheets:
        # Find column indices
        headers = [cell.value for cell in ws[1]]

        try:
            venue_idx = headers.index("venue")
            lat_idx = headers.index("latitude")
            lon_idx = headers.index("longitude")
            h3_idx = headers.index("h3_index")
        except ValueError as e:
            print(f"Sheet '{ws.title}': Missing required column: {e}")
            continue

        # Geocode each row
        for row_idx in range(2, ws.max_row + 1):
            venue = ws.cell(row=row_idx, column=venue_idx + 1).value

            results["total"] += 1

            if venue and str(venue).strip():
                results["unique_venues"].add(str(venue))
                lat, lon = geocoder.geocode(str(venue))

                if lat is not None and lon is not None:
                    ws.cell(row=row_idx, column=lat_idx + 1).value = round(lat, 6)
                    ws.cell(row=row_idx, column=lon_idx + 1).value = round(lon, 6)
                    # Compute H3 index
                    h3_cell = lat_lon_to_h3(lat, lon, h3_resolution)
                    ws.cell(row=row_idx, column=h3_idx + 1).value = h3_cell
                    results["h3_stats"][h3_cell] = results["h3_stats"].get(h3_cell, 0) + 1
                    results["geocoded"] += 1
                else:
                    ws.cell(row=row_idx, column=lat_idx + 1).value = None
                    ws.cell(row=row_idx, column=lon_idx + 1).value = None
                    ws.cell(row=row_idx, column=h3_idx + 1).value = None
                    results["failed_venues"].add(str(venue))
                    results["missing"] += 1
            else:
                ws.cell(row=row_idx, column=lat_idx + 1).value = None
                ws.cell(row=row_idx, column=lon_idx + 1).value = None
                ws.cell(row=row_idx, column=h3_idx + 1).value = None

    # Save workbook
    wb.save(output_path)
    geocoder.close()

    # Print summary
    print(f"\n{'='*50}")
    print("GEOCODING SUMMARY")
    print(f"{'='*50}")
    print(f"Total rows processed: {results['total']}")
    print(f"Successfully geocoded: {results['geocoded']}")
    print(f"Missing coordinates: {results['missing']}")
    print(f"Unique venues found: {len(results['unique_venues'])}")
    print(f"H3 Resolution: {results['h3_resolution']}")
    print(f"Unique H3 cells: {len(results['h3_stats'])}")

    if results["failed_venues"]:
        print(f"\nVenues that couldn't be geocoded:")
        for venue in sorted(results["failed_venues"]):
            print(f"  - {venue}")

    return results


if __name__ == "__main__":
    import sys
    import os

    # Get project root directory (parent of src)
    script_dir = Path(__file__).resolve().parent  # src/geocode_venues.py
    project_root = script_dir.parent  # project root
    data_dir = project_root / "data"
    cache_path = data_dir / ".geocode_cache.json"

    csv_path = data_dir / "event.csv"
    xlsx_path = data_dir / "event.xlsx"

    print("Starting venue geocoding...")
    print(f"Input CSV: {csv_path}")
    print(f"Cache: {cache_path}")

    if csv_path.exists():
        # Geocode CSV
        print("\n" + "="*50)
        print("Processing event.csv")
        print("="*50)
        results = geocode_csv(csv_path, csv_path, cache_path)

    if xlsx_path.exists():
        # Geocode Excel
        print("\n" + "="*50)
        print("Processing event.xlsx")
        print("="*50)
        results = geocode_xlsx(xlsx_path, xlsx_path, cache_path)

    print("\nGeocoding complete!")
