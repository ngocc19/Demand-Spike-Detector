"""Event ingestion orchestration.

This layer deliberately stops at curated event records.  Spatial allocation and
model features are separate downstream jobs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .attendance import VenueAttendanceEstimator
from .base import EventSource, parse_datetime_utc, to_utc_iso, utc_now
from .event_csv import EventCsvExporter
from .event_workbook import EventWorkbookExporter
from .registry import build_event_source
from .storage import EventLake


LOGGER = logging.getLogger(__name__)


class EventIngestionJob:
    """Run one source through fetch, raw persistence, curation, and state."""

    def __init__(
        self,
        config: Mapping[str, Any],
        source_name: str,
        source: EventSource | None = None,
        lake: EventLake | None = None,
    ) -> None:
        self.config = dict(config)
        self.source_name = source_name
        pipeline_config = self._mapping(self.config.get("pipeline"), "pipeline")
        events_config = self._mapping(self.config.get("events"), "events")
        sources_config = self._mapping(events_config.get("sources"), "events.sources")
        source_config = self._mapping(
            sources_config.get(source_name), f"events.sources.{source_name}"
        )
        if source_config.get("enabled", True) is False:
            raise ValueError(f"Event source '{source_name}' is disabled in config.")

        self.source_config = source_config
        self.source = source or build_event_source(source_name, source_config)
        self.lake = lake or EventLake(pipeline_config.get("data_dir", "data"))
        date_window = events_config.get("event_date_window", {})
        if not isinstance(date_window, Mapping):
            raise ValueError("Config section 'events.event_date_window' must be a mapping.")
        self.attendance_estimator = VenueAttendanceEstimator(
            events_config.get("attendance_estimation", {})
        )
        self.csv_exporter = EventCsvExporter(
            self.lake.root,
            timezone_name=str(pipeline_config.get("timezone", "Asia/Ho_Chi_Minh")),
            output_file=str(events_config.get("csv_output_file", "events.csv")),
            start_date=date_window.get("start_date"),
            end_date=date_window.get("end_date"),
        )
        self.workbook_exporter = EventWorkbookExporter(
            self.lake.root,
            output_file=str(events_config.get("workbook_output_file", "events.xlsx")),
            classification=events_config.get("sheet_classification"),
        )
        self.full_scan_every_runs = self._positive_int(
            source_config.get("full_scan_every_runs", 4),
            "events.sources.full_scan_every_runs",
        )

    @classmethod
    def from_yaml(cls, config_path: str | Path, source_name: str) -> "EventIngestionJob":
        """Load the source configuration selected by the CLI."""

        path = Path(config_path)
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"Config must be a YAML mapping: {path}")
        return cls(loaded, source_name)

    def run(self, force_full_scan: bool = False) -> dict[str, Any]:
        run_started_at_utc = to_utc_iso(utc_now())
        run_id = self._run_id(run_started_at_utc)
        state = self.lake.read_source_state(self.source_name)
        full_scan = force_full_scan or self._should_run_full_scan(state)

        try:
            fetch_result = self.source.fetch(state, full_scan=full_scan)
            completed_at_utc = to_utc_iso(utc_now())

            if fetch_result.not_modified:
                csv_result = self.csv_exporter.export()
                workbook_result = self.workbook_exporter.export()
                next_state = self._next_state(
                    previous=state,
                    fetch_result=fetch_result,
                    run_id=run_id,
                    completed_at_utc=completed_at_utc,
                    full_scan=full_scan,
                    watermark_after=state.get("watermark_utc"),
                )
                state_path = self.lake.write_source_state(self.source_name, next_state)
                manifest_path = self.lake.write_manifest(
                    run_id,
                    self.source_name,
                    run_started_at_utc,
                    {
                        "status": "no_change",
                        "completed_at_utc": completed_at_utc,
                        "full_scan": full_scan,
                        "watermark_used": fetch_result.watermark_used,
                        "watermark_after": state.get("watermark_utc"),
                        "counts": {
                            "fetched": 0,
                            "valid": 0,
                            "rejected": 0,
                            "new": 0,
                            "updated": 0,
                            "unchanged": 0,
                        },
                        "http_statuses": fetch_result.http_statuses,
                        "artifacts": {
                            "state": state_path,
                            "events_csv": csv_result["path"],
                            "events_workbook": workbook_result["path"],
                        },
                        "csv_records": csv_result["records"],
                        "csv_excluded_out_of_date_window": csv_result[
                            "excluded_out_of_date_window"
                        ],
                        "workbook_sheets": workbook_result["sheets"],
                    },
                )
                return {
                    "run_id": run_id,
                    "source": self.source_name,
                    "status": "no_change",
                    "manifest_path": manifest_path,
                    "csv_path": csv_result["path"],
                    "csv_records": csv_result["records"],
                    "workbook_path": workbook_result["path"],
                    "workbook_sheets": workbook_result["sheets"],
                }

            raw_path, raw_snapshot_sha256 = self.lake.write_raw(run_id, fetch_result)
            valid_records: list[dict[str, Any]] = []
            rejected_records: list[dict[str, Any]] = []
            ingested_at_utc = completed_at_utc

            for raw_record in fetch_result.fetched_records:
                try:
                    draft = self.source.normalize(raw_record)
                    draft = self.attendance_estimator.enrich(draft)
                    valid_records.append(draft.to_record(run_id, ingested_at_utc))
                except ValueError as error:
                    rejected_records.append(
                        {
                            "source": self.source_name,
                            "run_id": run_id,
                            "rejected_at_utc": ingested_at_utc,
                            "reason": str(error),
                            "raw_record": dict(raw_record),
                        }
                    )

            staging_path = self.lake.write_staging(
                self.source_name,
                run_id,
                ingested_at_utc,
                valid_records,
            )
            quarantine_path = self.lake.write_quarantine(
                self.source_name,
                run_id,
                ingested_at_utc,
                rejected_records,
            )
            merge_result = self.lake.merge_current(
                self.source_name,
                run_id,
                ingested_at_utc,
                valid_records,
            )
            csv_result = self.csv_exporter.export()
            workbook_result = self.workbook_exporter.export()
            watermark_after = self._maximum_seen_watermark(
                fetch_result.fetched_records, state.get("watermark_utc")
            )
            next_state = self._next_state(
                previous=state,
                fetch_result=fetch_result,
                run_id=run_id,
                completed_at_utc=completed_at_utc,
                full_scan=full_scan,
                watermark_after=watermark_after,
            )
            state_path = self.lake.write_source_state(self.source_name, next_state)
            manifest_path = self.lake.write_manifest(
                run_id,
                self.source_name,
                run_started_at_utc,
                {
                    "status": "success",
                    "completed_at_utc": completed_at_utc,
                    "full_scan": full_scan,
                    "watermark_used": fetch_result.watermark_used,
                    "watermark_after": watermark_after,
                    "http_statuses": fetch_result.http_statuses,
                    "counts": {
                        "fetched": len(fetch_result.fetched_records),
                        "valid": len(valid_records),
                        "rejected": len(rejected_records),
                        "new": merge_result["new"],
                        "updated": merge_result["updated"],
                        "unchanged": merge_result["unchanged"],
                    },
                    "artifacts": {
                        "raw": raw_path,
                        "raw_snapshot_sha256": raw_snapshot_sha256,
                        "staging": staging_path,
                        "quarantine": quarantine_path,
                        "current": merge_result["current_path"],
                        "versions": merge_result["versions_path"],
                        "state": state_path,
                        "events_csv": csv_result["path"],
                        "events_workbook": workbook_result["path"],
                    },
                    "csv_records": csv_result["records"],
                    "csv_excluded_out_of_date_window": csv_result[
                        "excluded_out_of_date_window"
                    ],
                    "workbook_sheets": workbook_result["sheets"],
                },
            )
            return {
                "run_id": run_id,
                "source": self.source_name,
                "status": "success",
                "full_scan": full_scan,
                "fetched": len(fetch_result.fetched_records),
                "valid": len(valid_records),
                "rejected": len(rejected_records),
                "new": merge_result["new"],
                "updated": merge_result["updated"],
                "unchanged": merge_result["unchanged"],
                "manifest_path": manifest_path,
                "csv_path": csv_result["path"],
                "csv_records": csv_result["records"],
                "workbook_path": workbook_result["path"],
                "workbook_sheets": workbook_result["sheets"],
            }
        except Exception as error:
            LOGGER.exception("Event ingestion failed for source %s.", self.source_name)
            try:
                self.lake.write_manifest(
                    run_id,
                    self.source_name,
                    run_started_at_utc,
                    {
                        "status": "failed",
                        "completed_at_utc": to_utc_iso(utc_now()),
                        "full_scan": full_scan,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                )
            except Exception:
                LOGGER.exception(
                    "Could not write failure manifest for source %s.", self.source_name
                )
            raise

    def _should_run_full_scan(self, state: Mapping[str, Any]) -> bool:
        if not state.get("watermark_utc"):
            return True
        successful_runs = self._non_negative_int(state.get("successful_runs", 0))
        return successful_runs % self.full_scan_every_runs == 0

    def _next_state(
        self,
        previous: Mapping[str, Any],
        fetch_result: Any,
        run_id: str,
        completed_at_utc: str,
        full_scan: bool,
        watermark_after: str | None,
    ) -> dict[str, Any]:
        successful_runs = self._non_negative_int(previous.get("successful_runs", 0)) + 1
        source_state_updates = getattr(fetch_result, "state_updates", {})
        if not isinstance(source_state_updates, Mapping):
            raise ValueError("Event source state updates must be a mapping.")
        next_state = {
            **dict(previous),
            **dict(source_state_updates),
            "source": self.source_name,
            "watermark_utc": watermark_after,
            "successful_runs": successful_runs,
            "last_successful_run_id": run_id,
            "last_success_at_utc": completed_at_utc,
        }
        etag = self._header(fetch_result.response_headers, "ETag")
        last_modified = self._header(fetch_result.response_headers, "Last-Modified")
        if etag:
            next_state["etag"] = etag
        if last_modified:
            next_state["last_modified"] = last_modified
        if full_scan:
            next_state["last_full_scan_at_utc"] = completed_at_utc
        return next_state

    @staticmethod
    def _maximum_seen_watermark(
        raw_records: list[dict[str, Any]],
        existing_watermark: Any,
    ) -> str | None:
        candidates: list[str] = []
        if existing_watermark:
            try:
                parsed_existing = parse_datetime_utc(
                    existing_watermark, "state.watermark_utc"
                )
                if parsed_existing:
                    candidates.append(parsed_existing)
            except ValueError:
                pass
        for record in raw_records:
            try:
                timestamp = parse_datetime_utc(record.get("updatedAt"), "updatedAt")
            except ValueError:
                continue
            if timestamp:
                candidates.append(timestamp)
        return max(candidates) if candidates else None

    @staticmethod
    def _mapping(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError(f"Config section '{label}' must be a mapping.")
        return dict(value)

    @staticmethod
    def _positive_int(value: Any, label: str) -> int:
        parsed = EventIngestionJob._non_negative_int(value)
        if parsed < 1:
            raise ValueError(f"Config value '{label}' must be at least 1.")
        return parsed

    @staticmethod
    def _non_negative_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Expected a non-negative integer.") from error
        if parsed < 0:
            raise ValueError("Expected a non-negative integer.")
        return parsed

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str | None:
        name_lower = name.lower()
        for key, value in headers.items():
            if key.lower() == name_lower:
                return value
        return None

    @staticmethod
    def _run_id(started_at_utc: str) -> str:
        timestamp = datetime.fromisoformat(started_at_utc.replace("Z", "+00:00"))
        return f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:10]}"
