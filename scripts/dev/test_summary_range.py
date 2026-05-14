# Archivo: src/test_summary_range.py
# Verifica que cada summary del output diario cumpla rango editorial [500, 1000].

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Dict, List


SUMMARY_MIN_CHARS = 500
SUMMARY_MAX_CHARS = 1000
DOCS_DIR = Path("docs")


def _latest_data_json_path() -> Path:
    """Devuelve el data.json más reciente dentro de docs/YYYY/MM/DD/."""
    candidates = sorted(DOCS_DIR.glob("*/??/??/data.json"))
    if not candidates:
        raise FileNotFoundError(
            "No se encontró ningún data.json en docs/YYYY/MM/DD/. "
            "Ejecutá primero: python -m src.main --mock"
        )
    return candidates[-1]


def _load_items(data_path: Path) -> List[Dict]:
    """Carga noticias_destacadas desde un data.json de salida."""
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    items = payload.get("noticias_destacadas", [])
    if not isinstance(items, list):
        raise ValueError("Campo 'noticias_destacadas' inválido: se esperaba lista")
    return items


class TestSummaryRange(unittest.TestCase):
    """Suite mínima para proteger el contrato de longitud de summaries."""

    def test_summaries_stay_within_editorial_range(self) -> None:
        data_path = _latest_data_json_path()
        items = _load_items(data_path)

        self.assertGreater(len(items), 0, "noticias_destacadas está vacío")

        out_of_range: List[str] = []
        for idx, item in enumerate(items):
            summary = str(item.get("summary", ""))
            size = len(summary)
            if size < SUMMARY_MIN_CHARS or size > SUMMARY_MAX_CHARS:
                item_id = str(item.get("id_referencia", f"idx={idx}"))
                out_of_range.append(f"id={item_id} size={size}")

        self.assertEqual(
            out_of_range,
            [],
            (
                "Se detectaron summaries fuera de rango "
                f"[{SUMMARY_MIN_CHARS}, {SUMMARY_MAX_CHARS}] en {data_path}: "
                + ", ".join(out_of_range)
            ),
        )


if __name__ == "__main__":
    unittest.main()
