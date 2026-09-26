"""Config-driven collector for official Hanoi education and civic events."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
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
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.lower() == "a" and values.get("href"): self.hrefs.append(values["href"] or "")
        if tag.lower() == "meta" and values.get("property", "").casefold() == "og:title": self.title = values.get("content") or self.title
        if tag.lower() == "title": self._in_title = True
    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title": self._in_title = False
    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())
            if self._in_title and not self.title: self.title = data.strip()


class OfficialOtherEventSource(EventSource):
    """Collect explicit-date events from configurable, official Hanoi listings.

    This adapter intentionally rejects articles without an event date.  It avoids
    turning publication dates, rumours, and routine news into model features.
    """
    source_name = "official_hanoi_other"
    _DATE_NUMERIC = re.compile(r"(?:ngày\s*)?(\d{1,2})[/-](\d{1,2})[/-](20\d{2})", re.I)
    _DATE_WORDS = re.compile(r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(20\d{2})", re.I)
    _TIME = re.compile(r"(?:lúc|vào)\s*(\d{1,2})(?:\s*(?:giờ|h))?(?:\s*[:h]\s*(\d{2}))?", re.I)

    def __init__(self, config: Mapping[str, Any], session: Any | None = None) -> None:
        self.config = dict(config); self.sources = self._sources(); self.timeout = int(self.config.get("timeout_seconds", 30))
        self.timezone = ZoneInfo(str(self.config.get("timezone", "Asia/Ho_Chi_Minh"))); self.city = str(self.config.get("scope_city", "hanoi"))
        self.duration = int(self.config.get("default_duration_minutes", 180)); self.user_agent = str(self.config.get("user_agent", "DemandSpikeDetector/0.1")); self.session = session or requests.Session()

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
                records.append({"url": url, "title": title, "body": body, "source": source["name"]})
            pages.append({"kind": "article", "url": url, "accepted": bool(records and records[-1].get("url") == url)})
        for seed in self.config.get("seed_events", []):
            if isinstance(seed, Mapping): records.append({"seed": dict(seed)})
        return FetchResult(self.source_name, self.sources[0]["listing_url"], to_utc_iso(utc_now()), pages, records, statuses, None, state_updates={"known_article_urls": sorted(known | urls)})

    def normalize(self, raw: Mapping[str, Any]) -> EventDraft:
        if isinstance(raw.get("seed"), Mapping): return self._normalize_seed(raw["seed"])
        url, title, body = raw.get("url"), raw.get("title"), raw.get("body")
        if not all(isinstance(value, str) and value.strip() for value in (url, title, body)): raise EventRecordError("Official event article lacks URL, title, or text.")
        start = self._event_time(body, title); end = to_utc_iso(datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(minutes=self.duration))
        return self._draft(url, title.strip(), body.strip(), start, end, None)

    def _normalize_seed(self, seed: Mapping[str, Any]) -> EventDraft:
        title = self._required(seed, "title"); url = self._required(seed, "source_url"); start = self._required(seed, "start_at_utc")
        return self._draft(url, title, str(seed.get("description") or "") or None, start, seed.get("end_at_utc") if isinstance(seed.get("end_at_utc"), str) else None, seed.get("venue"))

    def _draft(self, url: str, title: str, body: str | None, start: str, end: str | None, venue: object) -> EventDraft:
        return EventDraft(source=self.source_name, source_event_id=hashlib.sha256(url.encode()).hexdigest()[:20], title=title, description=body, raw_category="official_other", primary_category="other", publication_status="published", event_status="scheduled", start_at_utc=start, end_at_utc=end, venue_raw=str(venue).strip() if venue else None, source_url=url, source_created_at_utc=None, source_updated_at_utc=None, raw_payload_sha256=canonical_json_hash({"url": url, "title": title, "body": body}), city=self.city, tags=["official", "other"])

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
