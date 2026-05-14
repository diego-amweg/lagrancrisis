#!/usr/bin/env python3
"""
Chequeo automático de salud diaria del pipeline.

Valida artefactos críticos esperados para la fecha actual y emite alertas persistentes
si faltan outputs. Diseñado para ejecutarse automáticamente vía Task Scheduler.

Salidas:
- logs/health/health_check_YYYY-MM-DD.json (siempre)
- logs/health/alerts.log (append sólo cuando hay faltantes)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "raw"
DOCS_DIR = PROJECT_ROOT / "docs"
LOGS_DIR = PROJECT_ROOT / "logs"
HEALTH_DIR = LOGS_DIR / "health"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chequeo de salud diaria del pipeline")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Fecha a validar (YYYY-MM-DD). Default: hoy.",
    )
    return parser.parse_args()


def _expected_outputs(date_str: str) -> list[dict[str, str]]:
    yyyy, mm, dd = date_str.split("-")
    return [
        {"name": "intraday_accumulated", "path": str(RAW_DIR / date_str / "intraday_accumulated.json")},
        {"name": "raw_snapshot", "path": str(RAW_DIR / date_str / "raw.json")},
        {"name": "pipeline_metrics", "path": str(RAW_DIR / date_str / "pipeline_metrics.json")},
        {"name": "judge_report", "path": str(RAW_DIR / date_str / "judge_report.json")},
        {"name": "daily_review", "path": str(RAW_DIR / date_str / "daily_review.json")},
        {"name": "published_index", "path": str(DOCS_DIR / yyyy / mm / dd / "index.html")},
        {"name": "published_data", "path": str(DOCS_DIR / yyyy / mm / dd / "data.json")},
    ]


def _close_log_has_date(date_str: str) -> bool:
    close_log = LOGS_DIR / "close.log"
    if not close_log.exists():
        return False
    try:
        content = close_log.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return f"Inicio cierre diario para {date_str}" in content


def run_health_check(date_str: str) -> tuple[int, Path]:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, object]] = []
    missing: list[str] = []

    for item in _expected_outputs(date_str):
        path = Path(item["path"])
        present = path.exists()
        checks.append(
            {
                "name": item["name"],
                "path": item["path"],
                "present": present,
            }
        )
        if not present:
            missing.append(item["name"])

    close_log_ok = _close_log_has_date(date_str)
    checks.append(
        {
            "name": "close_log_entry",
            "path": str(LOGS_DIR / "close.log"),
            "present": close_log_ok,
        }
    )
    if not close_log_ok:
        missing.append("close_log_entry")

    status = "OK" if not missing else "ALERT"
    report = {
        "date": date_str,
        "status": status,
        "missing_count": len(missing),
        "missing": missing,
        "checks": checks,
        "generated_at": datetime.now().isoformat(),
    }

    report_path = HEALTH_DIR / f"health_check_{date_str}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if missing:
        alerts_path = HEALTH_DIR / "alerts.log"
        line = (
            f"{datetime.now().isoformat()} ALERT date={date_str} missing={','.join(missing)} "
            f"report={report_path}\n"
        )
        with alerts_path.open("a", encoding="utf-8") as f:
            f.write(line)

    return (0 if not missing else 2), report_path


def main() -> int:
    args = _parse_args()
    try:
        code, report_path = run_health_check(args.date)
    except ValueError:
        print(f"[HEALTH] Fecha inválida: {args.date}. Formato esperado YYYY-MM-DD")
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    if code == 0:
        print(f"[HEALTH] OK date={args.date} report={report_path}")
    else:
        print(
            f"[HEALTH] ALERT date={args.date} missing={report.get('missing_count', 0)} "
            f"items={report.get('missing', [])} report={report_path}"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
