"""Explicit registry for event adapters and factor plugins.

Adding a source means implementing its adapter and registering it here.  This
keeps source-specific scraping or API behavior out of the orchestrator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Type

import importlib
import inspect
import yaml

from .base import BaseFactorPlugin, EventSource
from .plugins.event_plugin import EventFactorPlugin, VanMieuEventSource
from .plugins.football import VffFootballEventSource, VpfFootballEventSource
from .plugins.concert import TicketboxConcertEventSource
from .plugins.festival import LeHoiVietNamEventSource, TicketboxFestivalEventSource
from .plugins.other import OfficialOtherEventSource
from .plugins.backstage import BackstageEventSource
from .plugins.ticketbox_comedy import TicketboxComedyEventSource
from .plugins.ticketbox_all import TicketboxAllEventSource


# ============================================================
# EVENT SOURCE REGISTRY (from feature/event_slot)
# ============================================================
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


# ============================================================
# FACTOR PLUGIN REGISTRY (from feature/data-pipeline)
# ============================================================
class PluginRegistry:
    """Class-level registry for factor plugins."""

    _plugins: Dict[str, Type[BaseFactorPlugin]] = {}

    @classmethod
    def register(cls, name: str):
        """
        Decorator to register a plugin.

        Usage:
            @PluginRegistry.register("weather")
            class WeatherFactorPlugin(BaseFactorPlugin):
                ...
        """
        def decorator(plugin_class: Type[BaseFactorPlugin]):
            cls._plugins[name] = plugin_class
            return plugin_class
        return decorator

    @classmethod
    def get_plugin_class(cls, name: str) -> Type[BaseFactorPlugin]:
        """Get plugin class by name."""
        if name not in cls._plugins:
            available = list(cls._plugins.keys())
            raise ValueError(f"Unknown plugin: '{name}'. Available: {available}")
        return cls._plugins[name]

    @classmethod
    def list_plugins(cls) -> List[str]:
        """List all registered plugin names."""
        return list(cls._plugins.keys())

    @classmethod
    def load_from_config(cls, config_path: str) -> Dict[str, BaseFactorPlugin]:
        """
        Load plugins from config file (factors.yaml).

        Args:
            config_path: Path to factors.yaml

        Returns:
            Dict mapping factor_name -> plugin instance
        """
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        plugins = {}

        for factor_config in config.get('factors', []):
            factor_name = factor_config['name']

            # Skip disabled plugins
            if not factor_config.get('enabled', True):
                print(f"[Registry] Skipping disabled plugin: {factor_name}")
                continue

            # Get plugin class from registry
            plugin_class = cls.get_plugin_class(factor_name)

            # Instantiate with config
            plugins[factor_name] = plugin_class(factor_config)

        return plugins

    @classmethod
    def auto_discover_plugins(cls, plugins_dir: str = "src/pipeline/plugins"):
        """
        Auto-discover plugins in plugins directory.

        When a new plugin file is added, it will be automatically discovered.
        """
        plugins_path = Path(plugins_dir)

        if not plugins_path.exists():
            print(f"[Registry] Plugins directory not found: {plugins_dir}")
            return

        for py_file in plugins_path.glob("*_plugin.py"):
            if py_file.name == "__init__.py":
                continue

            # Import module dynamically
            module_name = f"src.pipeline.plugins.{py_file.stem}"

            try:
                module = importlib.import_module(module_name)

                # Find plugin classes in module
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BaseFactorPlugin) and
                        obj != BaseFactorPlugin and
                        hasattr(obj, 'factor_name')):
                        # Auto-register
                        cls._plugins[obj.factor_name] = obj
                        print(f"[Registry] Auto-discovered: {obj.factor_name}")
            except Exception as e:
                print(f"[Registry] Failed to import {module_name}: {e}")


# Import all factor plugins to register them
# NOTE: Import order matters - base.py must be loaded first
from .plugins.holiday_plugin import HolidayFactorPlugin

# Weather ensemble plugins
from .plugins.owm_plugin import OWMFactorPlugin
from .plugins.vcw_plugin import VCWFactorPlugin
from .plugins.nchmf_plugin import NCHMFFactorPlugin
from .plugins.nchmf_api_plugin import NCHMFApiPlugin
from .plugins.hsdc_plugin import HSDCFactorPlugin
from .plugins.weather_ensemble_plugin import WeatherEnsemblePlugin

# HSDC flood plugin
from .plugins.hsdc_flood_plugin import HSDCFloodPlugin

# HERE traffic plugin
from .plugins.here_traffic_plugin import HERETrafficPlugin

# Register factor plugins with registry
PluginRegistry.register("event")(EventFactorPlugin)
PluginRegistry.register("holiday")(HolidayFactorPlugin)

# Register weather ensemble plugins
PluginRegistry.register("owm")(OWMFactorPlugin)
PluginRegistry.register("vcw")(VCWFactorPlugin)
PluginRegistry.register("nchmf")(NCHMFFactorPlugin)
PluginRegistry.register("nchmf_api")(NCHMFApiPlugin)
PluginRegistry.register("hsdc")(HSDCFactorPlugin)
PluginRegistry.register("weather_ensemble")(WeatherEnsemblePlugin)

# Register HSDC flood plugin
PluginRegistry.register("hsdc_flood")(HSDCFloodPlugin)

# Register HERE traffic plugin
PluginRegistry.register("here_traffic")(HERETrafficPlugin)
