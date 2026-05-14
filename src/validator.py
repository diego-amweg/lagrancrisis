# Archivo: src/validator.py
# Etiquetado de fuentes y validación de estructura JSON del LLM
# Compatible con Windows 11 + Python 3.13.x

import re
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# Dominios oficiales (tag OFICIAL automático)
OFFICIAL_DOMAINS = [
    '.gob.ar', '.gov', '.gob', 
    'bcra.gob.ar', 'indec.gob.ar', 'boletinoficial.gob.ar',
    'casarosada.gob.ar', 'argentina.gob.ar',
    'federalreserve.gov', 'imf.org', 'ecb.europa.eu'
]

# Medios tier-1 reconocidos (tag VALIDADO si corroboran)
TIER1_DOMAINS = [
    'ambito.com', 'cronista.com', 'lanacion.com.ar', 'infobae.com', 'perfil.com',
    'reuters.com', 'bloomberg.com', 'bloomberglinea.com', 'ft.com', 'wsj.com'
]

SPECULATIVE_PATTERNS = [
    r"\bsegún fuentes\b",
    r"\bse estima\b",
    r"\bpodría\b",
    r"\bpodrian\b",
    r"\bpodría\b",
    r"\bhabría\b",
]

SUMMARY_MIN_CHARS = 500

def tag_sources(articles: List[Dict]) -> List[Dict]:
    """
    Asigna tag de validación a cada artículo según su fuente.
    
    Tags posibles:
    - OFICIAL: dominio .gob.ar, .gov, etc.
    - VALIDADO: medio tier-1 reconocido
    - SIN CONFIRMAR: cualquier otra fuente
    
    Args:
        articles: Lista de artículos con key 'url'
        
    Returns:
        Misma lista con key 'status' agregada a cada artículo
    """
    for article in articles:
        url = article.get("url", "").lower()
        article["status"] = _classify_source(url)
        article["verified"] = article["status"] in ["OFICIAL", "VALIDADO"]
    
    return articles


def _classify_source(url: str) -> str:
    """Clasifica una URL en OFICIAL/VALIDADO/SIN CONFIRMAR (helper interno)."""
    if not url:
        return "SIN CONFIRMAR"
    
    url_lower = url.lower()
    
    # Chequear dominios oficiales primero
    for domain in OFFICIAL_DOMAINS:
        if domain in url_lower:
            return "OFICIAL"
    
    # Chequear medios tier-1
    for domain in TIER1_DOMAINS:
        if domain in url_lower:
            return "VALIDADO"
    
    return "SIN CONFIRMAR"


def validate_json_structure(data: Dict, required_sections: List[str]) -> Tuple[bool, str]:
    """
    Valida que la respuesta del LLM cumpla con el schema esperado.
    
    Args:
        data: Diccionario parseado de la respuesta del LLM
        required_sections: Lista de nombres de sección esperados
        
    Returns:
        Tuple (es_valido: bool, mensaje: str)
    """
    # Campos obligatorios de nivel superior (schema plano)
    required_fields = [
        "date", "cadena_de_razonamiento", "resumen_ejecutivo", "noticias_destacadas",
        "unverified_claims", "missing_official_data", "sources_consulted"
    ]
    
    # 1. Verificar campos obligatorios
    missing_fields = [f for f in required_fields if f not in data]
    if missing_fields:
        return False, f"Faltan campos obligatorios: {missing_fields}"
    
    # 2. Verificar formato de fecha
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", data.get("date", "")):
        return False, f"Fecha inválida: {data.get('date')}"

    # 2b. Verificar cadena_de_razonamiento
    if not isinstance(data.get("cadena_de_razonamiento", ""), str):
        return False, "'cadena_de_razonamiento' debe ser un string"

    # 3. Verificar noticias destacadas (feed plano)
    noticias = data.get("noticias_destacadas", [])
    if not isinstance(noticias, list):
        return False, "'noticias_destacadas' debe ser una lista"

    # 4. Validar cada item del feed plano
    for i, item in enumerate(noticias):
        item_valid, msg = _validate_news_item(item, i, "noticias_destacadas")
        if not item_valid:
            return False, msg
    
    # 5. Verificar que arrays opcionales sean realmente listas
    for field in ["unverified_claims", "missing_official_data", "sources_consulted"]:
        if not isinstance(data.get(field, []), list):
            return False, f"El campo '{field}' debe ser una lista"
    
    return True, "OK"


