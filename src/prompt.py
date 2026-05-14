# Archivo: src/prompt.py
# Prompts segmentados: extracción factual (A) + edición/síntesis (B)
# Compatible con Windows 11 + Python 3.13.x

import re
from typing import Dict, List


def _strip_html(text: str) -> str:
  cleaned = re.sub(r"<[^>]+>", " ", text or "")
  cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&")
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  return cleaned


def build_factual_extraction_prompt(canonical_items: List[Dict], date: str) -> str:
  """Paso A: extracción factual estricta por id_original y source_url."""

  payload = {
    "date": date,
    "task": "Extracción factual por noticia con anclaje referencial 1:1",
    "rules": [
      "REGLA ANTI-ALUCINACIÓN: Si un dato (cifra, fecha, nombre) NO aparece textualmente en los artículos provistos, DEBES escribir 'No informado' u omitirlo.",
      "Prohibido inferir, extrapolar o usar conocimiento externo.",
      "No mezclar noticias entre sí. Cada item es independiente por id_original.",
      "Debes devolver UN objeto factual por CADA id_original de entrada.",
      "PROHIBIDO combinar dos id_original distintos en un solo objeto.",
      "evidencia_literal debe ser una cita corta textual del contenido de entrada.",
      "FILTRO DE RELEVANCIA MACRO: Antes de extraer hechos, evaluar si el artículo tiene impacto macroeconómico directo (tasas, inflación, tipo de cambio, reservas, deuda, política fiscal, commodities, mercados financieros, decisiones de bancos centrales, comercio exterior, actividad económica sectorial, política económica nacional o global). Si el artículo NO tiene ese impacto, omitirlo del output: NO incluir ese id_original en factual_items. Categorías a omitir sin excepción: salarios individuales por oficio (niñeras, cocineros, supervisores), tecnología de consumo (Wi-Fi, apps, smartphones), notas de opinión personal sin datos macro, precios de nafta al consumidor sin contexto de política energética, montos de prestaciones sociales sin análisis de impacto fiscal, entretenimiento, deportes, farándula.",
      "Si omitís un artículo por filtro de relevancia, NO lo menciones en el output. Simplemente no incluyas su id_original en factual_items.",
      "Devuelve SOLO JSON válido.",
    ],
    "output_schema": {
      "factual_items": [
        {
          "id_referencia": "id_original exacto (ej. 01)",
          "source_url": "url original",
          "hechos_clave": ["hecho textual breve"],
          "evidencia_literal": "cita literal <= 220 chars",
          "incertidumbres": ["vacío informativo o punto no confirmado"],
        }
      ]
    },
    "canonical_items": canonical_items,
  }

  import json

  return json.dumps(payload, ensure_ascii=False)


