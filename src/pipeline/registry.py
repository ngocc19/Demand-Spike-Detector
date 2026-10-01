"""Explicit registry for event adapters.

Adding a source means implementing its adapter and registering it here.  This
keeps source-specific scraping or API behavior out of the orchestrator.
"""

from __future__ import annotations

from typing import Any, Mapping

from .base import EventSource
from .plugins.event_plugin import VanMieuEventSource
from .plugins.football import VffFootballEventSource, VpfFootballEventSource
from .plugins.concert import TicketboxConcertEventSource
from .plugins.festival import LeHoiVietNamEventSource, TicketboxFestivalEventSource
from .plugins.other import OfficialOtherEventSource
from .plugins.backstage import BackstageEventSource
from .plugins.ticketbox_comedy import TicketboxComedyEventSource
from .plugins.ticketbox_all import TicketboxAllEventSource


EVENT_SOURCE_TYPES = {
    "van_mieu": VanMieuEventSource,
    "vpf_football": VpfFootballEventSource,
    "vff_football": VffFootballEventSource,
    "ticketbox_concert": TicketboxConcertEventSource,
    "ticketbox_festival": TicketboxFestivalEventSource,
    "lehoivietnam_hanoi": LeHoiVietNamEventSource,
    "official_hanoi_other": OfficialOtherEventSource,
    "backstage_vn": BackstageEventSource,
    "ticketbox_comedy": TicketboxComedyEventSource,
    "ticketbox_all": TicketboxAllEventSource,
}


def build_event_source(
    source_name: str,
    source_config: Mapping[str, Any],
    event_date_window: Mapping[str, str] | None = None,
) -> EventSource:
    """Construct a source adapter selected explicitly by configuration.

    Args:
        source_name: Name of the event source
        source_config: Source-specific configuration from factors.yaml
        event_date_window: Optional date range filter with 'start_date' and 'end_date'.
                          When provided, only events within this range are collected.
    """

    try:
        source_type = EVENT_SOURCE_TYPES[source_name]
    except KeyError as error:
        supported = ", ".join(sorted(EVENT_SOURCE_TYPES))
        raise ValueError(
            f"Unknown event source '{source_name}'. Supported sources: {supported}."
        ) from error
    return source_type(source_config, event_date_window=event_date_window)
