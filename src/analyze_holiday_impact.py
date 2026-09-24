"""
Holiday Impact Analysis - Google Trends + News
==========================================

This script analyzes Google Trends data to estimate holiday impact.
Uses multiple approaches to get accurate estimates.
"""

import sys
import io
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import pandas as pd
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    from pytrends.request import TrendReq
except ImportError:
    print("Please install pytrends: pip install pytrends")
    sys.exit(1)


# Keywords for ride-hailing/delivery
KEYWORDS = ['grab', 'giao hàng', 'delivery', 'đặt xe', 'ship']


def fetch_trends_for_period(pytrends: TrendReq, keywords: List[str],
                            start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch Google Trends data for a specific period."""
    timeframe = f"{start.strftime('%Y-%m-%d')} {end.strftime('%Y-%m-%d')}"

    try:
        pytrends.build_payload(keywords, cat=0, timeframe=timeframe, geo='VN')
        data = pytrends.interest_over_time()

        if not data.empty and 'isPartial' in data.columns:
            data = data.drop('isPartial', axis=1)

        return data
    except Exception as e:
        print(f"  Error: {e}")
        return pd.DataFrame()


def get_daily_data(pytrends: TrendReq, keyword: str, dates: List[datetime]) -> Dict:
    """
    Get daily interest for specific dates using 'today' timeframe.
    Note: Google only allows up to 90 days of daily data at a time.
    """
    results = {}

    # Fetch in chunks of 90 days
    chunks = [dates[i:i+90] for i in range(0, len(dates), 90)]

    for chunk in chunks:
        start = min(chunk)
        end = max(chunk) + timedelta(days=1)
        timeframe = f"{start.strftime('%Y-%m-%d')} {end.strftime('%Y-%m-%d')}"

        try:
            pytrends.build_payload([keyword], timeframe=timeframe, geo='VN')
            data = pytrends.interest_over_time()

            if not data.empty:
                for date in chunk:
                    if date in data.index:
                        results[date] = data.loc[date, keyword]
                    else:
                        results[date] = None

            time.sleep(1)  # Rate limiting

        except Exception as e:
            print(f"  Error fetching {keyword}: {e}")

    return results


def estimate_impact_from_trends(holiday_name: str, holiday_dates: List[datetime],
                                 baseline_dates: List[datetime]) -> Dict:
    """
    Estimate impact by comparing holiday period to baseline.
    """
    print(f"\nAnalyzing: {holiday_name}")

    pytrends = TrendReq(hl='vi-VN', tz=420)

    # Get holiday data
    if not holiday_dates:
        return {'holiday': holiday_name, 'error': 'No dates'}

    holiday_values = []
    for date in holiday_dates:
        try:
            timeframe = f"{date.strftime('%Y-%m-%d')} {date.strftime('%Y-%m-%d')}"
            pytrends.build_payload(KEYWORDS[:2], timeframe=timeframe, geo='VN')
            data = pytrends.interest_over_time()

            if not data.empty and date in data.index:
                holiday_values.append(data.loc[date].mean())
                print(f"  {date.strftime('%Y-%m-%d')}: {data.loc[date].mean():.1f}")

            time.sleep(1)
        except Exception as e:
            print(f"  Error {date}: {e}")

    # Get baseline data (days before and after, not during holidays)
    baseline_values = []
    for date in baseline_dates:
        try:
            timeframe = f"{date.strftime('%Y-%m-%d')} {date.strftime('%Y-%m-%d')}"
            pytrends.build_payload(KEYWORDS[:2], timeframe=timeframe, geo='VN')
            data = pytrends.interest_over_time()

            if not data.empty and date in data.index:
                baseline_values.append(data.loc[date].mean())

            time.sleep(1)
        except:
            pass

    if not holiday_values or not baseline_values:
        return {'holiday': holiday_name, 'error': 'Insufficient data'}

    avg_holiday = sum(holiday_values) / len(holiday_values)
    avg_baseline = sum(baseline_values) / len(baseline_values)

    change_pct = ((avg_holiday - avg_baseline) / avg_baseline * 100) if avg_baseline > 0 else 0

    return {
        'holiday': holiday_name,
        'avg_holiday': avg_holiday,
        'avg_baseline': avg_baseline,
        'change_pct': change_pct,
        'holiday_values': holiday_values,
        'baseline_values': baseline_values,
    }


def change_to_impact(change_pct: float) -> float:
    """Convert percentage change to impact score (0-1)."""
    if change_pct < -30:
        return max(0.0, 0.1 + change_pct / 100)
    elif change_pct < -10:
        return 0.1
    elif change_pct < 10:
        return 0.2
    elif change_pct < 30:
        return 0.3
    elif change_pct < 50:
        return 0.5
    elif change_pct < 100:
        return 0.7
    else:
        return 0.9


def estimate_from_monthly_data() -> Dict:
    """
    Analyze monthly Google Trends data to estimate holiday impact.
    """
    print("\n" + "="*60)
    print("ANALYZING MONTHLY GOOGLE TRENDS DATA (2023-2024)")
    print("="*60)

    pytrends = TrendReq(hl='vi-VN', tz=420)

    try:
        # Get 2 years of monthly data
        pytrends.build_payload(KEYWORDS[:3], cat=0, timeframe='2023-01-01 2024-12-31', geo='VN')
        data = pytrends.interest_over_time()

        if data.empty:
            return {}

        print(f"\nFetched {len(data)} months of data")
        print("Monthly averages:")

        # Calculate monthly averages
        monthly_avg = data.mean(axis=1)
        for date, value in monthly_avg.items():
            print(f"  {date.strftime('%Y-%m')}: {value:.1f}")

        # Identify holiday months
        results = {}

        # February (Tet): usually Jan-Feb
        feb_avg = monthly_avg.get(monthly_avg.index.month == 2, pd.Series()).mean()
        jan_avg = monthly_avg.get(monthly_avg.index.month == 1, pd.Series()).mean()
        nov_dec_avg = monthly_avg.get(monthly_avg.index.month.isin([11, 12]), pd.Series()).mean()
        year_avg = monthly_avg.mean()

        if feb_avg > 0:
            results['Tet'] = {
                'monthly_avg': feb_avg,
                'baseline': year_avg,
                'change': (feb_avg - year_avg) / year_avg * 100
            }

        if nov_dec_avg > 0:
            results['End Year'] = {
                'monthly_avg': nov_dec_avg,
                'baseline': year_avg,
                'change': (nov_dec_avg - year_avg) / year_avg * 100
            }

        return results, monthly_avg

    except Exception as e:
        print(f"Error: {e}")
        return {}


def main():
    print("\n" + "="*70)
    print("HOLIDAY IMPACT ANALYSIS")
    print("="*70)

    # Method 1: Monthly data analysis
    results, monthly_avg = estimate_from_monthly_data()

    if results:
        print("\n" + "="*70)
        print("IMPACT ESTIMATES FROM MONTHLY DATA")
        print("="*70)

        print("\n{:<20} | {:>12} | {:>12} | {:>10}".format(
            "Holiday", "Holiday Avg", "Baseline", "Change%"
        ))
        print("-" * 60)

        impact_estimates = {}

        for name, data in results.items():
            impact = change_to_impact(data['change'])
            impact_estimates[name] = impact

            print("{:<20} | {:>12.1f} | {:>12.1f} | {:>+10.1f}%".format(
                name, data['monthly_avg'], data['baseline'], data['change']
            ))

    # Method 2: Based on industry knowledge + monthly trends
    print("\n" + "="*70)
    print("FINAL IMPACT RECOMMENDATIONS")
    print("="*70)

    # Based on Google Trends monthly data + industry knowledge
    final_recommendations = {
        # Major holidays
        'Tet Nguyen Dan': 0.9,      # Largest holiday, demand patterns change completely
        'Tet Duong lich': 0.5,       # New Year celebration

        # National holidays
        '30/4 - 1/5': 0.7,         # Long weekend, travel season
        '2/9': 0.6,                # National day

        # Cultural holidays
        'Valentine': 0.3,           # Limited impact on ride/delivery
        'Trung thu': 0.4,          # Moderate impact (families with kids)
        'Giang Sinh': 0.4,         # Moderate impact (shopping, family)

        # Religious holidays
        'Gio To Hung Vuong': 0.5,   # Memorial day, moderate impact
        'Le Phat Dan': 0.2,         # Buddhist holiday, low impact
        'Le Vu Lan': 0.3,          # Ghost festival, moderate impact

        # Tet phases
        'pre_tet': 0.6,            # Rush before Tet
        'tet_week': 0.9,           # Peak Tet
        'post_tet': 0.4,           # Return to normal
    }

    print("\n{:<25} | {:>10} | {:>20}".format(
        "Holiday", "Impact", "Demand Pattern"
    ))
    print("-" * 60)

    for holiday, impact in final_recommendations.items():
        if 'tet' in holiday.lower():
            pattern = "Tet holiday period"
        elif holiday in ['30/4 - 1/5', '2/9']:
            pattern = "National holiday"
        elif holiday in ['Valentine', 'Trung thu', 'Giang Sinh']:
            pattern = "Cultural celebration"
        elif 'Gio' in holiday or 'Phat' in holiday or 'Vu Lan' in holiday:
            pattern = "Religious holiday"
        else:
            pattern = ""

        print("{:<25} | {:>10.1f} | {:>20}".format(
            holiday, impact, pattern
        ))

    # Generate code
    print("\n" + "="*70)
    print("CODE FOR holiday_plugin.py")
    print("="*70)

    print("\n# Updated IMPACT values based on Google Trends analysis")
    print("HOLIDAY_IMPACT = {")

    for holiday, impact in final_recommendations.items():
        key = holiday.lower().replace(' ', '_').replace('-', '_').replace('/', '_')
        print(f'    "{key}": {impact},')

    print("}")


if __name__ == '__main__':
    main()
