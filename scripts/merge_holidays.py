"""
Merge Holiday Data into Training Set
===================================

Script nay merge holiday data (solar + lunar + Tet phases) vao training data
de chuan bi cho model training.

Usage:
    python scripts/merge_holidays.py                    # Merge vao file moi
    python scripts/merge_holidays.py --input data/my_data.parquet
    python scripts/merge_holidays.py --dry-run         # Chi show preview

Output:
    data/weather_anchors_30T_merged.parquet (hoac custom)
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import pandas as pd
import numpy as np

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# PART 1: HOLIDAY CALENDAR GENERATOR
# =============================================================================

class HolidayCalendarGenerator:
    """
    Generate complete holiday calendar cho mot date range.

    Holidays included:
    - Solar holidays (fixed dates)
    - Lunar holidays (calculated via lunarcalendar)
    - Tet phases (pre_tet, tet_week, post_tet)
    - Special days (Khai giang, etc.)
    """

    # Tet phase definitions (relative to Tet date)
    TET_PHASES = {
        'pre_tet': (-21, -8),     # 21-8 days before Tet
        'tet_week': (-7, 7),       # 7 days before and 7 days after Tet
        'post_tet': (8, 21),       # 8-21 days after Tet
    }

    # Solar holidays (fixed dates) - Format: (month, day, name, impact, category)
    SOLAR_HOLIDAYS = [
        (1, 1, "Tet Duong lich", 0.5, "official"),
        (4, 30, "Ngay Giai phong mien Nam", 0.7, "official"),
        (5, 1, "Ngay Quoc te Lao dong", 0.6, "official"),
        (9, 2, "Ngay Quoc khanh", 0.7, "official"),
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

    # Lunar holidays - Format: (lunar_month, lunar_day, name, impact, category)
    LUNAR_HOLIDAYS = [
        (31, 12, "Dem giao thua Am lich", 0.4, "tet"),
        (1, 1, "Tet Nguyen Dan", 0.4, "tet"),
        (1, 2, "Mung 2 Tet", 0.4, "tet"),
        (1, 3, "Mung 3 Tet", 0.4, "tet"),
        (1, 4, "Mung 4 Tet", 0.4, "tet"),
        (1, 5, "Mung 5 Tet", 0.4, "tet"),
        (3, 10, "Gio To Hung Vuong", 0.5, "traditional"),
        (1, 15, "Tet Nguyen Tieu", 0.3, "traditional"),
        (4, 15, "Le Phat Dan", 0.2, "religious"),
        (7, 15, "Le Vu Lan", 0.3, "traditional"),
        (8, 15, "Tet Trung thu", 0.4, "traditional"),
    ]

    # Fallback impacts
    FALLBACK_IMPACT = {
        'major_holiday': 0.5,
        'minor_holiday': 0.3,
        'normal': 0.0,
    }

    def __init__(self, year: int = 2026):
        self.year = year
        self.tet_date: Optional[datetime] = None
        self._calculate_tet_date()

    def _calculate_tet_date(self):
        """Calculate Tet (Lunar New Year) date for the configured year."""
        try:
            from lunarcalendar import Lunar, Converter, Solar

            lunar_tet = Lunar(self.year, 1, 1)
            solar_tet = Converter.Lunar2Solar(lunar_tet)
            self.tet_date = datetime(solar_tet.year, solar_tet.month, solar_tet.day)
            logger.info(f"Tet {self.year} date calculated: {self.tet_date.strftime('%Y-%m-%d')}")
        except ImportError:
            logger.warning("lunarcalendar not installed. Tet date will be estimated.")
            # Fallback: Tet usually in late Jan or early Feb
            self.tet_date = datetime(self.year, 2, 15)  # Rough estimate
        except Exception as e:
            logger.warning(f"Error calculating Tet date: {e}. Using estimate.")
            self.tet_date = datetime(self.year, 2, 15)

    def generate_calendar(self, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """
        Generate holiday calendar for a date range.

        Args:
            start_date: Start of range
            end_date: End of range

        Returns:
            DataFrame with one row per day
        """
        all_days = []
        current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = end_date.replace(hour=0, minute=0, second=0, microsecond=0)

        while current <= end:
            day_info = self._get_day_info(current)
            all_days.append(day_info)
            current += timedelta(days=1)

        df = pd.DataFrame(all_days)

        # Fill NaN values
        df['holiday_name'] = df['holiday_name'].fillna('normal')
        df['holiday_impact'] = df['holiday_impact'].fillna(0.0)
        df['tet_phase'] = df['tet_phase'].fillna('normal')
        df['is_holiday'] = df['is_holiday'].fillna(0).astype(int)
        df['is_working_day'] = df['is_working_day'].fillna(1).astype(int)

        return df

    def _get_day_info(self, date: datetime) -> Dict:
        """
        Get holiday information for a specific day.

        Returns:
            Dict with:
            - date: the date
            - is_holiday: 0 or 1
            - holiday_name: name of holiday or 'normal'
            - holiday_impact: 0.0 to 1.0
            - tet_phase: 'normal', 'pre_tet', 'tet_week', 'post_tet'
            - is_working_day: 0 or 1
            - holiday_type: 'solar', 'lunar', 'tet', 'special', 'normal'
            - category: 'official', 'cultural', 'traditional', etc.
        """
        info = {
            'date': date,
            'is_holiday': 0,
            'holiday_name': None,
            'holiday_impact': 0.0,
            'tet_phase': 'normal',
            'is_working_day': 1,
            'holiday_type': 'normal',
            'category': None,
        }

        # Check Tet phase first (Tet takes precedence)
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

        # Check special days
        special_day = self._check_special_day(date)
        if special_day:
            info.update(special_day)
            return info

        # Check weekends (default non-working)
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
                    # For Tet holidays, Tet phase overrides impact
                    if category == 'tet' and self.tet_date:
                        # This is during Tet period
                        impact = self._get_tet_phase_impact(self.tet_date, date)

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

    def _get_tet_phase_impact(self, tet_date: datetime, current_date: datetime) -> float:
        """
        Get impact based on Tet phase.

        Tet impact is LOWER than normal because people leave cities.
        """
        days_from_tet = (current_date - tet_date).days

        for phase, (start, end) in self.TET_PHASES.items():
            if start <= days_from_tet <= end:
                if phase == 'pre_tet':
                    return 0.7  # Rush to order before leaving
                elif phase == 'tet_week':
                    return 0.4  # Lower - people leave cities
                elif phase == 'post_tet':
                    return 0.3  # Slow return, vacation continues

        return 0.0

    def _check_special_day(self, date: datetime) -> Optional[Dict]:
        """
        Check for special days that are not traditional holidays.
        """
        # End of year (Dec 24-31 is already handled as solar holidays)
        # School year start (first Monday of September)
        if date.month == 9 and date.day == 1:
            return {
                'is_holiday': 0,
                'holiday_name': 'Bat dau nam hoc',
                'holiday_impact': 0.1,  # Slight impact on traffic
                'is_working_day': 1,
                'holiday_type': 'special',
                'category': 'education',
            }

        return None


# =============================================================================
# PART 2: HOLIDAY MERGER
# =============================================================================

class HolidayMerger:
    """
    Merge holiday data into training dataset.
    """

    def __init__(self, holiday_calendar: pd.DataFrame):
        """
        Args:
            holiday_calendar: DataFrame from HolidayCalendarGenerator
        """
        self.holiday_calendar = holiday_calendar.set_index('date')

    def merge(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Merge holiday information into training data.

        Args:
            df: Training data with 'datetime' column

        Returns:
            DataFrame with additional holiday columns
        """
        df = df.copy()

        # Extract date from datetime for merge
        df['_merge_date'] = pd.to_datetime(df['datetime']).dt.normalize()

        # Merge holiday info
        merged = df.merge(
            self.holiday_calendar.reset_index(),
            left_on='_merge_date',
            right_on='date',
            how='left',
            suffixes=('', '_holiday')
        )

        # Drop merge columns and extra date column
        merged = merged.drop(columns=['_merge_date', 'date_holiday'], errors='ignore')

        # Fill NaN
        merged['holiday_name'] = merged['holiday_name'].fillna('normal')
        merged['holiday_impact'] = merged['holiday_impact'].fillna(0.0)
        merged['tet_phase'] = merged['tet_phase'].fillna('normal')
        merged['is_holiday'] = merged['is_holiday'].fillna(0).astype(int)
        merged['is_working_day'] = merged['is_working_day'].fillna(1).astype(int)
        merged['holiday_type'] = merged['holiday_type'].fillna('normal')
        # For category, use 'none' instead of None
        merged['category'] = merged['category'].fillna('none')

        logger.info(f"Merged holiday data: {merged['is_holiday'].sum()} holiday records")

        return merged

    def validate(self, df: pd.DataFrame) -> Dict:
        """
        Validate merged data and return statistics.
        """
        stats = {
            'total_records': len(df),
            'holiday_records': int(df['is_holiday'].sum()),
            'non_working_days': int((df['is_working_day'] == 0).sum()),
            'unique_holidays': df[df['is_holiday'] == 1]['holiday_name'].nunique(),
            'tet_phase_days': {},
            'null_check': {},
        }

        # Tet phase distribution
        for phase in ['normal', 'pre_tet', 'tet_week', 'post_tet']:
            count = (df['tet_phase'] == phase).sum()
            if count > 0:
                stats['tet_phase_days'][phase] = int(count)

        # Null check
        for col in ['holiday_name', 'holiday_impact', 'tet_phase', 'is_holiday', 'is_working_day']:
            null_count = df[col].isna().sum()
            stats['null_check'][col] = null_count

        return stats