def build_editorial_prompt(
  factual_items: List[Dict],
  date: str,
  retry_instruction: str = "",
) -> str:
  """Paso B: edición de noticias por id_referencia, sin síntesis global."""
  extra_retry = f"\nINSTRUCCIÓN DE REINTENTO: {retry_instruction}\n" if retry_instruction else ""

  payload = {
    "date": date,
    "task": "Edición por item con mapeo estricto 1:1 a id_referencia",
    "rules": [
      "REGLAS NO-GO (PROHIBICIONES DURAS):",
      "1) PROHIBIDO mezclar datos de dos id_referencia distintos en un mismo objeto.",
      "2) PROHIBIDO inventar entidades, cifras, fechas o eventos no presentes en factual_items del mismo id_referencia.",
      "3) PROHIBIDO devolver menos o más items que ids de entrada.",
      "4) PROHIBIDO incluir o modificar metadatos de fuente (source_url/source_name/status/verified). Esos campos los completa el sistema.",
      "5) PROHIBIDO usar texto genérico de relleno salvo ausencia explícita de dato en factual_items.",
      "Usar EXCLUSIVAMENTE factual_items como base de contenido. No usar conocimiento externo.",
      "No menciones empresas/personas no presentes en datos de entrada del mismo id_referencia.",
      "REGLA ANTI-ALUCINACIÓN: Si falta dato textual, usar 'No informado' u omitirlo.",
      "Debes crear UN objeto en noticias_destacadas por CADA id_referencia recibido.",
      "PROHIBIDO combinar dos id_referencia distintos en un mismo objeto.",
      "Cada noticia_destacada debe mapear 1:1 a un único id_referencia.",
      "Todo claim en noticias_destacadas debe mapear a hechos_clave de su mismo id_referencia.",
      "Si no hay evidencia suficiente, mover esa afirmación a unverified_claims.",
      "No generar cadena_de_razonamiento ni resumen_ejecutivo en este paso.",
      "No incluir HTML en ningún campo de salida.",
      "Devuelve SOLO JSON válido.",
    ],
    "limits": {
      "headline_max_chars": 80,
      "summary_min_chars": 500,
      "evidencia_source_snippet_max_chars": 220,
    },
    "output_schema": {
      "noticias_destacadas": [
        {
          "id_referencia": "id_original exacto",
          "headline": "<=80 chars",
          "summary": ">=500 chars, factual, sin HTML",
          "impact": "ALTO|MEDIO|BAJO",
          "asset_relevance": ["DÓLAR", "BONOS", "ACCIONES", "TASAS", "COMMODITIES", "NO_APLICA"],
          "tags": ["Tag1", "Tag2"],
          "evidencia_source_snippet": "cita <=220 chars desde factual_items",
        }
      ],
      "unverified_claims": ["claim sin evidencia"],
      "missing_official_data": ["vacíos oficiales"],
      "sources_consulted": ["url1", "url2"],
    },
    "factual_items": factual_items,
    "acceptance_criteria": [
      "0 tags HTML en salida final.",
      "No incluir source_url/source_name/status/verified en noticias_destacadas.",
      "No entidades nuevas en cadena_de_razonamiento fuera de noticias_destacadas.",
    ],
    "retry_hint": retry_instruction,
  }

  import json

  return json.dumps(payload, ensure_ascii=False) + extra_retry


def build_redactor_prompt(
  factual_items: List[Dict],
  date: str,
  prompt_version: str = "redactor_v1",
  retry_instruction: str = "",
) -> str:
  """Agente Redactor: genera borrador editorial 1:1 por id_referencia."""
  extra_retry = f"\nINSTRUCCION DE REINTENTO: {retry_instruction}\n" if retry_instruction else ""

  payload = {
    "agent_role": "REDACTOR",
    "prompt_version": prompt_version,
    "date": date,
    "task": "Redactar una noticia por cada id_referencia usando SOLO factual_items.",
    "editorial_constitution": [
      "Idioma obligatorio: espanol.",
      "Prohibido metatexto operativo (normalizacion, sistema, fallback, IA).",
      "Fidelidad factual estricta: no inventar datos, entidades ni causalidades.",
      "Relevancia macro: priorizar impacto en tasas, dolar, bonos, acciones o commodities.",
      "Salida estrictamente estructurada y 1:1 por id_referencia.",
    ],
    "rules": [
      "Debes devolver UN objeto por cada id_referencia recibido.",
      "No mezclar dos ids en un mismo objeto.",
      "No incluir source_url/source_name/status/verified en noticias_destacadas.",
      "No incluir HTML en summary.",
      "Si falta evidencia, usar solo hechos textuales disponibles o No informado.",
      "Devuelve SOLO JSON valido.",
      "PROHIBIDO ABSOLUTO en summary: mencionar el nombre del diario, el proceso de generacion, el sistema, la IA, las fuentes de datos, instrucciones internas ni ninguna frase que describa como fue producida la nota. Ejemplos prohibidos: 'elaborado por La Gran Crisis', 'cobertura ampliada automaticamente', 'a partir de informacion publica', 'para cumplir estandar editorial', 'generado por sistema', 'feed RSS'. Si el lector puede inferir que hay un proceso automatizado detras, reescribir.",
      "Si el contenido de factual_items para un id_referencia es insuficiente para alcanzar 500 chars de summary con hechos verificables, escribir el summary con lo disponible y agregar al campo evidencia_source_snippet la nota: 'Contenido fuente limitado.' NUNCA rellenar con metatexto operativo ni frases genericas de relleno.",
      "PROHIBIDO repetir frases, oraciones o párrafos dentro de cualquier campo de salida. Si notás que estás repitiendo contenido, detené la generación y cerrá el JSON inmediatamente con los campos disponibles. Cada oración debe aportar información nueva. Si un campo summary ya alcanzó 500 chars, no agregar más texto.",
      "Devuelve SOLO JSON valido.",
    ],
    "limits": {
      "headline_max_chars": 80,
      "summary_min_chars": 500,
      "evidencia_source_snippet_max_chars": 220,
    },
    "output_schema": {
      "noticias_destacadas": [
        {
          "id_referencia": "id_original exacto",
          "headline": "<=80 chars",
          "summary": "500-700 chars exactos, sin repetición",
          "impact": "ALTO|MEDIO|BAJO",
          "asset_relevance": ["DOLAR", "BONOS", "ACCIONES", "TASAS", "COMMODITIES", "NO_APLICA"],
          "tags": ["Tag1", "Tag2"],
          "evidencia_source_snippet": "cita <=220 chars desde factual_items",
        }
      ],
      "agent_notes": {
        "quality_checks": ["lista breve opcional"],
      },
    },
    "factual_items": factual_items,
  }

  import json

  return json.dumps(payload, ensure_ascii=False) + extra_retry


