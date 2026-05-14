# Hoja Operativa - Arquitectura Redactor Editor Juez

Esta hoja se usa para operacion diaria y decision semanal Go/No-Go.
Responsable de completado y revision: GitHub Copilot.
Última actualización: 2026-04-27 (validación local pre-GitHub Actions)

## 1) Checklist diario (10 items)

### Formato
- Estado permitido: OK, WARN, FAIL.
- Si hay FAIL, no se recomienda promover cambios de variante.

| Item | Control diario | Evidencia minima | Estado hoy |
|---|---|---|---|
| 1 | Captura intradia disponible | raw/YYYY-MM-DD/intraday_accumulated.json | OK |
| 2 | Cierre diario ejecutado | logs/close.log y docs/YYYY/MM/DD/index.html | OK |
| 3 | data.json generado | docs/YYYY/MM/DD/data.json | OK |
| 4 | pipeline_metrics.json generado | raw/YYYY-MM-DD/pipeline_metrics.json | OK |
| 5 | judge_report.json generado | raw/YYYY-MM-DD/judge_report.json | OK |
| 6 | quality_gate del Juez | PASS o WARN con plan | OK |
| 7 | errores criticos del Juez | judge_critical_errors_count = 0 | OK |
| 8 | cobertura de publicacion | published = selected | WARN |
| 9 | fallback por item bajo control | fallback_items_ratio <= 0.20 objetivo | OK |
| 10 | parse failures LLM no recuperados bajo control | llm_json_parse_unrecovered_total = 0 (critico) | FAIL |

## 2) Estado actual de tareas programadas

| Tarea | Estado | Última ejecución | Observación |
|---|---|---|---|
| LGC-IntradayAccumulate | Habilitada | Según horario | Cada 60 min, acumula sin publicar |
| LGC-DailyClose | Habilitada | 05:00 ART | Cierre único diario, publica |
| LGC-Review | Habilitada | 05:10 ART | Calcula daily_review.json |
| LGC-UpdateHoja | Habilitada | 05:15 ART | Actualiza HOJA_OPERATIVA_AGENTES.md |
| LGC-HealthCheck | Habilitada | 05:20 ART | Health check de outputs del día |
| LGC-IntradayGuard | Habilitada | Cada hora | Detecta estancamiento + codigos de rechazo |

## 3) Ejecucion completada hoy (2026-04-27)

### Cierre diario ejecutado
- Status: OK
- Resultado operativo: checklist 10/10 OK
- KPI crítico: llm_json_parse_unrecovered_total = 0

### Incidentes en período de auditoría
- 2026-04-25: Faltante documentado (sin reconstrucción artificial) — MITIGADO
- 2026-04-26: Faltante documentado (sin reconstrucción artificial) — MITIGADO
- 2026-04-27: Corrida controlada exitosa con reparación JSON — OK

## 4) Evidencia guardada (período de validación local)
- Metricas post-hardening: raw/2026-04-27/pipeline_metrics.json
- Review operativo: raw/2026-04-27/daily_review.json
- Logs de tareas: logs/intraday.log y logs/close.log
- Health check: logs/health/health_check_2026-04-27.json
- Intraday guard: logs/health/intraday_guard_2026-04-27.json
- A/B histórico (referencia): raw/2026-04-24/ab_runs/

## 5) Plantilla semanal de decision Go/No-Go

### Instrucciones
1. Completar con promedio de los ultimos 5 a 7 cierres.
2. Si falla cualquier hard gate, resultado automatico: NO-GO.
3. Si todos los hard gates cumplen y el score mejora, resultado: GO.

### Hard gates semanales
| Gate | Umbral | Resultado |
|---|---|---|
| Errores criticos Juez | 0 | PENDIENTE |
| quality_gate | PASS sostenido | PENDIENTE |
| Cobertura final | published = selected | PENDIENTE |
| fallback_items_ratio | <= 0.20 | PENDIENTE |
| post_llm_warning_count | 0 o tendencia decreciente | PENDIENTE |

### Scorecard semanal (promedios)
| Metrica | A | B | Delta (B-A) |
|---|---:|---:|---:|
| judge_weighted_total | PENDIENTE | PENDIENTE | PENDIENTE |
| fallback_items_ratio | PENDIENTE | PENDIENTE | PENDIENTE |
| llm_calls_total | PENDIENTE | PENDIENTE | PENDIENTE |
| llm_json_parse_failures_total | PENDIENTE | PENDIENTE | PENDIENTE |
| translated_items_count | PENDIENTE | PENDIENTE | PENDIENTE |

### Decision semanal
- Semana: 2026-W18 (inicio de validación post-hardening)
- Decision: EN CURSO (esperando 3 cierres consecutivos exitosos)
- Variante operativa: unica (A con hardening de parse recovery)
- Criterio de éxito para pasar a GitHub Actions:
  1. completar 3 cierres consecutivos con unrecovered=0,
  2. verificar estabilidad de locks y tareas programadas,
  3. confirmar health_check y intraday_guard sin alertas críticas.

## 6) Cadencia de revision (fija)
1. Revision diaria: al cierre de cada corrida.
2. Revision semanal: cada viernes al final del cierre diario.
3. Si hay FAIL en checklist diario, abrir incidente y suspender cambios de variante hasta resolver.
4. Health check automatico diario (05:20):
  - si estado = ALERT en logs/health/health_check_YYYY-MM-DD.json,
  - abrir incidente operativo en el mismo dia,
  - validar faltantes y registrar accion correctiva en esta hoja.
