"""
Holiday Calendar Generator
==========================

Reusable holiday calendar for Vietnam, supporting:
- Solar holidays (fixed dates)
- Lunar holidays (calculated via lunarcalendar)
- Tet phases (pre_tet, tet_week, post_tet)
- Special days

This module is shared between:
- scripts/merge_holidays.py
- src/features/preprocessor.py
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union
import logging

import pandas as pd

logger = logging.getLogger(__name__)


class HolidayCalendarGenerator:
    """
    Generate complete holiday calendar for Vietnam.

    Holidays included:
    - Solar holidays (fixed dates)
    - Lunar holidays (calculated via lunarcalendar)
    - Tet phases (pre_tet, tet_week, post_tet)
    - Special days (Khai giang, etc.)

    Usage:
        generator = HolidayCalendarGenerator(year=2026)
        calendar = generator.generate_calendar(
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 12, 31)
        )

        # Merge with your dataframe
        df = generator.merge_holidays(df, datetime_col='timestamp')
    """

    # Tet phase definitions (relative to Tet date)
    TET_PHASES: Dict[str, Tuple[int, int]] = {
        'pre_tet': (-21, -8),     # 21-8 days before Tet
        'tet_week': (-7, 7),       # 7 days before and 7 days after Tet
        'post_tet': (8, 21),       # 8-21 days after Tet
    }

    # Solar holidays (fixed dates)
    # Format: (month, day, name, impact, category)
    SOLAR_HOLIDAYS: List[Tuple[int, int, str, float, str]] = [
        # Official holidays
        (1, 1, "Tet Duong lich", 0.5, "official"),
        (4, 30, "Ngay Giai phong mien Nam", 0.7, "official"),
        (5, 1, "Ngay Quoc te Lao dong", 0.6, "official"),
        (9, 2, "Ngay Quoc khanh", 0.7, "official"),
        # Cultural holidays
        (12, 24, "Le Giang Sinh", 0.4, "cultural"),
        (12, 25, "Le Giang Sinh", 0.4, "cultural"),
        (12, 31, "Dem giao thua Duong lich", 0.4, "cultural"),
        (2, 14, "Ngay Valentine", 0.3, "cultural"),
        (3, 8, "Quoc te Phu nu", 0.4, "cultural"),
        (6, 1, "Quoc te thieu nhi", 0.3, "cultural"),
        (9, 5, "Khai giang", 0.3, "cultural"),
        (10, 20, "Ngay Phu nu Viet Nam", 0.4, "cultural"),
        (11, 20, "Ngay Nha giao Viet Nam", 0.3, "cultural"),
    ]

    # Lunar holidays
    # Format: (lunar_month, lunar_day, name, impact, category)
    LUNAR_HOLIDAYS: List[Tuple[int, int, str, float, str]] = [
        # Tet holidays
        (31, 12, "Dem giao thua Am lich", 0.4, "tet"),
        (1, 1, "Tet Nguyen Dan", 0.4, "tet"),
        (1, 2, "Mung 2 Tet", 0.4, "tet"),
        (1, 3, "Mung 3 Tet", 0.4, "tet"),
        (1, 4, "Mung 4 Tet", 0.4, "tet"),
        (1, 5, "Mung 5 Tet", 0.4, "tet"),
        # Traditional holidays
        (3, 10, "Gio To Hung Vuong", 0.5, "traditional"),
        (1, 15, "Tet Nguyen Tieu", 0.3, "traditional"),
        # Religious holidays
        (4, 15, "Le Phat Dan", 0.2, "religious"),
        (7, 15, "Le Vu Lan", 0.3, "traditional"),
        (8, 15, "Tet Trung thu", 0.4, "traditional"),
    ]

    def __init__(self, year: Optional[int] = None):
        """
        Initialize holiday calendar generator.

        Args:
            year: Year to calculate holidays for. Defaults to current year.
        """
        self.year = year or datetime.now().year
        self.tet_date: Optional[datetime] = None
        self._calculate_tet_date()
        self._holiday_cache: Optional[pd.DataFrame] = None

    def _calculate_tet_date(self) -> None:
        """Calculate Tet (Lunar New Year) date for the configured year."""
        try:
            from lunarcalendar import Lunar, Converter, Solar

            lunar_tet = Lunar(self.year, 1, 1)
            solar_tet = Converter.Lunar2Solar(lunar_tet)
            self.tet_date = datetime(
                solar_tet.year, solar_tet.month, solar_tet.day
            )
            logger.debug(f"Tet {self.year} date: {self.tet_date.strftime('%Y-%m-%d')}")
        except ImportError:
            logger.warning(
                "lunarcalendar not installed. Tet date will use fallback."
            )
            # Fallback: Tet usually in late Jan or early Feb
            # This is approximate but works for most years
            self.tet_date = datetime(self.year, 2, 15)
        except Exception as e:
            logger.warning(f"Error calculating Tet date: {e}. Using fallback.")
            self.tet_date = datetime(self.year, 2, 15)

    def get_tet_date(self) -> Optional[datetime]:
        """Get calculated Tet date."""
        return self.tet_date

    def generate_calendar(
        self,
        start_date: Union[datetime, pd.Timestamp],
        end_date: Union[datetime, pd.Timestamp]
    ) -> pd.DataFrame:
        """
        Generate holiday calendar for a date range.

        Args:
            start_date: Start of range
            end_date: End of range

        Returns:
            DataFrame with one row per day containing:
            - date: The date
            - is_holiday: 1 if holiday, 0 otherwise
            - holiday_name: Name of holiday or 'normal'
            - holiday_impact: Impact score 0.0-1.0
            - tet_phase: 'normal', 'pre_tet', 'tet_week', 'post_tet'
            - is_working_day: 0 if non-working, 1 if working
            - holiday_type: 'solar', 'lunar', 'tet', 'special', 'normal'
            - category: 'official', 'cultural', etc.
        """
        # Normalize dates
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()

        all_days = []
        current = start

        while current <= end:
            day_info = self._get_day_info(current.to_pydatetime())
            day_info['date'] = current
            all_days.append(day_info)
            current += timedelta(days=1)

        df = pd.DataFrame(all_days)

        # Ensure correct types
        df['is_holiday'] = df['is_holiday'].fillna(0).astype(int)
        df['holiday_impact'] = df['holiday_impact'].fillna(0.0).astype(float)
        df['is_working_day'] = df['is_working_day'].fillna(1).astype(int)

        # String columns
        df['holiday_name'] = df['holiday_name'].fillna('normal').astype(str)
        df['tet_phase'] = df['tet_phase'].fillna('normal').astype(str)
        df['holiday_type'] = df['holiday_type'].fillna('normal').astype(str)
        df['category'] = df['category'].fillna('none').astype(str)

        # Cache the calendar
        self._holiday_cache = df.copy()

        return df

    def _get_day_info(self, date: datetime) -> Dict:
        """
        Get holiday information for a specific day.

        Args:
            date: The date to check

        Returns:
            Dictionary with holiday info
        """
        info = {
            'is_holiday': 0,
            'holiday_name': None,
            'holiday_impact': 0.0,
            'tet_phase': 'normal',
            'is_working_day': 1,
            'holiday_type': 'normal',
            'category': None,
        }

        # Check Tet phase first (Tet takes precedence for impact)
        if self.tet_date:
            days_from_tet = (date - self.tet_date).days

            for phase, (start, end) in self.TET_PHASES.items():
                if start <= days_from_tet <= end:
                    info['tet_phase'] = phase
                    info['holiday_type'] = 'tet'
                    break

        # Check solar holidays
        solar_holiday = self._check_solar_holiday(date)
        if solar_holiday:
            info.update(solar_holiday)
            return info

        # Check lunar holidays
        lunar_holiday = self._check_lunar_holiday(date)
        if lunar_holiday:
            info.update(lunar_holiday)
            return info

        # Check weekends as non-working
        if date.weekday() >= 5:  # Saturday=5, Sunday=6
            info['is_working_day'] = 0

        return info

    def _check_solar_holiday(self, date: datetime) -> Optional[Dict]:
        """Check if date is a solar holiday."""
        for month, day, name, impact, category in self.SOLAR_HOLIDAYS:
            if date.month == month and date.day == day:
                return {
                    'is_holiday': 1,
                    'holiday_name': name,
                    'holiday_impact': impact,
                    'is_working_day': 0,
                    'holiday_type': 'solar',
                    'category': category,
                }
        return None

    def _check_lunar_holiday(self, date: datetime) -> Optional[Dict]:
        """Check if date is a lunar holiday."""
        try:
            from lunarcalendar import Lunar, Converter, Solar

            # Get lunar date for this solar date
            solar = Solar(date.year, date.month, date.day)
            lunar = Converter.Solar2Lunar(solar)

            lunar_month = lunar.month
            lunar_day = lunar.day

            for lm, ld, name, impact, category in self.LUNAR_HOLIDAYS:
                if lunar_month == lm and lunar_day == ld:
                    # For Tet holidays, apply Tet phase impact
                    if category == 'tet':
                        impact = self._get_tet_phase_impact(date)

                    return {
                        'is_holiday': 1,
                        'holiday_name': name,
                        'holiday_impact': impact,
                        'is_working_day': 0,
                        'holiday_type': 'lunar',
                        'category': category,
                    }
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Error checking lunar holiday: {e}")

        return None

    def _get_tet_phase_impact(self, date: datetime) -> float:
        """
        Get impact based on Tet phase.

        Impact is LOWER during Tet because people leave cities.
        """
        if not self.tet_date:
            return 0.0

        days_from_tet = (date - self.tet_date).days

        for phase, (start, end) in self.TET_PHASES.items():
            if start <= days_from_tet <= end:
                if phase == 'pre_tet':
                    return 0.7  # Rush to order before leaving
                elif phase == 'tet_week':
                    return 0.4  # Lower - people leave cities
                elif phase == 'post_tet':
                    return 0.3  # Slow return

        return 0.0

    def merge_holidays(
        self,
        df: pd.DataFrame,
        datetime_col: str = 'timestamp'
    ) -> pd.DataFrame:
        """
        Merge holiday information into a DataFrame.

        Args:
            df: Input DataFrame with datetime column
            datetime_col: Name of datetime column in df

        Returns:
            DataFrame with additional holiday columns
        """
        df = df.copy()

        # Parse datetime
        dt_series = pd.to_datetime(df[datetime_col])

        # Get date range
        min_date = dt_series.min().normalize()
        max_date = dt_series.max().normalize()

        # Generate calendar if not cached or range changed
        if self._holiday_cache is None:
            self.generate_calendar(min_date, max_date)

        # Create date mapping
        holiday_map = self._holiday_cache.set_index('date')

        # Map each row to its date's holiday info
        dates = dt_series.dt.normalize()

        # Use vectorized lookup
        df['is_holiday'] = dates.map(holiday_map['is_holiday']).fillna(0).astype(int)
        df['holiday_name'] = dates.map(holiday_map['holiday_name']).fillna('normal').astype(str)
        df['holiday_impact'] = dates.map(holiday_map['holiday_impact']).fillna(0.0).astype(float)
        df['tet_phase'] = dates.map(holiday_map['tet_phase']).fillna('normal').astype(str)
        df['is_working_day'] = dates.map(holiday_map['is_working_day']).fillna(1).astype(int)
        df['holiday_type'] = dates.map(holiday_map['holiday_type']).fillna('normal').astype(str)
        df['category'] = dates.map(holiday_map['category']).fillna('none').astype(str)

        return df

    def get_holidays_in_range(
        self,
        start_date: Union[datetime, pd.Timestamp],
        end_date: Union[datetime, pd.Timestamp]
    ) -> pd.DataFrame:
        """
        Get list of holidays within a date range.

        Args:
            start_date: Start of range
            end_date: End of range

        Returns:
            DataFrame of holidays (is_holiday == 1)
        """
        calendar = self.generate_calendar(start_date, end_date)
        return calendar[calendar['is_holiday'] == 1]

    def get_summary(self) -> Dict:
        """
        Get summary of holidays for the configured year.

        Returns:
            Dictionary with holiday summary
        """
        calendar = self.generate_calendar(
            datetime(self.year, 1, 1),
            datetime(self.year, 12, 31)
        )

        holidays = calendar[calendar['is_holiday'] == 1]

        return {
            'year': self.year,
            'tet_date': self.tet_date.strftime('%Y-%m-%d') if self.tet_date else None,
            'total_holidays': len(holidays),
            'solar_count': len(holidays[holidays['holiday_type'] == 'solar']),
            'lunar_count': len(holidays[holidays['holiday_type'] == 'lunar']),
            'holidays': holidays[['date', 'holiday_name', 'holiday_type', 'holiday_impact']].to_dict('records'),
        }
