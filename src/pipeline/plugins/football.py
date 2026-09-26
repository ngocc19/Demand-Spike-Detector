"""Football source adapters, starting with official VPF fixture calendars.

VPF currently exposes server-rendered fixture calendars rather than a public
fixture API.  This adapter fetches only the configured pages and retains only
matches played at configured Hanoi venues.
"""

from __future__ import annotations

import logging
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests

from ..base import (
    EventDraft,
    EventSource,
    FetchResult,
    canonical_json_hash,
    to_utc_iso,
    utc_now,
)
from .event_plugin import EventRecordError, SourceFetchError


LOGGER = logging.getLogger(__name__)
VOID_HTML_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}


@dataclass
class _HtmlNode:
    tag: str
    attributes: dict[str, str] = field(default_factory=dict)
    children: list["_HtmlNode | str"] = field(default_factory=list)


class _CalendarHtmlParser(HTMLParser):
    """A deliberately small HTML tree builder for VPF's stable calendar markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("root")
        self._stack = [self.root]

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        node = _HtmlNode(tag.lower(), {key: value or "" for key, value in attrs})
        self._stack[-1].children.append(node)
        if tag.lower() not in VOID_HTML_TAGS:
            self._stack.append(node)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_HTML_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == lowered:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


class VpfFootballEventSource(EventSource):
    """Fetch Hanoi football fixtures from public VPF calendar pages."""

    source_name = "vpf_football"

    def __init__(
        self,
        config: Mapping[str, Any],
        session: requests.Session | Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.config = dict(config)
        self.calendars = self._parse_calendars(self.config.get("calendars"))
        self.allowed_venues = self._parse_allowed_venues(
            self.config.get("hanoi_venue_allowlist")
        )
        self.timezone = ZoneInfo(str(self.config.get("timezone", "Asia/Ho_Chi_Minh")))
        self.default_duration_minutes = self._positive_int(
            self.config.get("default_duration_minutes", 120),
            "default_duration_minutes",
        )
        self.timeout_seconds = self._positive_int(
            self.config.get("timeout_seconds", 30),
            "timeout_seconds",
        )
        self.max_retries = self._non_negative_int(
            self.config.get("max_retries", 3),
            "max_retries",
        )
        self.user_agent = str(
            self.config.get("user_agent", "DemandSpikeDetector/0.1")
        )
        self.city = str(self.config.get("scope_city", "hanoi"))
        self.session = session or requests.Session()
        self.sleep_fn = sleep_fn
        self.random_fn = random_fn

    def fetch(self, state: Mapping[str, Any], full_scan: bool) -> FetchResult:
        """Fetch the configured calendars; VPF pages have no update watermark."""

        del state, full_scan
        requested_at_utc = to_utc_iso(utc_now())
        response_pages: list[dict[str, Any]] = []
        fetched_records: list[dict[str, Any]] = []
        http_statuses: list[int] = []

        for calendar_name, calendar_url in self.calendars:
            html, status_code = self._request_html(calendar_url)
            http_statuses.append(status_code)
            all_fixtures = self._parse_calendar(calendar_name, calendar_url, html)
            hanoi_fixtures = [
                fixture
                for fixture in all_fixtures
                if self._is_hanoi_venue(fixture.get("venue"))
            ]
            response_pages.append(
                {
                    "calendar": calendar_name,
                    "url": calendar_url,
                    "html": html,
                    "fixture_count_total": len(all_fixtures),
                    "fixture_count_hanoi": len(hanoi_fixtures),
                }
            )
            fetched_records.extend(hanoi_fixtures)

        return FetchResult(
            source=self.source_name,
            endpoint=" | ".join(url for _, url in self.calendars),
            requested_at_utc=requested_at_utc,
            response_pages=response_pages,
            fetched_records=fetched_records,
            http_statuses=http_statuses,
            watermark_used=None,
        )

    def normalize(self, raw_record: Mapping[str, Any]) -> EventDraft:
        """Normalize one official VPF fixture into a football event."""

        calendar = self._required_text(raw_record, "calendar")
        calendar_url = self._required_text(raw_record, "calendar_url")
        venue = self._required_text(raw_record, "venue")
        home_team = self._required_text(raw_record, "home_team")
        away_team = self._required_text(raw_record, "away_team")
        start_at_utc = self._parse_start(
            self._required_text(raw_record, "date_text"),
            self._required_text(raw_record, "time_text"),
        )
        start_at = datetime.fromisoformat(start_at_utc.replace("Z", "+00:00"))
        end_at_utc = to_utc_iso(
            start_at + timedelta(minutes=self.default_duration_minutes)
        )
        match_url = self._optional_text(raw_record.get("match_url"))
        match_code = self._optional_text(raw_record.get("match_code"))
        source_event_id = match_url or canonical_json_hash(
            {
                "calendar": calendar,
                "match_code": match_code,
                "start_at_utc": start_at_utc,
                "home_team": home_team,
                "away_team": away_team,
            }
        )[:24]
        official_attendance = self._optional_positive_int(
            raw_record.get("official_attendance")
        )
        description_parts = [
            self._optional_text(raw_record.get("round_name")),
            self._optional_text(raw_record.get("channel")),
        ]
        description = " | ".join(part for part in description_parts if part) or None
        tags = ["football", "end_time_estimated"]
        if official_attendance is not None:
            tags.append("official_attendance")

        return EventDraft(
            source=self.source_name,
            source_event_id=source_event_id,
            title=f"{home_team} vs {away_team}",
            description=description,
            raw_category=calendar,
            primary_category="football",
            publication_status="published",
            event_status="unknown",
            start_at_utc=start_at_utc,
            end_at_utc=end_at_utc,
            venue_raw=venue,
            source_url=match_url or calendar_url,
            source_created_at_utc=None,
            source_updated_at_utc=None,
            raw_payload_sha256=canonical_json_hash(dict(raw_record)),
            city=self.city,
            tags=tags,
            official_attendance=official_attendance,
        )

    def _request_html(self, url: str) -> tuple[str, int]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            response: Any | None = None
            try:
                response = self.session.get(
                    url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "text/html,application/xhtml+xml",
                    },
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as error:
                last_error = error
            else:
                status_code = int(response.status_code)
                if 200 <= status_code < 300:
                    content = getattr(response, "content", None)
                    if isinstance(content, (bytes, bytearray)):
                        try:
                            return bytes(content).decode("utf-8"), status_code
                        except UnicodeDecodeError as error:
                            raise SourceFetchError(
                                f"VPF calendar is not valid UTF-8: {url}"
                            ) from error
                    text = getattr(response, "text", None)
                    if isinstance(text, str):
                        return text, status_code
                    raise SourceFetchError(f"VPF calendar response has no HTML body: {url}")
                if status_code not in {429, 500, 502, 503, 504}:
                    raise SourceFetchError(
                        f"VPF calendar returned non-retryable HTTP status {status_code}: {url}"
                    )
                last_error = SourceFetchError(
                    f"VPF calendar returned retryable HTTP status {status_code}: {url}"
                )

            if attempt == self.max_retries:
                break
            delay_seconds = min(2.0**attempt, 60.0) + self.random_fn() * 0.25
            LOGGER.warning(
                "VPF calendar request failed on attempt %s; retrying in %.2f seconds.",
                attempt + 1,
                delay_seconds,
            )
            self.sleep_fn(delay_seconds)

        raise SourceFetchError(
            f"Could not fetch VPF calendar after {self.max_retries + 1} attempts."
        ) from last_error

    def _parse_calendar(
        self,
        calendar_name: str,
        calendar_url: str,
        html: str,
    ) -> list[dict[str, Any]]:
        if "js-matchday-wrapper" not in html:
            raise SourceFetchError(
                f"VPF calendar markup changed or is empty: {calendar_url}"
            )
        parser = _CalendarHtmlParser()
        parser.feed(html)
        parser.close()
        fixtures: list[dict[str, Any]] = []
        current_round: str | None = None

        for node in self._walk(parser.root):
            if self._has_class(node, "jsrow-matchday-name"):
                current_round = self._text(node) or None
            elif self._has_class(node, "js-matchday-wrapper"):
                date_text = self._text(self._first_by_class(node, "js-matchday-date"))
                for match_node in self._descendants_with_class(node, "jstable-row"):
                    if self._first_by_class(match_node, "jsMatchDivVenue") is None:
                        continue
                    fixtures.append(
                        {
                            "calendar": calendar_name,
                            "calendar_url": calendar_url,
                            "round_name": current_round,
                            "date_text": date_text,
                            "time_text": self._text(
                                self._first_by_class(match_node, "jsMatchDivTime")
                            ),
                            "match_code": self._text(
                                self._first_by_class(match_node, "js-ma-tran")
                            )
                            or None,
                            "venue": self._text(
                                self._first_by_class(match_node, "jsMatchDivVenue")
                            ),
                            "home_team": self._text(
                                self._first_by_class(match_node, "jsMatchDivHome")
                            ),
                            "away_team": self._text(
                                self._first_by_class(match_node, "jsMatchDivAway")
                            ),
                            "channel": self._text(
                                self._first_by_class(match_node, "jsChannelDiv")
                            )
                            or None,
                            "official_attendance": self._parse_attendance(
                                self._text(
                                    self._first_by_class(match_node, "js-audience")
                                )
                            ),
                            "match_url": self._score_url(match_node, calendar_url),
                        }
                    )
        return fixtures

    def _is_hanoi_venue(self, venue: object) -> bool:
        normalized_venue = self._normalize_venue(venue)
        return any(
            allowed in normalized_venue or normalized_venue in allowed
            for allowed in self.allowed_venues
            if normalized_venue
        )

    def _parse_start(self, date_text: str, time_text: str) -> str:
        date_parts = [int(part) for part in re.findall(r"\d+", date_text)]
        if len(date_parts) < 3:
            raise EventRecordError(
                f"VPF fixture has an incomplete date and needs review: {date_text!r}."
            )
        time_match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", time_text)
        if not time_match:
            raise EventRecordError(
                f"VPF fixture has an invalid start time and needs review: {time_text!r}."
            )
        day, month, year = date_parts[:3]
        hour, minute = (int(value) for value in time_match.groups())
        try:
            local_start = datetime(
                year,
                month,
                day,
                hour,
                minute,
                tzinfo=self.timezone,
            )
        except ValueError as error:
            raise EventRecordError(
                f"VPF fixture has an invalid start date: {date_text!r}."
            ) from error
        return to_utc_iso(local_start)

    @staticmethod
    def _parse_attendance(value: str) -> int | None:
        match = re.search(r"(\d[\d.,\s]*)\s*(?:người|nguoi)\b", value, re.IGNORECASE)
        if not match:
            return None
        digits = re.sub(r"\D", "", match.group(1))
        return int(digits) if digits else None

    @staticmethod
    def _walk(node: _HtmlNode) -> Iterator[_HtmlNode]:
        yield node
        for child in node.children:
            if isinstance(child, _HtmlNode):
                yield from VpfFootballEventSource._walk(child)

    @staticmethod
    def _has_class(node: _HtmlNode, class_name: str) -> bool:
        return class_name in node.attributes.get("class", "").split()

    def _first_by_class(
        self,
        node: _HtmlNode | None,
        class_name: str,
    ) -> _HtmlNode | None:
        if node is None:
            return None
        for descendant in self._walk(node):
            if self._has_class(descendant, class_name):
                return descendant
        return None

    def _descendants_with_class(
        self,
        node: _HtmlNode,
        class_name: str,
    ) -> Iterator[_HtmlNode]:
        for descendant in self._walk(node):
            if self._has_class(descendant, class_name):
                yield descendant

    @staticmethod
    def _text(node: _HtmlNode | None) -> str:
        if node is None:
            return ""

        def collect(current: _HtmlNode) -> Iterator[str]:
            for child in current.children:
                if isinstance(child, str):
                    yield child
                else:
                    yield from collect(child)

        return re.sub(r"\s+", " ", "".join(collect(node))).strip()

    def _score_url(self, node: _HtmlNode, base_url: str) -> str | None:
        score_node = self._first_by_class(node, "jsMatchDivScore")
        if score_node is None:
            return None
        for descendant in self._walk(score_node):
            if descendant.tag == "a" and descendant.attributes.get("href"):
                return urljoin(base_url, descendant.attributes["href"])
        return None

    @staticmethod
    def _normalize_venue(value: object) -> str:
        if not isinstance(value, str):
            return ""
        normalized = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
        normalized = "".join(
            character for character in normalized if not unicodedata.combining(character)
        )
        return re.sub(r"[^a-z0-9]+", " ", normalized).strip()

    def _parse_calendars(self, value: object) -> tuple[tuple[str, str], ...]:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("VPF source config requires a non-empty calendars mapping.")
        calendars: list[tuple[str, str]] = []
        for name, url in value.items():
            if not isinstance(name, str) or not isinstance(url, str):
                raise ValueError("VPF calendar names and URLs must be strings.")
            if not url.startswith(("https://", "http://")):
                raise ValueError(f"VPF calendar URL is invalid: {url!r}.")
            calendars.append((name, url))
        return tuple(calendars)

    def _parse_allowed_venues(self, value: object) -> tuple[str, ...]:
        if not isinstance(value, list) or not value:
            raise ValueError(
                "VPF source config requires a non-empty hanoi_venue_allowlist."
            )
        normalized = tuple(
            self._normalize_venue(venue)
            for venue in value
            if isinstance(venue, str) and self._normalize_venue(venue)
        )
        if not normalized:
            raise ValueError(
                "VPF source config requires valid hanoi_venue_allowlist values."
            )
        return normalized

    @staticmethod
    def _required_text(raw_record: Mapping[str, Any], field_name: str) -> str:
        value = raw_record.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise EventRecordError(f"VPF fixture requires {field_name}.")
        return value.strip()

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        return value.strip() or None

    @staticmethod
    def _optional_positive_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise EventRecordError("VPF official attendance must be an integer.") from error
        if parsed < 0:
            raise EventRecordError("VPF official attendance cannot be negative.")
        return parsed

    @staticmethod
    def _positive_int(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"VPF config {label} must be a positive integer.") from error
        if parsed < 1:
            raise ValueError(f"VPF config {label} must be a positive integer.")
        return parsed

    @staticmethod
    def _non_negative_int(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"VPF config {label} must be an integer.") from error
        if parsed < 0:
            raise ValueError(f"VPF config {label} cannot be negative.")
        return parsed


class VffFootballEventSource(EventSource):
    """Discover Hanoi national-team fixtures from official VFF match notices."""

    source_name = "vff_football"
    _ARTICLE_KEYWORDS = (
        "trận",
        "đội tuyển",
        "asean",
        "aff",
        "cup",
        "vé",
    )

    def __init__(
        self,
        config: Mapping[str, Any],
        session: requests.Session | Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.config = dict(config)
        self.listing_url = self._required_url("listing_url")
        self.max_listing_pages = self._positive_int(
            self.config.get("max_listing_pages", 8),
            "max_listing_pages",
        )
        self.timeout_seconds = self._positive_int(
            self.config.get("timeout_seconds", 30),
            "timeout_seconds",
        )
        self.max_retries = self._non_negative_int(
            self.config.get("max_retries", 3),
            "max_retries",
        )
        self.user_agent = str(
            self.config.get("user_agent", "DemandSpikeDetector/0.1")
        )
        self.city = str(self.config.get("scope_city", "hanoi"))
        self.timezone = ZoneInfo(str(self.config.get("timezone", "Asia/Ho_Chi_Minh")))
        self.default_duration_minutes = self._positive_int(
            self.config.get("default_duration_minutes", 120),
            "default_duration_minutes",
        )
        self.session = session or requests.Session()
        self.sleep_fn = sleep_fn
        self.random_fn = random_fn

    def fetch(self, state: Mapping[str, Any], full_scan: bool) -> FetchResult:
        """Fetch VFF notice pages, then only their football-related articles."""

        del state, full_scan
        requested_at_utc = to_utc_iso(utc_now())
        pending = [self.listing_url]
        visited: set[str] = set()
        article_urls: set[str] = set()
        response_pages: list[dict[str, Any]] = []
        statuses: list[int] = []

        while pending and len(visited) < self.max_listing_pages:
            page_url = pending.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)
            html, status = self._request_html(page_url)
            statuses.append(status)
            response_pages.append(
                {"kind": "listing", "url": page_url, "html": html}
            )
            root = self._parse_html(html)
            article_urls.update(self._article_urls(root, page_url))
            next_url = self._next_listing_url(root, page_url)
            if next_url and next_url not in visited and next_url not in pending:
                pending.append(next_url)

        records: list[dict[str, Any]] = []
        for article_url in sorted(article_urls):
            html, status = self._request_html(article_url)
            statuses.append(status)
            response_pages.append(
                {"kind": "article", "url": article_url, "html": html}
            )
            record = self._parse_article(article_url, html)
            if record:
                records.append(record)

        return FetchResult(
            source=self.source_name,
            endpoint=self.listing_url,
            requested_at_utc=requested_at_utc,
            response_pages=response_pages,
            fetched_records=records,
            http_statuses=statuses,
            watermark_used=None,
        )

    def normalize(self, raw_record: Mapping[str, Any]) -> EventDraft:
        """Map an already evidence-backed VFF notice to one football event."""

        title = self._required_text(raw_record, "title")
        source_url = self._required_text(raw_record, "source_url")
        start_at_utc = self._required_text(raw_record, "start_at_utc")
        venue = self._required_text(raw_record, "venue")
        start_at = datetime.fromisoformat(start_at_utc.replace("Z", "+00:00"))
        end_at_utc = to_utc_iso(
            start_at + timedelta(minutes=self.default_duration_minutes)
        )
        home_team = self._optional_text(raw_record.get("home_team"))
        away_team = self._optional_text(raw_record.get("away_team"))
        source_event_id = canonical_json_hash(
            {
                "home_team": home_team,
                "away_team": away_team,
                "start_at_utc": start_at_utc,
                "venue": venue,
            }
        )[:24]
        return EventDraft(
            source=self.source_name,
            source_event_id=source_event_id,
            title=f"{home_team} vs {away_team}" if home_team and away_team else title,
            description=self._optional_text(raw_record.get("description")),
            raw_category=self._required_text(raw_record, "competition"),
            primary_category="football",
            publication_status="published",
            event_status="unknown",
            start_at_utc=start_at_utc,
            end_at_utc=end_at_utc,
            venue_raw=venue,
            source_url=source_url,
            source_created_at_utc=None,
            source_updated_at_utc=None,
            raw_payload_sha256=canonical_json_hash(dict(raw_record)),
            city=self.city,
            tags=["football", "vff_official", "end_time_estimated"],
        )

    def _article_urls(self, root: _HtmlNode, base_url: str) -> set[str]:
        urls: set[str] = set()
        for node in VpfFootballEventSource._walk(root):
            if not VpfFootballEventSource._has_class(node, "post-item"):
                continue
            card_text = VpfFootballEventSource._text(node).casefold()
            if not any(keyword in card_text for keyword in self._ARTICLE_KEYWORDS):
                continue
            for descendant in VpfFootballEventSource._walk(node):
                if descendant.tag != "a":
                    continue
                href = descendant.attributes.get("href")
                candidate = self._vff_url(href, base_url) if href else None
                if candidate:
                    urls.add(candidate)
                    break
        return urls

    def _next_listing_url(self, root: _HtmlNode, base_url: str) -> str | None:
        for node in VpfFootballEventSource._walk(root):
            if node.tag != "a" or not VpfFootballEventSource._has_class(
                node, "nextpostslink"
            ):
                continue
            href = node.attributes.get("href")
            return self._vff_url(href, base_url) if href else None
        return None

    def _parse_article(self, article_url: str, html: str) -> dict[str, Any] | None:
        root = self._parse_html(html)
        content_node = self._first_class(root, "entry-content")
        title_node = self._first_class(root, "post-title")
        content = VpfFootballEventSource._text(content_node)
        title = VpfFootballEventSource._text(title_node)
        if not content or not title:
            return None
        match = re.search(
            r"(?:diễn ra|thi đấu|đá).{0,180}?"
            r"(?:lúc\s*)?(\d{1,2}(?:h|:)\d{2})\s*"
            r"(?:ngày\s*)?(\d{1,2}/\d{1,2}/\d{4}).{0,220}?"
            r"(?:tại|trên sân)\s+([^.;]+)",
            content,
            re.IGNORECASE,
        )
        if not match:
            return None
        start_at_utc = self._to_start_at_utc(match.group(1), match.group(2))
        venue = re.split(r"\s+(?:như|với)\s+", match.group(3), maxsplit=1)[0].strip()
        if not self._is_hanoi_venue(venue):
            return None
        home_team, away_team = self._teams(title)
        if not home_team or not away_team:
            # A ticket article that only says "các trận sân nhà" can describe
            # several fixtures.  It is not one event and must not be emitted.
            return None
        competition = "asean_cup" if re.search(r"\b(?:asean|aff)\b", title, re.I) else "international_football"
        return {
            "title": title,
            "description": content,
            "home_team": home_team,
            "away_team": away_team,
            "competition": competition,
            "start_at_utc": start_at_utc,
            "venue": venue,
            "source_url": article_url,
        }

    def _request_html(self, url: str) -> tuple[str, int]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            response: Any | None = None
            try:
                response = self.session.get(
                    url,
                    headers={"User-Agent": self.user_agent, "Accept": "text/html"},
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as error:
                last_error = error
            else:
                status = int(response.status_code)
                if 200 <= status < 300:
                    content = getattr(response, "content", None)
                    if isinstance(content, (bytes, bytearray)):
                        return bytes(content).decode("utf-8"), status
                    text = getattr(response, "text", None)
                    if isinstance(text, str):
                        return text, status
                    raise SourceFetchError(f"VFF response has no HTML body: {url}")
                last_error = SourceFetchError(f"VFF returned HTTP {status}: {url}")
            if attempt < self.max_retries:
                self.sleep_fn(min(2.0**attempt, 60.0) + self.random_fn() * 0.25)
        raise SourceFetchError(f"Could not fetch VFF URL: {url}") from last_error

    @staticmethod
    def _parse_html(html: str) -> _HtmlNode:
        parser = _CalendarHtmlParser()
        parser.feed(html)
        parser.close()
        return parser.root

    @staticmethod
    def _first_class(root: _HtmlNode, class_name: str) -> _HtmlNode | None:
        for node in VpfFootballEventSource._walk(root):
            if VpfFootballEventSource._has_class(node, class_name):
                return node
        return None

    def _to_start_at_utc(self, time_text: str, date_text: str) -> str:
        normalized_time = time_text.replace("h", ":")
        local_start = datetime.strptime(
            f"{date_text} {normalized_time}",
            "%d/%m/%Y %H:%M",
        ).replace(tzinfo=self.timezone)
        return to_utc_iso(local_start)

    def _is_hanoi_venue(self, venue: str) -> bool:
        normalized = VpfFootballEventSource._normalize_venue(venue)
        return any(
            token in normalized
            for token in ("ha noi", "my dinh", "hang day", "tu liem")
        )

    @staticmethod
    def _teams(title: str) -> tuple[str | None, str | None]:
        match = re.search(
            r"(?:đt|đội tuyển)\s+(.+?)\s+(?:vs|gặp)\s+"
            r"(?:đt|đội tuyển)\s+(.+?)(?:\s*\(|$)",
            title,
            re.IGNORECASE,
        )
        if match:
            return match.groups()
        match = re.search(
            r"(?:giữa|trận đấu giữa)\s+(?:đt|đội tuyển)\s+(.+?)\s+"
            r"và\s+(?:đt|đội tuyển)\s+(.+?)(?:\s*\(|$)",
            title,
            re.IGNORECASE,
        )
        return match.groups() if match else (None, None)

    def _vff_url(self, href: str, base_url: str) -> str | None:
        candidate = urljoin(base_url, href)
        parsed = urlsplit(candidate)
        if parsed.scheme != "https" or parsed.netloc.casefold() != "vff.org.vn":
            return None
        if parsed.path.startswith("/chuyen-muc/") or parsed.path == "/":
            return None
        return candidate

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return value.strip() or None if isinstance(value, str) else None

    def _required_text(self, record: Mapping[str, Any], field: str) -> str:
        value = self._optional_text(record.get(field))
        if not value:
            raise EventRecordError(f"VFF event requires {field}.")
        return value

    def _required_url(self, name: str) -> str:
        value = self._optional_text(self.config.get(name))
        parsed = urlsplit(value) if value else None
        if (
            not value
            or not parsed
            or parsed.scheme != "https"
            or parsed.netloc.casefold() != "vff.org.vn"
        ):
            raise ValueError(f"VFF config {name} must be an HTTPS URL on vff.org.vn.")
        return value

    @staticmethod
    def _positive_int(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"VFF config {label} must be a positive integer.") from error
        if parsed < 1:
            raise ValueError(f"VFF config {label} must be a positive integer.")
        return parsed

    @staticmethod
    def _non_negative_int(value: object, label: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"VFF config {label} must be an integer.") from error
        if parsed < 0:
            raise ValueError(f"VFF config {label} cannot be negative.")
        return parsed
