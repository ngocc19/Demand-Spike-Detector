"""
Flood Factor Plugin
===================

Plugin for collecting flood news from RSS feeds (VNExpress).
Extracts flood-related news and maps to H3 hex locations.
"""

import feedparser
import requests
import pandas as pd
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import h3

from ..base import BaseFactorPlugin, FactorType
from ..registry import PluginRegistry


@PluginRegistry.register("flood")
class FloodFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting flood news from RSS feeds.

    Sources:
    - VNExpress RSS: https://vnexpress.net/rss/thoi-su.rss
    - Can add more RSS sources as needed
    """

    factor_type = FactorType.FLOOD
    factor_name = "flood"
    schedule = "*/15 * * * *"  # Every 15 minutes

    # Location extraction patterns
    # NOTE: Vietnamese has 2 character sets (uppercase/lowercase)
    # so we need to list both or convert
    LOCATION_PATTERNS = [
        # Street names
        r"đường\s+([A-Za-zÀ-ỹ\s]{2,})",
        r"Đường\s+([A-Za-zÀ-ỹ\s]{2,})",
        # District numbers
        r"quận\s+(\d+)",
        r"Quận\s+(\d+)",
        # Named districts
        r"quận\s+([A-Za-zÀ-ỹ\s]{2,})",
        r"Quận\s+([A-Za-zÀ-ỹ\s]{2,})",
        # City
        r"tp\.?\s+([A-Za-zÀ-ỹ\s]{2,})",
        r"TP\.?\s+([A-Za-zÀ-ỹ\s]{2,})",
    ]

    # Severity keywords mapping
    SEVERITY_KEYWORDS = {
        'SEVERE': [
            'ngập nặng', 'ngập sâu', 'ngập trắng',
            'chìm xe', 'ùn tắc nghiêm trọng',
            'ngập úng nghiêm trọng'
        ],
        'HIGH': [
            'ngập', 'ngập lụt', 'ứ đọng',
            'tắc đường', 'ùn tắc giao thông'
        ],
        'MEDIUM': [
            'ngập nhẹ', 'xe khó đi',
            'nước ngang bánh', 'đường ngập'
        ],
        'LOW': [
            'có nước', 'ẩm ướt',
            'trời mưa'
        ],
    }

    # Known flood-prone areas in Hanoi (for geocoding fallback)
    HANOI_DISTRICT_COORDS = {
        'cầu giấy': (21.0285, 105.8010),
        'đống đa': (21.0080, 105.8250),
        'hoàng mai': (20.9870, 105.8580),
        'thanh xuân': (21.0055, 105.8120),
        'hai bà trưng': (21.0135, 105.8450),
        'ba đình': (21.0350, 105.8200),
        'tây hồ': (21.0550, 105.8100),
        'long biên': (21.0380, 105.8800),
        'hà đông': (20.9680, 105.7800),
        'hoàn kiếm': (21.0280, 105.8500),
        'nam từ liêm': (21.0180, 105.7700),
        'bắc từ liêm': (21.0480, 105.7500),
        'thường tín': (20.9380, 105.8300),
        'than hóa': (19.8000, 105.7700),
        'nghệ an': (18.6700, 105.7900),
        'hà tĩnh': (18.3400, 105.8900),
    }

    def __init__(self, config: Dict):
        super().__init__(config)
        self.rss_sources = config.get('rss_sources', [
            'https://vnexpress.net/rss/thoi-su.rss',
        ])
        self.max_entries = config.get('max_entries', 50)
        self.max_age_hours = config.get('max_age_hours', 24)
        self.geocoding_api = config.get('geocoding_api', 'nominatim')

        # Default: Hanoi center
        self.latitude = config.get('latitude', 21.0285)
        self.longitude = config.get('longitude', 105.8542)

    def fetch(self) -> pd.DataFrame:
        """Fetch flood news from RSS feeds."""
        all_entries = []

        for source_url in self.rss_sources:
            try:
                feed = feedparser.parse(source_url)

                for entry in feed.entries[:self.max_entries]:
                    # Check if entry is flood-related
                    text = entry.get('title', '') + ' ' + entry.get('summary', '')

                    if self._is_flood_related(text):
                        # Parse published date
                        try:
                            published = pd.to_datetime(entry.get('published', datetime.now()))
                        except:
                            published = datetime.now()

                        all_entries.append({
                            'title': entry.get('title', ''),
                            'summary': entry.get('summary', ''),
                            'link': entry.get('link', ''),
                            'published': published,
                            'source': source_url,
                        })
            except Exception as e:
                print(f"[Flood] Error fetching {source_url}: {e}")

        return pd.DataFrame(all_entries)

    def _is_flood_related(self, text: str) -> bool:
        """Check if text is flood-related."""
        # Convert to lowercase for matching
        text_lower = text.lower()

        # Flood-related keywords
        flood_keywords = [
            'ngập', 'ngập lụt', 'ngập nặng', 'ngập nhẹ',
            'ngập sâu', 'ngập trắng', 'ngập úng',
            'lụt', 'mưa lớn', 'nước dâng',
            'triều cường', 'thoát nước', 'ùn tắc'
        ]

        return any(kw in text_lower for kw in flood_keywords)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract locations and severity from news."""
        if df.empty:
            return df

        df = df.copy()

        # Extract locations from title
        df['locations'] = df['title'].apply(self._extract_locations)

        # Extract severity
        df['severity'] = df['title'].apply(self._extract_severity)

        # Calculate impact value from severity
        severity_map = {
            'SEVERE': 0.9,
            'HIGH': 0.7,
            'MEDIUM': 0.5,
            'LOW': 0.25,
        }
        df['value'] = df['severity'].map(severity_map)

        # Metadata
        df['metadata'] = df.apply(
            lambda r: {
                'title': r['title'],
                'link': r['link'],
                'locations': r['locations']
            },
            axis=1
        )

        df['datetime'] = df['published']

        return df

    def _extract_locations(self, text: str) -> List[str]:
        """Extract location names from text."""
        locations = []

        for pattern in self.LOCATION_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            locations.extend([m.strip() for m in matches])

        return list(set(locations))

    def _extract_severity(self, text: str) -> str:
        """Extract severity level from text."""
        text_lower = text.lower()

        for severity, keywords in self.SEVERITY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return severity

        return 'LOW'

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Map extracted locations -> H3 hex_ids via geocoding.

        Uses a combination of:
        1. Known location cache (for common districts)
        2. OSM Nominatim API (free, rate limited)
        """
        if df.empty:
            return df

        df = df.copy()

        # Resolve hex_ids for each row
        hex_ids_list = []

        for _, row in df.iterrows():
            if not row['locations']:
                # No location found -> use city-wide coverage
                hex_ids = self._get_default_hex_ids()
            else:
                hex_ids = []
                for loc in row['locations']:
                    resolved = self._geocode_location(loc)
                    if resolved:
                        hex_ids.extend(resolved)

                if not hex_ids:
                    hex_ids = self._get_default_hex_ids()

            hex_ids_list.append(list(set(hex_ids)))  # Deduplicate

        # Expand rows: 1 news -> N rows (1 per hex_id)
        expanded_rows = []
        for idx, row in df.iterrows():
            for hex_id in hex_ids_list[idx]:
                new_row = row.copy()
                new_row['hex_id'] = hex_id
                expanded_rows.append(new_row)

        if not expanded_rows:
            return pd.DataFrame()

        return pd.DataFrame(expanded_rows)

    def _geocode_location(self, location: str) -> List[str]:
        """
        Geocode location string -> H3 hex_ids.

        Uses OSM Nominatim (free, 1 req/sec limit).
        """
        # Check cache first
        location_key = location.lower().strip()
        if location_key in self.HANOI_DISTRICT_COORDS:
            lat, lng = self.HANOI_DISTRICT_COORDS[location_key]
            # Return multiple hexes around the location
            center_hex = h3.latlng_to_cell(lat, lng, 9)
            return list(h3.grid_disk(center_hex, 5))  # ~2km radius

        # Use OSM Nominatim
        try:
            url = f"https://nominatim.openstreetmap.org/search"
            params = {
                'q': f"{location}, Vietnam",
                'format': 'json',
                'limit': 1,
                'accept-language': 'vi'
            }
            headers = {'User-Agent': 'DemandSpikeDetector/1.0'}

            response = requests.get(url, params=params, headers=headers, timeout=5)
            data = response.json()

            if data:
                lat, lng = float(data[0]['lat']), float(data[0]['lon'])
                center_hex = h3.latlng_to_cell(lat, lng, 9)
                return list(h3.grid_disk(center_hex, 5))  # ~2km radius
        except Exception as e:
            print(f"[Flood] Geocoding failed for '{location}': {e}")

        return []

    def _get_default_hex_ids(self) -> List[str]:
        """Get default hex coverage for the city center."""
        center_hex = h3.latlng_to_cell(self.latitude, self.longitude, 9)
        return list(h3.grid_disk(center_hex, 10))  # ~4.6km radius
