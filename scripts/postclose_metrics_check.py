#!/usr/bin/env python3
"""Verificación post-cierre automática de métricas clave del pipeline."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "raw"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verifica métricas post-cierre del pipeline")
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Fecha a validar en formato YYYY-MM-DD. Default: hoy.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_postclose_check(date_str: str) -> int:
    raw_dir = RAW_DIR / date_str
    metrics_path = raw_dir / "pipeline_metrics.json"
    raw_path = raw_dir / "raw.json"

    metrics = _load_json(metrics_path)
    raw_data = json.loads(raw_path.read_text(encoding="utf-8"))

    llm_unrecovered = metrics.get("llm_json_parse_unrecovered_total")
    translated_count = metrics.get("translated_items_count")
    if llm_unrecovered is None or translated_count is None:
        raise KeyError("pipeline_metrics.json no contiene las claves esperadas")

    language_en_count = sum(1 for item in raw_data if item.get("language") == "en")

    print(f"Fecha: {date_str}")
    print(f"llm_json_parse_unrecovered_total: {llm_unrecovered}")
    print(f"translated_items_count: {translated_count}")
    print(f"language=en en raw.json: {language_en_count}")
    print("")

    success = True
    if llm_unrecovered != 0:
        print("ERROR: llm_json_parse_unrecovered_total debe ser 0")
        success = False
    if translated_count >= 5:
        print("ERROR: translated_items_count debe bajar de 5")
        success = False
    if not (40 <= language_en_count <= 60):
        print("ERROR: language=en en raw.json debe estar en el rango aproximado 40-60")
        success = False

    if success:
        print("✓ Verificación post-cierre OK")
        return 0
    print("✗ Verificación post-cierre falló")
    return 1


def main() -> int:
    args = _parse_args()
    return run_postclose_check(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