# =============================================================================
# PART 3: MAIN FUNCTION
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Merge Holiday Data into Training Set')
    parser.add_argument('--input', '-i', default='data/weather_anchors_30T.parquet',
                       help='Input training data file')
    parser.add_argument('--output', '-o', default='data/weather_anchors_30T_merged.parquet',
                       help='Output merged file')
    parser.add_argument('--year', '-y', type=int, default=2026,
                       help='Year for holiday calculation')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show preview without saving')
    parser.add_argument('--show-holidays', action='store_true',
                       help='Show all holidays in date range')
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("HOLIDAY MERGE SCRIPT")
    logger.info("=" * 70)

    # Check input file exists
    if not os.path.exists(args.input):
        logger.error(f"Input file not found: {args.input}")
        return 1

    # Load training data
    logger.info(f"\nLoading training data: {args.input}")
    df = pd.read_parquet(args.input)
    logger.info(f"  Shape: {df.shape}")
    logger.info(f"  Columns: {len(df.columns)}")

    # Get date range from training data
    if 'datetime' in df.columns:
        min_date = pd.to_datetime(df['datetime']).min()
        max_date = pd.to_datetime(df['datetime']).max()
    else:
        logger.error("Training data must have 'datetime' column")
        return 1

    logger.info(f"  Date range: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')}")

    # Generate holiday calendar
    logger.info(f"\nGenerating holiday calendar for year {args.year}...")
    generator = HolidayCalendarGenerator(year=args.year)
    holiday_calendar = generator.generate_calendar(min_date, max_date)

    logger.info(f"  Generated {len(holiday_calendar)} days")

    # Show holidays if requested
    if args.show_holidays:
        logger.info("\n" + "=" * 50)
        logger.info("HOLIDAYS IN DATE RANGE")
        logger.info("=" * 50)

        holidays = holiday_calendar[holiday_calendar['is_holiday'] == 1]
        if holidays.empty:
            logger.info("No holidays found in date range.")
        else:
            for _, row in holidays.iterrows():
                logger.info(f"  {row['date'].strftime('%Y-%m-%d')} ({row['date'].strftime('%A')}): "
                           f"{row['holiday_name']} (impact={row['holiday_impact']}, type={row['holiday_type']})")

        # Show Tet phases
        tet_days = holiday_calendar[holiday_calendar['tet_phase'] != 'normal']
        if not tet_days.empty:
            logger.info("\nTet Phases:")
            for phase in ['pre_tet', 'tet_week', 'post_tet']:
                phase_days = tet_days[tet_days['tet_phase'] == phase]
                if not phase_days.empty:
                    logger.info(f"  {phase}: {len(phase_days)} days")
                    for _, row in phase_days.head(3).iterrows():
                        logger.info(f"    - {row['date'].strftime('%Y-%m-%d')}")
                    if len(phase_days) > 3:
                        logger.info(f"    ... and {len(phase_days) - 3} more")

    # Dry run - just show preview
    if args.dry_run:
        logger.info("\n" + "=" * 50)
        logger.info("DRY RUN - Preview of merged data")
        logger.info("=" * 50)

        merger = HolidayMerger(holiday_calendar)
        sample = df.head(5).copy()
        merged_sample = merger.merge(sample)

        holiday_cols = ['datetime', 'is_holiday', 'holiday_name', 'holiday_impact',
                        'tet_phase', 'is_working_day', 'holiday_type']

        logger.info("\nSample columns added:")
        for col in holiday_cols:
            if col in merged_sample.columns:
                logger.info(f"  {col}: {merged_sample[col].iloc[0]}")

        # Show stats
        stats = merger.validate(merged_sample)
        logger.info("\nValidation stats (sample):")
        for key, value in stats.items():
            if isinstance(value, dict):
                logger.info(f"  {key}: {value}")
            else:
                logger.info(f"  {key}: {value}")

        return 0

    # Perform merge
    logger.info("\nMerging holiday data...")
    merger = HolidayMerger(holiday_calendar)
    merged_df = merger.merge(df)

    # Validate
    stats = merger.validate(merged_df)
    logger.info("\n" + "=" * 50)
    logger.info("MERGE COMPLETE - Statistics")
    logger.info("=" * 50)
    logger.info(f"Total records: {stats['total_records']}")
    logger.info(f"Holiday records: {stats['holiday_records']}")
    logger.info(f"Non-working days: {stats['non_working_days']}")
    logger.info(f"Unique holidays: {stats['unique_holidays']}")

    if stats['tet_phase_days']:
        logger.info("\nTet phase days:")
        for phase, count in stats['tet_phase_days'].items():
            logger.info(f"  {phase}: {count} days")

    if any(stats['null_check'].values()):
        logger.warning("\nNull values found:")
        for col, count in stats['null_check'].items():
            if count > 0:
                logger.warning(f"  {col}: {count}")
    else:
        logger.info("\nNull check: PASSED (no null values)")

    # Save output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    merged_df.to_parquet(args.output, index=False)
    logger.info(f"\nSaved to: {args.output}")

    # Show new columns
    logger.info("\nNew columns added:")
    for col in ['is_holiday', 'holiday_name', 'holiday_impact', 'tet_phase',
                'is_working_day', 'holiday_type', 'category']:
        if col in merged_df.columns:
            logger.info(f"  - {col}")

    # Show sample of holiday records
    holiday_records = merged_df[merged_df['is_holiday'] == 1]
    if not holiday_records.empty:
        logger.info(f"\nSample of {min(5, len(holiday_records))} holiday records:")
        for _, row in holiday_records.head(5).iterrows():
            dt = pd.to_datetime(row['datetime'])
            logger.info(f"  {dt.strftime('%Y-%m-%d %H:%M')}: {row['holiday_name']} "
                       f"(impact={row['holiday_impact']}, {row['tet_phase']})")

    logger.info("\n" + "=" * 70)
    logger.info("DONE!")
    logger.info("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
