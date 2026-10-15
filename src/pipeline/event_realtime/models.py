"""Data models for Event Realtime Processing."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class EventChangeType(Enum):
    """Loại thay đổi của event."""
    NEW = "new"                    # Event mới được công bố
    CONFIRMED = "confirmed"        # Được xác nhận bởi source khác
    UPDATED = "updated"            # Event đã known bị sửa
    CANCELLED = "cancelled"       # Event không còn trong source


# =============================================================================
# REALTIME EVENT (Raw from crawl)
# =============================================================================

@dataclass
class RealtimeEvent:
    """Event từ crawl realtime."""
    event_id: str                    # Source + event_id (e.g., "van_mieu:123")
    source: str                      # Nguồn: van_mieu, ticketbox, etc.
    source_event_id: str             # ID từ source gốc

    # Event info
    title: str
    venue: str
    start_at: datetime
    end_at: Optional[datetime] = None
    category: str = "other"

    # Attendance (nullable - có thể trống với event chưa diễn ra)
    estimated_attendees: Optional[int] = None
    attendance_source_url: Optional[str] = None

    # Location (nullable - có thể chưa resolve được)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    h3_index: Optional[str] = None

    # Metadata
    fetched_at: datetime = field(default_factory=datetime.now)
    source_url: str = ""


# =============================================================================
# EVENT STATE (Tracked over time)
# =============================================================================

@dataclass
class EventState:
    """
    Trạng thái của một event trong hệ thống.

    Events được track theo event_id (source:source_event_id).
    """
    event_id: str
    source: str
    title: str
    venue: str
    start_at: datetime
    end_at: Optional[datetime] = None
    category: str = "other"

    # Attendance
    estimated_attendees: Optional[int] = None
    attendance_source_url: Optional[str] = None

    # Location
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    h3_index: Optional[str] = None

    # Source URLs history
    source_urls_history: List[str] = field(default_factory=list)
    current_source_url: str = ""

    # Timestamps
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)

    # Confirmed by multiple sources?
    confirmed_by_sources: List[str] = field(default_factory=list)

    @classmethod
    def from_realtime_event(cls, event: RealtimeEvent) -> EventState:
        """Create state từ realtime event."""
        return cls(
            event_id=event.event_id,
            source=event.source,
            title=event.title,
            venue=event.venue,
            start_at=event.start_at,
            end_at=event.end_at,
            category=event.category,
            estimated_attendees=event.estimated_attendees,
            attendance_source_url=event.attendance_source_url,
            latitude=event.latitude,
            longitude=event.longitude,
            h3_index=event.h3_index,
            source_urls_history=[event.source_url] if event.source_url else [],
            current_source_url=event.source_url,
            confirmed_by_sources=[event.source],
        )

    def update_from(self, event: RealtimeEvent):
        """Update state từ realtime event mới."""
        self.title = event.title
        self.venue = event.venue
        self.start_at = event.start_at
        self.end_at = event.end_at
        self.category = event.category
        self.last_updated = datetime.now()

        # Update attendance nếu có
        if event.estimated_attendees is not None:
            self.estimated_attendees = event.estimated_attendees
        if event.attendance_source_url:
            self.attendance_source_url = event.attendance_source_url

        # Update location nếu có
        if event.latitude is not None:
            self.latitude = event.latitude
        if event.longitude is not None:
            self.longitude = event.longitude
        if event.h3_index:
            self.h3_index = event.h3_index

        # Update source URL
        if event.source_url and event.source_url not in self.source_urls_history:
            self.source_urls_history.append(event.source_url)
            self.current_source_url = event.source_url

        # Add source to confirmed list
        if event.source not in self.confirmed_by_sources:
            self.confirmed_by_sources.append(event.source)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "event_id": self.event_id,
            "source": self.source,
            "title": self.title,
            "venue": self.venue,
            "start_at": self.start_at if isinstance(self.start_at, str) else (self.start_at.isoformat() if self.start_at else None),
            "end_at": self.end_at if isinstance(self.end_at, str) else (self.end_at.isoformat() if self.end_at else None),
            "category": self.category,
            "estimated_attendees": self.estimated_attendees,
            "attendance_source_url": self.attendance_source_url,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "h3_index": self.h3_index,
            "source_urls_history": self.source_urls_history,
            "current_source_url": self.current_source_url,
            "confirmed_by_sources": self.confirmed_by_sources,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EventState:
        """Create state from dict."""
        return cls(
            event_id=data["event_id"],
            source=data["source"],
            title=data["title"],
            venue=data["venue"],
            start_at=datetime.fromisoformat(data["start_at"]) if data.get("start_at") else datetime.now(),
            end_at=datetime.fromisoformat(data["end_at"]) if data.get("end_at") else None,
            category=data.get("category", "other"),
            estimated_attendees=data.get("estimated_attendees"),
            attendance_source_url=data.get("attendance_source_url"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            h3_index=data.get("h3_index"),
            source_urls_history=data.get("source_urls_history", []),
            current_source_url=data.get("current_source_url", ""),
            confirmed_by_sources=data.get("confirmed_by_sources", []),
            first_seen=datetime.fromisoformat(data.get("first_seen", datetime.now().isoformat())),
            last_seen=datetime.fromisoformat(data.get("last_seen", datetime.now().isoformat())),
            last_updated=datetime.fromisoformat(data.get("last_updated", datetime.now().isoformat())),
        )


# =============================================================================
# EVENT TRACE (Change history)
# =============================================================================

@dataclass
class EventTrace:
    """
    Trace cho một thay đổi.

    Lưu lịch sử thay đổi của event để track:
    - Thời gian crawl
    - Nguồn bài viết
    - Chi tiết thay đổi
    """
    trace_id: str
    crawl_time: datetime
    source: str

    # Event identity
    event_id: str
    title: str

    # Change info
    change_type: EventChangeType

    # Old state (for UPDATED/CANCELLED)
    old_state: Optional[Dict[str, Any]] = None

    # New state (for NEW/UPDATED/CONFIRMED)
    new_state: Optional[Dict[str, Any]] = None

    # Changes detail: field -> (old_value, new_value)
    changes_detail: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)

    # Source URLs
    source_url: str = ""
    source_urls_history: List[str] = field(default_factory=list)

    # Impact
    impact: float = 0.0
    should_notify: bool = False

    @classmethod
    def create_new(
        cls,
        event: RealtimeEvent,
        crawl_time: datetime,
        impact: float = 0.0,
    ) -> EventTrace:
        """Create trace for NEW event."""
        return cls(
            trace_id=str(uuid.uuid4()),
            crawl_time=crawl_time,
            source=event.source,
            event_id=event.event_id,
            title=event.title,
            change_type=EventChangeType.NEW,
            new_state={
                "title": event.title,
                "venue": event.venue,
                "start_at": event.start_at if isinstance(event.start_at, str) else (event.start_at.isoformat() if event.start_at else None),
                "end_at": event.end_at if isinstance(event.end_at, str) else (event.end_at.isoformat() if event.end_at else None),
                "category": event.category,
                "estimated_attendees": event.estimated_attendees,
                "source_url": event.source_url,
            },
            source_url=event.source_url,
            impact=impact,
            should_notify=impact >= 0.5,
        )

    @classmethod
    def create_updated(
        cls,
        event: RealtimeEvent,
        old_state: EventState,
        changes: Dict[str, Tuple[Any, Any]],
        crawl_time: datetime,
        impact: float = 0.0,
    ) -> EventTrace:
        """Create trace for UPDATED event."""
        return cls(
            trace_id=str(uuid.uuid4()),
            crawl_time=crawl_time,
            source=event.source,
            event_id=event.event_id,
            title=old_state.title,
            change_type=EventChangeType.UPDATED,
            old_state=old_state.to_dict(),
            new_state={
                "title": event.title,
                "venue": event.venue,
                "start_at": event.start_at if isinstance(event.start_at, str) else (event.start_at.isoformat() if event.start_at else None),
                "end_at": event.end_at if isinstance(event.end_at, str) else (event.end_at.isoformat() if event.end_at else None),
                "category": event.category,
                "estimated_attendees": event.estimated_attendees,
                "source_url": event.source_url,
            },
            changes_detail=changes,
            source_url=event.source_url,
            source_urls_history=old_state.source_urls_history.copy(),
            impact=impact,
            should_notify=impact >= 0.5,
        )

    @classmethod
    def create_cancelled(
        cls,
        state: EventState,
        crawl_time: datetime,
        impact: float = 0.0,
    ) -> EventTrace:
        """Create trace for CANCELLED event."""
        return cls(
            trace_id=str(uuid.uuid4()),
            crawl_time=crawl_time,
            source=state.source,
            event_id=state.event_id,
            title=state.title,
            change_type=EventChangeType.CANCELLED,
            old_state=state.to_dict(),
            source_url=state.current_source_url,
            source_urls_history=state.source_urls_history.copy(),
            impact=impact,
            should_notify=impact >= 0.5,
        )

    @classmethod
    def create_confirmed(
        cls,
        event: RealtimeEvent,
        existing_state: EventState,
        crawl_time: datetime,
        impact: float = 0.0,
    ) -> EventTrace:
        """Create trace for CONFIRMED event (found in new source)."""
        return cls(
            trace_id=str(uuid.uuid4()),
            crawl_time=crawl_time,
            source=event.source,
            event_id=event.event_id,
            title=existing_state.title,
            change_type=EventChangeType.CONFIRMED,
            old_state=existing_state.to_dict(),
            new_state={
                "title": existing_state.title,
                "confirmed_by": existing_state.confirmed_by_sources + [event.source],
                "new_source_url": event.source_url,
            },
            source_url=event.source_url,
            source_urls_history=existing_state.source_urls_history.copy() + [event.source_url],
            impact=impact,
            should_notify=impact >= 0.5,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for CSV export."""
        # Flatten changes_detail for CSV
        changes_str = "|".join(
            f"{k}:{v[0]}→{v[1]}" if v[0] is not None and v[1] is not None else f"{k}:{v[1]}"
            for k, v in self.changes_detail.items()
        )

        return {
            "trace_id": self.trace_id,
            "crawl_time": self.crawl_time.isoformat(),
            "source": self.source,
            "event_id": self.event_id,
            "title": self.title,
            "change_type": self.change_type.value,
            "old_start_at": self.old_state.get("start_at") if self.old_state else None,
            "new_start_at": self.new_state.get("start_at") if self.new_state else None,
            "old_venue": self.old_state.get("venue") if self.old_state else None,
            "new_venue": self.new_state.get("venue") if self.new_state else None,
            "source_url": self.source_url,
            "source_urls_history": "|".join(self.source_urls_history),
            "changes_detail": changes_str,
            "impact": self.impact,
            "should_notify": self.should_notify,
        }


