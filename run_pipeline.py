"""Command-line entry point for local pipeline jobs."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from src.pipeline.orchestrator import EventIngestionJob


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Demand Spike Detector pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_events = subparsers.add_parser(
        "ingest-events",
        help="Fetch, version, and persist events from one configured source.",
    )
    ingest_events.add_argument(
        "--source",
        required=True,
        help="Source key from config/factors.yaml, for example van_mieu.",
    )
    ingest_events.add_argument(
        "--config",
        default="config/factors.yaml",
        help="Path to the pipeline YAML configuration.",
    )
    ingest_events.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Minimum log level sent to stderr.",
    )
    ingest_events.add_argument(
        "--full-scan",
        action="store_true",
        help="Ignore the saved watermark and re-fetch all pages for this source.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "ingest-events":
        try:
            summary = EventIngestionJob.from_yaml(args.config, args.source).run(
                force_full_scan=args.full_scan
            )
        except Exception as error:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "source": args.source,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
