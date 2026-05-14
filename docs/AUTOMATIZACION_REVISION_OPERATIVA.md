# Automatización de Revisión Operativa

## Sistema Automático de Revisión Diaria y Actualización de HOJA_OPERATIVA

Este documento explica cómo el sistema automáticamente genera reportes de revisión y actualiza la hoja operativa cada día sin intervención manual.

---

## Arquitectura

### 1. **Tareas Task Scheduler (Windows)**

Cuatro tareas ejecutan automáticamente a horas fijas:

| Tarea | Hora | Función |
|-------|------|---------|
| LGC-IntradayAccumulate | Cada hora (08:00–04:59) | Acumula artículos intradiarios |
| LGC-DailyClose | 05:00 ART | Publica digest diario |
| **LGC-Review** | **05:05 ART** | Genera reporte de revisión |
| **LGC-UpdateHoja** | **05:10 ART** | Actualiza HOJA_OPERATIVA |

Las dos tareas nuevas (Review y UpdateHoja) se ejecutan automáticamente 5 y 10 minutos después del cierre diario.

---

## Flujo de Ejecución

```
05:00 ART
└─→ LGC-DailyClose
    └─→ Genera: pipeline_metrics.json, judge_report.json, data.json
    
05:05 ART
└─→ LGC-Review (scripts/operational_review.py)
    └─→ Lee: pipeline_metrics.json, judge_report.json
    └─→ Evalúa: Checklist de 10 items
    └─→ Determina: Ganador A/B (si aplica)
    └─→ Genera: raw/YYYY-MM-DD/daily_review.json
    
05:10 ART
└─→ LGC-UpdateHoja (scripts/update_hoja_operativa.py)
    └─→ Lee: daily_review.json
    └─→ Actualiza: docs/HOJA_OPERATIVA_AGENTES.md
        - Sección 1: Checklist diario (10 items)
        - Sección 2: Ejecución completada hoy
    └─→ Resultado: Hoja operativa lista para revisión manual
```

---

## Scripts

### A) **operational_review.py**

**Ubicación**: `scripts/operational_review.py`

**Función**: Genera reporte de revisión diaria con valores calculados.

**Entrada**: 
- Archivos: `raw/YYYY-MM-DD/pipeline_metrics.json`, `raw/YYYY-MM-DD/judge_report.json`
- Archivos A/B (opcional): `raw/YYYY-MM-DD/ab_runs/A_*.json`, `B_*.json`

**Proceso**:
1. Lee metrics y judge reports del día
2. Evalúa cada uno de los 10 items del checklist:
   - Item 1-5: Verifica existencia de archivos
   - Item 6-10: Evalúa valores numéricos (quality_gate, critical_errors, coverage, fallback_ratio, parse_failures)
3. Extrae datos A/B si existen
4. Determina ganador del día (A, B, o TIE)

**Salida**: `raw/YYYY-MM-DD/daily_review.json`
```json
{
  "date": "2026-04-24",
  "checklist": {
    "1": { "control": "...", "estado": "OK" },
    ...
  },
  "metrics": { ... },
  "judge": { ... },
  "ab_data": { "A": {...}, "B": {...} },
  "daily_winner": "A"
}
```

**Ejecución Manual**:
```bash
python scripts/operational_review.py
```

---

### B) **update_hoja_operativa.py**

**Ubicación**: `scripts/update_hoja_operativa.py`

**Función**: Lee reporte diario y actualiza HOJA_OPERATIVA.md automáticamente.

**Entrada**: `raw/YYYY-MM-DD/daily_review.json` (generado por operational_review.py)

**Proceso**:
1. Lee el archivo daily_review.json
2. Formatea tabla de checklist diario con estados (OK/WARN/FAIL)
3. Formatea sección 2 "Ejecución completada hoy" con:
   - Variante ganadora
   - Scores y métricas A/B
   - Hallazgos y acciones
4. Actualiza docs/HOJA_OPERATIVA_AGENTES.md mediante regex substitution

**Salida**: docs/HOJA_OPERATIVA_AGENTES.md actualizado

**Ejecución Manual**:
```bash
python scripts/update_hoja_operativa.py
```

---

## Archivos de Soporte

### run_review.bat
Batch wrapper que ejecuta operational_review.py desde Task Scheduler.
```batch
@echo off
cd /d C:\Users\Diego\lagrancrisis
C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe C:\Users\Diego\lagrancrisis\scripts\operational_review.py
```

### run_update_hoja.bat
Batch wrapper que ejecuta update_hoja_operativa.py desde Task Scheduler.
```batch
@echo off
cd /d C:\Users\Diego\lagrancrisis
C:\Users\Diego\lagrancrisis\venv\Scripts\python.exe C:\Users\Diego\lagrancrisis\scripts\update_hoja_operativa.py
```

---

## Operación Diaria

### Para ti (GitHub Copilot)

**A las 05:15 ART (aproximadamente)**, HOJA_OPERATIVA.md está automáticamente actualizada con:

1. ✅ Checklist diario completado (estados OK/WARN/FAIL)
2. ✅ Datos A/B evaluados (si hay corrida A/B)
3. ✅ Ganador del día determinado
4. ✅ Hallazgos y recomendaciones generados

**Tu rol es revisar**:
- Si hay algún FAIL en el checklist, investigar y resolver
- Cada viernes, evaluar sección 3 (plantilla semanal) manualmente
- Tomar decisiones Go/No-Go basadas en hard gates semanales

---

## Revisión Semanal

Para la revisión semanal (cada viernes), necesitas:

1. Leer datos de toda la semana desde `logs/weekly_summary.json`
2. Calcular promedios de métricas A/B
3. Evaluar hard gates:
   - Errores críticos = 0
   - quality_gate = PASS
   - Cobertura = 100%
   - fallback_items_ratio ≤ 0.20
   - post_llm_warning_count en tendencia decreciente
4. Decidir Go/No-Go en sección 3 de HOJA_OPERATIVA

**Nota**: Los datos aggregados están disponibles en `logs/weekly_summary.json` (actualizado diariamente por main.py).

---

## Mantenimiento

### Para agregar nuevos items de revisión

1. Modificar `evaluate_daily_checklist()` en `operational_review.py`
2. Actualizar tabla de sección 1 en `HOJA_OPERATIVA_AGENTES.md`
3. Actualizar formatos de salida en `update_hoja_operativa.py`

### Para cambiar horarios

Editar setup_local_tasks.ps1 y re-ejecutar:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_local_tasks.ps1
```

### Para ejecutar manualmente

```bash
# Generar reporte
python scripts/operational_review.py

# Actualizar hoja
python scripts/update_hoja_operativa.py
```

---

## Logs

Los resultados de cada ejecución se registran en:
- `logs/close.log` — Resultado del cierre diario
- Salida estándar de Task Scheduler — Resultado de review y update (visible en Event Viewer)

---

**Estado**: ✅ Operativo desde 2026-04-24  
**Responsable**: GitHub Copilot (ejecución automática)  
**Última actualización**: 2026-04-24
