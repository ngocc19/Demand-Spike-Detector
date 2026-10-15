"""Storage layer cho Event Realtime.

Inspired by weather_realtime (realtime_crawler.py) pattern:
- Parquet partitioned by date
- State JSON
- Trace CSV
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Iterable

import pandas as pd

from .models import EventState, EventTrace

logger = logging.getLogger(__name__)


class EventRealtimeStore:
    """
    Storage layer cho event realtime.

    Structure:
    data/
    ├── event_realtime/
    │   ├── events/
    │   │   └── date=2026-09-29/
    │   │       └── events.parquet
    │   ├── state.json
    │   └── traces/
    │       └── date=2026-09-29/
    │           └── traces.csv
    └── event_realtime.xlsx
    """

    def __init__(self, data_dir: str | Path):
        data_dir = Path(data_dir)
        # Resolve relative paths to absolute, anchored at project root.
        # This ensures storage is consistent regardless of CWD.
        if not data_dir.is_absolute():
            # Project root is 3 levels up: src/pipeline/event_realtime/storage.py
            project_root = Path(__file__).parent.parent.parent.parent
            data_dir = project_root / data_dir
        self.data_dir = data_dir
        self.realtime_dir = self.data_dir / "event_realtime"
        self.events_dir = self.realtime_dir / "events"
        self.traces_dir = self.realtime_dir / "traces"
        self.state_file = self.realtime_dir / "state.json"

        # Ensure directories exist
        self.realtime_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.traces_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================

    def load_state(self) -> Dict[str, EventState]:
        """Load known events từ state file."""
        if not self.state_file.exists():
            return {}

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            states = {}
            for item in data.get("states", []):
                try:
                    state = EventState.from_dict(item)
                    states[state.event_id] = state
                except Exception as e:
                    print(f"Failed to load state: {e}")
                    continue

            return states
        except Exception as e:
            print(f"Failed to load state file: {e}")
            return {}

    def save_state(self, states: Dict[str, EventState]) -> None:
        """Save state to JSON file."""
        states_data = []
        for event_id, state in states.items():
            states_data.append(state.to_dict())

        data = {
            "saved_at": datetime.now().isoformat(),
            "total_events": len(states),
            "states": states_data,
        }

        # Atomic write
        temp_file = self.state_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Replace
            if self.state_file.exists():
                self.state_file.unlink()
            temp_file.rename(self.state_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

    # =========================================================================
    # EVENTS STORAGE (Parquet)
    # =========================================================================

    def save_events(self, events: List[Dict[str, Any]], crawl_time: Optional[datetime] = None) -> None:
        """
        Save events to Parquet file partitioned by crawl date.

        Mỗi lần crawl tạo 1 row snapshot cho mỗi event. Dedup theo
        (event_id, crawl_time) để tránh trùng khi re-save cùng crawl.

        Args:
            events: List of event dicts (RealtimeEvent or EventState)
            crawl_time: Thời gian crawl. Nếu None, dùng datetime.now().
        """
        if not events:
            return

        if crawl_time is None:
            crawl_time = datetime.now()

        df = pd.DataFrame(events)

        # Add crawl_time as snapshot timestamp
        df["crawl_time"] = crawl_time.isoformat()
        df["fetched_at"] = crawl_time.isoformat()

        # Parse dates
        for col in ["start_at", "end_at", "fetched_at", "crawl_time"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        # Partition by CRAWL date (not event start date) - per PLAN_event_realtime.md
        # This way each crawl creates one partition, regardless of which events
        df["date"] = crawl_time.strftime("%Y-%m-%d")

        # Normalize event_id column (ensure it exists for dedup)
        if "event_id" not in df.columns:
            logger.warning("save_events: events missing event_id, skipping")
            return

        date_dir = self.events_dir / f"date={df['date'].iloc[0]}"
        date_dir.mkdir(parents=True, exist_ok=True)

        output_file = date_dir / "events.parquet"

        if output_file.exists():
            # Read existing and append
            existing_df = pd.read_parquet(output_file)
            combined_df = pd.concat([existing_df, df], ignore_index=True)

            # Dedup by (event_id, crawl_time) - keep latest
            # This handles re-saves of the same crawl (idempotent)
            combined_df = combined_df.drop_duplicates(
                subset=["event_id", "crawl_time"],
                keep="last"
            )

            combined_df.to_parquet(output_file, index=False)
        else:
            df.to_parquet(output_file, index=False)

        logger.info(
            f"Saved {len(df)} events to {output_file.relative_to(self.realtime_dir)}"
        )

    def load_events(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load events từ Parquet files.

        Args:
            from_date: Filter events from this date
            to_date: Filter events until this date
        """
        events = []

        # Find all date partitions
        for partition_dir in self.events_dir.glob("date=*"):
            if not partition_dir.is_dir():
                continue

            date_str = partition_dir.name.replace("date=", "")
            partition_date = datetime.strptime(date_str, "%Y-%m-%d")

            # Apply date filters
            if from_date and partition_date < from_date:
                continue
            if to_date and partition_date > to_date:
                continue

            # Read parquet
            parquet_file = partition_dir / "events.parquet"
            if parquet_file.exists():
                df = pd.read_parquet(parquet_file)
                events.extend(df.to_dict(orient="records"))

        return events

    def get_latest_events(
        self,
        horizon_days: int = 90,
    ) -> List[Dict[str, Any]]:
        """
        Get latest events within horizon.

        Args:
            horizon_days: Number of days in the future
        """
        cutoff = datetime.now() + pd.Timedelta(days=horizon_days)
        return self.load_events(to_date=cutoff)

    def get_event_history(self, event_id: str) -> List[Dict[str, Any]]:
        """
        Get all snapshots of a specific event across crawl history.

        Useful for ML training / audit - xem event đã thay đổi như thế nào
        qua các lần crawl.

        Args:
            event_id: Event ID (e.g. "van_mieu:123")

        Returns:
            List of snapshots sorted by crawl_time ascending
        """
        snapshots = []
        for partition_dir in self.events_dir.glob("date=*"):
            parquet_file = partition_dir / "events.parquet"
            if not parquet_file.exists():
                continue
            df = pd.read_parquet(parquet_file)
            matching = df[df["event_id"] == event_id]
            if not matching.empty:
                snapshots.extend(matching.to_dict(orient="records"))

        # Sort by crawl_time
        snapshots.sort(key=lambda x: x.get("crawl_time", ""))
        return snapshots

    def get_snapshots_at(self, crawl_date: str) -> List[Dict[str, Any]]:
        """
        Get all event snapshots from a specific crawl date.

        Args:
            crawl_date: Date string in YYYY-MM-DD format
        """
        partition_dir = self.events_dir / f"date={crawl_date}"
        parquet_file = partition_dir / "events.parquet"
        if not parquet_file.exists():
            return []
        df = pd.read_parquet(parquet_file)
        return df.to_dict(orient="records")

    # =========================================================================
    # TRACE LOGGING (CSV)
    # =========================================================================

    TRACE_COLUMNS = [
        "trace_id",
        "crawl_time",
        "source",
        "event_id",
        "title",
        "change_type",
        "old_start_at",
        "new_start_at",
        "old_venue",
        "new_venue",
        "source_url",
        "source_urls_history",
        "changes_detail",
        "impact",
        "should_notify",
    ]

    def log_traces(self, traces: List[EventTrace]) -> None:
        """
        Log traces to CSV file (append mode).

        Args:
            traces: List of EventTrace objects
        """
        if not traces:
            return

        # Get today's date partition
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = self.traces_dir / f"date={date_str}"
        date_dir.mkdir(parents=True, exist_ok=True)

        output_file = date_dir / "traces.csv"

        # Convert traces to dicts
        rows = [trace.to_dict() for trace in traces]

        # Write CSV
        file_exists = output_file.exists()

        with open(output_file, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=self.TRACE_COLUMNS,
                lineterminator="\n",
            )

            if not file_exists:
                writer.writeheader()

            writer.writerows(rows)

    def load_traces(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        change_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Load traces from CSV files.

        Args:
            from_date: Filter traces from this date
            to_date: Filter traces until this date
            change_types: Filter by change types (NEW, UPDATED, CANCELLED, CONFIRMED)
        """
        traces = []

        for partition_dir in self.traces_dir.glob("date=*"):
            if not partition_dir.is_dir():
                continue

            date_str = partition_dir.name.replace("date=", "")
            partition_date = datetime.strptime(date_str, "%Y-%m-%d")

            # Apply date filters
            if from_date and partition_date < from_date:
                continue
            if to_date and partition_date > to_date:
                continue

            # Read CSV
            csv_file = partition_dir / "traces.csv"
            if csv_file.exists():
                df = pd.read_csv(csv_file)

                # Filter by change type
                if change_types:
                    df = df[df["change_type"].isin(change_types)]

                traces.extend(df.to_dict(orient="records"))

        return traces

    def get_recent_changes(
        self,
        hours: int = 24,
        high_impact_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get recent changes in the last N hours.

        Args:
            hours: Number of hours to look back
            high_impact_only: Only return high impact changes
        """
        cutoff = datetime.now() - pd.Timedelta(hours=hours)

        traces = self.load_traces(
            from_date=cutoff,
            change_types=["NEW", "UPDATED", "CANCELLED"] if high_impact_only else None,
        )

        # Filter by impact if needed
        if high_impact_only:
            traces = [t for t in traces if t.get("impact", 0) >= 0.5]

        return traces

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        # Count events
        event_count = 0
        for partition_dir in self.events_dir.glob("date=*"):
            parquet_file = partition_dir / "events.parquet"
            if parquet_file.exists():
                df = pd.read_parquet(parquet_file)
                event_count += len(df)

        # Count traces
        trace_count = 0
        trace_by_type: Dict[str, int] = {}
        for partition_dir in self.traces_dir.glob("date=*"):
            csv_file = partition_dir / "traces.csv"
            if csv_file.exists():
                df = pd.read_csv(csv_file)
                trace_count += len(df)

                for change_type, count in df["change_type"].value_counts().items():
                    trace_by_type[change_type] = trace_by_type.get(change_type, 0) + count

        # Count state
        state_count = len(self.load_state())

        return {
            "total_events": event_count,
            "total_traces": trace_count,
            "traces_by_type": trace_by_type,
            "known_events_in_state": state_count,
            "events_partitions": len(list(self.events_dir.glob("date=*"))),
            "traces_partitions": len(list(self.traces_dir.glob("date=*"))),
        }
