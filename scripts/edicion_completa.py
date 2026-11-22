"""
¿La edición de una fecha salió completa? Lo usa el proceso de GitHub para decidir
si publica ya o si espera al próximo intento del día.

Completa = tiene data.json, el resumen ejecutivo lo escribió un modelo y la mayoría
de las noticias pasaron por la IA (no por el respaldo automático).
Un día con pocas noticias ("missing_documented") cuenta como completo: reintentar no lo cambia.

Uso: python scripts/edicion_completa.py 2026-11-22   (sale con 0 si está completa, 1 si no)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_RESPALDO = 0.5  # más de la mitad de las noticias sin IA = incompleta
AVISO_SIN_RESUMEN = "El resumen ejecutivo de hoy no pudo generarse"


def main() -> int:
    fecha = sys.argv[1]
    data_path = ROOT / "docs" / fecha.replace("-", "/") / "data.json"
    if not data_path.exists():
        print(f"Incompleta: no existe {data_path.relative_to(ROOT)}")
        return 1
    data = json.loads(data_path.read_text(encoding="utf-8"))
    if data.get("status") == "missing_documented":
        print("Completa: día con pocas noticias, se publica como sin edición.")
        return 0
    if str(data.get("resumen_ejecutivo", "")).startswith(AVISO_SIN_RESUMEN):
        print("Incompleta: el resumen ejecutivo no lo pudo escribir ningún modelo.")
        return 1
    metricas_path = ROOT / "raw" / fecha / "pipeline_metrics.json"
    if metricas_path.exists():
        ratio = float(json.loads(metricas_path.read_text(encoding="utf-8")).get("fallback_items_ratio", 0) or 0)
        if ratio > MAX_RESPALDO:
            print(f"Incompleta: {ratio:.0%} de las noticias se armaron sin IA.")
            return 1
    print("Completa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