def build_editor_prompt(
  factual_items: List[Dict],
  canonical_items: List[Dict],
  redactor_payload: Dict,
  date: str,
  prompt_version: str = "editor_v1",
) -> str:
  """Agente Editor: corrige y aprueba/rechaza borrador del Redactor por lote."""
  payload = {
    "agent_role": "EDITOR",
    "prompt_version": prompt_version,
    "date": date,
    "task": "Revisar borrador del Redactor y devolver contenido final publicable.",
    "rubric": [
      "factual_fidelity: 0-5",
      "spanish_quality: 0-5",
      "macro_relevance: 0-5",
      "clarity: 0-5",
      "no_operational_leak: 0-5",
    ],
    "rules": [
      "No inventar datos fuera de factual_items.",
      "Conservar mapeo 1:1 por id_referencia.",
      "No incluir metadatos de fuente en noticias_destacadas.",
      "No incluir HTML.",
      "Devuelve SOLO JSON valido.",
      "PROHIBIDO ABSOLUTO en summary: mencionar el nombre del diario, el proceso de generacion, el sistema, la IA, las fuentes de datos, instrucciones internas ni ninguna frase que describa como fue producida la nota. Ejemplos prohibidos: 'elaborado por La Gran Crisis', 'cobertura ampliada automaticamente', 'a partir de informacion publica', 'para cumplir estandar editorial', 'generado por sistema', 'feed RSS'. Si el lector puede inferir que hay un proceso automatizado detras, reescribir.",
      "Si el contenido de factual_items para un id_referencia es insuficiente para alcanzar 500 chars de summary con hechos verificables, escribir el summary con lo disponible y agregar al campo evidencia_source_snippet la nota: 'Contenido fuente limitado.' NUNCA rellenar con metatexto operativo ni frases genericas de relleno.",
      "PROHIBIDO repetir frases, oraciones o párrafos dentro de cualquier campo de salida. Si notás que estás repitiendo contenido, detené la generación y cerrá el JSON inmediatamente con los campos disponibles. Cada oración debe aportar información nueva. Si un campo summary ya alcanzó 500 chars, no agregar más texto.",
      "Devuelve SOLO JSON valido.",
    ],
    "decision_policy": [
      "Si factual_fidelity < 4 o spanish_quality < 4 o no_operational_leak < 5, corregir obligatoriamente.",
      "Si macro_relevance <= 2, mantener impacto BAJO salvo evidencia fuerte de canal macro.",
      "Si summary contiene cualquier referencia al proceso de generacion, nombre del diario como productor, o metatexto operativo: corregir obligatoriamente con factual_fidelity = 1.",
    ],
    "output_schema": {
      "decision": "ACEPTAR|CORREGIR|RECHAZAR",
      "scores": {
        "factual_fidelity": 0,
        "spanish_quality": 0,
        "macro_relevance": 0,
        "clarity": 0,
        "no_operational_leak": 0,
      },
      "editor_feedback": ["max 3 observaciones"],
      "noticias_destacadas": [
        {
          "id_referencia": "id_original exacto",
          "headline": "<=80 chars",
          "summary": "500-700 chars exactos, sin repetición",
          "impact": "ALTO|MEDIO|BAJO",
          "asset_relevance": ["DOLAR", "BONOS", "ACCIONES", "TASAS", "COMMODITIES", "NO_APLICA"],
          "tags": ["Tag1", "Tag2"],
          "evidencia_source_snippet": "cita <=220 chars",
        }
      ],
    },
    "canonical_items": canonical_items,
    "factual_items": factual_items,
    "redactor_output": redactor_payload,
  }

  import json

  return json.dumps(payload, ensure_ascii=False)


