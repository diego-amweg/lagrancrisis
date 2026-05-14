# La Gran Crisis
> Los datos no entran en panico.

Resumen macroeconomico diario, verificado y sin ruido.

## Estado actual (2026-04-27)
- Operacion automatizada local en Windows Task Scheduler.
- Pipeline editorial activo con orquestacion por agentes logicos:
  - Redactor
  - Editor
  - Juez
- Estrategia vigente: acumulado intradia (--accumulate) + cierre unico diario (--close).
- Publicacion automatica en docs/YYYY/MM/DD/ con indice historico.
- Etapa del proyecto: validacion final pre-GitHub Actions.

## Operacion local vigente

### Tareas programadas
- LGC-IntradayAccumulate
- LGC-DailyClose
- LGC-Review
- LGC-UpdateHoja
- LGC-HealthCheck
- LGC-IntradayGuard

### Monitoreo y guardias
- Health check diario de outputs esperados.
- Guardia horaria intradia (frescura de captura y codigos de rechazo del scheduler).
- Alertas persistentes en logs/health/alerts.log.

## Criterios tecnicos de calidad

### KPI de parseo LLM
- Critico: llm_json_parse_unrecovered_total (debe ser 0).
- Observacional: llm_json_parse_failures_total.
- Trazabilidad: llm_json_repair_attempts_total y llm_json_repair_success_total.

### Politicas editoriales activas
- Cobertura forzada del universo no-ruido.
- Espanol forzado en salida final.
- Orden determinista de publicacion: Argentina primero, luego internacional.
- Summary por item entre 500 y 1000 caracteres.

## Continuidad documental
- Auditoria raw vs docs (24-27/04) completada.
- 24/04 y 27/04 validados como corridas correctas.
- 25/04 y 26/04 publicados como faltante documentado (sin reconstruccion artificial).

## Proximo hito
- Completar 3 cierres diarios consecutivos exitosos post-hardening.
- Criterio de exito (Fase 2 → Fase 3):
  - llm_json_parse_unrecovered_total = 0 en todos los 3 días,
  - checklist diario 10/10 OK en todos los 3 días,
  - health_check y intraday_guard sin alertas críticas,
  - locks y tareas estables sin interferencias.
- Recien despues activar GitHub Actions con:
  - cron 05:00 ART,
  - GEMINI_API_KEY en secrets,
  - test obligatorio de rango de summaries en CI.

## Comandos basicos locales

### Preparar entorno
```powershell
python -m venv venv
.\venv\Scripts\Activate
pip install -r requirements.txt
```

### Ejecutar pipeline local
```powershell
python .\src\main.py --accumulate
python .\src\main.py --close
```

### Ejecutar revision operativa
```powershell
python .\scripts\operational_review.py
python .\scripts\update_hoja_operativa.py
```

## Documentacion viva
- Bitacora tecnica: docs/IMPLEMENTACION_Y_CAMBIOS.md
- Hoja operativa: docs/HOJA_OPERATIVA_AGENTES.md
- Plan de limpieza aplicado: docs/LIMPIEZA_REPO_PROPUESTA.md
- Contexto maestro: Documento_de_contexto_LGC.txt

## Referencias tecnicas
- Orquestador principal: src/main.py
- Runtime LLM y retries: src/llm.py
- Contratos de prompt: src/prompt.py
- Render y continuidad de indice: src/builder.py
- Setup de tareas locales: scripts/setup_local_tasks.ps1
