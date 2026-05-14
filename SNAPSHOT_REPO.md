## RESUMEN EJECUTIVO
1. La Gran Crisis es un pipeline local automatizado que ingesta RSS macro/finanzas/política, depura y publica un diario estático diario.
2. Stack principal: Python 3.13, feedparser/requests, RapidFuzz, Jinja2, Gemini (google-genai) con fallback de modelo y parsing robusto de JSON.
3. El output público se publica en docs/YYYY/MM/DD/index.html + data.json y se sirve como sitio estático (GitHub Pages).
4. La operación está programada por Windows Task Scheduler: acumulado intradía horario y cierre diario único a las 05:00 ART.
5. El sistema incluye validaciones editoriales/factuales, artefactos de observabilidad y mecanismos de fallback por etapa para mantener continuidad de publicación.

## FLUJO PRINCIPAL COMPLETO
```text
[Trigger Scheduler: LGC-IntradayAccumulate]
        |
        v
[main.py: main --accumulate]
        |
        v
[main.py: load_sources + fetch_rss.py: fetch_all_feeds]
        |
        v
[main.py: filter_articles_by_compliance]
        |
        v
[dedupe.py: deduplicate_articles]
        |
        v
[main.py: append_intraday_capture -> raw/YYYY-MM-DD/intraday_accumulated.json]

[Trigger Scheduler: LGC-DailyClose]
        |
        v
[main.py: main --close + _acquire_mode_lock]
        |
        v
[main.py: load_accumulated_articles_for_close]
        |
        v
[run_pipeline - Paso 1/2: load_sources + load_context_and_memory]
        |
        v
[Paso 3/4/5: fetch/preloaded -> compliance -> dedupe -> tag_sources -> classify_and_rank]
        |
        v
[Paso 6A factual: prompt.py build_factual_extraction_prompt -> llm.py call_gemini_with_retry -> validator.py validate_factual_extraction_by_id]
        |
        v
[Paso 6B editorial por chunks: prompt.py build_redactor_prompt/build_editor_prompt + autocorrect + validator.py referential integrity]
        |
        v
[Paso D síntesis global: prompt.py build_global_synthesis_prompt -> llm.py]
        |
        v
[Paso E juez: prompt.py build_judge_prompt -> llm.py]
        |
        v
[Guardrails finales en main.py: grounding, cobertura total, español, atribución, saneo]
        |
        v
[Persistencia: data.json + pipeline_metrics.json + judge_report.json + missing_data.json]
        |
        v
[builder.py: render_daily_page + update_index_page]
        |
        v
[Publicación estática en docs/]
        |
        v
[Post-close observabilidad: operational_review.py, daily_health_check.py, intraday_guard_check.py, scheduler_postclose_audit.py]
        |
        v
[Git commit/push y despliegue Pages: paso operativo externo, no automatizado en el repo]
```

