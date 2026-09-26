"""Shared contracts and deterministic helpers for event ingestion."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


UTC = timezone.utc
EVENT_SCHEMA_VERSION = "1.0"


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def to_utc_iso(value: datetime) -> str:
    """Serialize a timezone-aware datetime in one canonical UTC form."""

    if value.tzinfo is None:
        raise ValueError("Datetime must include a timezone.")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_datetime_utc(value: object, field_name: str) -> str | None:
    """Parse an ISO-8601 source timestamp and return canonical UTC text."""

    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 string or null.")

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{field_name} is not a valid ISO-8601 timestamp.") from error

    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include an explicit timezone.")
    return to_utc_iso(parsed)


def canonical_json_hash(value: object) -> str:
    """Hash JSON deterministically so records can be versioned reliably."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FetchResult:
    """Raw response material from a source before source-specific parsing."""

    source: str
    endpoint: str
    requested_at_utc: str
    response_pages: list[dict[str, Any]]
    fetched_records: list[dict[str, Any]]
    http_statuses: list[int]
    watermark_used: str | None
    response_headers: dict[str, str] = field(default_factory=dict)
    state_updates: dict[str, Any] = field(default_factory=dict)
    not_modified: bool = False


@dataclass(frozen=True)
class EventDraft:
    """A normalized event before it is assigned a revision by storage."""

    source: str
    source_event_id: str
    title: str
    description: str | None
    raw_category: str | None
    primary_category: str
    publication_status: str | None
    event_status: str
    start_at_utc: str
    end_at_utc: str | None
    venue_raw: str | None
    source_url: str
    source_created_at_utc: str | None
    source_updated_at_utc: str | None
    raw_payload_sha256: str
    city: str = "hanoi"
    tags: list[str] = field(default_factory=list)
    estimated_attendees: int | None = None
    attendee_estimation_method: str | None = None
    venue_capacity: int | None = None
    venue_capacity_key: str | None = None
    official_attendance: int | None = None
    attendance_source_url: str | None = None

    def to_record(self, run_id: str, ingested_at_utc: str) -> dict[str, Any]:
        """Return the canonical curated record without storage-owned fields."""

        event_id = f"{self.source}:{self.source_event_id}"
        version_material = {
            "source": self.source,
            "source_event_id": self.source_event_id,
            "title": self.title,
            "description": self.description,
            "raw_category": self.raw_category,
            "primary_category": self.primary_category,
            "publication_status": self.publication_status,
            "event_status": self.event_status,
            "start_at_utc": self.start_at_utc,
            "end_at_utc": self.end_at_utc,
            "venue_raw": self.venue_raw,
            "source_url": self.source_url,
            "source_created_at_utc": self.source_created_at_utc,
            "source_updated_at_utc": self.source_updated_at_utc,
            "raw_payload_sha256": self.raw_payload_sha256,
            "city": self.city,
            "tags": self.tags,
            "estimated_attendees": self.estimated_attendees,
            "attendee_estimation_method": self.attendee_estimation_method,
            "venue_capacity": self.venue_capacity,
            "venue_capacity_key": self.venue_capacity_key,
            "official_attendance": self.official_attendance,
            "attendance_source_url": self.attendance_source_url,
        }
        return {
            "event_id": event_id,
            **version_material,
            "version_hash": canonical_json_hash(version_material),
            "venue_id": None,
            "latitude": None,
            "longitude": None,
            "location_status": "unresolved" if self.venue_raw else "missing",
            "ingested_at_utc": ingested_at_utc,
            "run_id": run_id,
            "schema_version": EVENT_SCHEMA_VERSION,
        }


class EventSource(ABC):
    """Contract implemented by each permitted event source adapter."""

    source_name: str

    @abstractmethod
    def fetch(self, state: Mapping[str, Any], full_scan: bool) -> FetchResult:
        """Fetch source payloads without mutating persistent state."""

        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw_record: Mapping[str, Any]) -> EventDraft:
        """Turn one source-specific record into the common event contract."""

        raise NotImplementedError
