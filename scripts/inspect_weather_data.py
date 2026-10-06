"""
Inspect weather data file
"""

import pandas as pd
from pathlib import Path

def main():
    parquet_path = Path("data/weather_anchors_30T_merged.parquet")

    if not parquet_path.exists():
        print(f"File not found: {parquet_path}")
        return

    print(f"Reading: {parquet_path}")
    df = pd.read_parquet(parquet_path)

    print(f"\n{'='*60}")
    print("WEATHER DATA OVERVIEW")
    print(f"{'='*60}")
    print(f"Shape: {df.shape}")
    print(f"Rows: {len(df):,}")
    print(f"Columns: {len(df.columns)}")

    print(f"\n{'='*60}")
    print("COLUMNS")
    print(f"{'='*60}")
    for col in df.columns:
        dtype = df[col].dtype
        null_count = df[col].isnull().sum()
        print(f"  {col:30} | {str(dtype):15} | nulls: {null_count:,}")

    print(f"\n{'='*60}")
    print("SAMPLE DATA (first 5 rows)")
    print(f"{'='*60}")
    print(df.head().to_string())

    print(f"\n{'='*60}")
    print("DATA RANGE")
    print(f"{'='*60}")

    # Check datetime columns
    datetime_cols = [col for col in df.columns if 'time' in col.lower() or 'date' in col.lower() or 'datetime' in col.lower()]
    for col in datetime_cols:
        try:
            print(f"\n{col}:")
            print(f"  Min: {df[col].min()}")
            print(f"  Max: {df[col].max()}")
        except:
            print(f"\n{col}: (cannot get min/max)")

    # Check for h3_index
    if 'h3_index' in df.columns:
        print(f"\nUnique h3_index values: {df['h3_index'].nunique()}")
        print(f"Sample h3_index values:")
        for h3 in df['h3_index'].unique()[:5]:
            print(f"  {h3}")

    # Check for h3 resolution
    if 'h3_index' in df.columns:
        h3_lengths = df['h3_index'].dropna().astype(str).str.len().value_counts()
        print(f"\nh3_index lengths:")
        for length, count in h3_lengths.items():
            print(f"  Length {length}: {count:,} values")

if __name__ == "__main__":
    main()
