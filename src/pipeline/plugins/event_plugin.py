"""Adapter for the public Van Mieu - Quoc Tu Giam event API.

The adapter only knows the source contract.  Persistence, revisions, and
feature generation belong to the orchestrator and storage layers.
"""

from __future__ import annotations

import json
import logging
import random
import time
import unicodedata
from collections import deque
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import requests

from ..base import (
    EventDraft,
    EventSource,
    FetchResult,
    canonical_json_hash,
    parse_datetime_utc,
    to_utc_iso,
    utc_now,
)


LOGGER = logging.getLogger(__name__)


class SourceFetchError(RuntimeError):
    """The source could not be fetched safely after configured retries."""


class EventRecordError(ValueError):
    """One source record cannot be normalized into the event contract."""


CATEGORY_MAP = {
    "cultural": "cultural_event",
    "diplomatic": "official_or_diplomatic",
    "seminar": "conference_seminar",
    "workshop": "workshop",
}

RAW_EVENT_FIELDS = (
    "id",
    "title",
    "description",
    "contentLeft",
    "contentRight",
    "startDate",
    "endDate",
    "location",
    "category",
    "featured",
    "slug",
    "updatedAt",
    "createdAt",
    "_status",
)

ARTICLE_ROUTE_PREFIX = ("vi", "events", "event-calendar")
ARTICLE_STATUSES = frozenset(
    {"upcoming-events", "ongoing-events", "ended-events"}
)
ARTICLE_PAGE_PARAMETERS = frozenset(
    {"upcomingPage", "ongoingPage", "endedPage"}
)


