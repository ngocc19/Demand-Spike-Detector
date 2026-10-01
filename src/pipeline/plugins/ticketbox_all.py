"""Ticketbox catch-all event source - fetches all events and classifies them.

Ticketbox API's category filter is incomplete (most events have empty categories).
This plugin fetches ALL events and classifies them based on title keywords.
"""

from __future__ import annotations

import json
import random
import time
from datetime import date, datetime
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

from ..base import EventDraft, EventSource, FetchResult, canonical_json_hash, to_utc_iso, utc_now
from .event_plugin import EventRecordError, SourceFetchError


# Keywords for event classification
_CATEGORY_KEYWORDS = {
    "concert": [
        "concert", "live", "show", "nhạc", "nhac", "music", "musical",
        "band", "artist", "singer", "ca sĩ", "ca si", "tour", "album",
        "vpop", "kpop", "pop", "rock", "edm", "hiphop", "rap",
    ],
    "festival": [
        "festival", "fest", "lễ hội", "le hoi", "ngày hội", "ngay hoi",
        "carnival", "đại nhạc hội", "đại hội", "carnival",
    ],
    "theater": [
        "theater", "theatre", "kịch", "kich", "nhạc kịch", "nhac kich",
        "drama", "hài", "hai", "comedy", "rạp xiếc", "rap xiec",
        "xiếc", "xiec", "sân khấu", "san khau",
    ],
    "sports": [
        "football", "bóng đá", "bong da", "soccer", "vleague", "cup",
        "basketball", "bóng rổ", "bong ro", "tennis", "marathon",
        "giải đấu", "giai dau", "championship", " tournament",
    ],
    "exhibition": [
        "exhibition", "triển lãm", "trien lam", "trưng bày", "trung bay",
        "museum", "bảo tàng", "bao tang", "art", "gallery", "tranh",
    ],
    "workshop": [
        "workshop", "hội thảo", "hoi thao", "seminar", "conference",
        "training", "course", "lớp học", "lop hoc", "khoá học", "khoa hoc",
    ],
}

_EXCLUDED_TITLE_TERMS = [
    "merchandise", "merch", "test event", "merch ",
]