def build_judge_prompt(
  canonical_items: List[Dict],
  factual_items: List[Dict],
  final_news: List[Dict],
  date: str,
  prompt_version: str = "judge_v1",
) -> str:
  """Agente Juez: QA editorial del lote final para aprendizaje diario."""
  payload = {
    "agent_role": "JUEZ",
    "prompt_version": prompt_version,
    "date": date,
    "task": "Evaluar calidad editorial/factual del lote final y devolver scorecards.",
    "criteria_weights": {
      "factual_fidelity": 35,
      "spanish_quality": 25,
      "macro_relevance": 25,
      "clarity_non_repetition": 15,
    },
    "rules": [
      "Evaluar solo contra canonical_items y factual_items provistos.",
      "No inferir hechos externos.",
      "Marcar errores criticos: fuga_operativa, factual_critical, language_leak, off_topic.",
      "Devuelve SOLO JSON valido.",
    ],
    "output_schema": {
      "quality_gate": "PASS|WARN|FAIL",
      "scores": {
        "factual_fidelity": 0,
        "spanish_quality": 0,
        "macro_relevance": 0,
        "clarity_non_repetition": 0,
        "weighted_total": 0,
      },
      "critical_errors": ["lista breve"],
      "priority_fixes": ["max 5"],
      "sample_findings": [
        {
          "id_referencia": "01",
          "severity": "ALTA|MEDIA|BAJA",
          "issue": "descripcion breve",
        }
      ],
    },
    "canonical_items": canonical_items,
    "factual_items": factual_items,
    "noticias_destacadas": final_news,
  }

  import json

  return json.dumps(payload, ensure_ascii=False)


def build_editorial_autocorrect_prompt(
  factual_items: List[Dict],
  editorial_result: Dict,
  invalid_ids: List[str],
  date: str,
) -> str:
  """Autocorrección breve de Paso B: corrige solo IDs inválidos con reglas no-go."""
  payload = {
    "date": date,
    "task": "Autocorrección breve de salida editorial por incumplimientos referenciales",
    "rules": [
      "REGLAS NO-GO (PROHIBICIONES DURAS):",
      "1) PROHIBIDO mezclar id_referencia.",
      "2) PROHIBIDO inventar entidades/cifras/eventos fuera del factual del mismo id.",
      "3) PROHIBIDO incluir o modificar metadatos de fuente (source_url/source_name/status/verified).",
      "4) Debes devolver un objeto para cada id_referencia inválido listado.",
      "5) No incluir HTML.",
      "PROHIBIDO repetir frases, oraciones o párrafos dentro de cualquier campo de salida. Si notás que estás repitiendo contenido, detené la generación y cerrá el JSON inmediatamente con los campos disponibles. Cada oración debe aportar información nueva. Si un campo summary ya alcanzó 500 chars, no agregar más texto.",
      "Devuelve SOLO JSON válido.",
    ],
    "invalid_ids": invalid_ids,
    "factual_items": factual_items,
    "editorial_result_actual": editorial_result,
    "output_schema": {
      "noticias_destacadas": [
        {
          "id_referencia": "id inválido corregido",
          "headline": "<=80 chars",
          "summary": "500-700 chars exactos, sin repetición",
          "impact": "ALTO|MEDIO|BAJO",
          "asset_relevance": ["DÓLAR", "BONOS", "ACCIONES", "TASAS", "COMMODITIES", "NO_APLICA"],
          "tags": ["Tag1", "Tag2"],
          "evidencia_source_snippet": "cita <=220 chars",
        }
      ]
    },
  }

  import json

  return json.dumps(payload, ensure_ascii=False)


