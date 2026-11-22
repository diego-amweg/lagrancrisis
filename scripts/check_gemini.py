"""
Diagnóstico de los modelos de IA del Diario (Gemini y Claude).

Responde dos preguntas antes de una corrida real:
1. ¿Cada modelo configurado responde hoy, o está sin acceso, sin cuota o saturado?
2. ¿Qué modelos "flash" de Gemini puede ver la clave (para elegir reemplazos)?

Hace una llamada mínima por modelo configurado. No publica nada ni modifica archivos.

Uso:  GEMINI_API_KEY=... ANTHROPIC_API_KEY=... python scripts/check_gemini.py
Opcional: LGC_MODELS="modelo1,modelo2" para cambiar la lista y el orden.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import llm  # noqa: E402

EXPLICACION = {
    "responde": "OK",
    "sin clave": "falta la clave de esa empresa en GitHub",
    "error 429": "sin cuota (límite alcanzado o plan gratis agotado)",
    "error 404": "la clave no tiene acceso a ese modelo",
    "error 401": "clave inválida",
    "error 403": "clave sin permiso",
    "error 503": "saturado en este momento",
    "error conexion": "no se pudo conectar",
}


def main() -> int:
    if not any(os.getenv(v, "").strip() for v in llm.PROVIDER_KEYS.values()):
        print("ERROR: no hay ninguna clave cargada (GEMINI_API_KEY o ANTHROPIC_API_KEY).")
        return 1

    print("== Modelos configurados para el Diario, en orden ==")
    orden = llm.preflight_models()
    for modelo in llm.GEMINI_MODELS:
        estado = llm.LLM_PREFLIGHT.get(modelo, "sin probar")
        print(f"  {modelo:<28} {estado:<16} {EXPLICACION.get(estado, '')}")
    print(f"\nOrden que usaría hoy el Diario: {', '.join(orden) or 'ninguno'}")

    clave_gemini = os.getenv("GEMINI_API_KEY", "").strip()
    if clave_gemini:
        print("\n== Modelos 'flash' de Gemini que la clave puede ver ==")
        try:
            for model in llm._get_gemini_client(clave_gemini).models.list():
                name = str(getattr(model, "name", "")).replace("models/", "")
                if "flash" in name and not any(x in name for x in ("image", "tts", "audio", "live")):
                    print(f"  - {name}")
        except Exception as e:
            print(f"  No se pudo listar: {type(e).__name__}: {str(e)[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
