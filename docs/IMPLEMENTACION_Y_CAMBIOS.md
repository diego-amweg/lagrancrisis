# Implementacion y Cambios del Pipeline

Este documento es la bitacora operativa del repositorio.
Regla de trabajo: cada cambio funcional o de arquitectura debe agregar una entrada nueva en este archivo.

## Estado actual
- Repo operativo en Windows con tareas locales programadas.
- Flujo diario automatizado: captura intradia + cierre diario + publicacion.
- Pipeline LLM segmentado y ahora orquestado por agentes logicos (Redactor, Editor, Juez).

## Arquitectura vigente (resumen)
1. Ingesta RSS y deduplicacion.
2. Etiquetado de fuentes y ranking.
3. Paso A factual (anclado por id_referencia).
4. Paso B Redactor por chunk (borrador estructurado 1:1).
5. Paso B2 Editor por chunk (correccion y decision editorial 1:1).
6. Paso C autocorreccion puntual si quedan ids invalidos.
7. Ensamblado determinista y cobertura completa.
8. Paso D sintesis global.
9. Paso E Juez (scorecards de calidad editorial/factual).
10. Guardado de metricas, data.json, judge_report.json y HTML final.

## Historial de cambios

### 2026-04-16
- Hardening del flujo segmentado (Paso A factual + Paso B editorial + validaciones de grounding).
- Fallback deterministico por item para evitar huecos de cobertura.

### 2026-04-17
- Hidratacion canonica de metadatos de fuente para evitar drift de source_url/source_name.
- Endurecimiento del parser JSON en llm.py y guardado de respuestas fallidas por etapa.

### 2026-04-23 (bloque estabilidad)
- Correccion del setup de tareas locales para forzar working directory de repo.
- Validacion operativa de tareas intradia/cierre con ejecucion automatica estable.

### 2026-04-23 (bloque calidad editorial)
- Chunking editorial activo en cierre diario.
- Reintentos reforzados de autocorreccion cuando hay muchos ids invalidos.
- Metricas ampliadas de corrida (fallback por item, warnings, traducciones, chunk stats).

### 2026-04-23 (bloque agentes logicos)
- Nuevos contratos de prompt por rol en src/prompt.py:
  - build_redactor_prompt
  - build_editor_prompt
  - build_judge_prompt
- Integracion en src/main.py:
  - Redactor por chunk como borrador base.
  - Editor por chunk como segunda pasada de calidad.
  - Juez al final de la corrida para scorecard global.
- Nuevas metricas persistidas en pipeline_metrics.json:
  - prompt_redactor_version
  - prompt_editor_version
  - prompt_judge_version
  - editor_agent_runs
  - editor_agent_failed_runs
  - judge_quality_gate
  - judge_weighted_total
  - judge_critical_errors_count
- Nuevo artefacto diario:
  - raw/YYYY-MM-DD/judge_report.json

### 2026-04-23 (bloque documentacion y orden)
- README actualizado con estado operativo real y enlaces a documentacion viva.
- Creado docs/LIMPIEZA_REPO_PROPUESTA.md con plan de orden y mantenibilidad.
- Reparado .gitignore (estaba en formato markdown no valido) y agregado ignore para debug_response_failed_*.txt.

### 2026-04-24 (bloque A/B controlado + operacion)
- Ejecutadas corridas reales A/B con Juez activado para ambas variantes en la misma jornada.
- Artefactos guardados en raw/2026-04-24/ab_runs/:
  - A_pipeline_metrics.json
  - B_pipeline_metrics.json
  - A_judge_report.json
  - B_judge_report.json
  - AB_COMPARATIVO_2026-04-24.md
- Creada hoja operativa permanente para uso diario/semanal:
  - docs/HOJA_OPERATIVA_AGENTES.md
  - Incluye checklist diario de 10 items y plantilla semanal Go/No-Go.

### 2026-04-24 (bloque limpieza repo)
- **Implementada limpieza de repositorio** siguiendo propuesta en docs/LIMPIEZA_REPO_PROPUESTA.md:
  1. ✅ Debug artifact scoping: Modificado src/llm.py para enrutar artifacts a `raw/YYYY-MM-DD/debug/` via `_resolve_debug_dir()`. Legacy root artifacts movidos a `raw/YYYY-MM-DD/debug/legacy_root/`.
  2. ✅ Test script relocation: Movidos 4 scripts manuales (test_deps.py, test_gemini.py, test_gemini_minimal.py, test_summary_range.py) de src/ a scripts/dev/.
  3. ✅ Log retention policy: Agregada función `cleanup_old_logs(retention_days=30)` en src/main.py; elimina logs > 30 días de age.
  4. ✅ Weekly metrics aggregation: Agregada función `update_weekly_summary()` para agregación semanal en logs/weekly_summary.json keyed por ISO week.
  5. ✅ .github/workflows documentation: Creado README explicando que automation usa Windows Task Scheduler (no GitHub Actions).
- Validación: Pipeline ejecutado en mock mode sin errores de sintaxis ni runtime exceptions.
- Resultado: Repo más limpio, scoped directories, mejores políticas de retención de artefactos.

### 2026-04-27 (bloque continuidad operativa)
- Auditoria raw vs docs (24-27/04) completada.
- Incidente confirmado para 25/04 y 26/04: faltaron cierres reales por falla de tareas programadas.
- Mitigacion aplicada:
  - tareas recreadas (Intraday, DailyClose, Review, UpdateHoja),
  - wrappers .bat para robustez de ejecucion,
  - nueva tarea LGC-HealthCheck (05:20) con alertas persistentes en logs/health/alerts.log,
  - nueva tarea LGC-IntradayGuard (horaria) para detectar estancamiento intradia y codigos de rechazo del scheduler.
- Guardias operativos incorporados:
  - scripts/daily_health_check.py valida outputs diarios esperados,
  - scripts/intraday_guard_check.py controla frescura de captura (last_capture_at) y codigos de scheduler (ej: 0x800710E0).
- KPI operativo de parse LLM actualizado (severidad real):
  - llm_json_parse_failures_total queda como metrica observacional,
  - llm_json_parse_unrecovered_total pasa a criterio critico,
  - se agregan llm_json_repair_attempts_total y llm_json_repair_success_total para trazabilidad de recuperacion.
- operational_review.py y HOJA_OPERATIVA_AGENTES.md actualizados para evaluar como FAIL solo parseos no recuperados.
- Validacion controlada post-hardening:
  - corrida close real con reparacion JSON exitosa,
  - daily_review en estado 10 OK, 0 WARN, 0 FAIL.
- Decisión editorial/operativa:
  - 25/04 y 26/04 se mantienen como faltante documentado (no reconstruccion artificial),
  - 24/04 y 27/04 quedan validados como publicaciones correctas.

### 2026-04-27 (bloque continuidad documental)
- builder/index actualizado para reflejar estado missing_documented en el historial.
- Publicados placeholders de continuidad para 25/04 y 26/04 en docs/2026/04/ con transparencia editorial.

## Convencion para futuras actualizaciones
Al hacer un cambio, agregar una entrada con:
- Fecha
- Problema/objetivo
- Archivos tocados
- Cambio aplicado
- Resultado esperado
- Riesgo residual

## Referencias internas
- Orquestador principal: src/main.py
- Contratos de prompt: src/prompt.py
- Runtime LLM y retries: src/llm.py
- Validadores: src/validator.py
- Setup de tareas Windows: scripts/setup_local_tasks.ps1
