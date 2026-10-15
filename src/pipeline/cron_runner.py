"""
Pipeline Cron Runner
==================

Runs factor plugins on a schedule (every 30 minutes for traffic).

Usage:
    # Run continuously (daemon mode)
    python -m src.pipeline.cron_runner --daemon

    # Run once
    python -m src.pipeline.cron_runner

    # Run specific plugin
    python -m src.pipeline.cron_runner --plugin tomtom_traffic

    # Windows Task Scheduler (every 30 minutes):
    # python.exe path\to\cron_runner.py --daemon
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

import pandas as pd

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from dotenv import load_dotenv
load_dotenv()

from .registry import PluginRegistry
from .base import BaseFactorPlugin


# =============================================================================
# LOGGING
# =============================================================================

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "cron_runner.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# SCHEDULE INTERVALS (in seconds)
# =============================================================================

INTERVALS = {
    "*/30 * * * *": 30 * 60,      # 30 minutes
    "0 * * * *": 60 * 60,          # 1 hour
    "*/15 * * * *": 15 * 60,       # 15 minutes
    "0 0 * * *": 24 * 60 * 60,    # 1 day
}


class CronRunner:
    """
    Cron-style runner for factor plugins.

    Features:
    - Run plugins on schedule (30 min for traffic, 1 hour for weather)
    - Daemon mode (continuous) or single run
    - Error handling and retry
    - Logging
    """

    def __init__(
        self,
        config_path: str = "config/factors.yaml",
        data_lake_dir: str = "data",
    ):
        self.config_path = config_path
        self.data_lake_dir = Path(data_lake_dir)

        # Load plugins
        self._load_plugins()

        # Last run times
        self.last_run: Dict[str, datetime] = {}

    def _load_plugins(self):
        """Load plugins from registry."""
        self.plugins: Dict[str, BaseFactorPlugin] = {}

        # Manually create plugin instances based on available classes
        for plugin_name in PluginRegistry.list_plugins():
            try:
                plugin_class = PluginRegistry.get_plugin_class(plugin_name)

                # Create instance with minimal config
                if plugin_name == "here_traffic":
                    config = {
                        'api_key': os.environ.get('HERE_API_KEY', ''),
                        'data_lake_dir': str(self.data_lake_dir / 'traffic'),
                    }
                elif plugin_name == "weather_ensemble":
                    config = {'sources': {}}
                elif plugin_name == "event":
                    config = {'csv_path': 'data/event.xlsx'}
                elif plugin_name == "holiday":
                    config = {'holiday_file': 'data/holidays.csv'}
                else:
                    config = {}

                self.plugins[plugin_name] = plugin_class(config)
                logger.info(f"Loaded plugin: {plugin_name}")

            except Exception as e:
                logger.error(f"Failed to load {plugin_name}: {e}")

    def run_plugin(self, plugin_name: str) -> bool:
        """
        Run a single plugin.

        Args:
            plugin_name: Name of plugin to run

        Returns:
            True if successful, False otherwise
        """
        if plugin_name not in self.plugins:
            logger.error(f"Plugin not found: {plugin_name}")
            return False

        plugin = self.plugins[plugin_name]

        try:
            logger.info(f"Running {plugin_name}...")
            start_time = datetime.now()

            # Run pipeline
            if hasattr(plugin, 'run_pipeline'):
                records = plugin.run_pipeline()
            else:
                df = plugin.fetch()
                df = plugin.transform(df)
                df = plugin.map_spatial(df)
                records = plugin.get_records_df()

            # Save to data lake
            if hasattr(plugin, 'save_to_data_lake'):
                if plugin_name == "here_traffic":
                    # Save hex-level data
                    df = plugin.fetch()
                    df = plugin.transform(df)
                    hex_df = plugin.map_spatial(df)
                    plugin.save_to_data_lake(hex_df, 'hex')
                elif plugin_name == "weather_ensemble":
                    df = plugin.fetch()
                    plugin.save_to_data_lake(df, 'weather')

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✓ {plugin_name} completed in {elapsed:.1f}s")

            self.last_run[plugin_name] = datetime.now()
            return True

        except Exception as e:
            logger.error(f"✗ {plugin_name} failed: {e}")
            return False

    def run_all_due(self) -> int:
        """
        Run all plugins that are due.

        Returns:
            Number of plugins successfully run
        """
        success_count = 0

        for plugin_name, plugin in self.plugins.items():
            # Get schedule interval
            schedule = getattr(plugin, 'schedule', None)
            interval = INTERVALS.get(schedule, 30 * 60)  # Default 30 min

            # Check if due
            last_run = self.last_run.get(plugin_name)
            now = datetime.now()

            if last_run is None or (now - last_run).total_seconds() >= interval:
                if self.run_plugin(plugin_name):
                    success_count += 1
                else:
                    # Retry once after 5 minutes
                    time.sleep(5)
                    self.run_plugin(plugin_name)

        return success_count

    def run_daemon(self, check_interval: int = 60):
        """
        Run continuously as a daemon.

        Args:
            check_interval: How often to check if plugins are due (seconds)
        """
        logger.info("=" * 60)
        logger.info("CRON RUNNER - DAEMON MODE")
        logger.info("=" * 60)
        logger.info(f"Plugins: {list(self.plugins.keys())}")
        logger.info(f"Check interval: {check_interval}s")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 60)

        # Initial run
        logger.info("Running initial check...")
        self.run_all_due()

        try:
            while True:
                time.sleep(check_interval)
                self.run_all_due()

        except KeyboardInterrupt:
            logger.info("Stopping daemon...")
            sys.exit(0)

    def run_once(self, plugin_name: str = None) -> bool:
        """
        Run once and exit.

        Args:
            plugin_name: Specific plugin to run, or None for all
        """
        logger.info("=" * 60)
        logger.info("CRON RUNNER - SINGLE RUN")
        logger.info("=" * 60)

        if plugin_name:
            success = self.run_plugin(plugin_name)
        else:
            count = self.run_all_due()
            success = count > 0
            logger.info(f"Ran {count} plugins")

        return success


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Pipeline Cron Runner - Run factor plugins on schedule"
    )
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run continuously as daemon'
    )
    parser.add_argument(
        '--plugin',
        type=str,
        help='Run specific plugin only'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=60,
        help='Check interval for daemon mode (seconds)'
    )
    parser.add_argument(
        '--config',
        default='config/factors.yaml',
        help='Config path'
    )

    args = parser.parse_args()

    runner = CronRunner(config_path=args.config)

    if args.daemon:
        runner.run_daemon(check_interval=args.interval)
    else:
        success = runner.run_once(plugin_name=args.plugin)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
