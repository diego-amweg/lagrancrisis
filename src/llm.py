# Archivo: src/llm.py
# Llamadas a modelos de lenguaje (Gemini y Claude) con reintentos, validación
# y cambio automático de modelo si el preferido falla.

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

# Modelos en orden de preferencia. Si el primero falla se pasa al siguiente,
# aunque sea de otra empresa. Se cambian sin tocar código con la variable
# LGC_MODELS (o la anterior LGC_GEMINI_MODELS), nombres separados por coma.
# Los modelos cuya clave no está cargada se saltean solos.
DEFAULT_MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "claude-haiku-5-5"]
DEFAULT_GEMINI_MODELS = DEFAULT_MODELS  # nombre anterior, se mantiene por compatibilidad

PROVIDER_KEYS = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}

# Errores que no se arreglan reintentando el mismo modelo en esta corrida.
NON_RETRYABLE_CODES = {400, 401, 403, 404, 429}

JSON_SYSTEM_INSTRUCTION = (
    "Respondé exclusivamente con un objeto JSON válido, sin texto antes ni después "
    "y sin bloques de código."
)


def _provider_of(model_name: str) -> str:
    return "anthropic" if model_name.lower().startswith("claude") else "gemini"


def _has_key(model_name: str) -> bool:
    return bool(os.getenv(PROVIDER_KEYS[_provider_of(model_name)], "").strip())


def _load_gemini_models() -> List[str]:
    raw = os.getenv("LGC_MODELS", "") or os.getenv("LGC_GEMINI_MODELS", "")
    models = [name.strip() for name in raw.split(",") if name.strip()]
    # Sin duplicados, respetando el orden indicado.
    unique = list(dict.fromkeys(models))
    return unique or list(DEFAULT_MODELS)


GEMINI_MODELS = _load_gemini_models()  # lista configurada (todas las empresas)

# Modelos que se usan en la corrida actual: los configurados con clave cargada,
# reordenados por el chequeo previo (preflight_models).
ACTIVE_MODELS: List[str] = [m for m in GEMINI_MODELS if _has_key(m)]

LLM_RUNTIME_METRICS: Dict[str, int] = {
    "llm_calls_total": 0,
    "llm_json_parse_failures_total": 0,
    "llm_json_parse_unrecovered_total": 0,
    "llm_json_repair_attempts_total": 0,
    "llm_json_repair_success_total": 0,
    "llm_model_fallback_activations": 0,
}

# Uso por modelo: pedidos que respondieron y unidades de texto (tokens)
# leídas y escritas. Sirve para calcular el costo real de cada edición.
LLM_TOKEN_USAGE: Dict[str, Dict[str, int]] = {}
LLM_PREFLIGHT: Dict[str, str] = {}


def reset_llm_runtime_metrics() -> None:
    """Reinicia contadores de observabilidad de llamadas LLM para la corrida actual."""
    for key in LLM_RUNTIME_METRICS:
        LLM_RUNTIME_METRICS[key] = 0
    LLM_TOKEN_USAGE.clear()


def get_llm_runtime_metrics() -> Dict[str, int]:
    """Devuelve snapshot de métricas acumuladas de llamadas LLM en memoria."""
    return dict(LLM_RUNTIME_METRICS)


def get_llm_usage_report() -> Dict[str, object]:
    """Uso por modelo, orden final de modelos y resultado del chequeo previo."""
    return {
        "llm_token_usage": {m: dict(v) for m, v in LLM_TOKEN_USAGE.items()},
        "llm_models_order": list(ACTIVE_MODELS),
        "llm_preflight": dict(LLM_PREFLIGHT),
    }


class ModelCallError(Exception):
    """Error de un modelo, con el código normalizado (429, 503, 'timeout', etc.)."""

    def __init__(self, model_name: str, code: object, message: str):
        super().__init__(message)
        self.model_name = model_name
        self.code = code


