"""Small local event lake with immutable raw artifacts and versioned records."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from .base import FetchResult, canonical_json_hash


class EventLake:
    """Persist event ingestion artifacts using paths that are safe to replay."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir)

    def read_source_state(self, source: str) -> dict[str, Any]:
        path = self.root / "state" / "events" / f"{source}.json"
        if not path.exists():
            return {}
        payload = self._read_json(path)
        if not isinstance(payload, dict):
            raise ValueError(f"State file must contain a JSON object: {path}")
        return payload

    def write_source_state(self, source: str, state: Mapping[str, Any]) -> str:
        path = self.root / "state" / "events" / f"{source}.json"
        self._atomic_write_json(path, dict(state))
        return self._relative(path)

    def write_raw(self, run_id: str, result: FetchResult) -> tuple[str, str]:
        date = self._date_component(result.requested_at_utc)
        path = (
            self.root
            / "raw"
            / "events"
            / f"source={result.source}"
            / f"fetched_date={date}"
            / run_id
            / "response.json"
        )
        snapshot = {
            "source": result.source,
            "endpoint": result.endpoint,
            "requested_at_utc": result.requested_at_utc,
            "watermark_used": result.watermark_used,
            "http_statuses": result.http_statuses,
            "response_headers": result.response_headers,
            "state_updates": result.state_updates,
            "pages": result.response_pages,
        }
        snapshot_hash = canonical_json_hash(snapshot)
        self._atomic_write_json(
            path,
            {
                **snapshot,
                "raw_snapshot_sha256": snapshot_hash,
            },
        )
        return self._relative(path), snapshot_hash

    def write_staging(
        self,
        source: str,
        run_id: str,
        ingested_at_utc: str,
        records: Iterable[Mapping[str, Any]],
    ) -> str:
        date = self._date_component(ingested_at_utc)
        path = (
            self.root
            / "staging"
            / "events"
            / f"source={source}"
            / f"ingested_date={date}"
            / run_id
            / "events.jsonl"
        )
        self._atomic_write_jsonl(path, records)
        return self._relative(path)

    def write_quarantine(
        self,
        source: str,
        run_id: str,
        ingested_at_utc: str,
        records: Iterable[Mapping[str, Any]],
    ) -> str | None:
        materialized = list(records)
        if not materialized:
            return None
        date = self._date_component(ingested_at_utc)
        path = (
            self.root
            / "quarantine"
            / "events"
            / f"source={source}"
            / f"ingested_date={date}"
            / run_id
            / "rejected_records.jsonl"
        )
        self._atomic_write_jsonl(path, materialized)
        return self._relative(path)

    def merge_current(
        self,
        source: str,
        run_id: str,
        ingested_at_utc: str,
        records: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Append changed revisions and atomically materialize current records."""

        current_path = (
            self.root
            / "curated"
            / "events_current"
            / f"source={source}"
            / "events.jsonl"
        )
        existing = {
            str(record["event_id"]): record for record in self._read_jsonl(current_path)
        }
        incoming = self._deduplicate_batch(records)
        versions: list[dict[str, Any]] = []
        counts = {"new": 0, "updated": 0, "unchanged": 0}

        for event_id in sorted(incoming):
            record = dict(incoming[event_id])
            previous = existing.get(event_id)
            record["first_seen_at_utc"] = (
                previous.get("first_seen_at_utc", ingested_at_utc)
                if previous
                else ingested_at_utc
            )
            record["last_seen_at_utc"] = ingested_at_utc

            if previous is None:
                record["revision"] = 1
                record["change_type"] = "new"
                versions.append(dict(record))
                counts["new"] += 1
            elif previous.get("version_hash") == record.get("version_hash"):
                record["revision"] = int(previous.get("revision", 1))
                record["change_type"] = previous.get("change_type", "unchanged")
                counts["unchanged"] += 1
            else:
                record["revision"] = int(previous.get("revision", 1)) + 1
                record["change_type"] = "updated"
                versions.append(dict(record))
                counts["updated"] += 1

            existing[event_id] = record

        date = self._date_component(ingested_at_utc)
        versions_path = (
            self.root
            / "curated"
            / "event_versions"
            / f"ingested_date={date}"
            / f"source={source}"
            / f"{run_id}.jsonl"
        )
        self._atomic_write_jsonl(versions_path, versions)
        self._atomic_write_jsonl(
            current_path,
            (existing[event_id] for event_id in sorted(existing)),
        )
        return {
            **counts,
            "current_path": self._relative(current_path),
            "versions_path": self._relative(versions_path),
        }

    def write_manifest(
        self,
        run_id: str,
        source: str,
        run_started_at_utc: str,
        payload: Mapping[str, Any],
    ) -> str:
        date = self._date_component(run_started_at_utc)
        path = (
            self.root
            / "manifests"
            / "events"
            / f"ingested_date={date}"
            / f"{run_id}.json"
        )
        self._atomic_write_json(
            path,
            {
                "run_id": run_id,
                "source": source,
                "run_started_at_utc": run_started_at_utc,
                **dict(payload),
            },
        )
        return self._relative(path)

    def _deduplicate_batch(
        self, records: Iterable[Mapping[str, Any]]
    ) -> dict[str, Mapping[str, Any]]:
        selected: dict[str, Mapping[str, Any]] = {}
        for record in records:
            event_id = record.get("event_id")
            version_hash = record.get("version_hash")
            if not isinstance(event_id, str) or not event_id:
                raise ValueError("Curated records require a non-empty event_id.")
            if not isinstance(version_hash, str) or not version_hash:
                raise ValueError("Curated records require a non-empty version_hash.")

            previous = selected.get(event_id)
            if previous is None or self._batch_order(record) >= self._batch_order(previous):
                selected[event_id] = record
        return selected

    @staticmethod
    def _batch_order(record: Mapping[str, Any]) -> tuple[str, str]:
        return (
            str(record.get("source_updated_at_utc") or ""),
            str(record.get("version_hash") or ""),
        )

    @staticmethod
    def _date_component(timestamp: str) -> str:
        if len(timestamp) >= 10 and timestamp[4] == "-" and timestamp[7] == "-":
            return timestamp[:10]
        raise ValueError(f"Expected an ISO date-time, got {timestamp!r}.")

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _read_json(path: Path) -> Any:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"Invalid JSONL record at {path}:{line_number}."
                    ) from error
                if not isinstance(record, dict):
                    raise ValueError(
                        f"JSONL records must be objects at {path}:{line_number}."
                    )
                records.append(record)
        return records

    @staticmethod
    def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        EventLake._atomic_write_text(path, text)

    @staticmethod
    def _atomic_write_jsonl(
        path: Path,
        records: Iterable[Mapping[str, Any]],
    ) -> None:
        text = "".join(
            json.dumps(dict(record), ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        )
        EventLake._atomic_write_text(path, text)

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
