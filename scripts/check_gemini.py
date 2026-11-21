"""
Diagnóstico de Gemini para el Diario.

Responde dos preguntas antes de una corrida real:
1. ¿Qué modelos "flash" puede usar esta clave?
2. ¿Cada modelo responde hoy, o está sin acceso, sin cuota o saturado?

Hace como máximo una llamada mínima por modelo probado (gasta 1 de la cuota diaria
de cada uno). No publica nada ni modifica archivos.

Uso:  GEMINI_API_KEY=... python scripts/check_gemini.py
Opcional: LGC_GEMINI_MODELS="modelo1,modelo2" para probar esos primero.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.llm import GEMINI_MODELS  # noqa: E402  (respeta LGC_GEMINI_MODELS)

MAX_MODELS_TO_TEST = 6


def _describe_error(error: genai_errors.APIError) -> str:
    code = getattr(error, "code", None)
    text = str(error)
    if code == 429:
        detail = "sin cuota (límite alcanzado)"
        if "FreeTier" in text:
            detail += " — la clave está en el plan GRATIS"
        return f"429 {detail}"
    if code == 404:
        return "404 sin acceso para esta clave"
    if code == 503:
        return "503 saturado en este momento (reintentar más tarde)"
    if code in (401, 403):
        return f"{code} clave inválida o sin permiso"
    return f"{code} {text[:120]}"


def main() -> int:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: falta GEMINI_API_KEY (en GitHub: Settings > Secrets and variables > Actions).")
        return 1

    client = genai.Client(api_key=api_key)

    print("== Modelos 'flash' que la clave puede ver ==")
    visibles: list[str] = []
    try:
        for model in client.models.list():
            name = str(getattr(model, "name", "")).replace("models/", "")
            if "flash" in name and "image" not in name and "tts" not in name and "audio" not in name:
                visibles.append(name)
    except genai_errors.APIError as e:
        print(f"No se pudo listar modelos: {_describe_error(e)}")
    for name in sorted(visibles):
        print(f"  - {name}")

    # Primero los configurados para el Diario; después algunos visibles para comparar.
    candidatos = list(GEMINI_MODELS)
    for name in sorted(visibles, reverse=True):
        if name not in candidatos and "preview" not in name and "exp" not in name:
            candidatos.append(name)
    candidatos = candidatos[:MAX_MODELS_TO_TEST]

    print("\n== Prueba mínima (1 llamada por modelo) ==")
    print(f"Modelos configurados para el Diario: {', '.join(GEMINI_MODELS)}")
    for name in candidatos:
        try:
            response = client.models.generate_content(
                model=name,
                contents=[genai_types.Content(parts=[genai_types.Part(text="Respondé solo: OK")])],
                config=genai_types.GenerateContentConfig(temperature=0.0, max_output_tokens=20),
            )
            texto = (response.text or "").strip().replace("\n", " ")[:20]
            estado = f"OK (respondió: {texto!r})"
        except genai_errors.APIError as e:
            estado = _describe_error(e)
        except Exception as e:  # red, tiempo de espera, etc.
            estado = f"error inesperado: {type(e).__name__}: {str(e)[:100]}"
        marca = "*" if name in GEMINI_MODELS else " "
        print(f" {marca} {name:<32} {estado}")

    print("\n(* = modelo que usa hoy el Diario)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