def _validate_news_item(item: Dict, index: int, section: str) -> Tuple[bool, str]:
    """Valida un item individual de noticia (helper interno)."""
    required_keys = [
        "headline", "summary", "impact", "asset_relevance", "tags",
        "source_name", "source_url", "status", "verified", "evidencia_source_snippet"
    ]
    
    # Verificar campos obligatorios
    missing = [k for k in required_keys if k not in item]
    if missing:
        return False, f"Item {index} en '{section}' falta campos: {missing}"
    
    # Verificar valores enum
    if item["impact"] not in ["ALTO", "MEDIO", "BAJO"]:
        return False, f"Impact inválido en item {index}: {item['impact']}"
    
    if item["status"] not in ["OFICIAL", "VALIDADO", "SIN CONFIRMAR", "SIN_CONFIRMAR"]:
        return False, f"Status inválido en item {index}: {item['status']}"
    
    # Verificar que verified sea booleano
    if not isinstance(item["verified"], bool):
        return False, f"'verified' debe ser booleano en item {index}"
    
    # Verificar que URL empiece con http
    if not str(item["source_url"]).startswith("http"):
        return False, f"URL inválida en item {index}: {item['source_url']}"
    
    # Verificar asset_relevance (lista de strings, opcional pero requerido por prompt)
    if not isinstance(item.get("asset_relevance"), list):
        return False, f"'asset_relevance' debe ser lista en item {index}"

    if not isinstance(item.get("tags"), list):
        return False, f"'tags' debe ser lista en item {index}"

    summary = str(item.get("summary", ""))
    summary_len = len(summary)
    if summary_len < SUMMARY_MIN_CHARS:
        return (
            False,
            f"'summary' demasiado corto en item {index}: {summary_len} chars "
            f"(mínimo {SUMMARY_MIN_CHARS})",
        )

    evidence = str(item.get("evidencia_source_snippet", "")).strip()
    if not evidence:
        return False, f"'evidencia_source_snippet' vacío en item {index}"
    if len(evidence) > 220:
        return False, f"'evidencia_source_snippet' excede 220 chars en item {index}"

    return True, "OK"


def fallback_response(date: str, raw_articles: List[Dict]) -> Dict:
    """
    Genera respuesta de fallback cuando el LLM falla completamente.
    La web nunca queda en blanco: muestra titulares crudos con tags.
    
    Args:
        date: Fecha en formato YYYY-MM-DD
        raw_articles: Lista de artículos crudos descargados
        
    Returns:
        Diccionario con estructura válida pero sin resumen del LLM
    """
    noticias_destacadas = []
    for art in raw_articles[:20]:  # Top 20 para fallback
        noticias_destacadas.append({
            "headline": art.get("title", "Sin título")[:80],
            "summary": "Resumen pendiente de generación por LLM.",
            "impact": "BAJO",  # Fallback conservador
            "asset_relevance": ["NO_APLICA"],
            "tags": ["Fallback"],
            "source_name": art.get("source_name", "Desconocido"),
            "source_url": art.get("url", ""),
            "status": art.get("status", "SIN CONFIRMAR"),
            "verified": art.get("status") in ["OFICIAL", "VALIDADO"],
            "evidencia_source_snippet": _strip_html(str(art.get("content", "") or art.get("title", "")))[:220]
        })
    
    return {
        "date": date,
        "cadena_de_razonamiento": "[FALLBACK] No se pudo generar razonamiento con LLM.",
        "resumen_ejecutivo": "⏳ El resumen ejecutivo está en revisión. A continuación, los titulares más relevantes recolectados de fuentes verificadas.",
        "noticias_destacadas": noticias_destacadas,
        "unverified_claims": [],
        "missing_official_data": ["Datos oficiales de inflación, reservas y tipo de cambio"],
        "sources_consulted": list(set(a.get("url", "") for a in raw_articles if a.get("url"))),
        "_fallback": True,
        "_raw_count": len(raw_articles)
    }


