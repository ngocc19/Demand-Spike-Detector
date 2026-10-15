"""Processor cho Event Realtime - Change Detection.

Bao gồm:
- Detect changes: NEW, UPDATED, CANCELLED, CONFIRMED
- Calculate impact
- Generate traces
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    EventChangeType,
    EventImpactCalculator,
    EventState,
    EventTrace,
    RealtimeEvent,
)

logger = logging.getLogger(__name__)


class EventRealtimeProcessor:
    """
    Processor cho event realtime processing.

    Chức năng chính:
    1. Process events từ một source và phát hiện thay đổi
    2. Tính impact score cho mỗi change
    3. Detect cancellations (events biến mất)
    4. Generate traces cho tất cả changes
    """

    def __init__(self, horizon_days: int = 90, notify_threshold: float = 0.5):
        """
        Args:
            horizon_days: Số ngày tương lai để track
            notify_threshold: Ngưỡng impact để notify
        """
        self.horizon_days = horizon_days
        self.notify_threshold = notify_threshold
        self.impact_calculator = EventImpactCalculator()

    def detect_changes(
        self,
        known_events: Dict[str, EventState],
        new_events: List[RealtimeEvent],
        source: str,
        crawl_time: datetime,
    ) -> Tuple[List[EventTrace], Dict[str, EventState]]:
        """
        Detect changes và generate traces.

        Args:
            known_events: Dict of known event states (event_id -> EventState)
            new_events: List of events from current crawl
            source: Source name (van_mieu, ticketbox, etc.)
            crawl_time: Thời gian crawl

        Returns:
            Tuple of:
            - List of EventTrace objects
            - Updated state dict
        """
        traces: List[EventTrace] = []
        new_state: Dict[str, EventState] = dict(known_events)

        # Create lookup for new events
        new_events_by_id: Dict[str, RealtimeEvent] = {}
        for event in new_events:
            new_events_by_id[event.event_id] = event

        # Process each known event
        current_ids = set(new_events_by_id.keys())

        for event_id, state in known_events.items():
            # Check if this source still has this event
            if state.source == source:
                if event_id not in current_ids:
                    # Event không còn trong response - có thể bị hủy
                    trace = self._check_cancellation(state, crawl_time)
                    if trace:
                        traces.append(trace)

        # Process new events
        for event in new_events:
            existing = new_state.get(event.event_id)

            if existing is None:
                # ===== NEW EVENT =====
                trace = self._create_trace_new(event, crawl_time)
                traces.append(trace)

                # Add to state
                new_state[event.event_id] = EventState.from_realtime_event(event)
                start_str = event.start_at[:10] if isinstance(event.start_at, str) else (event.start_at.date() if event.start_at else 'TBD')
                logger.info(f"NEW: {event.title} ({start_str}) from {source}")

            elif source not in existing.confirmed_by_sources:
                # ===== CONFIRMED BY NEW SOURCE =====
                trace = self._create_trace_confirmed(event, existing, crawl_time)
                traces.append(trace)

                # Update state
                existing.update_from(event)
                if source not in existing.confirmed_by_sources:
                    existing.confirmed_by_sources.append(source)

                logger.info(f"CONFIRMED: {existing.title} from {source} (sources: {existing.confirmed_by_sources})")

            else:
                # ===== CHECK FOR UPDATES (same source) =====
                diff = self._diff_states(existing, event)
                if diff:
                    trace = self._create_trace_updated(event, existing, diff, crawl_time)
                    traces.append(trace)

                    # Update state
                    existing.update_from(event)

                    logger.warning(f"UPDATED: {existing.title} - changes: {list(diff.keys())}")

        return traces, new_state

    def _create_trace_new(
        self,
        event: RealtimeEvent,
        crawl_time: datetime,
    ) -> EventTrace:
        """Create trace for NEW event."""
        impact = self.impact_calculator.calculate(
            category=event.category,
            start_at=event.start_at,
            change_type=EventChangeType.NEW,
            source_count=1,
        )

        return EventTrace.create_new(
            event=event,
            crawl_time=crawl_time,
            impact=impact,
        )

    def _create_trace_confirmed(
        self,
        event: RealtimeEvent,
        existing: EventState,
        crawl_time: datetime,
    ) -> EventTrace:
        """Create trace for CONFIRMED event."""
        impact = self.impact_calculator.calculate(
            category=existing.category,
            start_at=existing.start_at,
            change_type=EventChangeType.CONFIRMED,
            source_count=len(existing.confirmed_by_sources) + 1,
        )

        return EventTrace.create_confirmed(
            event=event,
            existing_state=existing,
            crawl_time=crawl_time,
            impact=impact,
        )

    def _create_trace_updated(
        self,
        event: RealtimeEvent,
        existing: EventState,
        changes: Dict[str, Tuple[Any, Any]],
        crawl_time: datetime,
    ) -> EventTrace:
        """Create trace for UPDATED event."""
        impact = self.impact_calculator.calculate(
            category=event.category,
            start_at=event.start_at,
            change_type=EventChangeType.UPDATED,
            source_count=len(existing.confirmed_by_sources),
        )

        return EventTrace.create_updated(
            event=event,
            old_state=existing,
            changes=changes,
            crawl_time=crawl_time,
            impact=impact,
        )

    def _create_trace_cancelled(
        self,
        state: EventState,
        crawl_time: datetime,
    ) -> EventTrace:
        """Create trace for CANCELLED event."""
        impact = self.impact_calculator.calculate(
            category=state.category,
            start_at=state.start_at,
            change_type=EventChangeType.CANCELLED,
            source_count=len(state.confirmed_by_sources),
        )

        return EventTrace.create_cancelled(
            state=state,
            crawl_time=crawl_time,
            impact=impact,
        )

    def _check_cancellation(
        self,
        state: EventState,
        crawl_time: datetime,
    ) -> Optional[EventTrace]:
        """Check if an event should be marked as cancelled."""
        if state.start_at is None:
            return None

        # Normalize both sides to tz-naive UTC to avoid
        # "can't subtract offset-naive and offset-aware datetimes".
        start_naive = self._normalize_dt(state.start_at)
        crawl_naive = self._normalize_dt(crawl_time)
        hours_until_event = (start_naive - crawl_naive).total_seconds() / 3600

        # If event is more than 2 hours in the past, it's naturally ended
        if hours_until_event < -2:
            return None

        # If event is in the future (or within 2 hours), might be cancelled
        if hours_until_event > -2:
            return self._create_trace_cancelled(state, crawl_time)

        return None

    @staticmethod
    def _normalize_dt(value: Any) -> datetime:
        """
        Normalize a datetime-like value to a tz-naive UTC datetime.

        Accepts datetime objects or ISO 8601 strings. This mirrors the pattern
        already used in EventImpactCalculator.calculate so all comparisons
        (state.start_at vs datetime.now()) use the same reference frame.
        """
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                # Fall back to dateutil if the ISO format is non-standard
                from dateutil.parser import parse
                value = parse(value)
        if value is None:
            return datetime.now()
        if value.tzinfo is not None:
            # Convert to UTC then drop tzinfo so arithmetic with naive
            # datetime.now() works.
            from datetime import timezone
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def _diff_states(
        self,
        state: EventState,
        event: RealtimeEvent,
    ) -> Dict[str, Tuple[Any, Any]]:
        """
        Phát hiện sự khác biệt giữa state và new event.

        Args:
            state: Current state
            event: New event data

        Returns:
            Dict of changes: {field: (old_value, new_value)}
        """
        diffs: Dict[str, Tuple[Any, Any]] = {}

        # Compare title
        if event.title and event.title != state.title:
            diffs["title"] = (state.title, event.title)

        # Compare venue
        if event.venue and event.venue != state.venue:
            diffs["venue"] = (state.venue, event.venue)

        # Compare start_at (use normalized datetimes to be tz-safe)
        if event.start_at and state.start_at:
            new_start = self._normalize_dt(event.start_at)
            old_start = self._normalize_dt(state.start_at)
            # Compare date only
            if new_start.date() != old_start.date():
                diffs["start_date"] = (old_start.date(), new_start.date())
            # Compare time if date is same
            elif new_start.time() != old_start.time():
                diffs["start_time"] = (old_start.time(), new_start.time())

        # Compare end_at
        if event.end_at or state.end_at:
            new_end = (
                self._normalize_dt(event.end_at)
                if event.end_at
                else self._normalize_dt(state.start_at)
            )
            old_end = (
                self._normalize_dt(state.end_at)
                if state.end_at
                else self._normalize_dt(state.start_at)
            )
            if new_end.date() != old_end.date():
                diffs["end_date"] = (old_end.date(), new_end.date())
            elif new_end.time() != old_end.time():
                diffs["end_time"] = (old_end.time(), new_end.time())

        # Compare category
        if event.category and event.category != state.category:
            diffs["category"] = (state.category, event.category)

        # Compare estimated_attendees
        if event.estimated_attendees != state.estimated_attendees:
            diffs["estimated_attendees"] = (state.estimated_attendees, event.estimated_attendees)

        # Compare source_url
        if event.source_url and event.source_url != state.current_source_url:
            diffs["source_url"] = (state.current_source_url, event.source_url)

        # Compare location
        if event.latitude and event.latitude != state.latitude:
            diffs["latitude"] = (state.latitude, event.latitude)
        if event.longitude and event.longitude != state.longitude:
            diffs["longitude"] = (state.longitude, event.longitude)

        return diffs

    def filter_by_horizon(
        self,
        events: List[RealtimeEvent],
    ) -> List[RealtimeEvent]:
        """
        Filter events within horizon days.
        - Accept future events (within horizon)
        - Also accept recent past events (within past_window_days) for newly discovered events
        - Drop very old past events

        Args:
            events: List of RealtimeEvent

        Returns:
            Filtered list
        """
        now = datetime.now()
        horizon = now + timedelta(days=self.horizon_days)
        # Also include past events up to 7 days (events that just happened)
        past_window = now - timedelta(days=7)

        filtered = []
        for event in events:
            if event.start_at is None:
                # Include events without date
                filtered.append(event)
                continue

            # Normalize to tz-naive UTC so comparison with naive now/horizon works.
            event_start = self._normalize_dt(event.start_at)

            # Accept: past window (7 days) up to horizon (365 days)
            if past_window <= event_start <= horizon:
                filtered.append(event)

        return filtered

    def get_high_impact_changes(
        self,
        traces: List[EventTrace],
    ) -> List[EventTrace]:
        """Get high impact changes for notification."""
        return [
            trace for trace in traces
            if trace.should_notify
        ]

    def calculate_summary(
        self,
        traces: List[EventTrace],
    ) -> Dict[str, Any]:
        """Calculate summary of traces."""
        summary = {
            "total": len(traces),
            "by_type": {
                "NEW": 0,
                "CONFIRMED": 0,
                "UPDATED": 0,
                "CANCELLED": 0,
            },
            "high_impact": 0,
            "total_impact": 0.0,
        }

        for trace in traces:
            summary["by_type"][trace.change_type.value.upper()] += 1
            if trace.should_notify:
                summary["high_impact"] += 1
            summary["total_impact"] += trace.impact

        return summary
