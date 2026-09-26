"""Ticketbox festival discovery using its public search and event pages."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, time
from html.parser import HTMLParser
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

from ..base import EventDraft, EventSource, FetchResult, canonical_json_hash, to_utc_iso, utc_now
from .concert import TicketboxConcertEventSource
from .event_plugin import SourceFetchError


class TicketboxFestivalEventSource(TicketboxConcertEventSource):
    """Collect Hanoi festivals from Ticketbox's unfiltered public event search.

    Ticketbox currently does not return usable records for ``categories=festival``.
    Festival listings are instead interspersed with other public listings, so this
    adapter cheaply filters search-result titles before fetching event detail pages.
    The detail page remains the authority for Hanoi location and event timing.
    """

    source_name = "ticketbox_festival"
    _FESTIVAL_TERMS = (
        "festival",
        "fest",
        "lễ hội",
        "le hoi",
        "ngày hội",
        "ngay hoi",
        "carnival",
    )

    def __init__(self, config: Mapping[str, Any], **kwargs: Any) -> None:
        # The parent supplies shared HTTP, date, URL, and Ticketbox-page parsing
        # helpers.  Its category is not used by this adapter's unfiltered search.
        inherited_config = dict(config)
        inherited_config.setdefault("category", "all")
        super().__init__(inherited_config, **kwargs)

    def fetch(self, state: Mapping[str, Any], full_scan: bool) -> FetchResult:
        """Fetch matching public listings, then verify each candidate's detail page."""

        del state, full_scan
        requested_at_utc = to_utc_iso(utc_now())
        response_pages: list[dict[str, Any]] = []
        statuses: list[int] = []
        candidates: dict[int, dict[str, Any]] = {}

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
                title = self._optional_string(result.get("name"))
                event_id = self._event_id(result)
                if title and event_id is not None and self._looks_like_festival(title):
                    candidates[event_id] = dict(result)
            pagination = data.get("pagination", {})
            if not (isinstance(pagination, Mapping) and pagination.get("hasMore") is True):
                break

        records: list[dict[str, Any]] = []
        for result in candidates.values():
            public_url = self._public_url(result)
            if public_url is None:
                continue
            html, status = self._request_html(public_url)
            statuses.append(status)
            page_props = self._page_props(html)
            response_pages.append({"kind": "event", "url": public_url, "page_props": page_props})
            record = self._record_from_festival_page(result, public_url, page_props)
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
        draft = super().normalize(raw_record)
        return replace(
            draft,
            raw_category="festival",
            primary_category="festival",
            tags=["festival", "ticketbox"],
        )

    def _record_from_festival_page(
        self,
        search_result: Mapping[str, Any],
        public_url: str,
        page_props: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        info = page_props.get("infoEvent")
        if not isinstance(info, Mapping):
            return None
        title = self._optional_string(info.get("title")) or self._optional_string(search_result.get("name"))
        description = self._optional_string(page_props.get("description"))
        venue = self._optional_string(info.get("venue"))
        address = self._optional_string(info.get("address"))
        start_at_utc = self._optional_string(info.get("startTime"))
        if not title or not venue or not start_at_utc:
            return None
        if not self._looks_like_festival(f"{title} {description or ''}"):
            return None
        if not self._is_hanoi(venue, address):
            return None
        try:
            local_date = datetime.fromisoformat(
                start_at_utc.replace("Z", "+00:00")
            ).astimezone(self.timezone).date()
        except ValueError:
            return None
        if not self.from_date <= local_date <= self.to_date:
            return None
        event_id = self._event_id(info) or self._event_id(search_result)
        if event_id is None:
            return None
        return {
            "id": event_id,
            "title": title,
            "description": description,
            "venue": venue,
            "address": address,
            "start_at_utc": start_at_utc,
            "end_at_utc": self._optional_string(info.get("endTime")),
            "event_status": self._optional_string(info.get("status")),
            "source_url": public_url,
        }

    def _looks_like_festival(self, value: str) -> bool:
        normalized = value.casefold()
        return any(term in normalized for term in self._FESTIVAL_TERMS)


class _EventLinkParser(HTMLParser):
    """Extract public event-detail links from Le Hoi Viet Nam listings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href") if tag.lower() == "a" else None
        if href and "/vi/su-kien/" in href:
            self.hrefs.append(href)


class LeHoiVietNamEventSource(EventSource):
    """Discover Hanoi festivals/exhibitions from Event JSON-LD on public pages."""

    source_name = "lehoivietnam_hanoi"
    _EXHIBITION_TERMS = ("triển lãm", "trien lam", "exhibition", "expo", "hội chợ", "hoi cho")

    def __init__(self, config: Mapping[str, Any], session: Any | None = None) -> None:
        self.config = dict(config)
        self.listing_url = self._required_url("listing_url")
        self.max_pages = self._positive_int("max_pages", 20)
        self.timeout_seconds = self._positive_int("timeout_seconds", 30)
        self.user_agent = str(self.config.get("user_agent", "DemandSpikeDetector/0.1"))
        self.city = str(self.config.get("scope_city", "hanoi"))
        self.timezone = ZoneInfo(str(self.config.get("timezone", "Asia/Ho_Chi_Minh")))
        self.session = session or requests.Session()

    def fetch(self, state: Mapping[str, Any], full_scan: bool) -> FetchResult:
        del state, full_scan
        pages: list[dict[str, Any]] = []; statuses: list[int] = []; article_urls: set[str] = set()
        for page in range(1, self.max_pages + 1):
            url = self._with_page(page); html, status = self._get(url); statuses.append(status)
            hrefs = self._event_links(html, url); pages.append({"kind": "listing", "url": url, "article_urls": sorted(hrefs)})
            if not hrefs or hrefs.issubset(article_urls): break
            article_urls.update(hrefs)
        records: list[dict[str, Any]] = []
        for url in sorted(article_urls):
            html, status = self._get(url); statuses.append(status); event = self._event_json_ld(html)
            pages.append({"kind": "event", "url": url, "event": event})
            if event is not None: records.append({"url": url, "event": event})
        return FetchResult(self.source_name, self.listing_url, to_utc_iso(utc_now()), pages, records, statuses, None)

    def normalize(self, raw_record: Mapping[str, Any]) -> EventDraft:
        event, url = raw_record.get("event"), raw_record.get("url")
        if not isinstance(event, Mapping) or not isinstance(url, str):
            raise SourceFetchError("Le Hoi Viet Nam record requires public URL and JSON-LD Event.")
        title = self._text(event.get("name"), "name")
        start = self._date_to_utc(self._text(event.get("startDate"), "startDate"), end=False)
        end_value = event.get("endDate")
        end = self._date_to_utc(end_value, end=True) if isinstance(end_value, str) and end_value else None
        location = event.get("location"); venue = location.get("name") if isinstance(location, Mapping) else None
        category = "exhibition" if any(term in title.casefold() for term in self._EXHIBITION_TERMS) else "festival"
        return EventDraft(source=self.source_name, source_event_id=urlsplit(url).path, title=title,
            description=str(event.get("description") or "").strip() or None, raw_category=category,
            primary_category=category, publication_status="published", event_status="scheduled",
            start_at_utc=start, end_at_utc=end, venue_raw=str(venue).strip() if venue else None,
            source_url=url, source_created_at_utc=None, source_updated_at_utc=None,
            raw_payload_sha256=canonical_json_hash(dict(event)), city=self.city, tags=[category, "lehoivietnam"])

    def _get(self, url: str) -> tuple[str, int]:
        try:
            response = self.session.get(url, headers={"User-Agent": self.user_agent, "Accept": "text/html"}, timeout=self.timeout_seconds)
        except requests.RequestException as error:
            raise SourceFetchError(f"Could not fetch Le Hoi Viet Nam URL: {url}") from error
        if response.status_code != 200: raise SourceFetchError(f"Le Hoi Viet Nam returned HTTP {response.status_code}: {url}")
        return response.content.decode("utf-8"), response.status_code

    def _event_links(self, html: str, base_url: str) -> set[str]:
        parser = _EventLinkParser(); parser.feed(html); parser.close()
        return {self._public_url(urljoin(base_url, href)) for href in parser.hrefs}

    @staticmethod
    def _event_json_ld(html: str) -> dict[str, Any] | None:
        for payload in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
            try: values = json.loads(payload)
            except json.JSONDecodeError: continue
            for item in values if isinstance(values, list) else [values]:
                if isinstance(item, dict) and item.get("@type") == "Event": return item
        return None

    def _date_to_utc(self, value: str, end: bool) -> str:
        try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error: raise SourceFetchError(f"Invalid Event JSON-LD date: {value!r}") from error
        if parsed.tzinfo is None: parsed = datetime.combine(parsed.date(), time.max if end else time.min, self.timezone)
        return to_utc_iso(parsed)

    def _with_page(self, page: int) -> str:
        split = urlsplit(self.listing_url); query = dict(parse_qsl(split.query))
        if page > 1: query["page"] = str(page)
        else: query.pop("page", None)
        return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), ""))

    @staticmethod
    def _public_url(url: str) -> str:
        split = urlsplit(url); return urlunsplit((split.scheme, split.netloc, split.path, "", ""))

    def _required_url(self, key: str) -> str:
        value = self.config.get(key)
        if not isinstance(value, str) or urlsplit(value).scheme != "https": raise ValueError(f"Le Hoi Viet Nam {key} must be an HTTPS URL.")
        return value

    def _positive_int(self, key: str, default: int) -> int:
        try: value = int(self.config.get(key, default))
        except (TypeError, ValueError) as error: raise ValueError(f"Le Hoi Viet Nam {key} must be a positive integer.") from error
        if value < 1: raise ValueError(f"Le Hoi Viet Nam {key} must be a positive integer.")
        return value

    @staticmethod
    def _text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip(): raise SourceFetchError(f"Le Hoi Viet Nam Event requires {field}.")
        return value.strip()
