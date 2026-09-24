"""
NCHMF Spatial Lookup System
===========================

Pre-computed lookup dictionaries for O(1) hexagon → district → zone mapping.
No geometric calculations at runtime.

Design:
1. h3_to_district: Static lookup, pre-computed at startup
2. district_to_zone: Static lookup, pre-computed at startup
3. nchmf_zone_warnings: Dynamic cache, updated on NCHMF crawl
"""

import pandas as pd
import h3
from datetime import datetime
from typing import Dict, Optional, List
import json


# ============================================================================
# SECTION 1: STATIC LOOKUP TABLES
# ============================================================================

# Pre-computed H3 → District mapping
# These are pre-computed offline and loaded at startup
# Format: {h3_index: district_name}

H3_TO_DISTRICT: Dict[str, str] = {}

# Pre-computed District → Zone mapping
# Zones are NCHMF warning regions
# Format: {district_name: zone_name}

DISTRICT_TO_ZONE: Dict[str, str] = {
    # Nội thành (Inner city - highest priority)
    'HoanKiem': 'NoiThanh',
    'HaiBaTrung': 'NoiThanh',
    'DongDa': 'NoiThanh',
    'BaDinh': 'NoiThanh',
    'TayHo': 'NoiThanh',
    'CauGiay': 'NoiThanh',

    # Phía Tây (Western - hilly, flooding risk)
    'ThanhXuan': 'PhiaTay',
    'HoangMai': 'PhiaTay',
    'NamTuLiem': 'PhiaTay',
    'BacTuLiem': 'PhiaTay',

    # Phía Bắc (Northern)
    'LongBien': 'PhiaBac',
    'GiaLam': 'PhiaBac',
    'SocSon': 'PhiaBac',
    'DongAnh': 'PhiaBac',

    # Phía Nam (Southern)
    'ThanhTri': 'PhiaNam',
    'HoaiDuc': 'PhiaNam',
    'TuLiEm': 'PhiaNam',
    'SonTay': 'PhiaNam',

    # Ngoại thành (Outer city)
    'BaVi': 'NgoaiThanh',
    'PhuTho': 'NgoaiThanh',
    'HungYen': 'NgoaiThanh',
    'VinhPhuc': 'NgoaiThanh',
    'BacNinh': 'NgoaiThanh',
}

# Zone definitions for reference
ZONES = {
    'NoiThanh': {
        'priority': 1,
        'description': 'Nội thành - 6 quận trung tâm',
        'districts': ['HoanKiem', 'HaiBaTrung', 'DongDa', 'BaDinh', 'TayHo', 'CauGiay'],
    },
    'PhiaTay': {
        'priority': 2,
        'description': 'Khu vực phía Tây - đồi núi, ngập úng',
        'districts': ['ThanhXuan', 'HoangMai', 'NamTuLiem', 'BacTuLiem'],
    },
    'PhiaBac': {
        'priority': 3,
        'description': 'Khu vực phía Bắc - sông Hồng',
        'districts': ['LongBien', 'GiaLam', 'SocSon', 'DongAnh'],
    },
    'PhiaNam': {
        'priority': 4,
        'description': 'Khu vực phía Nam',
        'districts': ['ThanhTri', 'HoaiDuc', 'TuLiEm', 'SonTay'],
    },
    'NgoaiThanh': {
        'priority': 5,
        'description': 'Ngoại thành - huyện',
        'districts': ['BaVi', 'PhuTho', 'HungYen', 'VinhPhuc', 'BacNinh'],
    },
}


# ============================================================================
# SECTION 2: STATIC LOOKUP GENERATION
# ============================================================================

def generate_h3_to_district_map(resolution: int = 8) -> Dict[str, str]:
    """
    Generate H3 → District mapping using district boundaries.

    This runs ONCE at startup or during initialization.
    Not during real-time processing.
    """
    # Hanoi district boundaries (simplified polygons)
    HANOI_DISTRICTS = {
        'HoanKiem': [(21.020, 105.845), (21.035, 105.860)],
        'HaiBaTrung': [(21.005, 105.840), (21.020, 105.855)],
        'DongDa': [(21.005, 105.825), (21.025, 105.840)],
        'BaDinh': [(21.030, 105.815), (21.045, 105.840)],
        'TayHo': [(21.045, 105.770), (21.065, 105.800)],
        'CauGiay': [(21.025, 105.775), (21.040, 105.795)],
        'ThanhXuan': [(21.000, 105.800), (21.015, 105.820)],
        'HoangMai': [(20.975, 105.835), (21.005, 105.865)],
        'NamTuLiem': [(21.015, 105.755), (21.035, 105.775)],
        'BacTuLiem': [(21.035, 105.755), (21.055, 105.780)],
        'LongBien': [(21.040, 105.870), (21.080, 105.920)],
        'GiaLam': [(21.050, 105.920), (21.120, 105.980)],
        'ThanhTri': [(20.950, 105.815), (20.985, 105.850)],
    }

    h3_to_district = {}

    for district, (sw, ne) in HANOI_DISTRICTS.items():
        # Generate hexagons covering this district
        lat = sw[0]
        while lat <= ne[0]:
            lng = sw[1]
            while lng <= ne[1]:
                try:
                    hex_id = h3.latlng_to_cell(lat, lng, resolution)
                    h3_to_district[hex_id] = district
                except:
                    pass
                lng += 0.005
            lat += 0.005

    return h3_to_district


