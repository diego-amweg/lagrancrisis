#!/usr/bin/env python3
"""
Script de actualización automática de HOJA_OPERATIVA.md
Lee daily_review.json y actualiza la hoja operativa con valores calculados.
Se ejecuta después de operational_review.py via Task Scheduler.

Actualiza:
- Sección 1: Checklist diario (10 items)
- Sección 2: Ejecución completada hoy
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
RAW_DIR = PROJECT_ROOT / "raw"
HOJA_OPERATIVA = PROJECT_ROOT / "docs" / "HOJA_OPERATIVA_AGENTES.md"
TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_RAW_DIR = RAW_DIR / TODAY


def read_review_report():
    """Lee el reporte de revisión diaria generado por operational_review.py"""
    report_file = TODAY_RAW_DIR / "daily_review.json"
    if not report_file.exists():
        logger.warning(f"⚠️ No se encontró reporte diario en {report_file}")
        return None
    
    try:
        return json.loads(report_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"❌ Error leyendo reporte: {e}")
        return None


def format_checklist_table(report):
    """Formatea la tabla de checklist diario con datos del reporte."""
    checklist = report["checklist"]
    
    rows = []
    for item_num in range(1, 11):
        # JSON keys are strings, not integers
        item_key = str(item_num)
        if item_key not in checklist:
            continue
        item = checklist[item_key]
        control = item.get("control", "")
        evidencia = item.get("evidencia", "")
        estado = item.get("estado", "OK")
        
        rows.append(f"| {item_num} | {control} | {evidencia} | {estado} |")
    
    return "\n".join(rows)


def format_ab_section(report):
    """Formatea la sección 2 (Ejecución completada hoy) con datos A/B si existen."""
    if not report.get("ab_data"):
        return "### No hay corrida A/B registrada hoy\n"
    
    ab = report["ab_data"]
    winner = report.get("daily_winner", "N/A")
    
    score_a = ab["A"]["judge"].get("judge_weighted_total", 0)
    score_b = ab["B"]["judge"].get("judge_weighted_total", 0)
    
    calls_a = ab["A"]["metrics"].get("llm_calls_total", 0)
    calls_b = ab["B"]["metrics"].get("llm_calls_total", 0)
    
    fallback_a = ab["A"]["metrics"].get("fallback_items_ratio", 0.0)
    fallback_b = ab["B"]["metrics"].get("fallback_items_ratio", 0.0)
    
    errors_a = ab["A"]["judge"].get("critical_errors_count", 0)
    errors_b = ab["B"]["judge"].get("critical_errors_count", 0)
    
    text = f"""### A/B controlado con Juez activado
- Variante A: agentes desactivados, Juez activado.
- Variante B: agentes activados, Juez activado.

### Resumen de resultado
- Ganadora del día: {winner}
- Razon:
  - judge_weighted_total: A={score_a} vs B={score_b}
  - llamadas LLM: A={calls_a} vs B={calls_b}
  - fallback_items_ratio: A={fallback_a:.4f} vs B={fallback_b:.4f}

### Hallazgos de revision
1. Errores críticos: A={errors_a}, B={errors_b}
2. Score diferencial: {abs(score_a - score_b):.1f} puntos
3. Costo operativo: B usa {calls_b - calls_a:+d} llamadas vs A

### Accion aplicada
- Produccion diaria recomendada: {winner}
- Variante alternativa queda en experimento controlado para iterar.
"""
    return text


def update_hoja_operativa(report):
    """Actualiza HOJA_OPERATIVA.md con datos del reporte."""
    if not HOJA_OPERATIVA.exists():
        logger.error(f"❌ No se encontró {HOJA_OPERATIVA}")
        return False
    
    content = HOJA_OPERATIVA.read_text(encoding="utf-8")
    
    # Actualizar tabla de checklist
    checklist_table = format_checklist_table(report)
    
    # Pattern para la tabla de checklist (entre el header y el siguiente header)
    checklist_pattern = r"(## 1\) Checklist diario.*?\n\n### Formato\n.*?\n\n\| Item \| Control diario \| Evidencia minima \| Estado hoy \|\n\|.*?\|\n)"
    
    # Actualizar tabla
    new_checklist_section = f"""## 1) Checklist diario (10 items)

### Formato
- Estado permitido: OK, WARN, FAIL.
- Si hay FAIL, no se recomienda promover cambios de variante.

| Item | Control diario | Evidencia minima | Estado hoy |
|---|---|---|---|
{checklist_table}

"""
    
    content = re.sub(
        r"## 1\) Checklist diario.*?(?=## 2\))",
        new_checklist_section,
        content,
        flags=re.DOTALL
    )
    
    # Actualizar sección 2 (Ejecución completada hoy)
    ab_section = format_ab_section(report)
    
    new_section2 = f"""## 2) Ejecucion completada hoy ({TODAY})

{ab_section}
## 4) Evidencia guardada
"""
    
    content = re.sub(
        r"## 2\) Ejecucion completada hoy.*?(?=## [34]\) )",
        new_section2,
        content,
        flags=re.DOTALL
    )
    
    # Guardar actualización
    HOJA_OPERATIVA.write_text(content, encoding="utf-8")
    logger.info(f"✅ HOJA_OPERATIVA.md actualizada")
    
    return True


def process_daily_reviews():
    """Procesa reportes diarios y actualiza HOJA_OPERATIVA."""
    logger.info("🔄 Procesando reportes diarios...")
    
    report = read_review_report()
    if not report:
        logger.warning("⚠️ No se puede procesar sin reporte diario")
        return False
    
    if update_hoja_operativa(report):
        logger.info("✅ Actualización completada")
        return True
    
    return False


if __name__ == "__main__":
    try:
        if not process_daily_reviews():
            exit(1)
    except Exception as e:
        logger.error(f"❌ Error procesando reviews: {e}", exc_info=True)
        exit(1)