class TicketboxAllEventSource(EventSource):
    """Collect all Ticketbox events and classify them by type."""

    source_name = "ticketbox_all"

    def __init__(
        self,
        config: Mapping[str, Any],
        event_date_window: Mapping[str, Any] | None = None,
        session: requests.Session | Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        super().__init__(config, event_date_window)
        self.search_url = self._required_url("search_url")

        # Use event_date_window if provided, otherwise use defaults
        if event_date_window:
            start_str = event_date_window.get("start_date")
            end_str = event_date_window.get("end_date")
        else:
            start_str = self.config.get("from_date")
            end_str = self.config.get("to_date")

        self.from_date = self._parse_date(start_str, "start_date") if start_str else date(1970, 1, 1)
        self.to_date = self._parse_date(end_str, "end_date") if end_str else date(2999, 12, 31)

        if self.to_date < self.from_date:
            raise ValueError("Ticketbox to_date must not precede from_date.")
        self.page_size = self._positive_int(self.config.get("page_size", 100), "page_size")
        self.max_pages = self._positive_int(self.config.get("max_pages", 10), "max_pages")
        self.timeout_seconds = self._positive_int(
            self.config.get("timeout_seconds", 30), "timeout_seconds"
        )
        self.max_retries = self._non_negative_int(self.config.get("max_retries", 3), "max_retries")
        self.user_agent = str(self.config.get("user_agent", "DemandSpikeDetector/0.1"))
        self.city = str(self.config.get("scope_city", "hanoi"))
        self.timezone = ZoneInfo(str(self.config.get("timezone", "Asia/Ho_Chi_Minh")))
        self.session = session or requests.Session()
        self.sleep_fn = sleep_fn
        self.random_fn = random_fn

    def fetch(self, state: Mapping[str, Any], full_scan: bool) -> FetchResult:
        """Fetch all events and verify Hanoi location."""

        del state, full_scan
        requested_at_utc = to_utc_iso(utc_now())
        response_pages: list[dict[str, Any]] = []
        statuses: list[int] = []
        candidates: dict[int, dict[str, Any]] = {}

        # Fetch all events (no category filter)
        for page in range(1, self.max_pages + 1):
            payload, status = self._request_json(
                self.search_url,
                params={
                    "limit": self.page_size,
                    "page": page,
                    "from": self.from_date.isoformat(),
                    "to": self.to_date.isoformat(),
                    "at": "custom-date",
                },
            )
            statuses.append(status)
            response_pages.append({"kind": "search", "page": page, "payload": payload})
            data = self._mapping(payload.get("data"), "Ticketbox search data")
            results = data.get("results", [])
            if not isinstance(results, list):
                raise SourceFetchError("Ticketbox search results must be a list.")
            for result in results:
                if not isinstance(result, Mapping):
                    continue
                event_id = self._event_id(result)
                if event_id is not None:
                    candidates[event_id] = dict(result)
            pagination = data.get("pagination", {})
            has_more = isinstance(pagination, Mapping) and pagination.get("hasMore") is True
            if not has_more:
                break

        # Verify each event from detail pages and classify
        records: list[dict[str, Any]] = []
        for result in candidates.values():
            public_url = self._public_url(result)
            if public_url is None:
                continue
            html, status = self._request_html(public_url)
            statuses.append(status)
            page_props = self._page_props(html)
            response_pages.append(
                {"kind": "event", "url": public_url, "page_props": page_props}
            )
            record = self._record_from_page(result, public_url, page_props)
            if record is not None:
                records.append(record)

        return FetchResult(
            source=self.source_name,
            endpoint=self.search_url,
            requested_at_utc=requested_at_utc,
            response_pages=response_pages,
            fetched_records=records,
            http_statuses=statuses,
            watermark_used=None,
        )

    def normalize(self, raw_record: Mapping[str, Any]) -> EventDraft:
        """Map a verified Ticketbox event to the common contract."""

        event_id = self._event_id(raw_record)
        if event_id is None:
            raise EventRecordError("Ticketbox event is missing its id.")
        start_at_utc = self._required_string(raw_record.get("start_at_utc"), "start_at_utc")
        title = self._required_string(raw_record.get("title"), "title")
        event_type = raw_record.get("event_type", "other")
        source_url = self._required_string(raw_record.get("source_url"), "source_url")

        return EventDraft(
            source=self.source_name,
            source_event_id=str(event_id),
            title=title,
            description=self._optional_string(raw_record.get("description")),
            raw_category=event_type,
            primary_category=event_type,
            publication_status="published",
            event_status=str(raw_record.get("event_status") or "unknown"),
            start_at_utc=start_at_utc,
            end_at_utc=self._optional_string(raw_record.get("end_at_utc")),
            venue_raw=self._required_string(raw_record.get("venue"), "venue"),
            source_url=source_url,
            source_created_at_utc=None,
            source_updated_at_utc=None,
            raw_payload_sha256=canonical_json_hash(dict(raw_record)),
            city=self.city,
            tags=["ticketbox", event_type],
        )

    def _record_from_page(
        self,
        search_result: Mapping[str, Any],
        public_url: str,
        page_props: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        info = page_props.get("infoEvent")
        if not isinstance(info, Mapping):
            return None

        title = self._optional_string(info.get("title")) or self._optional_string(search_result.get("name"))
        venue = self._optional_string(info.get("venue"))
        address = self._optional_string(info.get("address"))
        start_at_utc = self._optional_string(info.get("startTime"))

        if not title or not venue or not start_at_utc:
            return None

        # Exclude non-events
        if self._is_excluded_title(title):
            return None

        # Filter by location (Hanoi)
        if not self._is_hanoi(venue, address):
            return None

        # Validate date range
        try:
            local_date = datetime.fromisoformat(
                start_at_utc.replace("Z", "+00:00")
            ).astimezone(self.timezone).date()
        except ValueError:
            return None
        if not self.from_date <= local_date <= self.to_date:
            return None

        # Classify event type
        event_type = self._classify_event(title, self._optional_string(page_props.get("description")))

        event_id = self._event_id(info) or self._event_id(search_result)
        if event_id is None:
            return None

        return {
            "id": event_id,
            "title": title,
            "description": self._optional_string(page_props.get("description")),
            "venue": venue,
            "address": address,
            "start_at_utc": start_at_utc,
            "end_at_utc": self._optional_string(info.get("endTime")),
            "event_status": self._optional_string(info.get("status")),
            "source_url": public_url,
            "event_type": event_type,
        }

    def _classify_event(self, title: str, description: str | None) -> str:
        """Classify event type based on title and description keywords."""
        combined = f"{title} {description or ''}".casefold()

        # Check each category in order of priority
        priority = ["concert", "festival", "sports", "theater", "workshop", "exhibition"]

        for category in priority:
            keywords = _CATEGORY_KEYWORDS.get(category, [])
            if any(kw in combined for kw in keywords):
                return category

        return "other"

    def _is_hanoi(self, venue: str, address: str | None) -> bool:
        combined = f"{venue} {address or ''}".casefold()
        return "hà nội" in combined or "ha noi" in combined

    def _is_excluded_title(self, title: str) -> bool:
        normalized = title.casefold()
        return any(term in normalized for term in _EXCLUDED_TITLE_TERMS)

    def _request_json(self, url: str, params: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
        response = self._request(url, params=params)
        try:
            payload = response.json()
        except ValueError as error:
            raise SourceFetchError(f"Ticketbox returned invalid JSON: {url}") from error
        if not isinstance(payload, dict):
            raise SourceFetchError(f"Ticketbox returned an invalid JSON object: {url}")
        return payload, response.status_code

    def _request_html(self, url: str) -> tuple[str, int]:
        response = self._request(url)
        try:
            return response.content.decode("utf-8"), response.status_code
        except UnicodeDecodeError as error:
            raise SourceFetchError(f"Ticketbox page is not UTF-8: {url}") from error

    def _request(self, url: str, params: Mapping[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=dict(params or {}),
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 200:
                    return response
                last_error = SourceFetchError(
                    f"Ticketbox returned HTTP {response.status_code}: {url}"
                )
            except requests.RequestException as error:
                last_error = error
            if attempt < self.max_retries:
                self.sleep_fn((2**attempt) + self.random_fn())
        raise SourceFetchError(f"Could not fetch Ticketbox URL: {url}") from last_error

    @staticmethod
    def _page_props(html: str) -> dict[str, Any]:
        marker = '<script id="__NEXT_DATA__" type="application/json">'
        start = html.find(marker)
        if start < 0:
            raise SourceFetchError("Ticketbox event page has no __NEXT_DATA__ payload.")
        start += len(marker)
        end = html.find("</script>", start)
        if end < 0:
            raise SourceFetchError("Ticketbox event page has an incomplete __NEXT_DATA__ payload.")
        try:
            payload = json.loads(html[start:end])
        except json.JSONDecodeError as error:
            raise SourceFetchError("Ticketbox event page has invalid __NEXT_DATA__ JSON.") from error
        props = payload.get("props", {}).get("pageProps", {})
        if not isinstance(props, dict):
            raise SourceFetchError("Ticketbox event page has invalid pageProps.")
        return props

    @staticmethod
    def _public_url(record: Mapping[str, Any]) -> str | None:
        deeplink = record.get("deeplink")
        if not isinstance(deeplink, str) or not deeplink.strip():
            return None
        split = urlsplit(deeplink.strip())
        if split.scheme != "https" or split.netloc != "ticketbox.vn":
            return None
        return urlunsplit((split.scheme, split.netloc, split.path, "", ""))

    @staticmethod
    def _event_id(record: Mapping[str, Any]) -> int | None:
        for key in ("originalId", "id"):
            value = record.get(key)
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    def _required_url(self, key: str) -> str:
        value = self._required_string(self.config.get(key), key)
        split = urlsplit(value)
        if split.scheme != "https" or not split.netloc:
            raise ValueError(f"Ticketbox {key} must be an HTTPS URL.")
        return value

    @staticmethod
    def _required_string(value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Ticketbox config/record {label} must be a non-empty string.")
        return value.strip()

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _parse_date(value: object, label: str) -> date:
        if not isinstance(value, str):
            raise ValueError(f"Ticketbox {label} must be YYYY-MM-DD.")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"Ticketbox {label} must be YYYY-MM-DD.") from error

    @staticmethod
    def _positive_int(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Ticketbox {label} must be a positive integer.") from error
        if parsed < 1:
            raise ValueError(f"Ticketbox {label} must be a positive integer.")
        return parsed

    @staticmethod
    def _non_negative_int(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Ticketbox {label} must be non-negative.") from error
        if parsed < 0:
            raise ValueError(f"Ticketbox {label} must be non-negative.")
        return parsed

    @staticmethod
    def _mapping(value: object, label: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise SourceFetchError(f"{label} must be an object.")
        return value