def initialize_static_lookups():
    """
    Initialize all static lookup tables at startup.
    Call this once when the application starts.
    """
    global H3_TO_DISTRICT

    print("Initializing static lookups...")

    # Generate H3 → District mapping
    H3_TO_DISTRICT = generate_h3_to_district_map(8)
    print(f"  H3 → District: {len(H3_TO_DISTRICT)} mappings")

    # Validate all districts have zones
    unmapped = []
    for district in set(H3_TO_DISTRICT.values()):
        if district not in DISTRICT_TO_ZONE:
            unmapped.append(district)

    if unmapped:
        print(f"  WARNING: Unmapped districts: {unmapped}")

    print("Static lookups initialized.")


# ============================================================================
# SECTION 3: NCHMF ZONE WARNING CACHE
# ============================================================================

class NCHMFZoneWarningCache:
    """
    Cache for NCHMF zone warnings.

    Updated when NCHMF is crawled.
    Queried at O(1) during hexagon processing.
    """

    def __init__(self):
        self._cache: Dict[str, Dict] = {
            'NoiThanh': {'storm': 0, 'heavy_rain': 0, 'flood': 0, 'timestamp': None},
            'PhiaTay': {'storm': 0, 'heavy_rain': 0, 'flood': 0, 'timestamp': None},
            'PhiaBac': {'storm': 0, 'heavy_rain': 0, 'flood': 0, 'timestamp': None},
            'PhiaNam': {'storm': 0, 'heavy_rain': 0, 'flood': 0, 'timestamp': None},
            'NgoaiThanh': {'storm': 0, 'heavy_rain': 0, 'flood': 0, 'timestamp': None},
        }
        self._last_update: Optional[datetime] = None

    def update(self, zone_warnings: Dict[str, Dict]):
        """
        Update cache with new zone warnings from NCHMF crawl.

        Args:
            zone_warnings: {
                'NoiThanh': {'storm': 1.0, 'heavy_rain': 0.8},
                'PhiaTay': {'storm': 0.5, 'heavy_rain': 0.9},
                ...
            }
        """
        for zone, warnings in zone_warnings.items():
            if zone in self._cache:
                self._cache[zone].update(warnings)
                self._cache[zone]['timestamp'] = datetime.now()

        self._last_update = datetime.now()
        print(f"NCHMF zone cache updated at {self._last_update}")

    def get_zone_warning(self, zone: str) -> Dict:
        """Get warning for a specific zone."""
        return self._cache.get(zone, {'storm': 0, 'heavy_rain': 0, 'flood': 0})

    def get_age_seconds(self) -> float:
        """Get age of cache in seconds."""
        if self._last_update is None:
            return float('inf')
        return (datetime.now() - self._last_update).total_seconds()

    def is_stale(self, threshold_seconds: float = 7200) -> bool:
        """Check if cache is stale (default: 2 hours)."""
        return self.get_age_seconds() > threshold_seconds


# Global cache instance
nchmf_zone_cache = NCHMFZoneWarningCache()


# ============================================================================
# SECTION 4: O(1) LOOKUP FUNCTIONS
# ============================================================================

def get_district_for_hex(h3_index: str) -> Optional[str]:
    """
    O(1) lookup: Get district name for a hexagon.

    Uses pre-computed static mapping.
    """
    return H3_TO_DISTRICT.get(h3_index)


def get_zone_for_district(district: str) -> Optional[str]:
    """
    O(1) lookup: Get zone name for a district.

    Uses static district_to_zone mapping.
    """
    return DISTRICT_TO_ZONE.get(district)


def get_zone_for_hex(h3_index: str) -> Optional[str]:
    """
    O(1) lookup: Get zone for a hexagon (chained lookup).

    h3_index → district → zone
    """
    district = get_district_for_hex(h3_index)
    if district is None:
        return None
    return get_zone_for_district(district)


def get_nchmf_warning_for_hex(h3_index: str) -> Dict:
    """
    O(1) lookup: Get NCHMF warning for a hexagon.

    h3_index → zone → NCHMF warning

    Returns dict with:
    - storm: probability of thunderstorm (0-1)
    - heavy_rain: probability of heavy rain (0-1)
    - flood: probability of flooding (0-1)
    """
    zone = get_zone_for_hex(h3_index)
    if zone is None:
        return {'storm': 0, 'heavy_rain': 0, 'flood': 0}

    return nchmf_zone_cache.get_zone_warning(zone)


def get_all_zones() -> List[str]:
    """Get list of all zone names."""
    return list(ZONES.keys())