def build_global_synthesis_prompt(
  noticias_destacadas: List[Dict],
  date: str,
  contexto_base: str,
  resumen_ayer: str,
  retry_instruction: str = "",
) -> str:
  """Paso D: síntesis global separada usando SOLO noticias ya validadas."""
  memoria_ayer = resumen_ayer if resumen_ayer else "Primer día de publicación."
  extra_retry = f"\nINSTRUCCIÓN DE REINTENTO: {retry_instruction}\n" if retry_instruction else ""

  payload = {
    "date": date,
    "task": "Sintetizar narrativa macro del día a partir de noticias_destacadas validadas",
    "rules": [
      "Usar SOLO noticias_destacadas provistas. Prohibido usar raw original o conocimiento externo.",
      "No introducir entidades nuevas que no estén presentes en noticias_destacadas.",
      "No incluir HTML.",
      "GUARD DE CONTENIDO INSUFICIENTE: Si noticias_destacadas tiene menos de 5 items, O si todos los items tienen impact=BAJO y asset_relevance contiene solo NO_APLICA, NO elaborar análisis macro con conocimiento externo. En ese caso, resumen_ejecutivo debe ser exactamente: 'Jornada con escasa actividad informativa. No se registraron eventos de alto impacto macroeconómico verificables en las fuentes disponibles.' y cadena_de_razonamiento debe ser: 'Cobertura insuficiente para síntesis.' PROHIBIDO usar conocimiento externo para compensar la falta de noticias.",
      "PROHIBIDO repetir frases, oraciones o párrafos dentro de\n       cadena_de_razonamiento o resumen_ejecutivo. Si notás que estás\n       repitiendo contenido, detené la generación y cerrá el JSON.\n       Cada oración debe aportar información nueva. Máximo 3 oraciones\n       por idea.",
      "Devuelve SOLO JSON válido.",
    ],
    "contexto_macro_base": contexto_base,
    "memoria_ayer": memoria_ayer,
    "output_schema": {
      "cadena_de_razonamiento": "<=600 chars (reducido de 1000)",
      "resumen_ejecutivo": "600-900 chars (reducido de 800-1200)",
    },
    "noticias_destacadas": noticias_destacadas,
  }

  import json

  return json.dumps(payload, ensure_ascii=False) + extra_retry


def build_gemini_prompt(
  articles: List[Dict],
  date: str,
  contexto_base: str,
  resumen_ayer: str,
) -> str:
  """Compatibilidad retro: mantiene API anterior usando factual determinista básico."""
  factual_items = []
  for idx, article in enumerate(articles, start=1):
    content = _strip_html(str(article.get("content", "")))
    title = _strip_html(str(article.get("title", "")))
    snippet = (content or title)[:220]
    factual_items.append(
      {
        "id_referencia": f"{idx:02d}",
        "source_url": article.get("url", ""),
        "hechos_clave": [title[:180]] if title else ["No informado"],
        "evidencia_literal": snippet if snippet else "No informado",
        "incertidumbres": [] if snippet else ["No informado"],
      }
    )

  return build_editorial_prompt(factual_items, date)

