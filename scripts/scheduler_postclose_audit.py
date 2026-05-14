#!/usr/bin/env python3
"""Audita el scheduler post-cierre y deja evidencia persistente en logs/health."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
HEALTH_DIR = LOGS_DIR / "health"

TARGET_TASKS = [
    "LGC-DailyClose",
    "LGC-Review",
    "LGC-UpdateHoja",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auditoría post-cierre del Task Scheduler")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Fecha a auditar (YYYY-MM-DD). Default: hoy.",
    )
    return parser.parse_args()


def _run_powershell(command: str) -> str:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "PowerShell command failed")
    return proc.stdout.strip()


def _get_task_snapshot() -> list[dict[str, Any]]:
    quoted_names = ",".join(f"'{name}'" for name in TARGET_TASKS)
    ps = f"""
    $names = @({quoted_names})
    $rows = foreach($name in $names) {{
      $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
      if ($null -eq $task) {{
        [PSCustomObject]@{{
          TaskName = $name
          Exists = $false
          LastRunTime = $null
          LastTaskResult = $null
          NextRunTime = $null
          State = 'MISSING'
        }}
      }} else {{
        $info = Get-ScheduledTaskInfo -TaskName $name
        [PSCustomObject]@{{
          TaskName = $name
          Exists = $true
          LastRunTime = $info.LastRunTime
          LastTaskResult = $info.LastTaskResult
          NextRunTime = $info.NextRunTime
          State = $task.State
        }}
      }}
    }}
    $rows | ConvertTo-Json -Compress
    """
    raw = _run_powershell(ps)
    payload = json.loads(raw)
    if isinstance(payload, dict):
        return [payload]
    return payload


def _get_operational_events(date_str: str) -> list[dict[str, Any]]:
    day_start = f"{date_str}T00:00:00"
    quoted_names = "|".join(TARGET_TASKS)
    ps = f"""
    $start = [datetime]::Parse('{day_start}')
    $events = Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational' -ErrorAction SilentlyContinue |
      Where-Object {{ $_.TimeCreated -ge $start -and $_.Message -match '{quoted_names}' }} |
      Select-Object -First 200 TimeCreated, Id, Message
    $events | ConvertTo-Json -Compress
    """
    raw = _run_powershell(ps)
    if not raw:
        return []
    payload = json.loads(raw)
    if isinstance(payload, dict):
        return [payload]
    return payload


def _to_iso(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("/Date("):
        match = re.match(r"/Date\((\d+)\)/", text)
        if not match:
            return text
        try:
            return datetime.fromtimestamp(int(match.group(1)) / 1000).isoformat()
        except (ValueError, OSError):
            return text
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return text


def run_audit(date_str: str) -> tuple[int, Path]:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)

    snapshots = _get_task_snapshot()
    events = _get_operational_events(date_str)

    issues: list[str] = []
    task_rows: list[dict[str, Any]] = []
    order_probe: list[tuple[str, str]] = []

    for row in snapshots:
        name = str(row.get("TaskName", "")).strip()
        exists = bool(row.get("Exists"))
        last_result = row.get("LastTaskResult")
        last_run_time = _to_iso(row.get("LastRunTime"))
        state = str(row.get("State", "")).strip()

        task_rows.append(
            {
                "task": name,
                "exists": exists,
                "last_run_time": last_run_time,
                "last_task_result": last_result,
                "state": state,
            }
        )

        if not exists:
            issues.append(f"missing_task:{name}")
            continue
        if str(last_result) != "0":
            issues.append(f"nonzero_result:{name}:{last_result}")
        if not last_run_time or not str(last_run_time).startswith(date_str):
            issues.append(f"not_run_today:{name}")
        else:
            order_probe.append((name, last_run_time))

    expected_order = TARGET_TASKS
    observed_order = [name for name, _ in sorted(order_probe, key=lambda item: item[1])]
    if observed_order[: len(expected_order)] != expected_order:
        issues.append(f"unexpected_order:{'->'.join(observed_order) or 'none'}")

    if not events:
        issues.append("missing_operational_events")

    report = {
        "date": date_str,
        "status": "OK" if not issues else "ALERT",
        "issues": issues,
        "expected_order": expected_order,
        "observed_order": observed_order,
        "task_snapshot": task_rows,
        "operational_event_count": len(events),
        "operational_events": events,
        "generated_at": datetime.now().isoformat(),
    }

    report_path = HEALTH_DIR / f"scheduler_audit_{date_str}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if issues:
        alerts_path = HEALTH_DIR / "alerts.log"
        with alerts_path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{datetime.now().isoformat()} ALERT kind=scheduler_audit date={date_str} issues={','.join(issues)} report={report_path}\n"
            )

    return (0 if not issues else 2), report_path


def main() -> int:
    args = _parse_args()
    try:
        code, report_path = run_audit(args.date)
    except Exception as exc:
        HEALTH_DIR.mkdir(parents=True, exist_ok=True)
        alerts_path = HEALTH_DIR / "alerts.log"
        with alerts_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat()} ALERT kind=scheduler_audit_unhandled error={exc}\n")
        print(f"[SCHEDULER_AUDIT] ALERT error={exc}")
        return 2

    if code == 0:
        print(f"[SCHEDULER_AUDIT] OK report={report_path}")
    else:
        print(f"[SCHEDULER_AUDIT] ALERT report={report_path}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())