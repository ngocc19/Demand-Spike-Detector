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


EVENT_SOURCE_TYPES = {
    "van_mieu": VanMieuEventSource,
    "vpf_football": VpfFootballEventSource,
    "vff_football": VffFootballEventSource,
    "ticketbox_concert": TicketboxConcertEventSource,
    "ticketbox_festival": TicketboxFestivalEventSource,
    "lehoivietnam_hanoi": LeHoiVietNamEventSource,
    "official_hanoi_other": OfficialOtherEventSource,
}


def build_event_source(
    source_name: str,
    source_config: Mapping[str, Any],
) -> EventSource:
    """Construct a source adapter selected explicitly by configuration."""

    try:
        source_type = EVENT_SOURCE_TYPES[source_name]
    except KeyError as error:
        supported = ", ".join(sorted(EVENT_SOURCE_TYPES))
        raise ValueError(
            f"Unknown event source '{source_name}'. Supported sources: {supported}."
        ) from error
    return source_type(source_config)
