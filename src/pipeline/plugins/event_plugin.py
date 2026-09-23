"""
Event Factor Plugin
==================

Plugin for collecting event data from manual CSV files.
Maps events to H3 hex locations based on venue coordinates.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any
import h3

from ..base import BaseFactorPlugin, FactorType
from ..registry import PluginRegistry


@PluginRegistry.register("event")
class EventFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting events from manual CSV files.

    Event data can be collected from:
    - Manual CSV file
    - Ticketbox API (if available)
    - Google Sheets
    - Other event platforms
    """

    factor_type = FactorType.EVENT
    factor_name = "event"
    schedule = "0 23 * * *"  # Daily at 23:00

    # Event type -> demand impact mapping
    EVENT_IMPACT_MAP = {
        'concert': 1.0,
        'music': 0.9,
        'festival': 0.9,
        'football': 0.8,
        'sports': 0.7,
        'match': 0.7,
        'conference': 0.5,
        'exhibition': 0.4,
        'seminar': 0.3,
        'workshop': 0.3,
        'default': 0.5,
    }

    # Known venue coordinates (Hanoi)
    # Format: venue_key -> (latitude, longitude)
    VENUE_COORDS = {
        # Stadiums
        'svd_my_dinh': (21.0285, 105.8195),      # Sân vận động Mỹ Đình
        'my_dinh': (21.0285, 105.8195),
        'thong_nhat': (10.7795, 106.7312),        # Thống Nhất Stadium
        'rong': (10.7950, 106.7100),              # Thống Nhất / Rạch Long
        'quan_khuc': (21.0450, 105.7450),         # Quần Khúc
        'hadilao': (21.0580, 105.7680),           # Cầu Giấy

        # Concert venues
        'arena': (21.0065, 105.8195),             # Royal City
        '的歌剧院': (21.0065, 105.8195),           # Nhà hát lớn
        ' national': (21.0280, 105.8500),         # Opera House
        'cazier': (21.0150, 105.8400),            # Cung Văn hóa

        # Exhibition centers
        'ice': (21.0150, 105.7850),               # ICE Hanoi
        ' friendship': (21.0380, 105.8350),       # Cung Hữu nghị
        'vitc': (21.0550, 105.7900),              # Trung tâm Hội chợ

        # Universities
        'đhqg': (21.0380, 105.7800),             # ĐH Quốc gia
        'bkhn': (21.0120, 105.8400),              # ĐH Bách khoa
        'hnue': (21.0280, 105.8200),              # ĐH Sư phạm

        # City center (default)
        'hoan_kiem': (21.0280, 105.8500),
        'old_quarter': (21.0340, 105.8500),
    }

    def __init__(self, config: Dict):
        super().__init__(config)
        self.csv_path = config.get('csv_path', 'data/events.csv')
        self.venue_coords = config.get('venue_coords', self.VENUE_COORDS)
        self.impact_radius = config.get('impact_radius', 3)  # Hexes

    def fetch(self) -> pd.DataFrame:
        """Fetch events from CSV file."""
        try:
            df = pd.read_csv(self.csv_path)
            return df
        except FileNotFoundError:
            print(f"[Event] CSV file not found: {self.csv_path}")
            return pd.DataFrame()
        except Exception as e:
            print(f"[Event] Error reading CSV: {e}")
            return pd.DataFrame()

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform events -> demand impact scores."""
        if df.empty:
            return df

        df = df.copy()

        # Normalize columns
        df['start_time'] = pd.to_datetime(df.get('start_time', df.get('datetime')))
        df['end_time'] = pd.to_datetime(df.get('end_time', df.get('start_time') + timedelta(hours=3)))

        # Calculate duration in 30-min slots
        df['duration_slots'] = ((df['end_time'] - df['start_time']).dt.total_seconds() / 1800).astype(int)

        # Map event type -> impact
        df['event_type'] = df.get('event_type', 'default').str.lower().str.strip()
        df['value'] = df['event_type'].map(self.EVENT_IMPACT_MAP).fillna(0.5)

        # Severity
        df['severity'] = df['value'].apply(
            lambda x: 'HIGH' if x >= 0.8 else 'MEDIUM' if x >= 0.5 else 'LOW'
        )

        # Metadata
        df['metadata'] = df.apply(
            lambda r: {
                'event_name': r.get('event_name', r.get('name', 'Unknown')),
                'venue': r.get('venue', 'Unknown'),
                'event_type': r.get('event_type')
            },
            axis=1
        )

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Map event venue -> H3 hex_ids.

        Creates time-expanded records for event duration.
        """
        if df.empty:
            return df

        df = df.copy()

        # Convert venue -> hex_id
        df['hex_ids'] = df['venue'].apply(self._venue_to_hex_ids)

        # Expand time slots: event lasts N hours -> N*2 records (30 min each)
        expanded_rows = []

        for _, row in df.iterrows():
            start = row['start_time']
            duration = max(1, row['duration_slots'])  # At least 1 slot

            for i in range(duration):
                slot_time = start + timedelta(minutes=30 * i)
                new_row = row.copy()
                new_row['datetime'] = slot_time

                # Set hex_id to the first (primary) hex
                hex_ids = row['hex_ids']
                new_row['hex_id'] = hex_ids[0] if hex_ids else None

                # For multiple hexes, expand further
                for hex_id in hex_ids[1:]:
                    extra_row = new_row.copy()
                    extra_row['hex_id'] = hex_id
                    expanded_rows.append(extra_row)

                expanded_rows.append(new_row)

        if not expanded_rows:
            return pd.DataFrame()

        return pd.DataFrame(expanded_rows)

    def _venue_to_hex_ids(self, venue: str) -> List[str]:
        """Convert venue name to H3 hex IDs."""
        if pd.isna(venue):
            return self._get_default_hex_ids()

        venue_key = venue.lower().strip().replace(' ', '_').replace('-', '_')

        # Check exact match
        if venue_key in self.venue_coords:
            lat, lng = self.venue_coords[venue_key]
            center_hex = h3.latlng_to_cell(lat, lng, 9)
            return list(h3.grid_disk(center_hex, self.impact_radius))

        # Check partial match
        for key, (lat, lng) in self.venue_coords.items():
            if key in venue_key or venue_key in key:
                center_hex = h3.latlng_to_cell(lat, lng, 9)
                return list(h3.grid_disk(center_hex, self.impact_radius))

        # Default: city center
        return self._get_default_hex_ids()

    def _get_default_hex_ids(self) -> List[str]:
        """Get default hex coverage for city center."""
        # Hanoi center
        center = (21.0285, 105.8542)
        center_hex = h3.latlng_to_cell(center[0], center[1], 9)
        return list(h3.grid_disk(center_hex, self.impact_radius))
