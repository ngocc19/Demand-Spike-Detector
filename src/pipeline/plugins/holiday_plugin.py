"""
Holiday Factor Plugin
====================

Plugin for collecting holiday data.
- Solar holidays: hardcoded in code (fixed dates, same every year)
- Lunar holidays: calculated automatically using lunarcalendar library

The plugin automatically handles:
- Lunar date to Solar date conversion
- Tet phase calculation (pre_tet, tet_week, post_tet)
- Multi-year support (2026, 2027, etc.)
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import h3

try:
    from lunarcalendar import Lunar, Converter, Solar
except ImportError:
    raise ImportError("Please install lunarcalendar: pip install lunarcalendar")

from ..base import BaseFactorPlugin, FactorType
from ..registry import PluginRegistry


@PluginRegistry.register("holiday")
class HolidayFactorPlugin(BaseFactorPlugin):
    """
    Plugin for collecting holidays.

    Vietnam has two types of holidays:
    1. Solar holidays (Dương lịch) - Fixed dates, hardcoded in code
    2. Lunar holidays (Âm lịch) - Variable dates, calculated automatically

    The plugin supports multi-year: just set the year in config.
    """

    factor_type = FactorType.HOLIDAY
    factor_name = "holiday"
    schedule = "0 0 1 1 *"  # Load at start of year + on-demand

    # ============================================================
    # SOLAR HOLIDAYS - Fixed dates (same every year)
    # Format: (month, day, name, impact, category)
    # ============================================================

    SOLAR_HOLIDAYS: List[Tuple[int, int, str, float, str]] = [
        # Official holidays (based on Google Trends analysis)
        (1, 1, "Tet Duong lich", 0.5, "official"),                # Jan 1
        (4, 30, "Ngay Giai phong mien Nam", 0.7, "official"),     # Apr 30 - travel season
        (5, 1, "Ngay Quoc te Lao dong", 0.6, "official"),          # May 1 - long weekend
        (9, 2, "Ngay Quoc khanh", 0.7, "official"),               # Sep 2 - travel season

        # Christmas & Year End
        (12, 24, "Le Giang Sinh", 0.4, "cultural"),                # Dec 24
        (12, 25, "Le Giang Sinh", 0.4, "cultural"),                # Dec 25
        (12, 31, "Dem giao thua Duong lich", 0.4, "cultural"),    # Dec 31

        # Valentine & Women Day
        (2, 14, "Ngay Valentine", 0.3, "cultural"),               # Feb 14
        (3, 8, "Quoc te Phu nu", 0.4, "cultural"),               # Mar 8
        (10, 20, "Ngay Phu nu Viet Nam", 0.4, "cultural"),       # Oct 20

        # Children & Family
        (6, 1, "Quoc te thieu nhi", 0.3, "cultural"),            # Jun 1
        (6, 28, "Ngay gia dinh Viet Nam", 0.3, "cultural"),      # Jun 28

        # School & Teacher
        (9, 5, "Khai giang", 0.3, "cultural"),                    # Sep 5
        (11, 20, "Ngay Nha giao Viet Nam", 0.3, "cultural"),     # Nov 20
    ]

    # ============================================================
    # LUNAR HOLIDAYS - Variable dates (change every year)
    # Format: (lunar_month, lunar_day, name, impact, category)
    # ============================================================

    LUNAR_HOLIDAYS: List[Tuple[int, int, str, float, str]] = [
        # Tết và gần Tết (Tet Holidays)
        # Impact lower than expected because people leave cities for hometown
        (31, 12, "Dem giao thua Am lich", 0.4, "tet"),  # Đêm giao thừa âm lịch
        (1, 1, "Tet Nguyen Dan", 0.4, "tet"),       # Mùng 1 Tết
        (1, 2, "Mung 2 Tet", 0.4, "tet"),         # Mùng 2 Tết
        (1, 3, "Mung 3 Tet", 0.4, "tet"),         # Mùng 3 Tết
        (1, 4, "Mung 4 Tet", 0.4, "tet"),         # Mùng 4 Tết
        (1, 5, "Mung 5 Tet", 0.4, "tet"),         # Mùng 5 Tết

        # Các ngày lễ lớn (Major holidays)
        (3, 10, "Gio To Hung Vuong", 0.5, "traditional"),  # Mùng 10 tháng 3 âm lịch

        # Tết Nguyên Tiêu (Lantern Festival)
        (1, 15, "Tet Nguyen Tieu", 0.3, "traditional"),    # Rằm tháng Giêng

        # Lễ Phật Đản
        (4, 15, "Le Phat Dan", 0.2, "religious"),          # 15 tháng 4 âm lịch

        # Lễ Vu Lan
        (7, 15, "Le Vu Lan", 0.3, "traditional"),           # Rằm tháng 7

        # Tết Trung thu
        (8, 15, "Tet Trung thu", 0.4, "traditional"),      # 15 tháng 8 âm lịch
    ]

    # ============================================================
    # TET PHASE DEFINITIONS
    # Relative to Tet date (Mùng 1 Tết)
    # ============================================================

    TET_PHASES = {
        'pre_tet': (-21, -8),    # 21-8 days before Tet
        'tet_week': (-7, 7),     # 7 days before and after Tet
        'post_tet': (8, 21),     # 8-21 days after Tet
        'normal': None,           # Normal days (placeholder)
    }

    # ============================================================
    # IMPACT VALUES (Based on Google Trends + Industry Analysis)
    # ============================================================
    #
    # Research sources:
    # - Google Trends (2023-2024 monthly data for "grab", "giao hàng", "delivery")
    # - Industry knowledge for VN delivery/ride-hailing market
    #
    # Key findings:
    # - Tet month: -4.4% vs baseline (people leave cities)
    # - May (Labor Day): spike to 32.0
    # - December: stable +1.0%
    #
    # Impact scale: 0.0 (no effect) to 1.0 (maximum effect)
    # ============================================================

    HOLIDAY_IMPACT = {
        # Tet Period
        'tet_week': 0.4,       # Lower - people leave cities for hometown
        'pre_tet': 0.7,        # Rush to order before leaving
        'post_tet': 0.3,       # Slow return, vacation continues

        # Major Solar Holidays
        'tet_duong_lich': 0.5,       # New Year celebration
        'ngay_giai_phong': 0.7,      # 30/4 - travel season
        'ngay_quoc_te_lao_dong': 0.6, # 1/5 - long weekend
        'ngay_quoc_khanh': 0.7,     # 2/9 - travel season

        # Lunar New Year (Tet)
        'tet_nguyen_dan': 0.4,      # Tet actual days - demand low in cities

        # Cultural Holidays
        'valentine': 0.3,          # Couples go to restaurants
        'trung_thu': 0.4,          # Family activities with kids
        'giang_sinh': 0.4,         # Shopping, gift-giving season
        'tet_nguyen_tieu': 0.3,    # Lantern festival

        # Religious Holidays
        'gio_to_hung_vuong': 0.5,   # Traditional observance
        'le_phat_dan': 0.2,        # Buddhist holiday
        'le_vu_lan': 0.3,         # Ghost festival

        # Fallback
        'major_holiday': 0.5,
        'minor_holiday': 0.3,
        'normal': 0.0,
    }

    def __init__(self, config: Dict):
        super().__init__(config)
        self.csv_path = config.get('holiday_file', 'data/holidays.csv')
        self.impact_radius = config.get('impact_radius', 50)  # Whole city

        # Year to calculate lunar holidays for
        self.year = config.get('year', datetime.now().year)

    def fetch(self) -> pd.DataFrame:
        """
        Fetch holidays from both sources:
        1. Solar holidays from code (fixed dates)
        2. Lunar holidays calculated automatically for the year
        """
        all_holidays = []

        # 1. Solar holidays (fixed, same every year)
        for month, day, name, impact, category in self.SOLAR_HOLIDAYS:
            all_holidays.append({
                'date': datetime(self.year, month, day),
                'holiday_name': name,
                'is_holiday': 1,
                'is_working_day': 0,
                'category': category,
                'holiday_type': 'solar',
                'value': impact,
            })

        # 2. Lunar holidays (calculated for the year)
        df_lunar = self._calculate_lunar_holidays()
        if not df_lunar.empty:
            all_holidays.extend(df_lunar.to_dict('records'))

        # Combine
        df = pd.DataFrame(all_holidays)

        # Remove duplicates (same date), keep the one with higher impact
        df = df.sort_values('value', ascending=False)
        df = df.drop_duplicates(subset=['date'], keep='first')

        return df.sort_values('date').reset_index(drop=True)

    def _calculate_lunar_holidays(self) -> pd.DataFrame:
        """
        Calculate lunar holidays for the configured year.

        Converts lunar dates to solar dates using lunarcalendar library.
        """
        holidays = []

        for lunar_month, lunar_day, name, impact, category in self.LUNAR_HOLIDAYS:
            try:
                # Convert lunar date to solar date for the configured year
                lunar_date = Lunar(self.year, lunar_month, lunar_day)
                solar_date = Converter.Lunar2Solar(lunar_date)

                holidays.append({
                    'date': datetime(solar_date.year, solar_date.month, solar_date.day),
                    'holiday_name': name,
                    'is_holiday': 1,
                    'is_working_day': 0,
                    'category': category,
                    'holiday_type': 'lunar',
                    'value': impact,
                })

            except Exception as e:
                print(f"[Holiday] Error converting lunar {lunar_month}/{lunar_day}: {e}")

        return pd.DataFrame(holidays)

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Transform holidays with Tet phase calculation."""
        if df.empty:
            return df

        df = df.copy()

        # Find Tet date for this year
        tet_date = self._get_tet_date()
        if tet_date is None:
            tet_date = datetime(self.year, 1, 1)

        # Calculate Tet phase
        def get_tet_phase(date: datetime) -> str:
            days_from_tet = (date - tet_date).days

            for phase, bounds in self.TET_PHASES.items():
                if phase == 'normal' or bounds is None:
                    continue
                start, end = bounds
                if start <= days_from_tet <= end:
                    return phase

            return 'normal'

        df['tet_phase'] = df['date'].apply(get_tet_phase)

        # Override impact for Tet period (only apply to Tet holidays)
        def calculate_impact(row) -> float:
            # Only apply Tet phase impact to Tet holidays
            if row['category'] == 'tet' and row['tet_phase'] != 'normal':
                return self.HOLIDAY_IMPACT.get(row['tet_phase'], 0.9)
            # For non-Tet holidays, use their own impact value
            return row.get('value', self.HOLIDAY_IMPACT['normal'])

        df['value'] = df.apply(calculate_impact, axis=1)

        # Severity
        def get_severity(value: float) -> str:
            if value >= 0.7:
                return 'HIGH'
            elif value >= 0.3:
                return 'MEDIUM'
            return 'LOW'

        df['severity'] = df['value'].apply(get_severity)

        # Metadata
        df['metadata'] = df.apply(
            lambda r: {
                'holiday_name': r['holiday_name'],
                'tet_phase': r['tet_phase'],
                'category': r.get('category', 'unknown'),
                'holiday_type': r.get('holiday_type', 'unknown'),
            },
            axis=1
        )

        df['datetime'] = df['date']

        return df

    def _get_tet_date(self) -> Optional[datetime]:
        """Get Tet (Lunar New Year) date for the configured year."""
        try:
            lunar_tet = Lunar(self.year, 1, 1)
            solar_tet = Converter.Lunar2Solar(lunar_tet)
            return datetime(solar_tet.year, solar_tet.month, solar_tet.day)
        except:
            return None

    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """Holidays affect the entire city uniformly."""
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

    def get_year_summary(self) -> Dict:
        """Get summary of holidays for the configured year."""
        df = self.fetch()
        df = self.transform(df)

        tet_date = self._get_tet_date()

        return {
            'year': self.year,
            'tet_date': tet_date.strftime('%Y-%m-%d') if tet_date else None,
            'total_holidays': len(df),
            'solar_count': len(df[df['holiday_type'] == 'solar']),
            'lunar_count': len(df[df['holiday_type'] == 'lunar']),
            'holidays': df[['date', 'holiday_name', 'holiday_type', 'value']].to_dict('records'),
        }