# =============================================================================
# IMPACT CALCULATION
# =============================================================================

class EventImpactCalculator:
    """Tính impact score cho event."""

    IMPACT_BY_CATEGORY: Dict[str, float] = {
        "concert": 0.9,
        "music_concert": 0.9,
        "festival": 0.8,
        "festival_public": 0.8,
        "sports": 0.7,
        "football": 0.7,
        "exhibition": 0.6,
        "theater": 0.6,
        "conference": 0.5,
        "seminar": 0.5,
        "cultural_event": 0.5,
        "official_or_diplomatic": 0.5,
        "official_other": 0.4,
        "workshop": 0.3,
        "other": 0.3,
    }

    # Time peak cho sigmoid (hours before event)
    TIME_PEAK_HOURS = 48

    # Notify threshold
    NOTIFY_THRESHOLD = 0.5

    @classmethod
    def calculate(
        cls,
        category: str,
        start_at: datetime,
        change_type: EventChangeType,
        source_count: int = 1,
    ) -> float:
        """
        Tính impact score.

        Impact = f(category, proximity, confidence, change_type)
        """
        # 1. Category impact
        cat_impact = cls.IMPACT_BY_CATEGORY.get(category, 0.3)

        # 2. Source confidence (multiple sources = more confident)
        if source_count >= 3:
            confidence = 1.0
        elif source_count == 2:
            confidence = 0.75
        else:
            confidence = 0.5

        # 3. Time proximity (sigmoid peak near event date)
        hours_until = float("inf")
        if start_at:
            now = datetime.now()
            # Make start_at timezone-naive for comparison
            start_dt = start_at
            # Handle both datetime objects and ISO strings
            if isinstance(start_dt, str):
                from dateutil.parser import parse
                start_dt = parse(start_dt)
            if start_dt.tzinfo is not None:
                start_dt = start_dt.replace(tzinfo=None)
            delta = start_dt - now
            hours_until = delta.total_seconds() / 3600

        if 0 < hours_until < 24 * 90:  # Within horizon
            time_factor = cls._sigmoid_time_factor(hours_until)
        elif hours_until <= 0:
            # Event đã diễn ra
            time_factor = 0.1
        else:
            # Quá xa trong tương lai
            time_factor = 0.2

        # 4. Change type bonus
        type_bonus = {
            EventChangeType.NEW: 1.2,
            EventChangeType.CONFIRMED: 1.0,
            EventChangeType.UPDATED: 1.5,
            EventChangeType.CANCELLED: 1.3,
        }.get(change_type, 1.0)

        # Final impact
        impact = cat_impact * confidence * time_factor * type_bonus
        return min(1.0, max(0.0, impact))

    @staticmethod
    def _sigmoid_time_factor(hours_until: float) -> float:
        """Tính time factor dùng sigmoid function."""
        import math
        k = 0.03  # Steepness
        x0 = EventImpactCalculator.TIME_PEAK_HOURS  # Peak position

        sig = 1 / (1 + math.exp(-k * (hours_until - x0)))
        return sig