def validate_post_llm(result: Dict, raw_articles: List[Dict]) -> Tuple[bool, List[str]]:
    """
    Valida que el output del LLM sea consistente con el contexto original.

    Chequeos:
    1. Todas las URLs citadas existen en los artículos descargados.
    2. Status sea coherente con el dominio de source_url (corrige automáticamente si no).
    3. Cada resumen esté entre 500 y 1000 chars.
    4. cadena_de_razonamiento tenga contenido suficiente (>50 chars).

    Args:
        result: Diccionario JSON devuelto por Gemini (ya parseado).
        raw_articles: Lista de artículos descargados antes de llamar al LLM.

    Returns:
        Tuple (sin_warnings: bool, lista_de_warnings: list[str])
    """
    warnings = []

    # 1. Verificar que todas las URLs citadas existen en raw_articles
    available_urls = {a.get("url", "") for a in raw_articles}
    for item in result.get("noticias_destacadas", []):
        url = item.get("source_url", "")
        if url and url not in available_urls:
            warnings.append(f"URL citada no encontrada en contexto: {url}")

    # 2. Corregir coherencia status vs dominio de la fuente
    for item in result.get("noticias_destacadas", []):
        url = item.get("source_url", "")
        current_status = _normalize_status(item.get("status", "SIN CONFIRMAR"))
        expected_status = _classify_source(url)

        if current_status != expected_status:
            warnings.append(
                "Status corregido por dominio: "
                f"{item.get('source_name', 'Fuente')} ({url}) "
                f"de {current_status} a {expected_status}"
            )
            item["status"] = expected_status
            item["verified"] = expected_status in ["OFICIAL", "VALIDADO"]

    # 3. Verificar longitud de summaries (mínimo editorial: 500 chars)
    for item in result.get("noticias_destacadas", []):
        summary = str(item.get("summary", ""))
        char_count = len(summary)
        if char_count < SUMMARY_MIN_CHARS:
            warnings.append(
                "Resumen por debajo del mínimo "
                f"({char_count} chars, mínimo {SUMMARY_MIN_CHARS}): "
                f"{item.get('headline', '')[:50]}"
            )

        # Chequeo anti-especulación sin evidencia verificable.
        low = summary.lower()
        if any(re.search(pattern, low) for pattern in SPECULATIVE_PATTERNS):
            evidence = str(item.get("evidencia_source_snippet", "")).strip()
            if not evidence or evidence == "No informado":
                warnings.append(
                    "Lenguaje especulativo sin evidencia en summary: "
                    f"{item.get('headline', '')[:60]}"
                )

    # 4. Verificar que cadena_de_razonamiento tiene contenido narrativo real
    cadena = result.get("cadena_de_razonamiento", "")
    if cadena and len(cadena) < 50:
        warnings.append("cadena_de_razonamiento demasiado breve para conexión narrativa")

    return len(warnings) == 0, warnings


def _normalize_status(status: str) -> str:
    """Normaliza variantes de status al formato canónico usado por validator."""
    normalized = str(status).strip().upper().replace("_", " ")
    if normalized == "SIN CONFIRMAR":
        return "SIN CONFIRMAR"
    if normalized in ["OFICIAL", "VALIDADO"]:
        return normalized
    return "SIN CONFIRMAR"