def get_zone_districts(zone: str) -> List[str]:
    """Get list of districts in a zone."""
    if zone in ZONES:
        return ZONES[zone]['districts']
    return []


# ============================================================================
# SECTION 5: NCHMF PARSING & NORMALIZATION
# ============================================================================

def parse_nchmf_warning(text: str) -> Dict[str, Dict]:
    """
    Parse NCHMF warning text and normalize to zone-level warnings.

    Input: "Cảnh báo giông lốc, sét, mưa đá khu vực nội thành Hà Nội"
    Output: {'NoiThanh': {'storm': 1.0, 'heavy_rain': 0.5}}

    Zone detection keywords:
    - Nội thành, nội thành → NoiThanh
    - Phía tây, phía Tây → PhiaTay
    - Phía bắc, phía Bắc → PhiaBac
    - Phía nam, phía Nam → PhiaNam
    - Ngoại thành, huyện → NgoaiThanh
    """
    text_lower = text.lower()

    zone_warnings = {}

    # Detect which zones are mentioned
    zone_keywords = {
        'NoiThanh': ['nội thành', 'nội thành', 'trung tâm'],
        'PhiaTay': ['phía tây', 'phía Tây', 'tây nam', ' tây bắc'],
        'PhiaBac': ['phía bắc', 'phía Bắc', 'bắc từ liêm', 'nam từ liêm'],
        'PhiaNam': ['phía nam', 'phía Nam', 'nam từ'],
        'NgoaiThanh': ['ngoại thành', 'huyện', 'tỉnh'],
    }

    # Detect warning types
    warning_types = {
        'storm': ['giông', 'lốc', 'sét', 'mưa đá', 'bão'],
        'heavy_rain': ['mưa to', 'mưa lớn', 'ngập'],
        'flood': ['ngập úng', 'lũ'],
    }

    mentioned_zones = set()
    detected_warnings = {}

    # Find zones
    for zone, keywords in zone_keywords.items():
        for kw in keywords:
            if kw in text_lower:
                mentioned_zones.add(zone)
                break

    # If no zone mentioned, apply to all
    if not mentioned_zones:
        mentioned_zones = set(ZONES.keys())

    # Find warning types
    for warning_type, keywords in warning_types.items():
        for kw in keywords:
            if kw in text_lower:
                detected_warnings[warning_type] = 1.0
                break
        else:
            detected_warnings[warning_type] = 0.0

    # Assign warnings to zones
    for zone in mentioned_zones:
        zone_warnings[zone] = detected_warnings.copy()

    return zone_warnings


# ============================================================================
# SECTION 6: INTEGRATION WITH SPATIAL ENSEMBLE
# ============================================================================

def get_nchmf_for_hex(h3_index: str) -> Dict:
    """
    Get NCHMF data for a hexagon.

    This is the O(1) lookup function used in the ensemble pipeline.

    Returns:
        {
            'zone': 'NoiThanh',
            'district': 'CauGiay',
            'storm_prob': 0.9,
            'heavy_rain_prob': 0.5,
            'flood_prob': 0.3,
            'has_nchmf_data': True,
            'data_age_seconds': 1800,
        }
    """
    zone = get_zone_for_hex(h3_index)
    district = get_district_for_hex(h3_index)
    warning = nchmf_zone_cache.get_zone_warning(zone or 'Unknown')

    return {
        'zone': zone,
        'district': district,
        'storm_prob': warning.get('storm', 0),
        'heavy_rain_prob': warning.get('heavy_rain', 0),
        'flood_prob': warning.get('flood', 0),
        'has_nchmf_data': zone is not None,
        'data_age_seconds': nchmf_zone_cache.get_age_seconds(),
    }


def demonstrate_lookup_chain():
    """
    Demonstrate the O(1) lookup chain.
    """
    print("=" * 70)
    print("NCHMF SPATIAL LOOKUP DEMO")
    print("=" * 70)
    print()

    # Initialize lookups
    initialize_static_lookups()
    print()

    # Sample hexagons
    sample_hexes = list(H3_TO_DISTRICT.items())[:5]

    print("Lookup Chain Demo:")
    for hex_id, district in sample_hexes:
        zone = get_zone_for_district(district)
        nchmf = nchmf_zone_cache.get_zone_warning(zone)

        print(f"Hex: {hex_id}")
        print(f"  → District: {district}")
        print(f"  → Zone: {zone}")
        print(f"  → NCHMF Warning: {nchmf}")
        print()

    # Demonstrate NCHMF parsing
    print("-" * 70)
    print("NCHMF Warning Parsing Demo:")
    print("-" * 70)

    test_warnings = [
        "Cảnh báo giông lốc, sét khu vực nội thành Hà Nội",
        "Dự báo mưa to, ngập úng khu vực phía Tây",
        "Cảnh báo bão cấp 5 toàn khu vực Hà Nội",
    ]

    for warning in test_warnings:
        parsed = parse_nchmf_warning(warning)
        print(f"Input: {warning}")
        print(f"Output: {parsed}")
        print()


if __name__ == '__main__':
    demonstrate_lookup_chain()
