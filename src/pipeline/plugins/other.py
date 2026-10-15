"""Config-driven collector for official Hanoi education and civic events."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Any, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

from ..base import EventDraft, EventSource, FetchResult, canonical_json_hash, to_utc_iso, utc_now
from .event_plugin import EventRecordError, SourceFetchError


class _ArticleParser(HTMLParser):
    """Collect public links, OpenGraph title, and readable page text."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True); self.hrefs: list[str] = []; self.text: list[str] = []; self.title = ""; self._in_title = False
        # Track if we're inside the main article content
        self._content_depth = 0
        self._content_text: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.lower() == "a" and values.get("href"): self.hrefs.append(values.get("href") or "")
        if tag.lower() == "meta" and values.get("property", "").casefold() == "og:title": self.title = values.get("content") or self.title
        if tag.lower() == "title": self._in_title = True
        # Detect article content containers
        cls = (values.get("class") or "").lower()
        itemprop = (values.get("itemprop") or "").lower()
        if tag.lower() in ("article", "main") or "news-content" in cls or "news-body" in cls or "article-body" in cls or "article-content" in cls or "post-content" in cls or itemprop == "articlebody":
            self._content_depth = 1
        elif self._content_depth > 0:
            self._content_depth += 1
    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title": self._in_title = False
        if self._content_depth > 0:
            self._content_depth -= 1
    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())
            if self._in_title and not self.title: self.title = data.strip()
            # Collect content from article body
            if self._content_depth > 0:
                self._content_text.append(data.strip())

    @property
    def article_body(self) -> str:
        """Get text from main article body only (excludes header/nav/footer/scripts)."""
        return " ".join(self._content_text)