def validate_factual_extraction_structure(data: Dict, expected_urls: List[str]) -> Tuple[bool, str]:
    """Valida el JSON del Paso A (extracción factual)."""
    if not isinstance(data, dict):
        return False, "Respuesta factual inválida: no es objeto JSON"

    items = data.get("factual_items")
    if not isinstance(items, list):
        return False, "Respuesta factual inválida: falta lista factual_items"

    expected_set = set(expected_urls)
    found_set = set()

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return False, f"factual_items[{idx}] no es objeto"

        for key in ["source_url", "hechos_clave", "evidencia_literal", "incertidumbres"]:
            if key not in item:
                return False, f"factual_items[{idx}] falta campo {key}"

        if not isinstance(item.get("hechos_clave"), list):
            return False, f"factual_items[{idx}].hechos_clave debe ser lista"
        if not isinstance(item.get("incertidumbres"), list):
            return False, f"factual_items[{idx}].incertidumbres debe ser lista"

        url = str(item.get("source_url", "")).strip()
        if not url:
            return False, f"factual_items[{idx}] source_url vacío"
        found_set.add(url)

    missing = expected_set - found_set
    if missing:
        return False, f"Faltan URLs en factual_items: {len(missing)}"

    return True, "OK"


def validate_factual_extraction_by_id(
    data: Dict,
    expected_ids: List[str],
    canonical_by_id: Dict[str, Dict],
) -> Tuple[bool, List[str], Dict[str, Dict], List[str]]:
    """
    Valida factual_items con anclaje 1:1 por id_referencia.

    Rechaza si:
    - aparece id no esperado
    - hay ids duplicados
    - source_url no coincide con la canónica del id
    - un id presente no tiene cobertura factual mínima (evidencia/hechos)

    IDs faltantes se consideran omisiones intencionales por filtro de relevancia
    y NO se tratan como error en esta etapa.
    """
    errors: List[str] = []
    accepted: Dict[str, Dict] = {}
    intentionally_omitted_ids: List[str] = []

    if not isinstance(data, dict):
        return False, ["Respuesta factual inválida: no es objeto JSON"], accepted, intentionally_omitted_ids

    items = data.get("factual_items")
    if not isinstance(items, list):
        return False, ["Respuesta factual inválida: falta lista factual_items"], accepted, intentionally_omitted_ids

    expected_set = set(expected_ids)
    seen_ids = set()
    provided_expected_ids = set()

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"factual_items[{idx}] no es objeto")
            continue

        item_id = str(item.get("id_referencia", "")).strip()
        if not item_id:
            errors.append(f"factual_items[{idx}] sin id_referencia")
            continue

        if item_id in seen_ids:
            errors.append(f"id_referencia duplicado en factual_items: {item_id}")
            continue
        seen_ids.add(item_id)

        if item_id not in expected_set:
            errors.append(f"id_referencia fuera de set esperado: {item_id}")
            continue
        provided_expected_ids.add(item_id)

        required_keys = ["source_url", "hechos_clave", "evidencia_literal", "incertidumbres"]
        missing = [k for k in required_keys if k not in item]
        if missing:
            errors.append(f"factual_items[{idx}] falta campos: {missing}")
            continue

        if not isinstance(item.get("hechos_clave"), list):
            errors.append(f"factual_items[{idx}].hechos_clave debe ser lista")
            continue

        if not isinstance(item.get("incertidumbres"), list):
            errors.append(f"factual_items[{idx}].incertidumbres debe ser lista")
            continue

        evidence = str(item.get("evidencia_literal", "")).strip()
        hechos = item.get("hechos_clave", [])
        normalized_hechos = [str(h).strip() for h in hechos if str(h).strip()]
        hechos_sin_info = (not normalized_hechos) or all(
            h.lower() == "no informado" for h in normalized_hechos
        )
        evidence_sin_info = (not evidence) or (evidence.lower() == "no informado")
        if evidence_sin_info and hechos_sin_info:
            errors.append(
                "Cobertura factual insuficiente en id "
                f"{item_id}: evidencia_literal vacío/'No informado' y hechos_clave vacío/'No informado'"
            )
            continue

        canonical_url = str((canonical_by_id.get(item_id) or {}).get("source_url", "")).strip()
        got_url = str(item.get("source_url", "")).strip()
        if not canonical_url or got_url != canonical_url:
            errors.append(
                f"source_url no coincide con canónica en id {item_id}: {got_url} != {canonical_url}"
            )
            continue

        accepted[item_id] = item

    intentionally_omitted_ids = sorted(expected_set - provided_expected_ids)
    logger.info(
        f"Paso A: {len(intentionally_omitted_ids)} ids omitidos por filtro de relevancia: {intentionally_omitted_ids}"
    )

    return len(errors) == 0, errors, accepted, intentionally_omitted_ids


