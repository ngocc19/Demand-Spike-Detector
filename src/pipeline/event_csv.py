"""Materialize the curated event store into the CSV contract in crawl_data.md."""

from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


CSV_COLUMNS = (
    "event_name",
    "venue",
    "start_date",
    "start_time",
    "end_time",
    "type",
    "estimate_attendence",
    "source_url",
    "attendance_source_url",
)


class EventCsvExporter:
    """Build one compatibility CSV from all currently curated event sources."""

    def __init__(
        self,
        data_dir: str | Path,
        timezone_name: str = "Asia/Ho_Chi_Minh",
        output_file: str = "event.csv",
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.timezone = ZoneInfo(timezone_name)
        relative_output = Path(output_file)
        if relative_output.is_absolute() or ".." in relative_output.parts:
            raise ValueError("events.csv_output_file must stay inside the data directory.")
        self.output_path = self.data_dir / relative_output
        self.start_date = self._parse_scope_date(start_date, "start_date")
        self.end_date = self._parse_scope_date(end_date, "end_date")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("events.event_date_window.end_date precedes start_date.")

    def export(self) -> dict[str, Any]:
        records = self._read_current_records()
        included_records = [
            record for record in records if self._is_in_date_window(record)
        ]
        included_records = self._deduplicate_same_public_event(included_records)
        rows = [row for record in included_records for row in self._to_csv_rows(record)]
        rows.sort(key=lambda row: (row["start_date"], row["start_time"], row["event_name"], row["venue"]))
        self._atomic_write(rows)
        return {
            "path": self.output_path.relative_to(self.data_dir).as_posix(),
            "records": len(rows),
            "excluded_out_of_date_window": len(records) - len(included_records),
        }

    @staticmethod
    def _deduplicate_same_public_event(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge records only when sources point to the same public event page/time.

        A single Ticketbox event can be discovered by more than one category
        connector (for example, a music festival).  It must appear once in the
        canonical CSV so feature jobs do not count it twice.  Festival wins over
        concert when the event is explicitly identified as both; reported
        attendance evidence from the duplicate is retained.
        """

        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        independent: list[dict[str, Any]] = []
        for record in records:
            source_url = record.get("source_url")
            start_at_utc = record.get("start_at_utc")
            title = record.get("title")
            if not all(isinstance(value, str) and value for value in (source_url, start_at_utc, title)):
                independent.append(record)
                continue
            groups.setdefault((source_url, start_at_utc, title), []).append(record)

        merged = list(independent)
        for group in groups.values():
            winner = min(
                group,
                key=lambda record: (
                    0 if record.get("primary_category") == "festival" else 1,
                    0 if record.get("estimated_attendees") is not None else 1,
                    str(record.get("event_id") or ""),
                ),
            )
            merged_record = dict(winner)
            evidence = next(
                (
                    record
                    for record in group
                    if record.get("estimated_attendees") is not None
                    and record.get("attendance_source_url")
                ),
                None,
            )
            if evidence is not None and merged_record.get("estimated_attendees") is None:
                merged_record["estimated_attendees"] = evidence["estimated_attendees"]
                merged_record["attendance_source_url"] = evidence["attendance_source_url"]
            merged.append(merged_record)
        return merged

    def _read_current_records(self) -> list[dict[str, Any]]:
        current_root = self.data_dir / "curated" / "events_current"
        if not current_root.exists():
            return []
        records_by_event_id: dict[str, dict[str, Any]] = {}
        for path in sorted(current_root.glob("source=*/events.jsonl")):
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"Invalid curated event JSON at {path}:{line_number}."
                        ) from error
                    event_id = record.get("event_id")
                    if not isinstance(event_id, str) or not event_id:
                        raise ValueError(
                            f"Curated event requires event_id at {path}:{line_number}."
                        )
                    records_by_event_id[event_id] = record
        return list(records_by_event_id.values())

    def _to_csv_rows(self, record: dict[str, Any]) -> list[dict[str, str | int]]:
        """Expand a multi-day event into one row per local calendar day.

        Attendance describes the whole event, not each day.  It is retained on
        the first row only so summing exported rows never triples demand.
        """
        estimate = record.get("estimated_attendees")
        start = self._to_hanoi_datetime(record.get("start_at_utc"))
        if start is None:
            return []
        end = self._to_hanoi_datetime(record.get("end_at_utc")) or start
        final_date = max(start.date(), end.date())
        rows: list[dict[str, str | int]] = []
        current_date = start.date()
        while current_date <= final_date:
            if (self.start_date and current_date < self.start_date) or (self.end_date and current_date > self.end_date):
                current_date += timedelta(days=1)
                continue
            is_first = not rows
            rows.append({
                "event_name": str(record.get("title") or ""),
                "venue": str(record.get("venue_raw") or ""),
                "start_date": current_date.strftime("%d/%m/%y"),
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M"),
                "type": str(record.get("primary_category") or "other"),
                "estimate_attendence": int(estimate) if is_first and estimate is not None else "",
                "source_url": str(record.get("source_url") or ""),
                "attendance_source_url": str(record.get("attendance_source_url") or ""),
            })
            current_date += timedelta(days=1)
        return rows

    def _to_hanoi_datetime(self, value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"Expected an ISO event timestamp, got {value!r}.") from error
        if parsed.tzinfo is None:
            raise ValueError(f"Event timestamp must include a timezone: {value!r}.")
        return parsed.astimezone(self.timezone)

    def _is_in_date_window(self, record: dict[str, Any]) -> bool:
        local_start = self._to_hanoi_datetime(record.get("start_at_utc"))
        if local_start is None:
            return False
        local_date = local_start.date()
        if self.start_date and local_date < self.start_date:
            return False
        if self.end_date and local_date > self.end_date:
            return False
        return True

    @staticmethod
    def _parse_scope_date(value: str | date | None, label: str) -> date | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            raise ValueError(f"events.event_date_window.{label} must be YYYY-MM-DD.")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(
                f"events.event_date_window.{label} must be YYYY-MM-DD."
            ) from error

    def _atomic_write(self, rows: list[dict[str, str | int]]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.output_path.with_suffix(f"{self.output_path.suffix}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            os.replace(temporary_path, self.output_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
