"""CLI entry point for event ingestion pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from .orchestrator import EventIngestionJob


def main() -> None:
    parser = argparse.ArgumentParser(description="Demand Spike Detector - Event Ingestion")
    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to factors.yaml config file",
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Run only this source (e.g., 'ticketbox_concert'). If omitted, runs all enabled sources.",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Force a full scan instead of incremental",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)

    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    events_config = config.get("events", {})
    sources_config = events_config.get("sources", {})

    if not sources_config:
        logger.error("No event sources configured in events.sources")
        sys.exit(1)

    # Determine which sources to run
    if args.source:
        sources_to_run = {args.source: sources_config.get(args.source)}
        if sources_to_run[args.source] is None:
            logger.error("Source '%s' not found in config", args.source)
            sys.exit(1)
    else:
        sources_to_run = {
            name: src_config
            for name, src_config in sources_config.items()
            if src_config.get("enabled", True)
        }

    logger.info("Configured sources: %s", list(sources_to_run.keys()))

    for source_name, source_config in sources_to_run.items():
        logger.info("=" * 60)
        logger.info("Running source: %s", source_name)
        logger.info("=" * 60)

        try:
            job = EventIngestionJob(
                config=config,
                source_name=source_name,
            )
            result = job.run(force_full_scan=args.full_scan)
            logger.info(
                "Result: fetched=%d, valid=%d, new=%d, updated=%d",
                result["fetched"],
                result["valid"],
                result["new"],
                result["updated"],
            )
            logger.info("CSV: %s (%d records)", result["csv_path"], result["csv_records"])
            logger.info("Workbook: %s (%d sheets)", result["workbook_path"], result["workbook_sheets"])
        except Exception as e:
            logger.exception("Failed to run source '%s': %s", source_name, e)
            if not args.source:
                continue
            sys.exit(1)


if __name__ == "__main__":
    main()
