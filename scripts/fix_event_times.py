"""
Script xu ly thoi gian su kien nhieu ngay.

Logic:
- Ngay dau tien: giu nguyen start_time, neu start_time == end_time thi dat end_time = 22:00
- Cac ngay o giua (khong phai ngay dau/cuoi): start_time = 08:00, end_time = 22:00
- Ngay cuoi cung: giu nguyen start_time va end_time, neu thieu thi dat end_time = 22:00
- Them cot end_date (ngay ket thuc cua su kien)
"""

import pandas as pd
from pathlib import Path


def fix_event_times(input_path: str, output_path: str = None):
    """Xử lý thời gian sự kiện nhiều ngày."""

    df = pd.read_excel(input_path)

    # Parse dates
    df['start_date'] = pd.to_datetime(df['start_date'], format='%d/%m/%y')

    # Sắp xếp theo event_name và start_date
    df = df.sort_values(['event_name', 'start_date']).reset_index(drop=True)

    # Thêm cột end_date (sẽ update sau)
    df['end_date'] = pd.NaT

    # Xác định ngày đầu và ngày cuối cho mỗi sự kiện
    event_dates = df.groupby('event_name')['start_date'].agg(['min', 'max'])
    event_dates.columns = ['first_date', 'last_date']

    # Merge thông tin ngày vào dataframe
    df = df.merge(event_dates, on='event_name', how='left')

    # Xác định loại ngày
    df['is_first_day'] = df['start_date'] == df['first_date']
    df['is_last_day'] = df['start_date'] == df['last_date']
    df['is_middle_day'] = ~df['is_first_day'] & ~df['is_last_day']

    # Xu ly thoi gian theo loai ngay
    # Chu y: end_time crawl duoc chinh la end_time cua NGAY CUOI CUNG
    for idx, row in df.iterrows():
        if row['is_first_day']:
            # Ngay dau: giu start_time, end_time = 22:00 (ket thuc trong ngay)
            df.at[idx, 'end_time'] = '22:00'

        elif row['is_middle_day']:
            # Ngay o giua: 08:00 - 22:00
            df.at[idx, 'start_time'] = '08:00'
            df.at[idx, 'end_time'] = '22:00'

        elif row['is_last_day']:
            # Ngay cuoi: start_time = 08:00, end_time = crawl duoc hoac 22:00
            df.at[idx, 'start_time'] = '08:00'
            # Neu khong crawl duoc end_time thi dat 22:00
            end_time_val = row['end_time']
            if pd.isna(end_time_val) or str(end_time_val).strip() == '':
                df.at[idx, 'end_time'] = '22:00'

    # Dat end_date cho tat ca cac dong = ngay cuoi cung cua su kien
    df['end_date'] = df['last_date']

    # Convert end_date về định dạng string
    df['end_date'] = df['end_date'].dt.strftime('%d/%m/%y')
    df['start_date'] = df['start_date'].dt.strftime('%d/%m/%y')

    # Xóa các cột tạm
    df = df.drop(columns=['first_date', 'last_date', 'is_first_day', 'is_last_day', 'is_middle_day'])

    # Sắp xếp lại columns: đưa end_date lên after start_date
    cols = df.columns.tolist()
    cols.remove('end_date')
    start_idx = cols.index('start_date')
    cols.insert(start_idx + 1, 'end_date')
    df = df[cols]

    # Lưu file
    if output_path is None:
        output_path = input_path

    df.to_excel(output_path, index=False)

    # In thống kê
    total_events = df['event_name'].nunique()
    multi_day_events = df.groupby('event_name')['start_date'].count()
    multi_day_count = (multi_day_events > 1).sum()
    single_day_count = total_events - multi_day_count

    print(f" Da xu ly xong!")
    print(f"  - Tong su kien: {total_events}")
    print(f"  - Su kien 1 ngay: {single_day_count}")
    print(f"  - Su kien nhieu ngay: {multi_day_count}")
    print(f"  - Tong rows: {len(df)}")
    print(f"  - Output: {output_path}")

    return df


if __name__ == '__main__':
    input_file = 'data/events.xlsx'
    output_file = 'data/events_fixed.xlsx'

    df = fix_event_times(input_file, output_file)

    # In sample de verify (export sang CSV de tranh loi encoding)
    print("\n--- Sample exported to temp_events_fixed.csv ---")
    event_counts = df.groupby('event_name')['start_date'].count()
    multi_day_event = event_counts[event_counts > 3].index[0] if any(event_counts > 3) else None

    if multi_day_event:
        sample = df[df['event_name'] == multi_day_event][['event_name', 'start_date', 'end_date', 'start_time', 'end_time']]
        sample.to_csv('temp_events_fixed.csv', index=False, encoding='utf-8')
        print("Sample exported")
