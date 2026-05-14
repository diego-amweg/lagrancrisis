"""Backfill de abril 2026 con pipeline LLM completo.

Uso:
  python -m src.backfill_april_2026

Este script descarga todos los items disponibles en los feeds activos,
filtra por abril de 2026, agrupa por fecha y ejecuta run_pipeline con
preloaded_articles para cada dia, sobrescribiendo data.json e index.html.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import feedparser
import requests

import src.main as pipeline


def _load_sources() -> List[Dict]:
    with open("src/sources.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    out: List[Dict] = []
    for region in ["argentina", "global"]:
        for tier in ["oficiales", "medios_tier1"]:
            out.extend(cfg.get(region, {}).get(tier, []))
    return out


def _parse_pub_dt(entry) -> datetime | None:
    parsed = getattr(entry, "published_parsed", None)
    if parsed:
        try:
            return datetime(*parsed[:6])
        except Exception:
            return None

    updated = getattr(entry, "updated_parsed", None)
    if updated:
        try:
            return datetime(*updated[:6])
        except Exception:
            return None

    date_text = entry.get("published", "") or entry.get("updated", "")
    if date_text:
        try:
            from dateutil import parser as dateutil_parser

            return dateutil_parser.parse(str(date_text))
        except Exception:
            pass

    title = str(entry.get("title", "") or "")
    title_date = _parse_date_from_title(title)
    if title_date:
        return title_date

    return None


def _parse_date_from_title(title: str) -> datetime | None:
    text = str(title or "").strip()
    if not text:
        return None

    text = (
        text.replace("�", "")
        .replace("N�mero", "Numero")
        .replace("N�", "N")
    )

    month_map = {
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "abril": 4,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "agosto": 8,
        "septiembre": 9,
        "setiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
    }

    match = re.search(r"(\d{1,2})\s+de\s+([A-Za-záéíóúÁÉÍÓÚñÑ]+)\s+de\s+(\d{4})", text, re.IGNORECASE)
    if match:
        day = int(match.group(1))
        month_name = match.group(2).lower()
        year = int(match.group(3))
        month = month_map.get(month_name)
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                return None

    match = re.search(r"([A-Za-záéíóúÁÉÍÓÚñÑ]+)\s+(\d{4})", text, re.IGNORECASE)
    if match:
        month_name = match.group(1).lower()
        year = int(match.group(2))
        month = month_map.get(month_name)
        if month:
            try:
                return datetime(year, month, 1)
            except ValueError:
                return None

    return None


def _fetch_april_2026_articles(sources: List[Dict]) -> Dict[str, List[Dict]]:
    by_date: Dict[str, List[Dict]] = {}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LGC-Backfill/1.0)"}

    for src in sources:
        if str(src.get("type", "rss")).lower() != "rss":
            continue

        url = str(src.get("url", "")).strip()
        if not url:
            continue

        try:
            resp = requests.get(url, timeout=30, headers=headers)
            feed = feedparser.parse(resp.content)
        except Exception:
            continue

        for entry in getattr(feed, "entries", []):
            pub_dt = _parse_pub_dt(entry)
            if not pub_dt:
                continue
            if pub_dt.year != 2026 or pub_dt.month != 4:
                continue

            date_key = pub_dt.strftime("%Y-%m-%d")
            article = {
                "title": entry.get("title", "Sin titulo"),
                "url": entry.get("link", ""),
                "content": entry.get("summary", entry.get("description", "")),
                "published": pub_dt.isoformat(),
                "source_name": src.get("name", "Fuente"),
                "source_category": src.get("category", "general"),
                "tier": src.get("tier", "unknown"),
                "language": "es" if ".ar" in url else "en",
            }
            by_date.setdefault(date_key, []).append(article)

    return by_date


def _set_pipeline_date(target_date: str) -> None:
    pipeline.TODAY = target_date
    pipeline.RAW_DIR = Path(f"raw/{target_date}")
    pipeline.DOCS_DIR = Path(f"docs/{target_date.replace('-', '/')}")


def run_backfill() -> int:
    sources = _load_sources()
    by_date = _fetch_april_2026_articles(sources)
    target_dates = sorted(by_date.keys())

    print(f"Fechas abril 2026 con articulos: {len(target_dates)}")
    if not target_dates:
        print("No hay articulos de abril 2026 para backfill.")
        return 1

    ok_count = 0
    fail_count = 0

    for date_key in target_dates:
        day_articles = by_date.get(date_key, [])
        print(f"\\n[{date_key}] articulos preloaded: {len(day_articles)}")

        _set_pipeline_date(date_key)
        success = pipeline.run_pipeline(
            use_mock=False,
            preloaded_articles=day_articles,
            pipeline_mode="close",
        )

        if success:
            ok_count += 1
            print(f"[{date_key}] OK")
        else:
            fail_count += 1
            print(f"[{date_key}] FAIL")

    print("\\n=== RESUMEN BACKFILL ===")
    print(f"Dias procesados OK: {ok_count}")
    print(f"Dias con falla: {fail_count}")

    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(run_backfill())
