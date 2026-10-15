"""Exporter cho Event Realtime - Export to Excel/CSV.

Theo PLAN_event_realtime.md: 12 cột giống event_fixed.xlsx.
"""
from __future__ import annotations

import csv
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, List, Optional, Dict
from zoneinfo import ZoneInfo

import pandas as pd

from .models import RealtimeEvent, EventState


# Output columns: 12 cột theo plan
OUTPUT_COLUMNS = [
    "event_name",
    "venue",
    "start_date",
    "start_time",
    "end_time",
    "type",
    "estimate_attendence",
    "source_url",
    "attendance_source_url",
    "latitude",
    "longitude",
    "h3_index",
]


class EventRealtimeExporter:
    """
    Exporter cho event realtime.

    Output columns (13):
    - event_name
    - venue
    - start_date (DD/MM/YY)
    - end_date (DD/MM/YY)
    - start_time (HH:MM)
    - end_time (HH:MM)
    - type (category)
    - estimate_attendence (nullable - để trống nếu không có)
    - source_url
    - attendance_source_url (nullable)
    - latitude (nullable)
    - longitude (nullable)
    - h3_index (nullable)

    Features:
    - Expand multi-day events vào nhiều rows (1 row/ngày)
    - Events chưa diễn ra: estimate_attendence = empty
    - Atomic write (không corrupt nếu crash)
    """

    def __init__(
        self,
        data_dir: str | Path,
        timezone_name: str = "Asia/Ho_Chi_Minh",
        output_xlsx: str = "event_realtime.xlsx",
        output_csv: str = "event_realtime.csv",
    ) -> None:
        data_dir = Path(data_dir)
        # Resolve relative paths to absolute, anchored at project root.
        # Mirrors EventRealtimeStore behavior for consistency.
        if not data_dir.is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            data_dir = project_root / data_dir
        self.data_dir = data_dir
        self.timezone = ZoneInfo(timezone_name)
        self.output_xlsx = self.data_dir / output_xlsx
        self.output_csv = self.data_dir / output_csv

    def export(
        self,
        events: List[RealtimeEvent | EventState],
    ) -> Dict[str, Any]:
        """
        Export events ra .xlsx và .csv.

        Args:
            events: List of RealtimeEvent hoặc EventState

        Returns:
            Dict với thông tin export
        """
        # Convert to EventState if needed
        states = self._to_states(events)

        # Filter events: include events within a window (past 90 days to future)
        now = datetime.now(self.timezone)
        window_start = now - timedelta(days=90)  # Include last 90 days for fireworks
        upcoming = []
        for s in states:
            if s.start_at is None:
                upcoming.append(s)
                continue
            # Convert to local
            start_local = self._to_local_datetime(s.start_at)
            if start_local is None:
                upcoming.append(s)
                continue
            # Include if within window
            if start_local >= window_start:
                upcoming.append(s)

        # Generate rows
        rows = []
        for state in upcoming:
            event_rows = self._to_rows(state)
            rows.extend(event_rows)

        # Sort by date, time, name
        rows.sort(key=lambda r: (
            r.get("start_date", ""),
            r.get("start_time", ""),
            r.get("event_name", ""),
            r.get("venue", ""),
        ))

        # Write files
        self._write_xlsx(rows)
        self._write_csv(rows)

        return {
            "xlsx_path": str(self.output_xlsx.relative_to(self.data_dir)),
            "csv_path": str(self.output_csv.relative_to(self.data_dir)),
            "total_rows": len(rows),
            "total_events": len(upcoming),
        }

    def _to_states(
        self,
        events: List[RealtimeEvent | EventState],
    ) -> List[EventState]:
        """Convert mixed list to EventState list."""
        states = []
        for event in events:
            if isinstance(event, EventState):
                states.append(event)
            else:
                # RealtimeEvent -> EventState
                states.append(EventState.from_realtime_event(event))
        return states

    def _to_rows(self, state: EventState) -> List[Dict[str, Any]]:
        """
        Expand multi-day event vào nhiều rows (12 cột theo plan).

        Attendance mô tả cả event, không phải mỗi ngày.
        Chỉ giữ lại ở row đầu tiên.

        Logic cho multi-day:
        - Ngày 1: start_time = giờ bắt đầu thực, end_time = 23:59
        - Ngày giữa: start_time = 00:00, end_time = 23:59
        - Ngày cuối: start_time = 00:00, end_time = giờ kết thúc thực
        """
        rows = []

        # Parse start/end in timezone
        start = self._to_local_datetime(state.start_at)
        if start is None:
            return rows

        end = self._to_local_datetime(state.end_at)
        if end is None:
            # No end time - assume event ends at 23:59 same day
            end = start.replace(hour=23, minute=59)

        final_date = max(start.date(), end.date())
        start_date = start.date()

        # Get attendance (nullable)
        attendance = state.estimated_attendees

        # If the source provided a real end_at, treat it as the real end
        # of the first day; otherwise expand the first day to 23:59 so
        # multi-day events (which the source only stamps on day 1) are
        # not cut short. A 23:59 end on the first day is the "no info"
        # signal coming from the plugins.
        first_day_end = end.strftime("%H:%M")
        if first_day_end == "23:59":
            first_day_end = "23:59"  # explicit, matches multi-day default

        current_date = start_date
        while current_date <= final_date:
            is_first = current_date == start_date
            is_last = current_date == final_date

            # Determine start_time và end_time cho mỗi ngày
            if is_first and is_last:
                # Event trong 1 ngày: dùng đúng giờ từ source
                row_start_time = start.strftime("%H:%M")
                row_end_time = first_day_end
            elif is_first:
                # Ngày đầu tiên của multi-day
                # Nếu source có end thật (≠ 23:59) thì dùng, ngược lại 23:59
                row_start_time = start.strftime("%H:%M")
                row_end_time = first_day_end
            elif is_last:
                # Ngày cuối cùng của multi-day
                row_start_time = "00:00"
                row_end_time = end.strftime("%H:%M")
            else:
                # Ngày giữa
                row_start_time = "00:00"
                row_end_time = "23:59"

            rows.append({
                "event_name": state.title,
                "venue": state.venue,
                "start_date": current_date.strftime("%d/%m/%y"),
                "start_time": row_start_time,
                "end_time": row_end_time,
                "type": state.category,
                "estimate_attendence": int(attendance) if is_first and attendance is not None else "",
                "source_url": state.current_source_url,
                "attendance_source_url": state.attendance_source_url or "",
                "latitude": self._format_float(state.latitude),
                "longitude": self._format_float(state.longitude),
                "h3_index": state.h3_index or "",
            })

            current_date += timedelta(days=1)

        return rows

    def _to_local_datetime(self, value: Any) -> datetime | None:
        """Convert to local datetime."""
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None

        # Convert to local timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.timezone)
        return dt.astimezone(self.timezone)

    @staticmethod
    def _format_float(value: Optional[float]) -> str:
        """Format float to string, empty if None."""
        if value is None:
            return ""
        return f"{value:.6f}"

    def _write_xlsx(self, rows: List[Dict[str, Any]]) -> None:
        """Write to Excel file."""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font

            df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)

            # Ensure output directory exists
            self.output_xlsx.parent.mkdir(parents=True, exist_ok=True)

            # Atomic write - use temp file
            temp_file = self.output_xlsx.with_suffix(".tmp.xlsx")

            with pd.ExcelWriter(temp_file, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Events")

            # Replace - handle file lock by using copy + remove
            if self.output_xlsx.exists():
                try:
                    self.output_xlsx.unlink()
                except PermissionError:
                    # File is locked (probably open in Excel) - just overwrite temp
                    # Keep old file, skip replace
                    import shutil
                    backup_file = self.output_xlsx.with_suffix(".bak.xlsx")
                    try:
                        shutil.copy2(str(self.output_xlsx), str(backup_file))
                    except Exception:
                        pass
                    # Try to remove again
                    try:
                        self.output_xlsx.unlink()
                    except PermissionError:
                        # File still locked - try direct overwrite via rename
                        import os
                        if os.name == 'nt':
                            os.replace(str(temp_file), str(self.output_xlsx))
                            return
                        raise
            temp_file.rename(self.output_xlsx)

        except ImportError:
            # openpyxl not installed, skip xlsx
            pass
        except PermissionError as e:
            # If file is locked, just skip xlsx update
            import logging
            logging.warning(f"Could not update xlsx (file locked): {e}")
        except Exception as e:
            import logging
            logging.error(f"Error writing xlsx: {e}")

    def _write_csv(self, rows: List[Dict[str, Any]]) -> None:
        """Write to CSV file."""
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write
        temp_file = self.output_csv.with_suffix(".tmp")

        with open(temp_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=OUTPUT_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)

        # Replace
        if self.output_csv.exists():
            self.output_csv.unlink()
        temp_file.rename(self.output_csv)
