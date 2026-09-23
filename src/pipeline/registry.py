"""
Plugin Registry - Manages all Factor Plugins
=============================================

This module implements the Registry Pattern + Factory Pattern for
dynamic plugin loading from configuration.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Type, Any
import importlib
import inspect

from .base import BaseFactorPlugin, FactorType


class PluginRegistry:
    """
    Registry managing all Factor Plugins.

    Design Pattern: Registry Pattern + Factory Pattern
    - Plugins register via @register decorator
    - Load plugins from config file
    - Factory creates instances based on config
    """

    # Class-level registry
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


# Import all plugins to register them
# NOTE: Import order matters - base.py must be loaded first
from .plugins.weather_plugin import WeatherFactorPlugin
from .plugins.flood_plugin import FloodFactorPlugin
from .plugins.event_plugin import EventFactorPlugin
from .plugins.holiday_plugin import HolidayFactorPlugin

# Register plugins with registry
PluginRegistry.register("weather")(WeatherFactorPlugin)
PluginRegistry.register("flood")(FloodFactorPlugin)
PluginRegistry.register("event")(EventFactorPlugin)
PluginRegistry.register("holiday")(HolidayFactorPlugin)
