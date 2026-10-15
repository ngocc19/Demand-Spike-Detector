"""CLI cho Event Realtime Crawler."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml

from .crawler import EventRealtimeCrawler, acquire_lock, release_lock
from .storage import EventRealtimeStore


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


def run_once(config: Dict[str, Any], verbose: bool = False) -> Dict[str, Any]:
    """
    Run crawl once.

    Note: Lock is acquired inside crawler.run() - no need to duplicate here.
    """
    # Create crawler
    crawler = EventRealtimeCrawler(config)

    # Run directly (lock handled inside crawler.run)
    result = crawler.run(verbose=verbose)
    return result


def run_loop(config: Dict[str, Any], interval_hours: int = 2, verbose: bool = False) -> None:
    """
    Run crawl in loop.

    Args:
        config: Configuration dict
        interval_hours: Interval between crawls in hours
        verbose: Enable verbose logging
    """
    logger = logging.getLogger(__name__)

    crawler = EventRealtimeCrawler(config)
    interval_seconds = interval_hours * 3600

    logger.info(f"Starting event realtime crawler loop (interval: {interval_hours}h)")

    while True:
        try:
            # Run crawler (lock handled inside crawler.run)
            result = crawler.run(verbose=verbose)

            # Print summary
            print("\n" + "=" * 60)
            print("CRAWL RESULT:")
            print(f"  Crawl time: {result['crawl_time']}")
            print(f"  Fetched events:")
            for source, count in result['fetch_stats'].items():
                print(f"    - {source}: {count}")
            print(f"  Total events: {result['total_events']}")
            print(f"  Total traces: {result['total_traces']}")
            print(f"  Changes: {result['trace_summary']['by_type']}")
            print(f"  High impact: {result['trace_summary']['high_impact']}")
            print(f"  Export: {result['export']}")
            print("=" * 60)

            # Show recent changes
            if result['trace_summary']['high_impact'] > 0:
                store = EventRealtimeStore(config.get('pipeline', {}).get('data_dir', 'data'))
                recent = store.get_recent_changes(hours=2, high_impact_only=True)

                if recent:
                    print("\nRECENT HIGH IMPACT CHANGES:")
                    for change in recent[:5]:
                        print(f"  [{change['change_type']}] {change['title']}")
                        print(f"    Old: {change.get('old_start_at', 'N/A')} -> New: {change.get('new_start_at', 'N/A')}")
                        print(f"    Source: {change['source_url']}")
                        print(f"    Impact: {change['impact']:.2f}")
                    print()

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            break

        except Exception as e:
            logger.exception(f"Error in crawl loop: {e}")
            # Retry nhanh hơn (5 phút) khi fail, tránh chờ full interval
            logger.info("Retrying in 5 minutes due to error...")
            time.sleep(300)
            continue  # skip the long sleep below

        # Sleep until next run
        logger.info(f"Sleeping for {interval_hours} hours...")
        time.sleep(interval_seconds)


def show_status(config: Dict[str, Any]) -> None:
    """Show current status of event realtime."""
    data_dir = config.get('pipeline', {}).get('data_dir', 'data')
    store = EventRealtimeStore(data_dir)

    stats = store.get_stats()

    print("\n" + "=" * 60)
    print("EVENT REALTIME STATUS:")
    print(f"  Total events in storage: {stats['total_events']}")
    print(f"  Known events in state: {stats['known_events_in_state']}")
    print(f"  Total traces: {stats['total_traces']}")
    print(f"  Traces by type: {stats['traces_by_type']}")
    print(f"  Event partitions: {stats['events_partitions']}")
    print(f"  Trace partitions: {stats['traces_partitions']}")
    print("=" * 60)

    # Show recent traces
    recent = store.get_recent_changes(hours=24)
    if recent:
        print(f"\nRecent changes (last 24h): {len(recent)}")
        for trace in recent[:10]:
            print(f"  [{trace['change_type']}] {trace['title']}")
    else:
        print("\nNo recent changes")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Event Realtime Crawler - Crawl events every 2 hours",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run once
  python -m pipeline.event_realtime.cli --config config/factors.yaml --once

  # Run in loop (every 2 hours)
  python -m pipeline.event_realtime.cli --config config/factors.yaml

  # Run with custom interval
  python -m pipeline.event_realtime.cli --config config/factors.yaml --interval 1

  # Show status
  python -m pipeline.event_realtime.cli --config config/factors.yaml --status

  # Verbose mode
  python -m pipeline.event_realtime.cli --config config/factors.yaml -v
        """
    )

    parser.add_argument(
        "--config", "-c",
        required=True,
        help="Path to configuration YAML file"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (for cron job)"
    )

    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=2,
        help="Interval in hours between crawls (default: 2)"
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status and exit"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        # Load config
        config = load_config(args.config)
        logger.info(f"Loaded config from {args.config}")

        if args.status:
            show_status(config)
            return

        if args.once:
            # Run once
            result = run_once(config, args.verbose)
            logger.info("Crawl completed")
            print(f"\nResult: {result}")
        else:
            # Run in loop
            run_loop(config, args.interval, args.verbose)

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
