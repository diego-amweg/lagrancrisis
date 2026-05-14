#!/usr/bin/env python3
"""
Hourly intraday guard check.

Checks:
1) Task Scheduler result for LGC-IntradayAccumulate (reject/refusal codes)
2) raw/YYYY-MM-DD/intraday_accumulated.json freshness via last_capture_at
3) Emits persistent alerts to logs/health/alerts.log when unhealthy

Outputs:
- logs/health/intraday_guard_YYYY-MM-DD_HHMMSS.json
- logs/health/alerts.log (append on ALERT)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "raw"
LOGS_DIR = PROJECT_ROOT / "logs"
HEALTH_DIR = LOGS_DIR / "health"

# Known refusal/rejection code observed in this environment.
REFUSAL_CODES = {0x800710E0}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hourly guard for intraday RSS ingestion")
    parser.add_argument("--task-name", default="LGC-IntradayAccumulate", help="Task Scheduler name")
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=95,
        help="Max allowed minutes since last_capture_at before ALERT",
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date to inspect intraday file (YYYY-MM-DD), default=today",
    )
    return parser.parse_args()


def _to_uint32(value: int) -> int:
    return value & 0xFFFFFFFF


def _get_task_info(task_name: str) -> dict[str, Any]:
    ps = (
        "$i = Get-ScheduledTaskInfo -TaskName '{0}'; "
        "$o = [PSCustomObject]@{{"
        "LastTaskResult=$i.LastTaskResult;"
        "LastRunTime=$i.LastRunTime;"
        "NextRunTime=$i.NextRunTime"
        "}}; "
        "$o | ConvertTo-Json -Compress"
    ).format(task_name)

    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"Could not read task info for {task_name}: {proc.stderr.strip()}")

    payload = json.loads(proc.stdout)
    raw_result = int(payload.get("LastTaskResult", 0))
    payload["LastTaskResultUInt32"] = _to_uint32(raw_result)
    return payload


def _read_intraday_last_capture(date_str: str) -> tuple[datetime | None, int | None, Path]:
    intraday_path = RAW_DIR / date_str / "intraday_accumulated.json"
    if not intraday_path.exists():
        return None, None, intraday_path

    try:
        data = json.loads(intraday_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Invalid intraday JSON at {intraday_path}: {exc}") from exc

    last_capture_str = data.get("last_capture_at")
    last_capture = None
    if isinstance(last_capture_str, str) and last_capture_str.strip():
        last_capture = datetime.fromisoformat(last_capture_str.strip())

    articles = data.get("articles")
    total = len(articles) if isinstance(articles, list) else None
    return last_capture, total, intraday_path


def run_guard(task_name: str, date_str: str, max_age_minutes: int) -> tuple[int, Path]:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    checks: list[dict[str, Any]] = []
    issues: list[str] = []

    # Check task scheduler result.
    task_info = _get_task_info(task_name)
    task_code = int(task_info["LastTaskResultUInt32"])
    code_ok = task_code not in REFUSAL_CODES
    checks.append(
        {
            "name": "task_result_code",
            "task": task_name,
            "value_uint32": task_code,
            "value_hex": f"0x{task_code:08X}",
            "last_run_time": task_info.get("LastRunTime"),
            "next_run_time": task_info.get("NextRunTime"),
            "ok": code_ok,
        }
    )
    if not code_ok:
        issues.append(f"task_result_code_refusal:{task_code}")

    # Check intraday freshness.
    last_capture, total_articles, intraday_path = _read_intraday_last_capture(date_str)
    if last_capture is None:
        checks.append(
            {
                "name": "intraday_last_capture",
                "path": str(intraday_path),
                "ok": False,
                "reason": "missing_or_empty_last_capture_at",
            }
        )
        issues.append("intraday_last_capture_missing")
    else:
        age_minutes = (now - last_capture).total_seconds() / 60.0
        fresh = age_minutes <= float(max_age_minutes)
        checks.append(
            {
                "name": "intraday_last_capture",
                "path": str(intraday_path),
                "last_capture_at": last_capture.isoformat(),
                "age_minutes": round(age_minutes, 2),
                "max_age_minutes": max_age_minutes,
                "total_articles": total_articles,
                "ok": fresh,
            }
        )
        if not fresh:
            issues.append(f"intraday_stale:{round(age_minutes, 2)}m")

    status = "OK" if not issues else "ALERT"
    report = {
        "date": date_str,
        "status": status,
        "issues": issues,
        "checks": checks,
        "generated_at": now.isoformat(),
    }

    report_path = HEALTH_DIR / f"intraday_guard_{now.strftime('%Y-%m-%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if issues:
        alerts_path = HEALTH_DIR / "alerts.log"
        line = (
            f"{now.isoformat()} ALERT kind=intraday_guard date={date_str} "
            f"issues={','.join(issues)} report={report_path}\n"
        )
        with alerts_path.open("a", encoding="utf-8") as f:
            f.write(line)

    return (0 if status == "OK" else 2), report_path


def main() -> int:
    args = _parse_args()
    try:
        code, report_path = run_guard(args.task_name, args.date, args.max_age_minutes)
    except Exception as exc:
        HEALTH_DIR.mkdir(parents=True, exist_ok=True)
        alerts_path = HEALTH_DIR / "alerts.log"
        now = datetime.now().isoformat()
        with alerts_path.open("a", encoding="utf-8") as f:
            f.write(f"{now} ALERT kind=intraday_guard_unhandled error={str(exc)}\n")
        print(f"[INTRADAY_GUARD] ALERT error={exc}")
        return 2

    if code == 0:
        print(f"[INTRADAY_GUARD] OK report={report_path}")
    else:
        print(f"[INTRADAY_GUARD] ALERT report={report_path}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
