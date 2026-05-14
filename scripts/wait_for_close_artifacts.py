#!/usr/bin/env python3
"""Waits until daily close artifacts exist before running dependent tasks."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path


def _build_required_paths(repo_root: Path, target_date: str) -> list[Path]:
    year, month, day = target_date.split("-")
    return [
        repo_root / "docs" / year / month / day / "index.html",
        repo_root / "docs" / year / month / day / "data.json",
        repo_root / "raw" / target_date / "pipeline_metrics.json",
        repo_root / "raw" / target_date / "judge_report.json",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=r"C:\Users\Diego\lagrancrisis")
    parser.add_argument("--date", dest="target_date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--timeout-seconds", type=int, default=5400)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    required_paths = _build_required_paths(repo_root, args.target_date)
    deadline = time.monotonic() + max(args.timeout_seconds, 1)

    while time.monotonic() <= deadline:
        missing = [path for path in required_paths if not path.exists()]
        if not missing:
            print(f"READY {args.target_date}")
            return 0
        time.sleep(max(args.poll_seconds, 1))

    print(f"TIMEOUT {args.target_date}")
    for path in missing:
        print(f"MISSING {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())