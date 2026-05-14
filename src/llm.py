# Archivo: src/llm.py
# Llamada a Gemini API con retries, validación y fallback automático de modelo
# Compatible con Windows 11 + Python 3.13.x + google-genai SDK

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

# Modelos en orden de preferencia (fallback automático)
GEMINI_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]

LLM_RUNTIME_METRICS: Dict[str, int] = {
    "llm_calls_total": 0,
    "llm_json_parse_failures_total": 0,
    "llm_json_parse_unrecovered_total": 0,
    "llm_json_repair_attempts_total": 0,
    "llm_json_repair_success_total": 0,
    "llm_model_fallback_activations": 0,
}


def reset_llm_runtime_metrics() -> None:
    """Reinicia contadores de observabilidad de llamadas LLM para la corrida actual."""
    for key in LLM_RUNTIME_METRICS:
        LLM_RUNTIME_METRICS[key] = 0


def get_llm_runtime_metrics() -> Dict[str, int]:
    """Devuelve snapshot de métricas acumuladas de llamadas LLM en memoria."""
    return dict(LLM_RUNTIME_METRICS)


def _resolve_debug_dir() -> Path:
    """Resuelve carpeta de debug para artefactos LLM (scope diario)."""
    configured = os.getenv("LGC_DEBUG_DIR", "").strip()
    if configured:
        base = Path(configured)
    else:
        day = datetime.now().strftime("%Y-%m-%d")
        base = Path("raw") / day / "debug"

    base.mkdir(parents=True, exist_ok=True)
    return base

def _get_gemini_client(api_key: str) -> genai.Client:
    """Inicializa el cliente Gemini una sola vez."""
    return genai.Client(api_key=api_key)

