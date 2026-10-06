"""Backstage.vn event discovery for Vietnam domestic events.

Backstage publishes event articles with dates and venues. This adapter
crawls listing pages and detail articles to extract structured event data.

NOTE: Backstage.vn articles contain brief summaries. Full article content is
loaded dynamically. The plugin extracts what information is available in the
static HTML and JSON-LD metadata. Fields that cannot be determined are left
as None/empty.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

from ..base import EventDraft, EventSource, FetchResult, canonical_json_hash, to_utc_iso, utc_now
from .event_plugin import EventRecordError, SourceFetchError


class BackstageEventSource(EventSource):
    """Discover events from Backstage.vn article listings."""

    source_name = "backstage_vn"
    _EXCLUDED_PATHS = frozenset({
        "/su-kien/",
        "/su-kien/su-kien-trong-nuoc/",
        "/su-kien/su-kien-quoc-te/",
    })

    def __init__(
        self,
        config: Mapping[str, Any],
        event_date_window: Mapping[str, str] | None = None,
        session: Any | None = None,
    ) -> None:
        super().__init__(config, event_date_window)
        self.listing_url = self._required_url("listing_url")
        self.max_pages = self._positive_int("max_pages", 20)
        self.timeout_seconds = self._positive_int("timeout_seconds", 30)
        self.user_agent = str(self.config.get("user_agent", "DemandSpikeDetector/0.1"))
        self.city = str(self.config.get("scope_city", "hanoi"))
        self.timezone = ZoneInfo(str(self.config.get("timezone", "Asia/Ho_Chi_Minh")))
        self.default_duration_minutes = self._positive_int("default_duration_minutes", 180)
        self.session = session or requests.Session()

        # Parse date window for filtering
        self._start_date = None
        self._end_date = None
        if self.event_date_window:
            start_str = self.event_date_window.get("start_date")
            end_str = self.event_date_window.get("end_date")
            if start_str:
                self._start_date = self._parse_date(start_str)
            if end_str:
                self._end_date = self._parse_date(end_str)

    def fetch(self, state: Mapping[str, Any], full_scan: bool) -> FetchResult:
        del state, full_scan
        pages: list[dict[str, Any]] = []
        statuses: list[int] = []
        article_urls: set[str] = set()

        # Crawl listing pages to find article links
        for page in range(1, self.max_pages + 1):
            url = self._listing_url(page)
            html_content, status = self._get(url)
            statuses.append(status)

            # Extract article URLs from jeg_post blocks
            hrefs = self._extract_article_links(html_content, url)
            pages.append({"kind": "listing", "url": url, "article_urls": sorted(hrefs)})

            if not hrefs:
                break
            article_urls.update(hrefs)

        # Fetch detail pages
        records: list[dict[str, Any]] = []
        for url in sorted(article_urls):
            html_content, status = self._get(url)
            statuses.append(status)
            event_data = self._parse_detail(html_content, url)
            pages.append({"kind": "event", "url": url, "event": event_data})
            if event_data is not None:
                records.append(event_data)

        # Filter by date window if configured
        if self._start_date is not None or self._end_date is not None:
            records = [record for record in records if self._is_within_date_window(record)]

        # Only keep records that have both date AND venue
        # Events without these fields are too incomplete to be useful
        records = [
            record for record in records
            if record.get("start_at_utc") is not None and record.get("venue") is not None
        ]

        return FetchResult(
            self.source_name,
            self.listing_url,
            to_utc_iso(utc_now()),
            pages,
            records,
            statuses,
            None,
        )

    def normalize(self, raw_record: Mapping[str, Any]) -> EventDraft:
        url = self._required("raw_record", raw_record, "url")
        title = self._required("raw_record", raw_record, "title")

        # start_at_utc may be None if date not found in article
        start_at_utc = raw_record.get("start_at_utc")
        if not start_at_utc:
            raise EventRecordError(
                f"Backstage article has no event date: {title}"
            )

        start_dt = datetime.fromisoformat(start_at_utc.replace("Z", "+00:00"))
        end_at_utc = to_utc_iso(
            start_dt.replace(hour=23, minute=59) if start_dt.hour == 0 else start_dt
        )

        venue = raw_record.get("venue")
        description = raw_record.get("description")
        category = self._infer_category(title, description)
        inferred_city = raw_record.get("city", self.city)

        return EventDraft(
            source=self.source_name,
            source_event_id=canonical_json_hash({"url": url, "title": title})[:20],
            title=title,
            description=description,
            raw_category=category,
            primary_category=category,
            publication_status="published",
            event_status="scheduled",
            start_at_utc=start_at_utc,
            end_at_utc=end_at_utc,
            venue_raw=str(venue).strip() if venue else None,
            source_url=url,
            source_created_at_utc=None,
            source_updated_at_utc=None,
            raw_payload_sha256=canonical_json_hash(dict(raw_record)),
            city=inferred_city,
            tags=["backstage", category],
        )

    def _get(self, url: str) -> tuple[str, int]:
        try:
            response = self.session.get(
                url,
                headers={"User-Agent": self.user_agent, "Accept": "text/html"},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as error:
            raise SourceFetchError(f"Could not fetch Backstage URL: {url}") from error
        if response.status_code != 200:
            raise SourceFetchError(f"Backstage returned HTTP {response.status_code}: {url}")
        return response.content.decode("utf-8"), response.status_code

    def _listing_url(self, page: int) -> str:
        if page == 1:
            return self.listing_url
        split = urlsplit(self.listing_url)
        path = split.path.rstrip("/")
        if not path.endswith("/"):
            path += "/"
        new_path = f"{path}page/{page}/"
        return urlunsplit((split.scheme, split.netloc, new_path, "", ""))

    def _extract_article_links(self, html_content: str, base_url: str) -> set[str]:
        """Extract article URLs from jeg_post blocks in the HTML."""
        pattern = r'class="jeg_post[^"]*"[^>]*>.*?<a[^>]+href="(https://backstage\.vn/[^"]+)"'
        matches = re.findall(pattern, html_content, re.DOTALL)

        urls = set()
        for href in matches:
            parsed = urlsplit(href)
            if parsed.path in self._EXCLUDED_PATHS:
                continue
            if "/page/" in parsed.path:
                continue
            urls.add(self._public_url(urljoin(base_url, href)))

        return urls

    def _parse_detail(self, html_content: str, url: str) -> dict[str, Any] | None:
        """Parse event details from article page.

        Backstage articles are brief summaries. We extract:
        - Title from <title> or og:title
        - Date from article body text (format: DD/MM/YYYY)
        - Venue from article body text
        - Description from available text content

        Fields not found in the article are left as None.
        """
        # Extract title from og:title meta tag
        title = self._extract_title(html_content)
        if not title:
            return None

        # Extract article body text
        article_text = self._extract_article_text(html_content)

        # Extract event date from text
        start_at_utc = self._extract_date(article_text)

        # Extract venue from text
        venue = self._extract_venue(article_text)

        # Infer city from venue/content
        city = self._infer_city(article_text, venue)

        # Description is limited since articles are brief summaries
        description = article_text if len(article_text) > 20 else None

        return {
            "url": url,
            "title": title,
            "description": description,
            "start_at_utc": start_at_utc,  # May be None if not found
            "venue": venue,  # May be None if not found
            "city": city,
        }

    def _extract_title(self, html_content: str) -> str | None:
        """Extract article title from og:title or <title> tag."""
        # Try og:title first
        match = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content="([^"]+)"',
            html_content, re.I
        )
        if not match:
            match = re.search(
                r'<meta[^>]+content="([^"]+)"[^>]+property=["\']og:title["\']',
                html_content, re.I
            )
        if match:
            return html.unescape(match.group(1).strip())

        # Fall back to <title>
        match = re.search(r'<title>([^<]+)</title>', html_content, re.I)
        if match:
            # Take first part before |
            title = match.group(1).split("|")[0].strip()
            return html.unescape(title)

        return None

    def _extract_article_text(self, html_content: str) -> str:
        """Extract readable text from article content area.

        Backstage articles are brief summaries. We try to get what text
        is available in the article body.
        """
        # Clean HTML - remove scripts and styles
        cleaned = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.I)
        cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.DOTALL | re.I)

        # Try to find article tag content
        article_match = re.search(r'<article[^>]*>(.*?)</article>', cleaned, re.DOTALL | re.I)
        if article_match:
            content = article_match.group(1)
        else:
            content = cleaned

        # Remove HTML tags but unescape HTML entities first
        text = re.sub(r'<[^>]+>', ' ', content)
        text = html.unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def _extract_date(self, text: str) -> str | None:
        """Extract event date from content text.

        Dates appear in format DD/MM/YYYY or similar patterns.
        Returns None if no date found - this is acceptable.
        """
        # Pattern for DD/MM/YYYY
        match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
        if match:
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            try:
                # Default to noon in local timezone
                dt = datetime(year, month, day, 12, 0, tzinfo=self.timezone)
                return to_utc_iso(dt)
            except ValueError:
                pass

        return None

    def _extract_venue(self, text: str) -> str | None:
        """Extract venue from content text.

        Venue is extracted from keywords like 'tại', 'sân', 'trung tâm', etc.
        Returns None if no venue found - this is acceptable.
        """
        venue_keywords = [
            "tại",
            "địa điểm",
            "sân vận động",
            "sân",
            "trung tâm",
            "nhà hát",
            "cung",
            "khách sạn",
            "ve",
        ]

        for keyword in venue_keywords:
            # Pattern: keyword followed by venue name until punctuation/end
            pattern = re.compile(
                rf"{re.escape(keyword)}\s*[:\-]?\s*([^.,;\n]+?)(?:\.|,|và|$)",
                re.I,
            )
            match = pattern.search(text)
            if match:
                venue = match.group(1).strip()
                # Clean up venue name
                venue = re.sub(r"\s+", " ", venue)
                venue = html.unescape(venue)
                if len(venue) > 2 and len(venue) < 200:
                    return venue

        return None

    def _infer_city(self, text: str, venue: str | None) -> str:
        """Infer city from content and venue text."""
        combined = f"{text} {venue or ''}".casefold()

        # Check for Hanoi
        hanoi_keywords = ["hà nội", "ha noi", "hanoi", "miền bắc", "mien bac", "phía bắc"]
        if any(kw in combined for kw in hanoi_keywords):
            return "hanoi"

        # Check for Ho Chi Minh City
        hcm_keywords = [
            "tp.hcm",
            "tphcm",
            "hồ chí minh",
            "ho chi minh",
            "sài gòn",
            "sai gon",
            "tp hcm",
        ]
        if any(kw in combined for kw in hcm_keywords):
            return "ho_chi_minh"

        return self.city

    def _infer_category(self, title: str, description: str | None) -> str:
        """Infer event category from title and description."""
        combined = f"{title} {description or ''}".casefold()

        category_keywords = {
            "concert": ["concert", "nhạc", "show", "ca nhạc", "live", "nhóm", "band"],
            "festival": ["festival", "lễ hội", "ngày hội", "carnival", "đại nhạc hội"],
            "exhibition": ["triển lãm", "exhibition", "trưng bày", "trưng bày"],
            "workshop": ["workshop", "hội thảo", "seminar"],
            "sports": ["marathon", "bóng đá", "football", "giải đấu", "thi đấu"],
        }

        for category, keywords in category_keywords.items():
            if any(kw in combined for kw in keywords):
                return category

        return "other"

    @staticmethod
    def _public_url(url: str) -> str:
        split = urlsplit(url)
        return urlunsplit((split.scheme, split.netloc, split.path, "", ""))

    def _required_url(self, key: str) -> str:
        value = self.config.get(key)
        if not isinstance(value, str):
            raise ValueError(f"Backstage config requires '{key}'.")
        parsed = urlsplit(value)
        if parsed.scheme != "https":
            raise ValueError(f"Backstage {key} must be an HTTPS URL.")
        return value

    def _positive_int(self, key: str, default: int) -> int:
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Backstage {key} must be a positive integer.") from error
        if value < 1:
            raise ValueError(f"Backstage {key} must be a positive integer.")
        return value

    @staticmethod
    def _required(label: str, record: Mapping[str, Any], key: str) -> str:
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            raise EventRecordError(f"Backstage {label} requires {key}.")
        return value.strip()

    @staticmethod
    def _parse_date(value: str) -> datetime:
        """Parse a YYYY-MM-DD date string."""
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError(f"Invalid date format: {value!r}. Expected YYYY-MM-DD.") from error

    def _is_within_date_window(self, record: dict[str, Any]) -> bool:
        """Check if record's event date is within configured date window.

        Records without dates are kept (date validation happens in normalize).
        """
        start_at_utc = record.get("start_at_utc")
        if not start_at_utc:
            return True  # Keep records without date

        try:
            dt = datetime.fromisoformat(start_at_utc.replace("Z", "+00:00"))
            record_date = dt.date()
        except (ValueError, AttributeError):
            return True

        if self._start_date is not None and record_date < self._start_date.date():
            return False
        if self._end_date is not None and record_date > self._end_date.date():
            return False
        return True