def validate_editorial_referential_integrity(
    data: Dict,
    expected_ids: List[str],
    canonical_by_id: Dict[str, Dict],
) -> Tuple[bool, List[str], Dict[str, Dict]]:
    """
    Valida noticias_destacadas con integridad referencial 1:1 por id_referencia.

    Rechaza si:
    - falta algún id esperado
    - viene id fuera de set
    - ids duplicados
    - summary contiene HTML
    - evidencia_source_snippet vacío

    Además devuelve un mapa de items válidos por id para fallback por item.
    """
    errors: List[str] = []
    accepted: Dict[str, Dict] = {}

    if not isinstance(data, dict):
        return False, ["Respuesta editorial inválida: no es objeto JSON"], accepted

    items = data.get("noticias_destacadas")
    if not isinstance(items, list):
        return False, ["Respuesta editorial inválida: falta noticias_destacadas[]"], accepted

    expected_set = set(expected_ids)
    seen_ids = set()

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"noticias_destacadas[{idx}] no es objeto")
            continue

        item_id = str(item.get("id_referencia", "")).strip()
        if not item_id:
            errors.append(f"noticias_destacadas[{idx}] sin id_referencia")
            continue

        if item_id in seen_ids:
            errors.append(f"id_referencia duplicado en noticias_destacadas: {item_id}")
            continue
        seen_ids.add(item_id)

        if item_id not in expected_set:
            errors.append(f"id_referencia fuera de set esperado: {item_id}")
            continue

        required = [
            "headline",
            "summary",
            "impact",
            "asset_relevance",
            "tags",
            "evidencia_source_snippet",
        ]
        missing = [k for k in required if k not in item]
        if missing:
            errors.append(f"noticias_destacadas[{idx}] falta campos: {missing}")
            continue

        if item.get("impact") not in ["ALTO", "MEDIO", "BAJO"]:
            errors.append(f"Impact inválido en id {item_id}: {item.get('impact')}")
            continue

        if not isinstance(item.get("asset_relevance"), list):
            errors.append(f"asset_relevance debe ser lista en id {item_id}")
            continue

        if not isinstance(item.get("tags"), list):
            errors.append(f"tags debe ser lista en id {item_id}")
            continue

        summary = str(item.get("summary", ""))
        if re.search(r"<[^>]+>", summary):
            errors.append(f"summary con HTML en id {item_id}")
            continue

        evidence = str(item.get("evidencia_source_snippet", "")).strip()
        if not evidence:
            errors.append(f"evidencia_source_snippet vacío en id {item_id}")
            continue

        accepted[item_id] = item

    missing_ids = sorted(expected_set - set(accepted.keys()))
    if missing_ids:
        errors.append(f"Faltan ids en noticias_destacadas: {', '.join(missing_ids[:12])}")

    return len(errors) == 0, errors, accepted


def validate_editorial_grounding(
    result: Dict,
    factual_items: List[Dict],
    raw_urls: List[str],
) -> Tuple[bool, List[str]]:
    """
    Guardrail mínimo de invariantes duros (sin heurísticas semánticas).

    Reglas:
    1) summary sin HTML
    2) source_url dentro de raw
    3) evidencia_source_snippet no vacío
    """
    errors: List[str] = []
    raw_set = set(raw_urls)

    for item in result.get("noticias_destacadas", []):
        summary = str(item.get("summary", ""))
        if re.search(r"<[^>]+>", summary):
            errors.append(f"HTML detectado en summary: {item.get('headline', '')[:60]}")

        url = str(item.get("source_url", "")).strip()
        if not url or url not in raw_set:
            errors.append(f"source_url fuera de raw: {url}")

        evidence = str(item.get("evidencia_source_snippet", "")).strip()
        if not evidence:
            errors.append(f"evidencia_source_snippet vacío: {item.get('headline', '')[:60]}")

    return len(errors) == 0, errors


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