class OfficialOtherEventSource(EventSource):
    """Collect explicit-date events from configurable, official Hanoi listings.

    This adapter intentionally rejects articles without an event date.  It avoids
    turning publication dates, rumours, and routine news into model features.
    """
    source_name = "official_hanoi_other"
    _DATE_NUMERIC = re.compile(r"(?:ngày\s*)?(\d{1,2})[/-](\d{1,2})[/-](20\d{2})", re.I)
    _DATE_WORDS = re.compile(r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(20\d{2})", re.I)
    _TIME = re.compile(r"(?:lúc|vào)\s*(\d{1,2})(?:\s*(?:giờ|h))?(?:\s*[:h]\s*(\d{2}))?", re.I)

    # Extract venue (school name) from title
    # Pattern 1: "tại Trường X" or "dự khai giảng tại Trường X" - stop at action words or weekday/date
    _VENUE_PATTERN_1 = re.compile(r"tại\s+(Trường\s+[^,.()\n]+?)(?=\s+(?:triển\s*khai|tổ\s*chức|năm\s+học|thứ\s|tại\s|ngày|chủ\s*nhật|thứ\s*[a-z]+|\d|$)|\s*[-–—]|\s*\(|\s*$|\.|,)", re.I)
    # Pattern 2: "Trường X triển khai/tổ chức/khai giảng..." (anywhere in text)
    _VENUE_PATTERN_2 = re.compile(r"(Trường\s+[^,.()\n]+?)\s+(?:triển\s*khai|tổ\s*chức|khai\s*giảng)", re.I)
    # Pattern 3: "tại trường X" (lowercase - "trường Mầm non, Tiểu học")
    _VENUE_PATTERN_3 = re.compile(r"tại\s+(trường\s+[^,.()\n]+?)(?=\s+(?:triển\s*khai|tổ\s*chức|năm\s+học|thứ\s|tại\s|ngày|chủ\s*nhật|thứ\s*[a-z]+|\d|$)|\s*[-–—]|\s*\(|\s*$|\.|,)", re.I)
    # Pattern 4: Stop at "triển khai", "tổ chức", "năm học", etc.
    _VENUE_PATTERN_4 = re.compile(r"((?:Mầm\s*non|Tiểu\s*học|THCS|THPT|Trung\s*học)\s+[^,.()\n]+?)(?=\s+(?:triển\s*khai|tổ\s*chức|năm\s+học|thứ\s|tại\s|ngày|chủ\s*nhật|thứ\s*[a-z]+|\d|$)|\s*[-–—]|\s*\(|\s*$|\.|,)", re.I)
    # Pattern 5: "trường Mầm non, Tiểu học" (standalone, anywhere in title)
    _VENUE_PATTERN_5 = re.compile(r"trường\s+(Mầm\s*non|Tiểu\s*học|THCS|THPT|Trung\s*học)(?:\s+[A-ZĐÂĂÊÔƠƯ][^,.()\n]*?)?(?=\s+(?:triển\s*khai|tổ\s*chức|năm\s+học|thứ\s|tại\s|ngày|chủ\s*nhật|thứ\s*[a-z]+|\d|$)|\s*[-–—]|\s*\(|\s*$|\.|,)", re.I)

    # Extract attendance from text - STRICT patterns to avoid date/time numbers
    # Must be near action keywords like "tập huấn", "dự", "tham dự", "cho", "có"
    # Pattern 1: "<action> X <unit>"
    _ATTENDANCE_PATTERN_1 = re.compile(r"(?:tập\s*huấn|dự|tham\s*dự|tham\s*gia|cho|có|với|quy\s*tụ|hơn)\s+(?:hơn\s+)?(\d{1,3}(?:[.,]\d{3})+|\d{2,4})\s+(người|hiệu\s*trưởng|giáo\s*viên|học\s*sinh|cán\s*bộ|trường|đại\s*biểu|thầy\s*cô)", re.I)
    # Pattern 2: "X <unit>" with specific context (counted/measured)
    _ATTENDANCE_PATTERN_2 = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d{2,4})\s+(người|hiệu\s*trưởng|giáo\s*viên|học\s*sinh|cán\s*bộ|trường|đại\s*biểu|thầy\s*cô)\s+(?:tham\s*dự|tham\s*gia|dự\s*kiến|có\s*mặt)", re.I)

    def __init__(
        self,
        config: Mapping[str, Any],
        event_date_window: Mapping[str, str] | None = None,
        session: Any | None = None,
    ) -> None:
        super().__init__(config, event_date_window)
        self.sources = self._sources()
        self.timeout = int(self.config.get("timeout_seconds", 30))
        self.timezone = ZoneInfo(str(self.config.get("timezone", "Asia/Ho_Chi_Minh")))
        self.city = str(self.config.get("scope_city", "hanoi"))
        self.duration = int(self.config.get("default_duration_minutes", 180))
        self.user_agent = str(self.config.get("user_agent", "DemandSpikeDetector/0.1"))
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
        pages: list[dict[str, Any]] = []; statuses: list[int] = []; urls: set[str] = set()
        for source in self.sources:
            html, status = self._get(source["listing_url"]); statuses.append(status)
            parser = self._parse(html); links = [self._public_url(urljoin(source["listing_url"], href)) for href in parser.hrefs]
            accepted = [url for url in links if self._allowed_url(url, source)]
            urls.update(accepted); pages.append({"kind": "listing", "url": source["listing_url"], "article_urls": accepted})
        known = {value for value in state.get("known_article_urls", []) if isinstance(value, str)}
        detail_urls = urls if full_scan else urls.difference(known)
        records: list[dict[str, Any]] = []
        for url in sorted(detail_urls):
            html, status = self._get(url); statuses.append(status); parsed = self._parse(html)
            title, body = unescape(parsed.title).strip(), " ".join(parsed.text)
            source = next(item for item in self.sources if self._allowed_url(url, item))
            # Match the article title only.  Site navigation and related-news
            # widgets often contain these words, which would otherwise create
            # false events from category pages or unrelated announcements.
            if title and self._matches(title, source["keywords"]) and not self._excluded_title(title, source):
                records.append({"url": url, "title": title, "body": body, "article_body": parsed.article_body, "source": source["name"]})
            pages.append({"kind": "article", "url": url, "accepted": bool(records and records[-1].get("url") == url)})
        for seed in self.config.get("seed_events", []):
            if isinstance(seed, Mapping): records.append({"seed": dict(seed)})

        # Filter by date window if configured
        if self._start_date is not None or self._end_date is not None:
            records = [record for record in records if self._is_within_date_window(record)]

        return FetchResult(self.source_name, self.sources[0]["listing_url"], to_utc_iso(utc_now()), pages, records, statuses, None, state_updates={"known_article_urls": sorted(known | urls)})

    def normalize(self, raw: Mapping[str, Any]) -> EventDraft:
        if isinstance(raw.get("seed"), Mapping): return self._normalize_seed(raw["seed"])
        url, title, body = raw.get("url"), raw.get("title"), raw.get("body")
        if not all(isinstance(value, str) and value.strip() for value in (url, title, body)):
            raise EventRecordError("Official event article lacks URL, title, or text.")

        # Get article body (cleaned from scripts/nav) if available
        article_body = raw.get("article_body", body)

        # Extract date from body
        start = self._event_time(body, title)
        end = to_utc_iso(datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(minutes=self.duration))

        # Extract venue from article body FIRST (more reliable than title)
        venue = self._extract_venue(article_body)
        # If body has no specific venue, try title (e.g., body only repeats title)
        if not venue:
            venue = self._extract_venue(title)
        # Final fallback: combine title + body
        if not venue:
            venue = self._extract_venue(f"{title} {article_body}")

        # Skip events without a SPECIFIC venue (chung chung)
        if not venue or self._is_generic_venue(venue):
            raise EventRecordError(f"Event lacks specific venue (got: {venue!r}). Skipped.")

        # Extract attendance from article body only (must have source URL as evidence)
        attendance, attendance_evidence = self._extract_attendance_with_evidence(article_body)

        return self._draft(
            url, title.strip(), body.strip(), start, end, venue,
            attendance=attendance,
            attendance_source_url=url if attendance_evidence else None,
        )

    def _normalize_seed(self, seed: Mapping[str, Any]) -> EventDraft:
        title = self._required(seed, "title"); url = self._required(seed, "source_url"); start = self._required(seed, "start_at_utc")
        return self._draft(url, title, str(seed.get("description") or "") or None, start, seed.get("end_at_utc") if isinstance(seed.get("end_at_utc"), str) else None, seed.get("venue"), seed.get("estimated_attendees"))

    def _draft(self, url: str, title: str, body: str | None, start: str, end: str | None, venue: object, attendance: int | None = None, attendance_source_url: str | None = None) -> EventDraft:
        return EventDraft(
            source=self.source_name,
            source_event_id=hashlib.sha256(url.encode()).hexdigest()[:20],
            title=title,
            description=body,
            raw_category="official_other",
            primary_category="other",
            publication_status="published",
            event_status="scheduled",
            start_at_utc=start,
            end_at_utc=end,
            venue_raw=str(venue).strip() if venue else None,
            source_url=url,
            source_created_at_utc=None,
            source_updated_at_utc=None,
            raw_payload_sha256=canonical_json_hash({"url": url, "title": title, "body": body}),
            city=self.city,
            tags=["official", "other"],
            estimated_attendees=attendance,
            attendee_estimation_method="parsed_from_article_body" if attendance else None,
            attendance_source_url=attendance_source_url,
        )

    @staticmethod
    def _is_generic_venue(venue: str) -> bool:
        """Check if venue is too generic (no specific name).

        Examples of generic venues to skip:
        - "Trường Mầm non" (without specific school name)
        - "trường Mầm non, Tiểu học" (just type, no name)
        - "Trường" alone
        - Common locations like "Hà Nội"
        """
        if not venue:
            return True

        venue_lower = venue.lower().strip()

        # Too short
        if len(venue_lower) < 5:
            return True

        # Generic school types without specific name
        generic_patterns = [
            r"^trường\s*mầm\s*non$",
            r"^trường\s*tiểu\s*học$",
            r"^trường\s*thcs$",
            r"^trường\s*thpt$",
            r"^trường\s+trung\s*học$",
            r"^trường\s+mầm\s*non,\s*tiểu\s*học$",
            r"^trường\s+tiểu\s*học,\s*thcs$",
            r"^trường\s+thcs,\s*thpt$",
            r"^hà\s*nội$",
            r"^trường\s*$",
        ]
        for pattern in generic_patterns:
            if re.match(pattern, venue_lower):
                return True

        return False

    @classmethod
    def _extract_attendance_with_evidence(cls, text: str) -> tuple[int | None, str | None]:
        """Extract attendance from text WITH evidence.

        Returns:
            (attendance_number, matched_phrase) - matched_phrase is the exact text
        """
        if not text:
            return None, None

        # Try patterns in order
        for pattern in (cls._ATTENDANCE_PATTERN_1, cls._ATTENDANCE_PATTERN_2):
            match = pattern.search(text)
            if match:
                number_str = match.group(1).replace(".", "").replace(",", "")
                try:
                    return int(number_str), match.group(0)
                except ValueError:
                    continue

        return None, None

    @classmethod
    def _extract_venue(cls, title: str) -> str | None:
        """Extract school name from title.

        Patterns (priority order):
        1. "tại Trường X" (e.g., "dự khai giảng tại Trường THCS Hoàng Liệt")
        2. "Trường X triển khai/tổ chức/khai giảng..." (at start of title)
        3. "tại trường X" (lowercase)
        4. "Trường X" at start (full name with type)
        5. "...trường Mầm non, Tiểu học" (general)
        6. "trường Mầm non" / "trường Tiểu học" (anywhere)
        """
        if not title:
            return None

        # Normalize whitespace - replace zero-width space and other invisible chars
        normalized = re.sub(r"[‌‍﻿]", " ", title)
        # Also collapse multiple spaces
        normalized = re.sub(r"\s+", " ", normalized).strip()

        candidates: list[tuple[str, int]] = []  # (venue, priority_score)

        # Priority 1: "tại Trường X" - HIGHEST priority (most specific)
        match = cls._VENUE_PATTERN_1.search(normalized)
        if match:
            venue = cls._clean_venue(match.group(1))
            if cls._is_valid_venue(venue):
                candidates.append((venue, 100))

        # Priority 2: "Trường X triển khai/tổ chức" at start
        match = cls._VENUE_PATTERN_2.search(normalized)
        if match:
            venue = cls._clean_venue(match.group(1))
            if cls._is_valid_venue(venue):
                candidates.append((venue, 90))

        # Priority 3: "tại trường X" (lowercase)
        match = cls._VENUE_PATTERN_3.search(normalized)
        if match:
            venue = cls._clean_venue(match.group(1))
            if cls._is_valid_venue(venue):
                candidates.append((venue, 80))

        # Priority 4: "Trường X" at start (without triển khai) - more general
        match = re.match(r"^(Trường\s+[^,.()\n]+?)(?=\s+(?:triển\s*khai|tổ\s*chức|năm\s*học|thứ\s|tại\s|ngày|chủ\s*nhật|\d|$)|\s*[-–—]|\s*\(|\s*$|\.|,)", normalized)
        if match:
            venue = cls._clean_venue(match.group(1))
            if cls._is_valid_venue(venue):
                candidates.append((venue, 70))

        # Priority 5: "...Tiểu học X..." mid-sentence
        match = cls._VENUE_PATTERN_4.search(normalized)
        if match:
            venue = cls._clean_venue(match.group(1))
            if cls._is_valid_venue(venue):
                candidates.append((venue, 50))

        # Priority 6: "trường Mầm non" with optional name
        match = cls._VENUE_PATTERN_5.search(normalized)
        if match:
            venue = cls._clean_venue(match.group(0))
            if cls._is_valid_venue(venue):
                candidates.append((venue, 30))

        # Return highest-priority valid candidate (shorter wins ties)
        if candidates:
            candidates.sort(key=lambda x: (-x[1], len(x[0])))
            return candidates[0][0]

        return None

    @staticmethod
    def _is_valid_venue(venue: str) -> bool:
        """Check if venue looks valid (not too long, must start with Trường)."""
        if not venue:
            return False
        if len(venue) > 60:  # Too long - probably sidebar/random text
            return False
        if not re.match(r"(?i)^trường\s", venue.strip()):
            return False
        return True


    @staticmethod
    def _clean_venue(venue: str) -> str:
        """Clean up venue string."""
        venue = venue.strip()
        venue = re.sub(r"[\s\-–—,]+$", "", venue).strip()
        return venue

    @classmethod
    def _extract_attendance(cls, title: str) -> int | None:
        """Extract attendance number from title.

        Patterns:
        - "hơn 600" or "hơn 1.500" → 600 or 1500
        - "600 người/hiệu trưởng/giáo viên/học sinh"
        - Supports Vietnamese thousand separator: 1.500 = 1500, 1,500 = 1500
        """
        if not title:
            return None

        # Try "hơn X" first (more specific)
        match = cls._ATTENDANCE_PATTERN_1.search(title)
        if not match:
            match = cls._ATTENDANCE_PATTERN_2.search(title)

        if not match:
            return None

        number_str = match.group(1)
        # Convert "1.500" or "1,500" to "1500"
        number_str = number_str.replace(".", "").replace(",", "")

        try:
            return int(number_str)
        except ValueError:
            return None

    def _event_time(self, text: str, title: str) -> str:
        dates = [(*match.groups(), match.start()) for match in self._DATE_NUMERIC.finditer(text)] + [(*match.groups(), match.start()) for match in self._DATE_WORDS.finditer(text)]
        if not dates: raise EventRecordError("Article has no explicit event date; it is not ingested.")
        ordered = sorted(dates, key=lambda item: item[3])
        # A school-opening notice is often published days earlier; its final
        # explicit date is the ceremony date, while the first is the document date.
        day, month, year, position = (ordered[-1] if "khai giảng" in title.casefold() else ordered[0])
        time_match = self._TIME.search(text, max(0, position - 80), min(len(text), position + 100)); hour, minute = (7, 0) if not time_match else (int(time_match.group(1)), int(time_match.group(2) or 0))
        try: value = datetime(int(year), int(month), int(day), hour, minute, tzinfo=self.timezone)
        except ValueError as error: raise EventRecordError("Article has an invalid event date.") from error
        return to_utc_iso(value)

    def _get(self, url: str) -> tuple[str, int]:
        try: response = self.session.get(url, headers={"User-Agent": self.user_agent, "Accept": "text/html"}, timeout=self.timeout)
        except requests.RequestException as error: raise SourceFetchError(f"Could not fetch official source: {url}") from error
        if response.status_code != 200: raise SourceFetchError(f"Official source returned HTTP {response.status_code}: {url}")
        return response.content.decode("utf-8"), response.status_code

    def _sources(self) -> list[dict[str, Any]]:
        items = self.config.get("listing_sources")
        if not isinstance(items, list) or not items: raise ValueError("official_hanoi_other requires listing_sources.")
        result=[]
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("listing_url"), str) or not isinstance(item.get("keywords"), list): raise ValueError("Each official listing source requires listing_url and keywords.")
            result.append({"name": str(item.get("name") or item["listing_url"]), "listing_url": item["listing_url"], "keywords": [str(x).casefold() for x in item["keywords"]], "excluded_prefixes": [str(x).casefold() for x in item.get("excluded_title_prefixes", [])], "hosts": [str(x).casefold() for x in item.get("allowed_hosts", [urlsplit(item["listing_url"]).netloc])]})
        return result

    @staticmethod
    def _parse(html: str) -> _ArticleParser:
        parser=_ArticleParser(); parser.feed(html); parser.close(); return parser
    @staticmethod
    def _public_url(url: str) -> str:
        split=urlsplit(url); return urlunsplit((split.scheme,split.netloc,split.path,split.query,""))
    @staticmethod
    def _matches(text: str, keywords: list[str]) -> bool: return any(keyword in text.casefold() for keyword in keywords)
    @staticmethod
    def _excluded_title(title: str, source: Mapping[str, Any]) -> bool: return any(title.casefold().startswith(prefix) for prefix in source["excluded_prefixes"])
    @staticmethod
    def _allowed_url(url: str, source: Mapping[str, Any]) -> bool: return urlsplit(url).scheme == "https" and urlsplit(url).netloc.casefold() in source["hosts"]
    @staticmethod
    def _required(value: Mapping[str, Any], key: str) -> str:
        raw=value.get(key)
        if not isinstance(raw,str) or not raw.strip(): raise EventRecordError(f"Seed event requires {key}.")
        return raw.strip()

    @staticmethod
    def _parse_date(value: str) -> date:
        """Parse a YYYY-MM-DD date string."""
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as error:
            raise ValueError(f"Invalid date format: {value!r}. Expected YYYY-MM-DD.") from error

    def _is_within_date_window(self, record: dict[str, Any]) -> bool:
        """Check if record's event date is within configured date window."""
        # For seed events, use start_at_utc
        if isinstance(record.get("seed"), Mapping):
            start_at_utc = record["seed"].get("start_at_utc")
        else:
            # Extract date from body text for regular records
            text = record.get("body", "")
            dates = list(self._DATE_NUMERIC.finditer(text)) + list(self._DATE_WORDS.finditer(text))
            if not dates:
                return True  # Keep records without date
            # Get first date found
            match = dates[0]
            start_at_utc = f"{match.group(3)}-{int(match.group(2)):02d}-{int(match.group(1)):02d}"

        if not start_at_utc:
            return True
        try:
            # Try parsing as datetime first
            if isinstance(start_at_utc, str):
                if "T" in start_at_utc or "Z" in start_at_utc:
                    dt = datetime.fromisoformat(start_at_utc.replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(start_at_utc, "%Y-%m-%d")
                record_date = dt.date()
            else:
                return True
        except (ValueError, AttributeError):
            return True
        if self._start_date is not None and record_date < self._start_date:
            return False
        if self._end_date is not None and record_date > self._end_date:
            return False
        return True
