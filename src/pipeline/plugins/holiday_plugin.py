"""
Holiday Factor Plugin
=====================

Plugin for collecting holiday data from static calendar files.
Holidays affect demand patterns significantly (especially Tet in Vietnam).
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List
import h3

from ..base import BaseFactorPlugin, FactorType
from ..registry import PluginRegistry


@PluginRegistry.register("holiday")
class HolidayFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting holidays from static CSV file.

    Vietnam has several major holidays:
    - Tết Nguyên Đán (Lunar New Year) - most impactful
    - Tết Dương Lịch (New Year)
    - Giỗ Tổ Hùng Vương (Hung Kings' Commemoration Day)
    - Quốc Khánh (Independence Day)
    - etc.
    """

    factor_type = FactorType.HOLIDAY
    factor_name = "holiday"
    schedule = "0 0 1 1 *"  # Load at start of year + on-demand

    # Tet phase definitions (relative to Tet date)
    TET_PHASES = {
        'pre_tet': (-21, -8),    # 21-8 days before Tet (preparation)
        'tet_week': (-7, 7),     # 7 days before and after Tet
        'post_tet': (8, 21),     # 8-21 days after Tet (return to normal)
        'normal': None,          # Normal days
    }

    # Tet impact by phase
    TET_IMPACT_MAP = {
        'pre_tet': 0.6,     # Rush to travel, high demand
        'tet_week': 0.9,    # Peak holiday, different demand pattern
        'post_tet': 0.4,    # Return to normal
        'normal': 0.0,
    }

    # Holiday impact values
    HOLIDAY_IMPACT_MAP = {
        # Major holidays
        'tết nguyên đán': 0.9,
        'tết': 0.9,
        'tet': 0.9,
        'lunar new year': 0.9,

        # Other major holidays
        'tết dương lịch': 0.5,
        'new year': 0.5,
        'giỗ tổ hùng vương': 0.6,
        'hung kings': 0.6,

        # National holidays
        'quốc khánh': 0.7,
        'independence day': 0.7,

        # Other observances
        'giờ tr': 0.3,
        'valentine': 0.3,
        'christmas': 0.2,

        # Default
        'default': 0.0,
    }

    def __init__(self, config: Dict):
        super().__init__(config)
        self.holiday_file = config.get('holiday_file', 'data/holidays.csv')
        self.tet_date = config.get('tet_date', '2025-01-29')  # Tet 2025
        self.impact_radius = config.get('impact_radius', 50)  # Whole city

        # Parse Tet date
        try:
            self.tet_date = datetime.strptime(self.tet_date, '%Y-%m-%d')
        except:
            # Default: Tet 2025
            self.tet_date = datetime(2025, 1, 29)

    def fetch(self) -> pd.DataFrame:
        """Fetch holiday data from CSV file."""
        try:
            df = pd.read_csv(self.holiday_file)
            df['date'] = pd.to_datetime(df['date'])
            return df
        except FileNotFoundError:
            print(f"[Holiday] File not found: {self.holiday_file}")
            return self._create_default_holidays()
        except Exception as e:
            print(f"[Holiday] Error reading file: {e}")
            return self._create_default_holidays()

    def _create_default_holidays(self) -> pd.DataFrame:
        """Create default holidays for Vietnam 2024-2025."""
        holidays = [
            # 2024 Holidays
            {'date': '2024-01-01', 'holiday_name': 'Tết Dương Lịch', 'is_holiday': True},
            {'date': '2024-02-10', 'holiday_name': 'Tết Nguyên Đán 2024', 'is_holiday': True},
            {'date': '2024-02-11', 'holiday_name': 'Tết Nguyên Đán 2024', 'is_holiday': True},
            {'date': '2024-02-12', 'holiday_name': 'Tết Nguyên Đán 2024', 'is_holiday': True},
            {'date': '2024-04-18', 'holiday_name': 'Giỗ Tổ Hùng Vương', 'is_holiday': True},
            {'date': '2024-04-30', 'holiday_name': 'Ngày Thống nhất', 'is_holiday': True},
            {'date': '2024-05-01', 'holiday_name': 'Ngày Lao động', 'is_holiday': True},
            {'date': '2024-09-02', 'holiday_name': 'Quốc Khánh', 'is_holiday': True},
            {'date': '2024-09-02', 'holiday_name': 'Quốc Khánh (nghỉ bù)', 'is_holiday': True},

            # 2025 Holidays
            {'date': '2025-01-01', 'holiday_name': 'Tết Dương Lịch', 'is_holiday': True},
            {'date': '2025-01-29', 'holiday_name': 'Tết Nguyên Đán 2025', 'is_holiday': True},
            {'date': '2025-01-30', 'holiday_name': 'Tết Nguyên Đán 2025', 'is_holiday': True},
            {'date': '2025-01-31', 'holiday_name': 'Tết Nguyên Đán 2025', 'is_holiday': True},
            {'date': '2025-04-07', 'holiday_name': 'Giỗ Tổ Hùng Vương', 'is_holiday': True},
            {'date': '2025-04-30', 'holiday_name': 'Ngày Thống nhất', 'is_holiday': True},
            {'date': '2025-05-01', 'holiday_name': 'Ngày Lao động', 'is_holiday': True},
            {'date': '2025-09-02', 'holiday_name': 'Quốc Khánh', 'is_holiday': True},
        ]

        df = pd.DataFrame(holidays)
        df['date'] = pd.to_datetime(df['date'])
        return df

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform holidays -> impact scores with Tet phase."""
        if df.empty:
            return df

        df = df.copy()

        # Calculate Tet phase
        def get_tet_phase(date: datetime) -> str:
            if date.year in [2024, 2025]:
                # Find Tet date for this year
                tet_dates = {
                    2024: datetime(2024, 2, 10),
                    2025: datetime(2025, 1, 29),
                }
                tet_date = tet_dates.get(date.year, self.tet_date)
                days_from_tet = (date - tet_date).days

                # Check each phase (skip 'normal' which has None value)
                for phase, bounds in self.TET_PHASES.items():
                    if phase == 'normal' or bounds is None:
                        continue
                    start, end = bounds
                    if start <= days_from_tet <= end:
                        return phase

            return 'normal'

        df['tet_phase'] = df['date'].apply(get_tet_phase)

        # Calculate impact based on holiday_name or tet_phase
        def calculate_impact(row) -> float:
            # If in Tet period, use Tet phase impact
            if row['tet_phase'] != 'normal':
                return self.TET_IMPACT_MAP.get(row['tet_phase'], 0.5)

            # Otherwise, look up holiday name
            holiday_key = str(row.get('holiday_name', '')).lower()
            return self.HOLIDAY_IMPACT_MAP.get(holiday_key, self.HOLIDAY_IMPACT_MAP['default'])

        df['value'] = df.apply(calculate_impact, axis=1)

        # Severity
        df['severity'] = df['value'].apply(
            lambda x: 'HIGH' if x >= 0.7 else 'MEDIUM' if x >= 0.3 else 'LOW'
        )

        # Metadata
        df['metadata'] = df.apply(
            lambda r: {
                'holiday_name': r.get('holiday_name'),
                'tet_phase': r['tet_phase'],
                'is_holiday': r.get('is_holiday', True)
            },
            axis=1
        )

        df['datetime'] = df['date']

        return df

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Holidays affect the entire city uniformly.

        Creates full city coverage for each holiday.
        """
        df = df.copy()

        # Get city center hex (Hanoi)
        center = (21.0285, 105.8542)
        center_hex = h3.latlng_to_cell(center[0], center[1], 9)
        hex_ids = list(h3.grid_disk(center_hex, self.impact_radius))

        # Expand: each holiday -> N rows (1 per hex_id)
        expanded_rows = []
        for _, row in df.iterrows():
            for hex_id in hex_ids:
                new_row = row.copy()
                new_row['hex_id'] = hex_id
                expanded_rows.append(new_row)

        if not expanded_rows:
            return pd.DataFrame()

        return pd.DataFrame(expanded_rows)
