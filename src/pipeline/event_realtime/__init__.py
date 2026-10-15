"""Event Realtime Processing - Change Detection & Cross-Reference.

Architecture inspired by Weather Ensemble but adapted for discrete events:
- Change Detection: NEW, CONFIRMED, UPDATED, CANCELLED
- Signature-based deduplication across sources
- Impact scoring for notifications
- Trace logging for change history
"""

from .models import (
    EventChangeType,
    EventImpactCalculator,
    EventState,
    EventTrace,
    RealtimeEvent,
)
from .processor import EventRealtimeProcessor
from .storage import EventRealtimeStore
from .exporter import EventRealtimeExporter
from .crawler import EventRealtimeCrawler

__all__ = [
    # Models
    "EventChangeType",
    "EventImpactCalculator",
    "EventState",
    "EventTrace",
    "RealtimeEvent",
    # Processor
    "EventRealtimeProcessor",
    # Storage
    "EventRealtimeStore",
    # Exporter
    "EventRealtimeExporter",
    # Crawler
    "EventRealtimeCrawler",
]