## MÓDULOS
| Archivo | Responsabilidad | Inputs | Outputs | Dependencias clave |
|---|---|---|---|---|
| src/main.py | Orquestador end-to-end de acumulado y cierre, validaciones, métricas y publicación | args CLI, RSS/snapshot, contexto base, memoria previa, variables de entorno | raw/*.json, docs/YYYY/MM/DD/{data.json,index.html}, logs, métricas | fetch_rss, classifier, dedupe, validator, prompt, llm, builder |
| src/llm.py | Cliente Gemini, retries, fallback de modelo, reparación JSON, métricas runtime, traducción ES | prompt JSON string, GEMINI_API_KEY | dict parseado por etapa, debug_response.txt, respuestas fallidas en raw/YYYY-MM-DD/debug | google-genai, json, logging |
| src/prompt.py | Contratos de prompts (Paso A, Redactor, Editor, Juez, autocorrect, síntesis global) | canonical_items, factual_items, outputs previos, contexto | payload JSON serializado por etapa | re, json |
| src/classifier.py | Filtro de ruido y ranking estable con diversidad de fuente/tags | artículos etiquetados | lista ordenada de artículos no-ruido | logging, reglas de keywords, score por tier |
| src/dedupe.py | Deduplicación por URL exacta y similitud de título | artículos crudos | artículos únicos | RapidFuzz |
| src/validator.py | Tagging de fuente y validación de estructura/referencial/grounding | output LLM por etapa + expected ids/urls | estado OK/errores + items válidos + intentionally_omitted_ids | regex, reglas de schema y dominios |
| src/builder.py | Render HTML diario, índice histórico y página fallback | data dict final + output path | docs/YYYY/MM/DD/index.html, docs/index.html | Jinja2, templates/diario.html.j2 |
| src/fetch_rss.py | Descarga y normalización RSS con ventana temporal y parse de fechas | fuentes (name/url/category/tier), hours_back, max_entries | artículos normalizados para pipeline | feedparser, requests, datetime/dateutil fallback |
| src/backfill_april_2026.py | Backfill histórico abril 2026 reusando run_pipeline | sources.json + RSS históricos | re-publicación diaria histórica en raw/docs | feedparser, requests, src.main |
| src/__init__.py | Marcador de paquete | N/A | N/A | N/A |

## ESTRUCTURA DE DATOS
Esquema de salida principal de docs/YYYY/MM/DD/data.json:

```yaml
date: string (YYYY-MM-DD)
cadena_de_razonamiento: string
resumen_ejecutivo: string
noticias_destacadas:
  - id_referencia: string (ej. "01")
    headline: string (<=80 chars objetivo)
    summary: string (>=500 chars)
    impact: enum [ALTO, MEDIO, BAJO]
    asset_relevance: array[string]  # típicos: DOLAR/BONOS/ACCIONES/TASAS/COMMODITIES/NO_APLICA
    tags: array[string]
    is_argentina: boolean
    source_name: string
    source_url: string (URL absoluta)
    source_datetime: string (ISO8601 esperado)
    status: enum [OFICIAL, VALIDADO, SIN CONFIRMAR]  # validator acepta también SIN_CONFIRMAR
    verified: boolean  # true cuando status in [OFICIAL, VALIDADO]
    evidencia_source_snippet: string (<=220 chars objetivo)
unverified_claims: array[string]
missing_official_data: array[string]
sources_consulted: array[string]  # en builder se filtra a URLs presentes en noticias_destacadas.source_url
# campos opcionales de fallback/errores de pipeline
_fallback: boolean (opcional)
_error: string (opcional)
_raw_count: number (opcional)
```

## SISTEMA DE PROMPTS LLM
- Agente A (Extracción factual)
  - Función: extraer hechos por id_referencia y filtrar artículos sin relevancia macro.
  - Inputs: canonical_items, date.
  - Outputs: factual_items[] con id_referencia, source_url, hechos_clave, evidencia_literal, incertidumbres.
  - Builder: build_factual_extraction_prompt().

- Agente Redactor (Paso B1)
  - Función: generar borrador editorial 1:1 por id_referencia desde factual_items.
  - Inputs: factual_items, date, prompt_version.
  - Outputs: noticias_destacadas[] + agent_notes.
  - Builder: build_redactor_prompt().

- Agente Editor (Paso B2)
  - Función: corregir/validar salida del Redactor con rúbrica factual-lingüística y anti-fugas operativas.
  - Inputs: factual_items, canonical_items, redactor_output, date.
  - Outputs: decision, scores, editor_feedback, noticias_destacadas[] finalizadas.
  - Builder: build_editor_prompt().

- Agente Juez (Paso E)
  - Función: QA editorial/factual del lote final para scorecards diarios.
  - Inputs: canonical_items, factual_items, noticias_destacadas finales, date.
  - Outputs: quality_gate, scores ponderados, critical_errors, priority_fixes.
  - Builder: build_judge_prompt().

- Agente D (Síntesis global)
  - Función: construir cadena_de_razonamiento y resumen_ejecutivo solo desde noticias validadas.
  - Inputs: noticias_destacadas, contexto_base, memoria de ayer, date.
  - Outputs: cadena_de_razonamiento, resumen_ejecutivo.
  - Builder: build_global_synthesis_prompt().

## FUENTES RSS
| Nombre | URL | Categoría | Tier (oficial/t1) |
|---|---|---|---|
| BCRA | https://www.argentina.gob.ar/rss.xml | macro_argentina | oficial |
| INDEC | https://www.indec.gob.ar/rss/ultimas_noticias.xml | macro_argentina | oficial |
| Boletín Oficial | https://www.boletinoficial.gob.ar/rss/home | politica_argentina | oficial |
| Casa Rosada | https://www.argentina.gob.ar/rss.xml | politica_argentina | oficial |
| Ministerio de Economía | https://www.argentina.gob.ar/rss.xml | macro_argentina | oficial |
| Ámbito Financiero | https://www.ambito.com/rss/economia.xml | macro_argentina | t1 |
| El Cronista | https://www.cronista.com/files/rss/finanzas.xml | macro_argentina | t1 |
| La Nación Economía | https://www.lanacion.com.ar/arc/outboundfeeds/rss/category/economia/?outputType=xml | macro_argentina | t1 |
| Infobae Economía | https://www.infobae.com/arc/outboundfeeds/rss/category/economia/?outputType=xml | macro_argentina | t1 |
| Perfil Economía | https://www.perfil.com/feed/economia | politica_argentina | t1 |
| CIPPEC | https://www.cippec.org/feed/ | politica_argentina | t1 |
| FIEL | https://www.fiel.org/rss_feed | macro_argentina | t1 |
| Federal Reserve | https://www.federalreserve.gov/feeds/press_all.xml | internacional | oficial |
| FMI | https://www.imf.org/en/News/rss?language=eng | internacional | oficial |
| Banco Central Europeo | https://www.ecb.europa.eu/rss/press.html | internacional | oficial |
| SEC Press Releases | https://www.sec.gov/news/pressreleases.rss | internacional | oficial |
| SEC Speeches and Statements | https://www.sec.gov/news/speeches-statements.rss | internacional | oficial |
| SEC Litigation Releases | https://www.sec.gov/enforcement-litigation/litigation-releases/rss | internacional | oficial |
| US BEA News | https://apps.bea.gov/rss/rss.xml | internacional | oficial |
| Bank of England News | https://www.bankofengland.co.uk/rss/news | internacional | oficial |
| Bank of England Statistics | https://www.bankofengland.co.uk/rss/statistics | internacional | oficial |
| FCA News | https://www.fca.org.uk/news/rss.xml | internacional | oficial |
| CEPR | https://cepr.org/rss.xml | economica_mundo | t1 |
| PIIE | https://www.piie.com/rss/update.xml | economica_mundo | t1 |

## OBSERVABILIDAD
- logs/digest.log
  - Qué guarda: logging general del orquestador.
  - Frecuencia: cada ejecución de main.py.

- logs/close.log e logs/intraday.log
  - Qué guarda: eventos por modo (logger por lock de modo).
  - Frecuencia: close diario e intraday horario.

- raw/YYYY-MM-DD/raw.json
  - Qué guarda: snapshot de artículos descargados post-compliance.
  - Frecuencia: en cada cierre.

- raw/YYYY-MM-DD/intraday_accumulated.json
  - Qué guarda: acumulado idempotente intradía (capturas, first/last capture, articles).
  - Frecuencia: cada ejecución de --accumulate (horaria).

- raw/YYYY-MM-DD/pipeline_metrics.json
  - Qué guarda: KPIs operativos (cobertura, fallbacks, parse metrics, macro_filtered_ids, etc.).
  - Frecuencia: cierre diario.

- raw/YYYY-MM-DD/judge_report.json
  - Qué guarda: evaluación del agente Juez.
  - Frecuencia: cierre diario (cuando no es mock).

- raw/YYYY-MM-DD/missing_data.json
  - Qué guarda: missing_official_data para revisión.
  - Frecuencia: cierre diario si hay faltantes.

- raw/YYYY-MM-DD/daily_review.json
  - Qué guarda: checklist operativo consolidado (10 ítems) y resumen de estado.
  - Frecuencia: tarea diaria LGC-Review.

- raw/YYYY-MM-DD/debug/debug_response.txt
  - Qué guarda: última respuesta cruda LLM.
  - Frecuencia: en cada llamada LLM.

- raw/YYYY-MM-DD/debug/debug_response_failed_*.txt
  - Qué guarda: respuestas no parseables por modelo/intento/etapa.
  - Frecuencia: cuando falla parseo.

- logs/health/health_check_YYYY-MM-DD.json
  - Qué guarda: presencia/ausencia de artefactos críticos del día.
  - Frecuencia: tarea diaria LGC-HealthCheck.

- logs/health/intraday_guard_YYYY-MM-DD_HHMMSS.json
  - Qué guarda: frescura de intradía y códigos de rechazo del Scheduler.
  - Frecuencia: tarea horaria LGC-IntradayGuard.

- logs/health/scheduler_audit_YYYY-MM-DD.json
  - Qué guarda: auditoría post-cierre de orden/estado de tareas críticas.
  - Frecuencia: tarea diaria post-cierre.

- logs/health/alerts.log
  - Qué guarda: alertas persistentes de health/intraday_guard/scheduler_audit.
  - Frecuencia: append cuando hay ALERT.

- docs/HOJA_OPERATIVA_AGENTES.md
  - Qué guarda: estado operativo y checklist actualizado automáticamente.
  - Frecuencia: tarea diaria LGC-UpdateHoja.

## PUNTOS DE FALLO Y FALLBACKS
| Fallo posible | Módulo afectado | Comportamiento de fallback | Impacto en el usuario |
|---|---|---|---|
| RSS inaccesible/parcial | fetch_rss.py, main.py | continúa con fuentes disponibles; si queda vacío, fallback_response | puede bajar cobertura temática del día |
| Error de parseo JSON en LLM | llm.py | saneo + reparación JSON automática + retries + fallback de modelo | mayor latencia; normalmente sin corte visible |
| Falla total de Gemini | llm.py | _build_fallback_from_error y/o fallback_response en pipeline | publicación con contenido degradado, pero no queda vacío |
| Inconsistencia factual por id (Paso A) | validator.py + main.py | fallback factual determinístico por id (excepto macro_filtered_ids) | noticia potencialmente menos rica, pero publicada |
| Falta/rotura editorial por chunk (Paso B) | main.py + validator.py | autocorrección por invalid_ids y fallback por item en ensamblado | puede aumentar fallback_items_count |
| Síntesis global incompleta (Paso D) | main.py | reintento de síntesis; si falla, síntesis determinística local | resumen ejecutivo menos elaborado |
| Error crítico de pipeline | main.py, builder.py | render_fallback_page y health check KO | se publica página de contingencia |
| Solapamiento o lock stale | main.py | _acquire_mode_lock con limpieza stale (4h o cambio de día) | evita corridas concurrentes, posible delay puntual |
| Encoding cp1252 en consola Windows | main.py | stdout/stderr reconfigure(errors="replace") | logs sin crash, algunos símbolos reemplazados |

## DEUDA TÉCNICA CONOCIDA
- Orquestación CI/CD en GitHub Actions aún no implementada; .github/workflows no contiene daily.yml (solo README de estrategia local).
- Dos fuentes argentinas siguen limitadas por formato no-RSS usable: INDEC y Boletín Oficial aparecen como pendientes en el contexto operativo.
- La fase de promoción a Fase 3 (Actions) sigue pendiente según Documento_de_contexto_LGC.txt.
- Hard gates semanales de la hoja operativa figuran en estado PENDIENTE (quality gate sostenido, cobertura y tendencias).
- En src/fetch_rss.py persiste comentario de placeholder/testing heredado, señal de deuda documental respecto al comportamiento real en producción.
- En src/prompt.py permanece build_gemini_prompt como compatibilidad retro, coexistiendo con la arquitectura por agentes segmentados.

## PRÓXIMO HITO
<proximo_hito>
  - Completar 3 días consecutivos de cierre local exitoso post-hardening.
  - Validar estabilidad de:
    - locks
    - scheduler
    - health_check
    - intraday_guard
  - Recién después activar GitHub Actions con cron 05:00 ART + test de summaries obligatorio.
</proximo_hito>