def call_gemini_with_retry(
    prompt: str,
    max_retries: int = 3,
    initial_delay: float = 5.0,
    debug_label: str = "generic",
) -> Dict:
    """
    Llama a Gemini con retries exponenciales y fallback de modelo.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY no configurada en variables de entorno")

    LLM_RUNTIME_METRICS["llm_calls_total"] += 1
    
    last_error = None
    parse_failures_by_model = {model: 0 for model in GEMINI_MODELS}
    unrecovered_parse_failures_by_model = {model: 0 for model in GEMINI_MODELS}
    
    for model_name in GEMINI_MODELS:
        logger.info(f"Intentando con modelo: {model_name}")
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Intento {attempt + 1}/{max_retries} con {model_name}")
                
                client = _get_gemini_client(api_key)
                
                # Configurar generación determinista
                config = genai_types.GenerateContentConfig(
                    temperature=0.0,
                    top_p=1.0,
                    max_output_tokens=12000,
                    response_mime_type="application/json"
                )
                
                response = client.models.generate_content(
                    model=model_name,
                    contents=[genai_types.Content(parts=[genai_types.Part(text=prompt)])],
                    config=config
                )
                
                response_text = (response.text or "").strip()

                # Guardar respuesta cruda siempre (éxito o fallo de parseo)
                # Sobrescribe en cada llamada → última respuesta siempre inspeccionable
                try:
                    debug_file = _resolve_debug_dir() / "debug_response.txt"
                    with open(debug_file, "w", encoding="utf-8") as f:
                        f.write(response_text)
                except OSError:
                    pass  # No bloquear el pipeline si el disco falla
                
                # Parsear JSON
                result = _extract_json_from_response(response_text)
                
                if result is None:
                    logger.warning(f"No se pudo extraer JSON válido con {model_name}")
                    parse_failures_by_model[model_name] += 1
                    LLM_RUNTIME_METRICS["llm_json_parse_failures_total"] += 1
                    _save_failed_response(response_text, model_name, attempt + 1, debug_label)

                    repaired_result = _attempt_json_repair_with_model(
                        client,
                        model_name,
                        response_text,
                    )
                    if repaired_result is not None:
                        LLM_RUNTIME_METRICS["llm_json_repair_success_total"] += 1
                        logger.info("JSON reparado exitosamente con %s tras fallo de parseo", model_name)
                        return repaired_result

                    unrecovered_parse_failures_by_model[model_name] += 1
                    LLM_RUNTIME_METRICS["llm_json_parse_unrecovered_total"] += 1
                    if attempt < max_retries - 1:
                        time.sleep(initial_delay)
                    continue  # Probar siguiente retry
                
                # Verificar error explícito del LLM
                if isinstance(result, dict) and "error" in result:
                    logger.warning(f"LLM reportó error: {result['error']}")
                    continue
                
                logger.info(f"Respuesta exitosa con {model_name}")
                if model_name != GEMINI_MODELS[0]:
                    LLM_RUNTIME_METRICS["llm_model_fallback_activations"] += 1
                    logger.warning(
                        "Fallback de modelo activado: %s → %s",
                        GEMINI_MODELS[0],
                        model_name,
                    )
                logger.info(
                    "Métrica parseo JSON: %s | no recuperados: %s",
                    ", ".join(
                        f"{m}={parse_failures_by_model[m]} fallos"
                        for m in GEMINI_MODELS
                    ),
                    ", ".join(
                        f"{m}={unrecovered_parse_failures_by_model[m]}"
                        for m in GEMINI_MODELS
                    ),
                )
                return result
                
            except genai_errors.APIError as e:
                logger.warning(
                    "Error API con %s (status=%s): %s",
                    model_name,
                    getattr(e, "code", "n/a"),
                    e,
                )
                last_error = e
                if attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    time.sleep(delay)
                continue
                
            except Exception as e:
                logger.warning(f"Error inesperado con {model_name}: {type(e).__name__}: {e}")
                last_error = e
                if attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    time.sleep(delay)
                continue
        
        # Si llegamos acá, el modelo actual falló todos los retries
        logger.warning(f"Modelo {model_name} agotó retries, probando siguiente...")
    
    # Todos los modelos y retries fallaron → fallback
    logger.error("Todos los intentos fallaron. Usando fallback.")
    logger.info(
        "Métrica parseo JSON final: %s | no recuperados: %s",
        ", ".join(
            f"{m}={parse_failures_by_model[m]} fallos"
            for m in GEMINI_MODELS
        ),
        ", ".join(
            f"{m}={unrecovered_parse_failures_by_model[m]}"
            for m in GEMINI_MODELS
        ),
    )
    return _build_fallback_from_error(str(last_error))


def _attempt_json_repair_with_model(
    client: genai.Client,
    model_name: str,
    raw_response_text: str,
) -> Optional[Dict]:
    """Intenta reparar una respuesta no parseable pidiendo SOLO JSON válido."""
    LLM_RUNTIME_METRICS["llm_json_repair_attempts_total"] += 1

    repair_payload = {
        "task": "repair_invalid_json",
        "rules": [
            "Return ONLY valid JSON.",
            "Do not add markdown fences.",
            "Do not add explanations.",
            "Preserve fields and values when possible.",
        ],
        "invalid_response": (raw_response_text or "")[:60000],
    }

    repair_prompt = json.dumps(repair_payload, ensure_ascii=False)
    try:
        config = genai_types.GenerateContentConfig(
            temperature=0.0,
            top_p=1.0,
            max_output_tokens=12000,
            response_mime_type="application/json",
        )
        response = client.models.generate_content(
            model=model_name,
            contents=[genai_types.Content(parts=[genai_types.Part(text=repair_prompt)])],
            config=config,
        )
        repaired_text = (response.text or "").strip()
        repaired_result = _extract_json_from_response(repaired_text)
        if isinstance(repaired_result, dict):
            return repaired_result
    except Exception as e:
        logger.debug("Fallo en intento de reparación JSON con %s: %s", model_name, e)

    return None

def _extract_json_from_response(response_text: str) -> Optional[Dict]:
    """Extrae JSON válido de la respuesta cruda de Gemini."""
    cleaned = response_text.strip()
    import re

    candidates: List[str] = [cleaned]

    # Caso 2: JSON en markdown ```json ... ```
    markdown_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(markdown_pattern, cleaned, re.IGNORECASE | re.DOTALL)
    if match:
        candidates.append(match.group(1).strip())

    # Caso 3: heurística para objeto o lista embebida en texto
    start_obj = cleaned.find("{")
    end_obj = cleaned.rfind("}")
    if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
        candidates.append(cleaned[start_obj:end_obj + 1].strip())

    start_arr = cleaned.find("[")
    end_arr = cleaned.rfind("]")
    if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        candidates.append(cleaned[start_arr:end_arr + 1].strip())

    for candidate_text in candidates:
        sanitized = _sanitize_json_candidate(candidate_text)
        try:
            parsed = json.loads(sanitized)
            normalized = _normalize_llm_payload(parsed)
            if isinstance(normalized, dict):
                return normalized
        except json.JSONDecodeError:
            repaired = _escape_inner_quotes_in_json_strings(sanitized)
            if repaired != sanitized:
                try:
                    parsed = json.loads(repaired)
                    normalized = _normalize_llm_payload(parsed)
                    if isinstance(normalized, dict):
                        return normalized
                except json.JSONDecodeError:
                    continue

    return None


def _sanitize_json_candidate(text: str) -> str:
    """Normaliza prefijos y comillas tipográficas para facilitar json.loads."""
    normalized = text.strip()

    if normalized.lower().startswith("json"):
        normalized = normalized[4:].lstrip("\n\r\t :")

    # Normalizar comillas tipográficas a comillas ASCII.
    replacements = {
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    # Si ya parece JSON completo (objeto o lista), no recortar más.
    if (normalized.startswith("{") and normalized.endswith("}")) or (
        normalized.startswith("[") and normalized.endswith("]")
    ):
        return normalized.strip()

    # Recortar cualquier texto fuera del bloque JSON principal.
    start_obj = normalized.find("{")
    end_obj = normalized.rfind("}")
    start_arr = normalized.find("[")
    end_arr = normalized.rfind("]")

    obj_candidate = ""
    arr_candidate = ""
    if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
        obj_candidate = normalized[start_obj:end_obj + 1]
    if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        arr_candidate = normalized[start_arr:end_arr + 1]

    # Priorizar el primer bloque que aparece en el texto.
    if obj_candidate and arr_candidate:
        normalized = obj_candidate if start_obj < start_arr else arr_candidate
    elif obj_candidate:
        normalized = obj_candidate
    elif arr_candidate:
        normalized = arr_candidate

    return normalized.strip()


def _escape_inner_quotes_in_json_strings(text: str) -> str:
    """Escapa comillas internas no escapadas dentro de strings JSON."""
    chars: List[str] = []
    in_string = False
    escaped = False
    length = len(text)

    for i, ch in enumerate(text):
        if ch == "\\" and in_string and not escaped:
            chars.append(ch)
            escaped = True
            continue

        if ch == '"' and not escaped:
            if not in_string:
                in_string = True
                chars.append(ch)
                continue

            # Dentro de string: si no cierra valor JSON, asumir comilla literal y escapar.
            j = i + 1
            while j < length and text[j] in " \t\r\n":
                j += 1
            next_char = text[j] if j < length else ""
            if next_char in [",", "}", "]", ":"]:
                in_string = False
                chars.append(ch)
            else:
                chars.append("\\\"")
            escaped = False
            continue

        chars.append(ch)
        escaped = False

    return "".join(chars)


def _normalize_llm_payload(parsed: Any) -> Optional[Dict]:
    """Normaliza payloads lista->objeto según el schema esperado de cada etapa."""
    if isinstance(parsed, dict):
        return parsed

    if not isinstance(parsed, list):
        return None

    if not parsed:
        return {"items": []}

    if not all(isinstance(item, dict) for item in parsed):
        return None

    sample = parsed[0]
    keys = set(sample.keys())

    if "id_referencia" in keys and ("hechos_clave" in keys or "evidencia_literal" in keys):
        return {"factual_items": parsed}

    if "id_referencia" in keys and ("headline" in keys or "summary" in keys):
        return {"noticias_destacadas": parsed}

    if "idx" in keys and ("headline" in keys or "summary" in keys):
        return {"items": parsed}

    return {"items": parsed}


def _save_failed_response(response_text: str, model_name: str, attempt: int, debug_label: str) -> None:
    """Guarda respuestas no parseables para auditoría puntual por modelo/intento."""
    safe_model = model_name.replace("/", "_").replace(".", "_")
    safe_label = (debug_label or "generic").strip().lower().replace(" ", "_")
    safe_label = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in safe_label)
    failed_path = _resolve_debug_dir() / f"debug_response_failed_{safe_label}_{safe_model}_attempt_{attempt}.txt"
    try:
        with open(failed_path, "w", encoding="utf-8") as f:
            f.write(response_text)
    except OSError:
        logger.debug("No se pudo guardar respuesta fallida en %s", failed_path)

def _build_fallback_from_error(error_msg: str) -> Dict:
    """Construye respuesta de fallback cuando Gemini falla irreparablemente."""
    safe_error = error_msg[:150] + ("..." if len(error_msg) > 150 else "")
    return {
        "date": "",
        "cadena_de_razonamiento": "[FALLBACK] Razonamiento no disponible por error de LLM.",
        "resumen_ejecutivo": f"⚠️ El procesamiento automático encontró un inconveniente: {safe_error}. Los titulares a continuación fueron recolectados directamente de fuentes primarias.",
        "noticias_destacadas": [],
        "unverified_claims": [],
        "missing_official_data": ["Procesamiento LLM no disponible"],
        "sources_consulted": [],
        "_fallback": True,
        "_error": safe_error
    }

def call_gemini_mock(prompt_text: str) -> dict:
    """
    Mock para pruebas locales sin consumir API.
    Devuelve una estructura mínima válida.
    """
    from datetime import datetime
    logger.info("Usando mock de Gemini (modo pruebas)")
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "date": today,
        "cadena_de_razonamiento": "[MOCK] Razonamiento de prueba.",
        "resumen_ejecutivo": "[MODO PRUEBAS] Este es un resumen generado por el mock.",
        "noticias_destacadas": [
            {
                "headline": "[MOCK] Inflación mensual se mantiene bajo observación",
                "summary": "[MODO PRUEBAS] Síntesis técnica de ejemplo para validar el pipeline end-to-end con schema plano.",
                "impact": "MEDIO",
                "asset_relevance": ["TASAS", "DÓLAR"],
                "tags": ["Inflación", "BCRA"],
                "source_name": "Fuente Mock",
                "source_url": "https://example.com/mock",
                "status": "VALIDADO",
                "verified": True,
                "evidencia_source_snippet": "[MODO PRUEBAS] Cita de evidencia para validación del schema."
            }
        ],
        "unverified_claims": [],
        "missing_official_data": ["[MODO PRUEBAS] Ejemplo de dato faltante"],
        "sources_consulted": ["https://example.com"]
    }


def translate_items_to_spanish(items: List[Dict], max_retries: int = 2) -> List[Dict]:
    """
    Traduce en lote titulares/summaries/tags al español usando Gemini.
    Devuelve solo los items traducidos válidos con su idx original.
    """
    if not items:
        return []

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("No se pudo traducir a español: GEMINI_API_KEY ausente")
        return []

    client = _get_gemini_client(api_key)

    prompt_payload = {
        "task": "Traducir a español neutro financiero",
        "rules": [
            "No agregar ni quitar hechos.",
            "Mantener números, porcentajes, monedas y nombres propios.",
            "Traducir headline, summary y tags al español.",
            "Devolver SOLO JSON válido.",
        ],
        "items": items,
        "output_schema": {
            "items": [
                {
                    "idx": 0,
                    "headline": "texto en español",
                    "summary": "texto en español",
                    "tags": ["tag1", "tag2"],
                }
            ]
        },
    }

    prompt_text = json.dumps(prompt_payload, ensure_ascii=False)

    for attempt in range(1, max_retries + 1):
        try:
            config = genai_types.GenerateContentConfig(
                temperature=0.0,
                top_p=1.0,
                max_output_tokens=12000,
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=GEMINI_MODELS[0],
                contents=[genai_types.Content(parts=[genai_types.Part(text=prompt_text)])],
                config=config,
            )

            response_text = (response.text or "").strip()
            parsed = _extract_json_from_response(response_text)
            if not isinstance(parsed, dict):
                continue

            translated_items = parsed.get("items", [])
            if not isinstance(translated_items, list):
                continue

            valid_items = []
            for item in translated_items:
                if not isinstance(item, dict):
                    continue
                if "idx" not in item:
                    continue
                valid_items.append(item)

            if valid_items:
                return valid_items
        except Exception as e:
            logger.warning(
                "Error traduciendo items a español (intento %d/%d): %s",
                attempt,
                max_retries,
                e,
            )

    logger.warning("No se pudieron traducir items a español tras %d intentos", max_retries)
    return []


def translate_items_to_spanish_contextual(items: List[Dict], max_retries: int = 2) -> List[Dict]:
    """
    Segunda pasada de traducción con contexto de fuente/URL para casos difíciles.
    Devuelve solo los items traducidos válidos con su idx original.
    """
    if not items:
        return []

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("No se pudo ejecutar traducción contextual: GEMINI_API_KEY ausente")
        return []

    client = _get_gemini_client(api_key)

    prompt_payload = {
        "task": "Reescritura-traducción contextual al español para titulares financieros",
        "rules": [
            "Resolver textos parcialmente traducidos o ambiguos usando el contexto de source_name y source_url.",
            "No inventar hechos nuevos; mantener semántica del original.",
            "Conservar cifras, porcentajes, monedas y nombres propios.",
            "headline debe ser breve y claro en español (max 80 caracteres aprox).",
            "Traducir también summary y tags.",
            "Devolver SOLO JSON válido.",
        ],
        "items": items,
        "output_schema": {
            "items": [
                {
                    "idx": 0,
                    "headline": "texto en español",
                    "summary": "texto en español",
                    "tags": ["tag1", "tag2"],
                }
            ]
        },
    }

    prompt_text = json.dumps(prompt_payload, ensure_ascii=False)

    for attempt in range(1, max_retries + 1):
        try:
            config = genai_types.GenerateContentConfig(
                temperature=0.0,
                top_p=1.0,
                max_output_tokens=12000,
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=GEMINI_MODELS[0],
                contents=[genai_types.Content(parts=[genai_types.Part(text=prompt_text)])],
                config=config,
            )

            response_text = (response.text or "").strip()
            parsed = _extract_json_from_response(response_text)
            if not isinstance(parsed, dict):
                continue

            translated_items = parsed.get("items", [])
            if not isinstance(translated_items, list):
                continue

            valid_items = []
            for item in translated_items:
                if not isinstance(item, dict):
                    continue
                if "idx" not in item:
                    continue
                valid_items.append(item)

            if valid_items:
                return valid_items
        except Exception as e:
            logger.warning(
                "Error en traducción contextual (intento %d/%d): %s",
                attempt,
                max_retries,
                e,
            )

    logger.warning("No se pudieron traducir items en pasada contextual tras %d intentos", max_retries)
    return []