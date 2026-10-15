"""Main Crawler cho Event Realtime.

Sử dụng lại EventSource plugins từ backfill (src/pipeline/plugins/).
Không duplicate logic - chỉ wrap plugin results thành RealtimeEvent.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from zoneinfo import ZoneInfo

# Add parent to path for plugin imports
_PARENT_DIR = Path(__file__).parent.parent
if str(_PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(_PARENT_DIR))

from pipeline.base import EventSource
from pipeline.event_realtime.models import (
    EventState,
    RealtimeEvent,
)
from pipeline.event_realtime.processor import EventRealtimeProcessor
from pipeline.event_realtime.storage import EventRealtimeStore
from pipeline.event_realtime.exporter import EventRealtimeExporter


# =============================================================================
# DIRECT PLUGIN REGISTRY (không qua pipeline.registry để tránh BaseFactorPlugin)
# =============================================================================

def _import_plugin_classes():
    """Import plugin classes directly (bypass registry)."""
    from pipeline.plugins.event_plugin import VanMieuEventSource
    from pipeline.plugins.football import VpfFootballEventSource, VffFootballEventSource
    from pipeline.plugins.concert import TicketboxConcertEventSource
    from pipeline.plugins.festival import TicketboxFestivalEventSource, LeHoiVietNamEventSource
    from pipeline.plugins.other import OfficialOtherEventSource

    return {
        "van_mieu": VanMieuEventSource,
        "vpf_football": VpfFootballEventSource,
        "vff_football": VffFootballEventSource,
        "ticketbox_concert": TicketboxConcertEventSource,
        "ticketbox_festival": TicketboxFestivalEventSource,
        "lehoivietnam_hanoi": LeHoiVietNamEventSource,
        "official_hanoi_other": OfficialOtherEventSource,
    }


EVENT_SOURCE_TYPES = _import_plugin_classes()


def build_event_source(
    source_name: str,
    source_config: Dict[str, Any],
    event_date_window: Optional[Dict[str, str]] = None,
) -> EventSource:
    """Build source từ direct registry."""
    if source_name not in EVENT_SOURCE_TYPES:
        supported = ", ".join(sorted(EVENT_SOURCE_TYPES))
        raise ValueError(
            f"Unknown event source '{source_name}'. Supported: {supported}"
        )
    return EVENT_SOURCE_TYPES[source_name](source_config, event_date_window=event_date_window)

logger = logging.getLogger(__name__)


# =============================================================================
# FILE LOCKING (Mutex)
# =============================================================================

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False


def acquire_lock(lock_file: Path, timeout: int = 5) -> Optional[Any]:
    """Acquire exclusive lock to prevent parallel execution."""
    if not HAS_MSVCRT and not HAS_FCNTL:
        logger.warning("No file locking available")
        return None

    lock_path = str(lock_file)

    try:
        lock_handle = open(lock_path, 'w')

        if HAS_FCNTL:
            start_time = datetime.now()
            while True:
                try:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_handle.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
                    lock_handle.flush()
                    logger.info(f"[LOCK] Acquired lock: {lock_path}")
                    return lock_handle
                except (IOError, OSError):
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed >= timeout:
                        lock_handle.close()
                        logger.error(f"[LOCK] Cannot acquire lock after {timeout}s")
                        return None
                    time.sleep(0.5)

        elif HAS_MSVCRT:
            start_time = datetime.now()
            while True:
                try:
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
                    lock_handle.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
                    lock_handle.flush()
                    logger.info(f"[LOCK] Acquired lock: {lock_path}")
                    return lock_handle
                except (IOError, OSError):
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed >= timeout:
                        lock_handle.close()
                        logger.error(f"[LOCK] Cannot acquire lock after {timeout}s")
                        return None
                    time.sleep(0.5)

    except Exception as e:
        logger.error(f"[LOCK] Error acquiring lock: {e}")
        return None


def release_lock(lock_handle: Any, lock_file: Path) -> None:
    """Release the exclusive lock."""
    if lock_handle:
        try:
            if HAS_FCNTL:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            elif HAS_MSVCRT:
                try:
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except:
                    pass

            lock_handle.close()

            if lock_file.exists():
                lock_file.unlink()

            logger.info("[LOCK] Released lock")
        except Exception as e:
            logger.warning(f"[LOCK] Error releasing lock: {e}")


# =============================================================================
# PLUGIN-BASED SOURCE WRAPPER
# =============================================================================

class PluginSourceWrapper:
    """
    Wrapper around EventSource plugin từ backfill.

    Chuyển đổi FetchResult → List[RealtimeEvent].
    Tái sử dụng toàn bộ logic fetch/normalize từ plugins.
    """

    def __init__(
        self,
        source_name: str,
        source_config: Dict[str, Any],
        event_date_window: Optional[Dict[str, str]] = None,
    ):
        self.source_name = source_name
        self.event_date_window = event_date_window

        # Build plugin instance từ registry
        self._source: EventSource = build_event_source(
            source_name,
            source_config,
            event_date_window=event_date_window,
        )
        logger.info(f"Initialized plugin: {self._source.__class__.__name__}")

    def fetch(self) -> List[RealtimeEvent]:
        """
        Fetch events bằng plugin và convert sang RealtimeEvent.

        Returns:
            List of RealtimeEvent
        """
        try:
            # Empty state, full_scan=True (realtime luôn full scan)
            result = self._source.fetch(state={}, full_scan=True)

            events = []
            for record in result.fetched_records:
                try:
                    # Normalize record thành EventDraft
                    draft = self._source.normalize(record)

                    # Convert EventDraft → RealtimeEvent
                    event = self._to_realtime_event(draft)
                    events.append(event)

                except Exception as e:
                    logger.debug(f"Error normalizing record: {e}")
                    continue

            return events

        except Exception as e:
            logger.error(f"Error fetching from plugin {self.source_name}: {e}")
            return []

    def _to_realtime_event(self, draft) -> RealtimeEvent:
        """Convert EventDraft → RealtimeEvent."""
        return RealtimeEvent(
            event_id=f"{draft.source}:{draft.source_event_id}",
            source=draft.source,
            source_event_id=draft.source_event_id,
            title=draft.title,
            venue=draft.venue_raw or "",
            start_at=self._parse_datetime(draft.start_at_utc) if draft.start_at_utc else None,
            end_at=self._parse_datetime(draft.end_at_utc) if draft.end_at_utc else None,
            category=draft.primary_category or "other",
            estimated_attendees=draft.official_attendance or draft.estimated_attendees,
            attendance_source_url=draft.attendance_source_url,
            latitude=draft.latitude,
            longitude=draft.longitude,
            h3_index=draft.h3_index,
            source_url=draft.source_url,
            fetched_at=datetime.now(),
        )

    @staticmethod
    def _parse_datetime(dt_str: str) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None


# =============================================================================
# EVENT REALTIME CRAWLER
# =============================================================================

class EventRealtimeCrawler:
    """
    Crawler chính cho event realtime.

    Features:
    - Poll 2h một lần
    - Sử dụng plugins từ backfill (không duplicate logic)
    - Detect changes: NEW, UPDATED, CANCELLED, CONFIRMED
    - Save to storage (Parquet + State JSON)
    - Export to .xlsx
    - Trace logging
    - Mutex lock
    """

    # SOURCES dùng từ registry - danh sách nguồn hợp lệ
    SOURCES = [
        "van_mieu",
        "vpf_football",
        "vff_football",
        "ticketbox_concert",
        "ticketbox_festival",
        "lehoivietnam_hanoi",
        "official_hanoi_other",
    ]

    def __init__(self, config: Dict[str, Any]):
        """Initialize crawler với config."""
        self.config = config

        # Get event config
        events_config = config.get("events", {})
        data_dir = Path(config.get("pipeline", {}).get("data_dir", "data"))
        # Resolve relative path to project root for consistent storage
        # regardless of CWD (mirrors storage.py / exporter.py behavior).
        if not data_dir.is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            data_dir = project_root / data_dir
        self.data_dir = data_dir

        # Get realtime config
        realtime_config = config.get("event_realtime", {})
        self.horizon_days = realtime_config.get("horizon_days", 90)
        self.notify_threshold = realtime_config.get("notify_threshold", 0.5)

        # Get date window
        self.event_date_window = events_config.get("event_date_window", {})
        if not self.event_date_window.get("start_date"):
            self.event_date_window["start_date"] = "2026-09-29"

        # Initialize components
        self.store = EventRealtimeStore(self.data_dir)
        self.processor = EventRealtimeProcessor(
            horizon_days=self.horizon_days,
            notify_threshold=self.notify_threshold,
        )
        self.exporter = EventRealtimeExporter(self.data_dir)

        # Initialize source wrappers (using plugins)
        self.sources = self._build_sources(events_config.get("sources", {}))

        # Lock file (use absolute path resolved by store)
        self.lock_file = self.data_dir / ".event_realtime.lock"

    def _build_sources(self, sources_config: Dict[str, Any]) -> Dict[str, PluginSourceWrapper]:
        """
        Build source wrappers từ config, sử dụng plugins từ registry.

        Không duplicate logic - chỉ wrap plugin instances.
        """
        sources = {}

        for name, source_config in sources_config.items():
            if not source_config.get("enabled", True):
                continue

            # Chỉ xử lý các sources đã biết
            if name not in self.SOURCES:
                logger.warning(f"Unknown source: {name}, skipping")
                continue

            try:
                wrapper = PluginSourceWrapper(
                    source_name=name,
                    source_config=source_config,
                    event_date_window=self.event_date_window,
                )
                sources[name] = wrapper
                logger.info(f"Registered source: {name}")

            except Exception as e:
                logger.error(f"Failed to build source {name}: {e}")

        return sources

    def run(self, verbose: bool = False) -> Dict[str, Any]:
        """Run one crawl cycle."""
        # Acquire lock
        lock_handle = acquire_lock(self.lock_file)
        if not lock_handle and (HAS_MSVCRT or HAS_FCNTL):
            logger.warning("Another crawl is running, skipping this cycle")
            return {"error": "locked"}

        try:
            return self._run_cycle(verbose)
        finally:
            if lock_handle:
                release_lock(lock_handle, self.lock_file)

    def _run_cycle(self, verbose: bool) -> Dict[str, Any]:
        """Main crawl cycle logic."""
        crawl_time = datetime.now()
        logger.info("=" * 60)
        logger.info(f"EVENT REALTIME CRAWLER - {crawl_time.isoformat()}")
        logger.info(f"Sources: {list(self.sources.keys())}")
        logger.info("=" * 60)

        # 1. Load known events
        known_events = self.store.load_state()
        logger.info(f"Loaded {len(known_events)} known events from state")

        # 2. Fetch all sources (via plugins)
        all_events: List[RealtimeEvent] = []
        fetch_stats = {}

        for source_name, wrapper in self.sources.items():
            logger.info(f"Fetching from {source_name}...")
            try:
                events = wrapper.fetch()
                fetch_stats[source_name] = len(events)
                all_events.extend(events)
                logger.info(f"  -> Got {len(events)} events from {source_name}")
            except Exception as e:
                logger.error(f"  -> Error fetching {source_name}: {e}")
                fetch_stats[source_name] = 0

        # 3. Filter by horizon
        filtered_events = self.processor.filter_by_horizon(all_events)
        logger.info(f"Total events after filtering: {len(filtered_events)}")

        # 4. Detect changes (process từng source)
        all_traces = []
        all_updated_states = dict(known_events)

        for source_name, wrapper in self.sources.items():
            source_events = [e for e in filtered_events if e.source == source_name]

            traces, updated_states = self.processor.detect_changes(
                known_events=all_updated_states,
                new_events=source_events,
                source=source_name,
                crawl_time=crawl_time,
            )
            all_traces.extend(traces)
            all_updated_states.update(updated_states)

        # 5. Calculate summary
        summary = self.processor.calculate_summary(all_traces)

        # 6. Log traces
        if all_traces:
            self.store.log_traces(all_traces)
            logger.info(f"Logged {len(all_traces)} traces")

        # 7. Save state
        self.store.save_state(all_updated_states)
        logger.info(f"Saved {len(all_updated_states)} events to state")

        # 7b. Save events snapshot to Parquet (per PLAN_event_realtime.md)
        # Convert EventState → dict for Parquet storage
        state_dicts = [s.to_dict() for s in all_updated_states.values()]
        self.store.save_events(state_dicts, crawl_time=crawl_time)
        logger.info(f"Saved {len(state_dicts)} event snapshots to Parquet")

        # 8. Export to .xlsx
        export_result = self.exporter.export(list(all_updated_states.values()))
        logger.info(f"Exported to {export_result['xlsx_path']}")

        # 9. Post-process: fix times, geocode, assign anchors
        self._post_process()

        # Log summary
        logger.info("=" * 60)
        logger.info("CRAWL SUMMARY:")
        logger.info(f"  Fetched: {fetch_stats}")
        logger.info(f"  Changes: {summary['by_type']}")
        logger.info(f"  High Impact: {summary['high_impact']}")
        logger.info("=" * 60)

        return {
            "crawl_time": crawl_time.isoformat(),
            "fetch_stats": fetch_stats,
            "total_events": len(filtered_events),
            "total_traces": len(all_traces),
            "trace_summary": summary,
            "export": export_result,
        }

    def _post_process(self) -> None:
        """Post-process: fix times, geocode, assign anchors."""
        import sys

        logger.info("Running post-processing...")

        data_dir = Path(self.data_dir) if isinstance(self.data_dir, str) else self.data_dir
        input_path = str(data_dir / "event_realtime.csv")
        output_path = str(data_dir / "event_realtime_fixed.xlsx")

        try:
            project_root = Path(__file__).parent.parent.parent.parent
            scripts_dir = project_root / "scripts"
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))

            from process_event_realtime import process_event_realtime
            process_event_realtime(input_path, output_path)
            logger.info(f"Post-processed: {output_path}")
        except Exception as e:
            logger.warning(f"Post-processing error: {e}")