_GEMINI_CLIENTS: Dict[str, genai.Client] = {}
_ANTHROPIC_CLIENTS: Dict[str, Any] = {}


def _get_gemini_client(api_key: str) -> genai.Client:
    """Inicializa el cliente Gemini una sola vez por clave."""
    if api_key not in _GEMINI_CLIENTS:
        _GEMINI_CLIENTS[api_key] = genai.Client(api_key=api_key)
    return _GEMINI_CLIENTS[api_key]


def _get_anthropic_client(api_key: str):
    if api_key not in _ANTHROPIC_CLIENTS:
        import anthropic

        # Sin reintentos internos: los maneja este módulo, igual que con Gemini.
        _ANTHROPIC_CLIENTS[api_key] = anthropic.Anthropic(api_key=api_key, timeout=300.0, max_retries=0)
    return _ANTHROPIC_CLIENTS[api_key]


def _record_usage(model_name: str, input_tokens: int, output_tokens: int) -> None:
    usage = LLM_TOKEN_USAGE.setdefault(model_name, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    usage["calls"] += 1
    usage["input_tokens"] += int(input_tokens or 0)
    usage["output_tokens"] += int(output_tokens or 0)


def _generate(model_name: str, prompt: str, max_output_tokens: int = 12000, json_mode: bool = True) -> str:
    """Pide texto a un modelo (Gemini o Claude) y devuelve la respuesta cruda."""
    provider = _provider_of(model_name)
    api_key = os.getenv(PROVIDER_KEYS[provider], "").strip()
    if not api_key:
        raise ModelCallError(model_name, "sin_clave", f"Falta {PROVIDER_KEYS[provider]}")

    if provider == "gemini":
        try:
            config_kwargs: Dict[str, Any] = {
                "temperature": 0.0,
                "top_p": 1.0,
                "max_output_tokens": max_output_tokens,
            }
            if json_mode:
                config_kwargs["response_mime_type"] = "application/json"
            response = _get_gemini_client(api_key).models.generate_content(
                model=model_name,
                contents=[genai_types.Content(parts=[genai_types.Part(text=prompt)])],
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )
        except genai_errors.APIError as e:
            raise ModelCallError(model_name, getattr(e, "code", "n/a"), str(e)) from e
        except Exception as e:  # red, tiempo de espera
            raise ModelCallError(model_name, "conexion", f"{type(e).__name__}: {e}") from e
        meta = getattr(response, "usage_metadata", None)
        output_tokens = (getattr(meta, "candidates_token_count", 0) or 0) + (
            getattr(meta, "thoughts_token_count", 0) or 0
        )
        _record_usage(model_name, getattr(meta, "prompt_token_count", 0) or 0, output_tokens)
        return (response.text or "").strip()

    import anthropic

    try:
        kwargs: Dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_output_tokens,
            # La API actual de Claude no acepta "temperature": no se puede fijar en 0
            # como en Gemini. Por eso la prueba comparativa mide el resultado, no la configuración.
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            kwargs["system"] = JSON_SYSTEM_INSTRUCTION
        response = _get_anthropic_client(api_key).messages.create(**kwargs)
    except anthropic.APIStatusError as e:
        code = 503 if e.status_code == 529 else e.status_code  # 529 = saturado
        raise ModelCallError(model_name, code, str(e)) from e
    except anthropic.APIConnectionError as e:
        raise ModelCallError(model_name, "conexion", f"{type(e).__name__}: {e}") from e
    usage = getattr(response, "usage", None)
    _record_usage(model_name, getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0))
    return "".join(getattr(block, "text", "") for block in response.content).strip()


def _drop_model(model_name: str, reason: object) -> None:
    """Saca un modelo de la corrida actual (sin cuota, sin acceso, sin clave)."""
    if model_name in ACTIVE_MODELS and len(ACTIVE_MODELS) > 1:
        ACTIVE_MODELS.remove(model_name)
        logger.warning("Modelo %s descartado por el resto de la corrida (%s)", model_name, reason)


