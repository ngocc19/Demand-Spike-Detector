"""
Cron wrapper cho Event Realtime Crawler.

Chạy mỗi 2 giờ qua Task Scheduler (Windows) hoặc Cron (Linux).

Usage:
    # Windows Task Scheduler
    schtasks /create /tn "EventRealtime" /tr "python scripts/event_realtime_cron.py" /sc hour /mo 2

    # Linux Cron
    0 */2 * * * cd /path/to/project && python scripts/event_realtime_cron.py >> logs/cron.log 2>&1
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """
    Run event realtime crawler once.

    Returns:
        Exit code (0 = success)
    """
    # Get project root
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent

    # Config path
    config_path = project_root / "config" / "factors.yaml"

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        return 1

    # Python executable
    python_exe = sys.executable

    # Command
    cmd = [
        python_exe,
        "-m", "pipeline.event_realtime.cli",
        "--config", str(config_path),
        "--once",  # Run once, cron will call again
    ]

    print(f"Running: {' '.join(cmd)}")
    print(f"Working directory: {project_root}")
    print("-" * 60)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=False,
            text=True,
        )

        print("-" * 60)
        print(f"Exit code: {result.returncode}")

        return result.returncode

    except Exception as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
