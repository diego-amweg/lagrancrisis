"""
Marca días sin edición como "faltante documentado": data.json con el motivo y una página
que explica por qué no hay edición. Después actualiza la portada y el historial.

No borra ni pisa una edición real: si el día ya tiene una edición, lo saltea.

Uso: python scripts/marcar_faltante.py --fechas 2026-08-15,2026-08-16 --motivo "Texto público" [--nota "Motivo interno"]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.builder import render_missing_page, update_index_page  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fechas", required=True)
    p.add_argument("--motivo", required=True, help="Lo que lee el público en la página del día")
    p.add_argument("--nota", default="", help="Motivo interno que queda en data.json")
    args = p.parse_args()

    hechas = []
    for fecha in [f.strip() for f in args.fechas.split(",") if f.strip()]:
        carpeta = ROOT / "docs" / fecha.replace("-", "/")
        data_path = carpeta / "data.json"
        if data_path.exists():
            actual = json.loads(data_path.read_text(encoding="utf-8"))
            if actual.get("status") != "missing_documented":
                print(f"✗ {fecha}: ya tiene una edición, no se toca")
                continue
        carpeta.mkdir(parents=True, exist_ok=True)
        data_path.write_text(json.dumps({
            "date": fecha,
            "status": "missing_documented",
            "reason": args.nota or args.motivo,
            "public_reason": args.motivo,
            "resumen_ejecutivo": "",
            "cadena_de_razonamiento": "",
            "noticias_destacadas": [],
            "missing_official_data": [],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        render_missing_page(fecha, args.motivo, carpeta / "index.html")
        hechas.append(fecha)
        print(f"✓ {fecha}: faltante documentado")

    if hechas:
        update_index_page(max(hechas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