def preflight_models() -> List[str]:
    """Antes de procesar, pregunta a cada modelo si responde y ordena la lista.

    Los que responden quedan primero (en el orden configurado); los saturados
    (503) quedan al final por si se recuperan; los que no tienen acceso, clave
    o cuota se descartan. Si ninguno responde, se deja la lista como estaba.
    """
    LLM_PREFLIGHT.clear()
    configured = list(GEMINI_MODELS)
    ok: List[str] = []
    saturated: List[str] = []
    for model_name in configured:
        if not _has_key(model_name):
            LLM_PREFLIGHT[model_name] = "sin clave"
            continue
        try:
            _generate(model_name, "Respondé solo: OK", max_output_tokens=64, json_mode=False)
            LLM_PREFLIGHT[model_name] = "responde"
            ok.append(model_name)
        except ModelCallError as e:
            LLM_PREFLIGHT[model_name] = f"error {e.code}"
            if e.code not in NON_RETRYABLE_CODES and e.code != "sin_clave":
                saturated.append(model_name)
    new_order = ok + saturated
    if new_order:
        ACTIVE_MODELS[:] = new_order
    else:
        ACTIVE_MODELS[:] = [m for m in configured if _has_key(m)] or configured
    logger.info("Chequeo previo de modelos: %s → orden de uso: %s", LLM_PREFLIGHT, ACTIVE_MODELS)
    return list(ACTIVE_MODELS)


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

def call_gemini_with_retry(
    prompt: str,
    max_retries: int = 3,
    initial_delay: float = 5.0,
    debug_label: str = "generic",
) -> Dict:
    """
    Pide la respuesta a los modelos en orden, con reintentos y cambio de modelo.

    El nombre se conserva por compatibilidad: hoy puede responder Gemini o Claude.
    - Saturado (503) o corte de red: reintenta el mismo modelo con espera creciente.
    - Sin cuota, sin acceso o sin clave: pasa al siguiente y lo descarta en la corrida.
    - Respuesta ilegible: intenta repararla y, si no, reintenta.
    """
    models = list(ACTIVE_MODELS)
    if not models:
        raise ValueError("No hay ninguna clave de modelo cargada (GEMINI_API_KEY o ANTHROPIC_API_KEY)")

    LLM_RUNTIME_METRICS["llm_calls_total"] += 1

    last_error: Optional[Exception] = None
    parse_failures_by_model = {model: 0 for model in models}
    unrecovered_parse_failures_by_model = {model: 0 for model in models}

    def _log_parse_metrics(prefix: str) -> None:
        logger.info(
            "%s: %s | no recuperados: %s",
            prefix,
            ", ".join(f"{m}={parse_failures_by_model[m]} fallos" for m in models),
            ", ".join(f"{m}={unrecovered_parse_failures_by_model[m]}" for m in models),
        )

    for model_name in models:
        if model_name not in ACTIVE_MODELS:
            continue  # descartado durante esta misma llamada
        logger.info(f"Intentando con modelo: {model_name}")

        for attempt in range(max_retries):
            try:
                logger.info(f"Intento {attempt + 1}/{max_retries} con {model_name}")
                response_text = _generate(model_name, prompt)

                # Guardar respuesta cruda siempre (éxito o fallo de parseo)
                # Sobrescribe en cada llamada → última respuesta siempre inspeccionable
                try:
                    debug_file = _resolve_debug_dir() / "debug_response.txt"
                    with open(debug_file, "w", encoding="utf-8") as f:
                        f.write(response_text)
                except OSError:
                    pass  # No bloquear el pipeline si el disco falla

                result = _extract_json_from_response(response_text)

                if result is None:
                    logger.warning(f"No se pudo extraer JSON válido con {model_name}")
                    parse_failures_by_model[model_name] += 1
                    LLM_RUNTIME_METRICS["llm_json_parse_failures_total"] += 1
                    _save_failed_response(response_text, model_name, attempt + 1, debug_label)

                    repaired_result = _attempt_json_repair_with_model(model_name, response_text)
                    if repaired_result is not None:
                        LLM_RUNTIME_METRICS["llm_json_repair_success_total"] += 1
                        logger.info("JSON reparado exitosamente con %s tras fallo de parseo", model_name)
                        return repaired_result

                    unrecovered_parse_failures_by_model[model_name] += 1
                    LLM_RUNTIME_METRICS["llm_json_parse_unrecovered_total"] += 1
                    if attempt < max_retries - 1:
                        time.sleep(initial_delay)
                    continue

                if isinstance(result, dict) and "error" in result:
                    logger.warning(f"LLM reportó error: {result['error']}")
                    continue

                logger.info(f"Respuesta exitosa con {model_name}")
                if model_name != models[0]:
                    LLM_RUNTIME_METRICS["llm_model_fallback_activations"] += 1
                    logger.warning("Fallback de modelo activado: %s → %s", models[0], model_name)
                _log_parse_metrics("Métrica parseo JSON")
                return result

            except ModelCallError as e:
                logger.warning("Error API con %s (status=%s): %s", model_name, e.code, e)
                last_error = e
                if e.code in NON_RETRYABLE_CODES or e.code == "sin_clave":
                    _drop_model(model_name, e.code)
                    break  # reintentar el mismo modelo no sirve
                if attempt < max_retries - 1:
                    time.sleep(initial_delay * (2 ** attempt))
                continue

            except Exception as e:
                logger.warning(f"Error inesperado con {model_name}: {type(e).__name__}: {e}")
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(initial_delay * (2 ** attempt))
                continue

        logger.warning(f"Modelo {model_name} agotó retries, probando siguiente...")

    logger.error("Todos los intentos fallaron. Usando fallback.")
    _log_parse_metrics("Métrica parseo JSON final")
    motivo = str(last_error) if last_error else "respuestas ilegibles (JSON inválido) en todos los intentos"
    return _build_fallback_from_error(motivo)


