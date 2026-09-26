"""Transparent venue-capacity heuristics for event attendance estimates."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any, Mapping

from .base import EventDraft


@dataclass(frozen=True)
class VenueCapacity:
    """One canonical venue and the phrases that can identify it."""

    key: str
    capacity: int
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ReportedAttendanceOverride:
    """A manually verified attendance figure tied to one exact event."""

    source: str
    title: str
    start_at_utc: str
    attendance: int
    source_url: str


class VenueAttendanceEstimator:
    """Estimate attendance from configured capacity and type-specific fill rate."""

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        config = dict(config or {})
        self.fill_missing_with_heuristic = self._boolean(
            config.get("fill_missing_with_heuristic", False),
            "events.attendance_estimation.fill_missing_with_heuristic",
        )
        self.default_capacity = self._positive_int(
            config.get("default_venue_capacity", 1000),
            "events.attendance_estimation.default_venue_capacity",
        )
        self.default_fill_rate = self._fill_rate(
            config.get("default_fill_rate", 0.50),
            "events.attendance_estimation.default_fill_rate",
        )
        raw_fill_rates = config.get("fill_rates", {})
        if not isinstance(raw_fill_rates, Mapping):
            raise ValueError("events.attendance_estimation.fill_rates must be a mapping.")
        self.fill_rates = {
            str(event_type): self._fill_rate(value, f"fill_rates.{event_type}")
            for event_type, value in raw_fill_rates.items()
        }
        self.venues = self._parse_venues(config.get("venue_capacities", {}))
        self.reported_attendance_overrides = self._parse_reported_attendance_overrides(
            config.get("reported_attendance_overrides", [])
        )

    def enrich(self, draft: EventDraft) -> EventDraft:
        """Attach an auditable heuristic; it is not observed ticket sales."""

        venue = self._match_venue(draft.venue_raw)
        override = self._match_reported_attendance_override(draft)
        if override is not None:
            return replace(
                draft,
                official_attendance=override.attendance,
                attendance_source_url=override.source_url,
                estimated_attendees=override.attendance,
                attendee_estimation_method="verified_reported_attendance",
                venue_capacity=venue.capacity if venue else None,
                venue_capacity_key=venue.key if venue else None,
            )
        if draft.official_attendance is not None:
            return replace(
                draft,
                estimated_attendees=draft.official_attendance,
                attendee_estimation_method="official_reported_attendance",
                venue_capacity=venue.capacity if venue else None,
                venue_capacity_key=venue.key if venue else None,
            )
        if not self.fill_missing_with_heuristic:
            return replace(
                draft,
                estimated_attendees=None,
                attendee_estimation_method=None,
                venue_capacity=None,
                venue_capacity_key=None,
            )
        capacity = venue.capacity if venue else self.default_capacity
        fill_rate = self.fill_rates.get(
            draft.primary_category,
            self.fill_rates.get("other", self.default_fill_rate),
        )
        method = (
            "venue_capacity_x_fill_rate"
            if venue
            else "default_capacity_x_fill_rate"
        )
        return replace(
            draft,
            estimated_attendees=int(capacity * fill_rate),
            attendee_estimation_method=method,
            venue_capacity=capacity,
            venue_capacity_key=venue.key if venue else None,
        )

    def _parse_reported_attendance_overrides(
        self, raw_overrides: object
    ) -> tuple[ReportedAttendanceOverride, ...]:
        if not isinstance(raw_overrides, list):
            raise ValueError(
                "events.attendance_estimation.reported_attendance_overrides must be a list."
            )
        parsed: list[ReportedAttendanceOverride] = []
        seen: set[tuple[str, str, str]] = set()
        for index, raw_override in enumerate(raw_overrides):
            label = f"reported_attendance_overrides[{index}]"
            if not isinstance(raw_override, Mapping):
                raise ValueError(f"{label} must be a mapping.")
            source = self._required_string(raw_override.get("source"), f"{label}.source")
            title = self._required_string(raw_override.get("title"), f"{label}.title")
            start_at_utc = self._required_string(
                raw_override.get("start_at_utc"), f"{label}.start_at_utc"
            )
            attendance = self._positive_int(raw_override.get("attendance"), f"{label}.attendance")
            source_url = self._required_string(
                raw_override.get("source_url"), f"{label}.source_url"
            )
            key = (source, self._normalize_title(title), start_at_utc)
            if key in seen:
                raise ValueError(f"Duplicate reported-attendance override for {title!r}.")
            seen.add(key)
            parsed.append(
                ReportedAttendanceOverride(
                    source=source,
                    title=title,
                    start_at_utc=start_at_utc,
                    attendance=attendance,
                    source_url=source_url,
                )
            )
        return tuple(parsed)

    def _match_reported_attendance_override(
        self, draft: EventDraft
    ) -> ReportedAttendanceOverride | None:
        event_key = (draft.source, self._normalize_title(draft.title), draft.start_at_utc)
        for override in self.reported_attendance_overrides:
            override_key = (
                override.source,
                self._normalize_title(override.title),
                override.start_at_utc,
            )
            if event_key == override_key:
                return override
        return None

    def _parse_venues(self, raw_venues: object) -> tuple[VenueCapacity, ...]:
        if not isinstance(raw_venues, Mapping):
            raise ValueError(
                "events.attendance_estimation.venue_capacities must be a mapping."
            )
        venues: list[VenueCapacity] = []
        for key, value in raw_venues.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Venue capacity keys must be non-empty strings.")
            aliases: list[str] = [key]
            if isinstance(value, Mapping):
                capacity = self._positive_int(
                    value.get("capacity"),
                    f"venue_capacities.{key}.capacity",
                )
                configured_aliases = value.get("aliases", [])
                if not isinstance(configured_aliases, list) or not all(
                    isinstance(alias, str) for alias in configured_aliases
                ):
                    raise ValueError(
                        f"venue_capacities.{key}.aliases must be a list of strings."
                    )
                aliases.extend(configured_aliases)
            else:
                capacity = self._positive_int(value, f"venue_capacities.{key}")
            normalized_aliases = tuple(
                alias for alias in aliases if self._normalize_venue(alias)
            )
            venues.append(VenueCapacity(key=key, capacity=capacity, aliases=normalized_aliases))
        return tuple(venues)

    def _match_venue(self, venue_raw: str | None) -> VenueCapacity | None:
        normalized_venue = self._normalize_venue(venue_raw)
        if not normalized_venue:
            return None

        matches: list[tuple[int, VenueCapacity]] = []
        for venue in self.venues:
            for alias in venue.aliases:
                normalized_alias = self._normalize_venue(alias)
                if normalized_alias and (
                    normalized_alias in normalized_venue
                    or normalized_venue in normalized_alias
                ):
                    matches.append((len(normalized_alias), venue))
        if not matches:
            return None
        return max(matches, key=lambda item: item[0])[1]

    @staticmethod
    def _normalize_venue(value: object) -> str:
        if not isinstance(value, str):
            return ""
        normalized = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
        normalized = "".join(
            character for character in normalized if not unicodedata.combining(character)
        )
        return re.sub(r"[^a-z0-9]+", " ", normalized).strip()

    @classmethod
    def _normalize_title(cls, value: object) -> str:
        return cls._normalize_venue(value)

    @staticmethod
    def _required_string(value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string.")
        return value.strip()

    @staticmethod
    def _positive_int(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} must be a positive integer.") from error
        if parsed < 1:
            raise ValueError(f"{label} must be a positive integer.")
        return parsed

    @staticmethod
    def _fill_rate(value: object, label: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} must be a number between 0 and 1.") from error
        if not 0 <= parsed <= 1:
            raise ValueError(f"{label} must be between 0 and 1.")
        return parsed

    @staticmethod
    def _boolean(value: object, label: str) -> bool:
        if not isinstance(value, bool):
            raise ValueError(f"{label} must be true or false.")
        return value