class _HrefParser(HTMLParser):
    """Extract actual anchor href attributes from a server-rendered listing."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.hrefs.append(value)
                return


class VanMieuEventSource(EventSource):
    """Fetch and normalize events published by Van Mieu - Quoc Tu Giam."""

    source_name = "van_mieu"

    def __init__(
        self,
        config: Mapping[str, Any],
        session: requests.Session | Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.config = dict(config)
        self.endpoint = self._required_text("endpoint")
        self.listing_url = self._required_text("listing_url")
        self.resolve_article_urls = self._boolean(
            "resolve_article_urls",
            default=False,
        )
        self.article_listing_urls = self._article_listing_urls()
        self.article_listing_max_pages = self._positive_int(
            "article_listing_max_pages",
            20,
        )
        self.locale = str(self.config.get("locale", "vi"))
        self.limit = self._positive_int("limit", 100)
        self.max_pages = self._positive_int("max_pages", 20)
        self.timeout_seconds = self._positive_int("timeout_seconds", 30)
        self.max_retries = self._non_negative_int("max_retries", 3)
        self.overlap_minutes = self._non_negative_int(
            "watermark_overlap_minutes", 10
        )
        self.user_agent = str(
            self.config.get("user_agent", "DemandSpikeDetector/0.1")
        )
        self.city = str(self.config.get("scope_city", "hanoi"))
        self.session = session or requests.Session()
        self.sleep_fn = sleep_fn
        self.random_fn = random_fn

    def fetch(self, state: Mapping[str, Any], full_scan: bool) -> FetchResult:
        """Fetch all pages, using a watermark when this is an incremental run."""

        requested_at_utc = to_utc_iso(utc_now())
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if not full_scan:
            if state.get("etag"):
                headers["If-None-Match"] = str(state["etag"])
            if state.get("last_modified"):
                headers["If-Modified-Since"] = str(state["last_modified"])

        watermark_used = None if full_scan else self._overlap_watermark(state)
        page = 1
        visited_pages: set[int] = set()
        response_pages: list[dict[str, Any]] = []
        fetched_records: list[dict[str, Any]] = []
        http_statuses: list[int] = []
        response_headers: dict[str, str] = {}

        while True:
            if page in visited_pages:
                raise SourceFetchError(
                    f"{self.source_name} returned a repeated page number: {page}."
                )
            if len(visited_pages) >= self.max_pages:
                raise SourceFetchError(
                    f"{self.source_name} exceeded max_pages={self.max_pages}."
                )
            visited_pages.add(page)

            params: dict[str, Any] = {
                "locale": self.locale,
                "limit": self.limit,
                "page": page,
                "depth": 0,
                "sort": "updatedAt",
                "where[_status][equals]": "published",
            }
            if watermark_used:
                params["where[updatedAt][greater_than]"] = watermark_used

            payload, status_code, page_headers = self._request_page(params, headers)
            http_statuses.append(status_code)
            response_headers = page_headers

            if status_code == 304:
                if page != 1:
                    raise SourceFetchError(
                        "The source returned 304 after pagination had started."
                    )
                return FetchResult(
                    source=self.source_name,
                    endpoint=self.endpoint,
                    requested_at_utc=requested_at_utc,
                    response_pages=[],
                    fetched_records=[],
                    http_statuses=http_statuses,
                    watermark_used=watermark_used,
                    response_headers=response_headers,
                    not_modified=True,
                )

            if not isinstance(payload, dict):
                raise SourceFetchError("Source response must be a JSON object.")
            docs = payload.get("docs")
            if not isinstance(docs, list):
                raise SourceFetchError("Source response does not contain a docs list.")
            if not all(isinstance(doc, dict) for doc in docs):
                raise SourceFetchError("Source docs must be JSON objects.")

            response_pages.append(payload)
            # Keep the API response immutable for raw provenance.  The
            # public article URL is added to separate copies below.
            fetched_records.extend(dict(doc) for doc in docs)

            if not payload.get("hasNextPage", False):
                break

            next_page = payload.get("nextPage")
            if isinstance(next_page, bool):
                raise SourceFetchError("Source nextPage must be a positive integer.")
            try:
                next_page = int(next_page)
            except (TypeError, ValueError) as error:
                raise SourceFetchError(
                    "Source response declared another page without nextPage."
                ) from error
            if next_page < 1:
                raise SourceFetchError("Source nextPage must be a positive integer.")
            page = next_page

        state_updates: dict[str, Any] = {}
        if self.resolve_article_urls and fetched_records:
            (
                fetched_records,
                listing_artifacts,
                listing_statuses,
                article_url_cache,
            ) = self._attach_public_article_urls(
                fetched_records,
                state,
                refresh_cache=full_scan,
            )
            response_pages.extend(listing_artifacts)
            http_statuses.extend(listing_statuses)
            state_updates["article_url_cache_by_slug"] = article_url_cache

        return FetchResult(
            source=self.source_name,
            endpoint=self.endpoint,
            requested_at_utc=requested_at_utc,
            response_pages=response_pages,
            fetched_records=fetched_records,
            http_statuses=http_statuses,
            watermark_used=watermark_used,
            response_headers=response_headers,
            state_updates=state_updates,
        )

    def normalize(self, raw_record: Mapping[str, Any]) -> EventDraft:
        """Map one whitelisted source document to the shared contract."""

        source_event_id = self._required_record_text(raw_record, "id")
        title = self._required_record_text(raw_record, "title")
        start_at_utc = parse_datetime_utc(raw_record.get("startDate"), "startDate")
        if start_at_utc is None:
            raise EventRecordError("startDate is required.")
        end_at_utc = parse_datetime_utc(raw_record.get("endDate"), "endDate")
        if end_at_utc and self._as_datetime(end_at_utc) < self._as_datetime(start_at_utc):
            raise EventRecordError("endDate cannot be earlier than startDate.")

        raw_category = self._optional_text(raw_record.get("category"))
        category_key = raw_category.lower() if raw_category else ""
        article_url = self._optional_text(raw_record.get("_article_url"))
        if self.resolve_article_urls and not article_url:
            slug = self._optional_text(raw_record.get("slug"))
            raise EventRecordError(
                "No public article URL was resolved for "
                f"Van Mieu event slug {slug!r}."
            )
        publication_status = self._optional_text(raw_record.get("_status"))
        venue_raw = self._optional_text(raw_record.get("location"))
        description = self._description(raw_record)
        source_updated_at_utc = parse_datetime_utc(
            raw_record.get("updatedAt"), "updatedAt"
        )
        source_created_at_utc = parse_datetime_utc(
            raw_record.get("createdAt"), "createdAt"
        )
        raw_payload = {
            field_name: raw_record.get(field_name) for field_name in RAW_EVENT_FIELDS
        }

        return EventDraft(
            source=self.source_name,
            source_event_id=source_event_id,
            title=title,
            description=description,
            raw_category=raw_category,
            primary_category=CATEGORY_MAP.get(category_key, "other"),
            publication_status=publication_status,
            event_status="unknown",
            start_at_utc=start_at_utc,
            end_at_utc=end_at_utc,
            venue_raw=venue_raw,
            source_url=article_url
            or f"{self.endpoint.rstrip('/')}/{quote(source_event_id, safe='')}",
            source_created_at_utc=source_created_at_utc,
            source_updated_at_utc=source_updated_at_utc,
            raw_payload_sha256=canonical_json_hash(raw_payload),
            city=self.city,
        )

    def _attach_public_article_urls(
        self,
        records: list[dict[str, Any]],
        state: Mapping[str, Any],
        refresh_cache: bool,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[int],
        dict[str, str],
    ]:
        """Resolve exact public article links without guessing their status."""

        cache = self._article_url_cache(state)
        records_with_urls = [dict(record) for record in records]
        unresolved_by_listing: dict[str, set[str]] = {}

        for record in records_with_urls:
            slug = self._optional_text(record.get("slug"))
            if not slug:
                continue
            slug_key = self._slug_key(slug)
            if refresh_cache:
                cache.pop(slug_key, None)
            cached_url = cache.get(slug_key)
            if cached_url:
                record["_article_url"] = cached_url
                continue
            listing_url = self._listing_url_for_category(record.get("category"))
            if listing_url:
                unresolved_by_listing.setdefault(listing_url, set()).add(slug_key)

        listing_artifacts: list[dict[str, Any]] = []
        listing_statuses: list[int] = []
        for listing_url, wanted_slugs in sorted(unresolved_by_listing.items()):
            resolved, artifacts, statuses = self._discover_article_urls(
                listing_url,
                wanted_slugs,
            )
            cache.update(resolved)
            listing_artifacts.extend(artifacts)
            listing_statuses.extend(statuses)

        for record in records_with_urls:
            slug = self._optional_text(record.get("slug"))
            if slug:
                article_url = cache.get(self._slug_key(slug))
                if article_url:
                    record["_article_url"] = article_url

        return records_with_urls, listing_artifacts, listing_statuses, cache

    def _discover_article_urls(
        self,
        listing_url: str,
        wanted_slugs: set[str],
    ) -> tuple[dict[str, str], list[dict[str, Any]], list[int]]:
        """Walk only official listing pagination until target slugs are found."""

        first_page = self._canonical_url(listing_url, self.listing_url)
        if not first_page:
            raise ValueError(f"Invalid Van Mieu article listing URL: {listing_url!r}.")

        pending: deque[str] = deque([first_page])
        visited: set[str] = set()
        resolved: dict[str, str] = {}
        artifacts: list[dict[str, Any]] = []
        statuses: list[int] = []

        while (
            pending
            and len(visited) < self.article_listing_max_pages
            and not wanted_slugs.issubset(resolved)
        ):
            page_url = pending.popleft()
            if page_url in visited:
                continue
            visited.add(page_url)

            html, status_code = self._request_listing_page(page_url)
            statuses.append(status_code)
            hrefs = self._listing_hrefs(html)
            page_article_urls = self._article_urls_from_hrefs(hrefs, page_url)
            newly_resolved = {
                slug: url
                for slug, url in page_article_urls.items()
                if slug in wanted_slugs and slug not in resolved
            }
            resolved.update(newly_resolved)
            artifacts.append(
                {
                    "kind": "public_article_url_listing",
                    "listing_url": page_url,
                    "resolved_article_urls": [
                        {"slug": slug, "url": url}
                        for slug, url in sorted(newly_resolved.items())
                    ],
                }
            )

            for pagination_url in self._pagination_urls(hrefs, first_page):
                if pagination_url not in visited and pagination_url not in pending:
                    pending.append(pagination_url)

        unresolved_count = len(wanted_slugs.difference(resolved))
        if unresolved_count:
            reason = (
                "reached article_listing_max_pages"
                if pending
                else "listing pages did not contain all requested slugs"
            )
            LOGGER.warning(
                "Van Mieu public article URL resolution left %s slug(s) unresolved "
                "for %s: %s.",
                unresolved_count,
                listing_url,
                reason,
            )
        return resolved, artifacts, statuses

    def _request_listing_page(self, url: str) -> tuple[str, int]:
        """Fetch one public listing page using the source retry policy."""

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
                    try:
                        return self._decode_html(response), status_code
                    except UnicodeDecodeError as error:
                        raise SourceFetchError(
                            f"Van Mieu listing is not valid UTF-8: {url}"
                        ) from error
                if status_code not in {429, 500, 502, 503, 504}:
                    raise SourceFetchError(
                        "Van Mieu public listing returned non-retryable "
                        f"HTTP status {status_code}: {url}"
                    )
                last_error = SourceFetchError(
                    "Van Mieu public listing returned retryable "
                    f"HTTP status {status_code}: {url}"
                )

            if attempt == self.max_retries:
                break
            delay_seconds = self._retry_delay(attempt, response)
            LOGGER.warning(
                "Van Mieu listing %s failed on attempt %s; retrying in %.2f seconds.",
                url,
                attempt + 1,
                delay_seconds,
            )
            self.sleep_fn(delay_seconds)

        raise SourceFetchError(
            "Could not fetch Van Mieu public event listing after "
            f"{self.max_retries + 1} attempts: {url}"
        ) from last_error

    @staticmethod
    def _decode_html(response: Any) -> str:
        content = getattr(response, "content", None)
        if isinstance(content, (bytes, bytearray)):
            return bytes(content).decode("utf-8")
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return text
        raise UnicodeDecodeError("utf-8", b"", 0, 0, "response has no HTML body")

    @staticmethod
    def _listing_hrefs(html: str) -> list[str]:
        parser = _HrefParser()
        parser.feed(html)
        parser.close()
        return parser.hrefs

    def _article_urls_from_hrefs(
        self,
        hrefs: list[str],
        base_url: str,
    ) -> dict[str, str]:
        article_urls: dict[str, str] = {}
        for href in hrefs:
            candidate = self._canonical_url(href, base_url)
            if not candidate:
                continue
            slug = self._article_slug_from_url(candidate)
            if slug:
                article_urls.setdefault(slug, candidate)
        return article_urls

    def _pagination_urls(
        self,
        hrefs: list[str],
        listing_url: str,
    ) -> list[str]:
        listing_parts = urlsplit(listing_url)
        pagination_urls: set[str] = set()
        for href in hrefs:
            candidate = self._canonical_url(href, listing_url)
            if not candidate:
                continue
            candidate_parts = urlsplit(candidate)
            if (
                candidate_parts.scheme != listing_parts.scheme
                or candidate_parts.netloc != listing_parts.netloc
                or candidate_parts.path != listing_parts.path
            ):
                continue
            query = parse_qsl(candidate_parts.query, keep_blank_values=True)
            if any(
                name in ARTICLE_PAGE_PARAMETERS
                and value.isdigit()
                and int(value) >= 1
                for name, value in query
            ):
                pagination_urls.add(candidate)
        return sorted(pagination_urls)

    def _article_url_cache(self, state: Mapping[str, Any]) -> dict[str, str]:
        raw_cache = state.get("article_url_cache_by_slug")
        if not isinstance(raw_cache, Mapping):
            return {}
        cache: dict[str, str] = {}
        for raw_slug, raw_url in raw_cache.items():
            if not isinstance(raw_slug, str) or not isinstance(raw_url, str):
                continue
            candidate = self._canonical_url(raw_url, self.listing_url)
            slug = self._article_slug_from_url(candidate) if candidate else None
            slug_key = self._slug_key(raw_slug)
            if slug and slug == slug_key:
                cache[slug_key] = candidate
        return cache

    def _listing_url_for_category(self, raw_category: object) -> str | None:
        category = self._optional_text(raw_category)
        category_key = self._slug_key(category) if category else ""
        return self.article_listing_urls.get(
            category_key,
            self.article_listing_urls.get("*"),
        )

    def _article_listing_urls(self) -> dict[str, str]:
        if not self.resolve_article_urls:
            return {}

        configured = self.config.get("article_listing_urls")
        if configured is None:
            configured = {"*": self.listing_url}
        if not isinstance(configured, Mapping) or not configured:
            raise ValueError(
                "Van Mieu article_listing_urls must be a non-empty mapping."
            )

        listing_urls: dict[str, str] = {}
        for category, url in configured.items():
            if not isinstance(category, str) or not isinstance(url, str):
                raise ValueError(
                    "Van Mieu article_listing_urls keys and values must be strings."
                )
            category_key = self._slug_key(category)
            canonical_url = self._canonical_url(url, self.listing_url)
            if not category_key or not canonical_url:
                raise ValueError(
                    f"Invalid Van Mieu article listing configuration: {category!r}."
                )
            listing_urls[category_key] = canonical_url
        return listing_urls

    def _canonical_url(self, href: str, base_url: str) -> str | None:
        try:
            parsed = urlsplit(urljoin(base_url, href))
        except ValueError:
            return None
        expected = urlsplit(self.listing_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.netloc.casefold() != expected.netloc.casefold()
        ):
            return None
        path = quote(
            unquote(parsed.path),
            safe="/%:@!$&'()*+,;=-._~",
        )
        query = urlencode(parse_qsl(parsed.query, keep_blank_values=True), doseq=True)
        return urlunsplit(
            (
                parsed.scheme.casefold(),
                parsed.netloc.casefold(),
                path,
                query,
                "",
            )
        )

    def _article_slug_from_url(self, url: str) -> str | None:
        parts = [
            unquote(part)
            for part in urlsplit(url).path.split("/")
            if part
        ]
        if (
            len(parts) != 5
            or tuple(parts[:3]) != ARTICLE_ROUTE_PREFIX
            or parts[3] not in ARTICLE_STATUSES
            or not parts[4].strip()
        ):
            return None
        return self._slug_key(parts[4])

    @staticmethod
    def _slug_key(value: str) -> str:
        return unicodedata.normalize("NFC", value).strip().casefold()

    def _request_page(
        self,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> tuple[dict[str, Any] | None, int, dict[str, str]]:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            response: Any | None = None
            try:
                response = self.session.get(
                    self.endpoint,
                    params=dict(params),
                    headers=dict(headers),
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as error:
                last_error = error
            else:
                status_code = int(response.status_code)
                response_headers = {
                    str(key): str(value)
                    for key, value in getattr(response, "headers", {}).items()
                }
                if status_code == 304:
                    return None, status_code, response_headers
                if 200 <= status_code < 300:
                    try:
                        return self._decode_json(response), status_code, response_headers
                    except (UnicodeDecodeError, ValueError) as error:
                        raise SourceFetchError(
                            "Source returned a successful response with invalid JSON."
                        ) from error
                if status_code not in {429, 500, 502, 503, 504}:
                    raise SourceFetchError(
                        f"Source returned non-retryable HTTP status {status_code}."
                    )
                last_error = SourceFetchError(
                    f"Source returned retryable HTTP status {status_code}."
                )

            if attempt == self.max_retries:
                break
            delay_seconds = self._retry_delay(attempt, response)
            LOGGER.warning(
                "Event source %s failed on attempt %s; retrying in %.2f seconds.",
                self.source_name,
                attempt + 1,
                delay_seconds,
            )
            self.sleep_fn(delay_seconds)

        raise SourceFetchError(
            f"Could not fetch {self.source_name} after {self.max_retries + 1} attempts."
        ) from last_error

    @staticmethod
    def _decode_json(response: Any) -> Any:
        """Decode JSON response bytes explicitly as UTF-8, the JSON default."""

        content = getattr(response, "content", None)
        if isinstance(content, (bytes, bytearray)):
            try:
                return json.loads(bytes(content).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        return response.json()

    def _retry_delay(self, attempt: int, response: Any | None) -> float:
        retry_after = None
        if response is not None:
            raw_retry_after = getattr(response, "headers", {}).get("Retry-After")
            try:
                retry_after = float(raw_retry_after)
            except (TypeError, ValueError):
                retry_after = None
        if retry_after is not None and retry_after >= 0:
            return min(retry_after, 120.0)
        return min(2.0**attempt, 60.0) + self.random_fn() * 0.25

    def _overlap_watermark(self, state: Mapping[str, Any]) -> str | None:
        existing = state.get("watermark_utc")
        if not existing:
            return None
        try:
            canonical = parse_datetime_utc(existing, "state.watermark_utc")
            if canonical is None:
                return None
            return to_utc_iso(
                self._as_datetime(canonical) - timedelta(minutes=self.overlap_minutes)
            )
        except ValueError:
            LOGGER.warning(
                "Ignoring an invalid saved watermark for source %s.", self.source_name
            )
            return None

    @staticmethod
    def _as_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _required_text(self, name: str) -> str:
        value = self._optional_text(self.config.get(name))
        if not value:
            raise ValueError(f"Event source config requires '{name}'.")
        return value

    def _boolean(self, name: str, default: bool) -> bool:
        value = self.config.get(name, default)
        if not isinstance(value, bool):
            raise ValueError(f"Event source config '{name}' must be true or false.")
        return value

    def _positive_int(self, name: str, default: int) -> int:
        value = self._non_negative_int(name, default)
        if value < 1:
            raise ValueError(f"Event source config '{name}' must be at least 1.")
        return value

    def _non_negative_int(self, name: str, default: int) -> int:
        try:
            value = int(self.config.get(name, default))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Event source config '{name}' must be an integer.") from error
        if value < 0:
            raise ValueError(f"Event source config '{name}' cannot be negative.")
        return value

    def _required_record_text(
        self,
        raw_record: Mapping[str, Any],
        field_name: str,
    ) -> str:
        value = raw_record.get(field_name)
        if value is None:
            raise EventRecordError(f"{field_name} is required.")
        normalized = str(value).strip()
        if not normalized:
            raise EventRecordError(f"{field_name} cannot be blank.")
        return normalized

    def _description(self, raw_record: Mapping[str, Any]) -> str | None:
        direct_description = self._optional_text(raw_record.get("description"))
        if direct_description:
            return direct_description

        rich_text = " ".join(
            text
            for field_name in ("contentLeft", "contentRight")
            if (text := self._lexical_to_text(raw_record.get(field_name)))
        ).strip()
        return rich_text or None

    def _lexical_to_text(self, value: object) -> str:
        fragments: list[str] = []

        def visit(node: object) -> None:
            if isinstance(node, Mapping):
                text = node.get("text")
                if isinstance(text, str) and text.strip():
                    fragments.append(text.strip())
                root = node.get("root")
                if isinstance(root, (Mapping, list)):
                    visit(root)
                children = node.get("children")
                if isinstance(children, list):
                    for child in children:
                        visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(value)
        return " ".join(fragments)