def _attempt_json_repair_with_model(
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
        repaired_text = _generate(model_name, repair_prompt)
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
    # El detalle técnico del error va solo al log y al campo interno _error;
    # nunca al texto que lee el público (antes se publicaba el error crudo de la API).
    logger.error("Detalle del error LLM (no se publica): %s", safe_error)
    return {
        "date": "",
        "cadena_de_razonamiento": "[FALLBACK] Razonamiento no disponible por error de LLM.",
        "resumen_ejecutivo": "El resumen ejecutivo de hoy no pudo generarse. Los titulares a continuación fueron recolectados directamente de fuentes primarias.",
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


def _generate_with_any_model(prompt_text: str) -> str:
    """Prueba los modelos activos en orden hasta que uno responda (para tareas cortas)."""
    last_error: Optional[Exception] = None
    for model_name in list(ACTIVE_MODELS):
        try:
            return _generate(model_name, prompt_text)
        except ModelCallError as e:
            logger.warning("Error API con %s (status=%s): %s", model_name, e.code, e)
            last_error = e
            if e.code in NON_RETRYABLE_CODES or e.code == "sin_clave":
                _drop_model(model_name, e.code)
    raise RuntimeError(f"Ningún modelo respondió: {last_error}")


def translate_items_to_spanish(items: List[Dict], max_retries: int = 2) -> List[Dict]:
    """
    Traduce en lote titulares/summaries/tags al español usando Gemini.
    Devuelve solo los items traducidos válidos con su idx original.
    """
    if not items:
        return []

    if not ACTIVE_MODELS:
        logger.warning("No se pudo traducir: no hay ninguna clave de modelo cargada")
        return []

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
            response_text = _generate_with_any_model(prompt_text)
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

    if not ACTIVE_MODELS:
        logger.warning("No se pudo traducir: no hay ninguna clave de modelo cargada")
        return []

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
            response_text = _generate_with_any_model(prompt_text)
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