"""
Resumen en castellano de una corrida del Diario, para la página de la corrida en GitHub.

Lee raw/AAAA-MM-DD/pipeline_metrics.json y logs/digest.log y escribe una tabla corta
con lo que importa para decidir si la edición salió bien. No modifica nada.

Uso: python scripts/resumen_corrida.py 2026-11-22
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Umbrales recalibrados en mayo de 2026 (ver Documento de Contexto del Diario).
MAX_UNRECOVERED = 10
MAX_TRANSLATED = 40


def _contar_en_log(fecha: str) -> dict[str, int]:
    log = ROOT / "logs" / "digest.log"
    conteo = {"ok": 0, "429": 0, "503": 0}
    if not log.exists():
        return conteo
    with open(log, encoding="utf-8", errors="replace") as f:
        for linea in f:
            if not linea.startswith(fecha):
                continue
            if 'generateContent "HTTP/1.1 200' in linea:
                conteo["ok"] += 1
            elif "status=429" in linea:
                conteo["429"] += 1
            elif "status=503" in linea:
                conteo["503"] += 1
    return conteo


def main() -> int:
    if len(sys.argv) < 2:
        print("Falta la fecha (AAAA-MM-DD).")
        return 0
    fecha = sys.argv[1]
    metricas_path = ROOT / "raw" / fecha / "pipeline_metrics.json"

    print(f"## Edición {fecha}\n")
    if not metricas_path.exists():
        print("No se generaron métricas: la corrida se cortó antes de terminar. Ver el registro del paso 'Armar la edición'.")
        return 0

    m = json.loads(metricas_path.read_text(encoding="utf-8"))
    llamadas = _contar_en_log(fecha)
    unrecovered = int(m.get("llm_json_parse_unrecovered_total", 0) or 0)
    translated = int(m.get("translated_items_count", 0) or 0)
    juez = str(m.get("judge_quality_gate", "NA"))
    puntaje = m.get("judge_weighted_total", 0)

    def marca(ok: bool) -> str:
        return "✅" if ok else "⚠️"

    filas = [
        ("Noticias descargadas", m.get("downloaded"), ""),
        ("Noticias publicadas", m.get("published"), ""),
        ("Respuestas de Gemini que llegaron bien", llamadas["ok"], ""),
        ("Rechazos por falta de cuota (429)", llamadas["429"], marca(llamadas["429"] == 0)),
        ("Rechazos por saturación (503)", llamadas["503"], ""),
        (f"Respuestas ilegibles sin recuperar (tope {MAX_UNRECOVERED})", unrecovered, marca(unrecovered <= MAX_UNRECOVERED)),
        (f"Noticias traducidas a mano (tope {MAX_TRANSLATED})", translated, marca(translated <= MAX_TRANSLATED)),
        ("Control del agente Juez", f"{juez} ({puntaje})", marca(juez == "PASS")),
        ("Noticias armadas sin Gemini (respaldo)", m.get("fallback_items_count"), ""),
    ]
    print("| Dato | Valor | |")
    print("|---|---|---|")
    for nombre, valor, icono in filas:
        print(f"| {nombre} | {valor} | {icono} |")

    if llamadas["429"]:
        print(
            "\n**Gemini rechazó pedidos por falta de cuota.** Si la clave está en el plan gratis, "
            "la edición sale incompleta (resumen ejecutivo sin generar y noticias sin redactar)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
