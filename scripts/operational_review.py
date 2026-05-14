#!/usr/bin/env python3
"""
Script de revisión operativa diaria.
Lee metrics y judge reports, evalúa checklist, genera reporte con hallazgos.
Se ejecuta automáticamente después de LGC-Close via Task Scheduler.

Genera: raw/YYYY-MM-DD/daily_review.json
"""

import json
import logging
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
TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_RAW_DIR = RAW_DIR / TODAY


def read_json(file_path):
    """Lee archivo JSON, retorna {} si no existe o hay error."""
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def evaluate_daily_checklist():
    """Evalúa los 10 items del checklist diario."""
    checklist = {}
    
    # Item 1: Captura intradia disponible
    intraday_file = TODAY_RAW_DIR / "intraday_accumulated.json"
    checklist[1] = {
        "control": "Captura intradia disponible",
        "evidencia": "raw/YYYY-MM-DD/intraday_accumulated.json",
        "estado": "OK" if intraday_file.exists() else "FAIL",
        "presente": intraday_file.exists()
    }
    
    # Item 2: Cierre diario ejecutado
    close_log = PROJECT_ROOT / "logs" / "close.log"
    docs_dir = PROJECT_ROOT / "docs" / TODAY.split("-")[0] / TODAY.split("-")[1] / TODAY.split("-")[2]
    cierre_ejecutado = close_log.exists() and (docs_dir / "index.html").exists()
    checklist[2] = {
        "control": "Cierre diario ejecutado",
        "evidencia": "logs/close.log y docs/YYYY/MM/DD/index.html",
        "estado": "OK" if cierre_ejecutado else "FAIL",
        "presente": cierre_ejecutado
    }
    
    # Item 3: data.json generado
    data_json = docs_dir / "data.json"
    checklist[3] = {
        "control": "data.json generado",
        "evidencia": "docs/YYYY/MM/DD/data.json",
        "estado": "OK" if data_json.exists() else "FAIL",
        "presente": data_json.exists()
    }
    
    # Item 4: pipeline_metrics.json generado
    metrics_file = TODAY_RAW_DIR / "pipeline_metrics.json"
    checklist[4] = {
        "control": "pipeline_metrics.json generado",
        "evidencia": "raw/YYYY-MM-DD/pipeline_metrics.json",
        "estado": "OK" if metrics_file.exists() else "FAIL",
        "presente": metrics_file.exists()
    }
    
    # Item 5: judge_report.json generado
    judge_file = TODAY_RAW_DIR / "judge_report.json"
    checklist[5] = {
        "control": "judge_report.json generado",
        "evidencia": "raw/YYYY-MM-DD/judge_report.json",
        "estado": "OK" if judge_file.exists() else "FAIL",
        "presente": judge_file.exists()
    }
    
    # Items 6-10 requieren leer los archivos
    metrics = read_json(metrics_file)
    judge = read_json(judge_file)
    
    # Item 6: quality_gate del Juez
    quality_gate = judge.get("quality_gate", "NA")
    checklist[6] = {
        "control": "quality_gate del Juez",
        "evidencia": "PASS o WARN con plan",
        "estado": "OK" if quality_gate == "PASS" else ("WARN" if quality_gate == "WARN" else "FAIL"),
        "valor": quality_gate
    }
    
    # Item 7: errores criticos del Juez
    critical_errors = judge.get("critical_errors_count", 0)
    checklist[7] = {
        "control": "errores criticos del Juez",
        "evidencia": "judge_critical_errors_count = 0",
        "estado": "OK" if critical_errors == 0 else "WARN" if critical_errors < 5 else "FAIL",
        "valor": critical_errors
    }
    
    # Item 8: cobertura de publicacion
    selected = metrics.get("selected", 0)
    published = metrics.get("published", 0)
    coverage_ok = selected > 0 and published == selected
    checklist[8] = {
        "control": "cobertura de publicacion",
        "evidencia": "published = selected",
        "estado": "OK" if coverage_ok else "WARN" if published > 0 else "FAIL",
        "selected": selected,
        "published": published
    }
    
    # Item 9: fallback por item bajo control
    fallback_ratio = metrics.get("fallback_items_ratio", 0.0)
    fallback_state = "OK" if fallback_ratio <= 0.20 else "WARN" if fallback_ratio <= 0.30 else "FAIL"
    checklist[9] = {
        "control": "fallback por item bajo control",
        "evidencia": "fallback_items_ratio <= 0.20 objetivo",
        "estado": fallback_state,
        "valor": fallback_ratio
    }
    
    # Item 10: parse failures no recuperados (criterio operativo crítico)
    parse_failures_raw = metrics.get("llm_json_parse_failures_total", 0)
    parse_failures_unrecovered = metrics.get("llm_json_parse_unrecovered_total", None)
    if parse_failures_unrecovered is None:
        # Compatibilidad hacia atrás: si aún no existe la nueva métrica
        parse_state = "OK" if parse_failures_raw == 0 else "WARN" if parse_failures_raw < 3 else "FAIL"
        parse_evidence = "llm_json_parse_failures_total en tendencia no creciente"
        parse_value = parse_failures_raw
        parse_control = "parse failures LLM bajo control"
    else:
        parse_state = "OK" if parse_failures_unrecovered == 0 else "FAIL"
        parse_evidence = "llm_json_parse_unrecovered_total = 0 (critico)"
        parse_value = {
            "unrecovered": parse_failures_unrecovered,
            "raw_total": parse_failures_raw,
        }
        parse_control = "parse failures LLM no recuperados bajo control"

    checklist[10] = {
        "control": parse_control,
        "evidencia": parse_evidence,
        "estado": parse_state,
        "valor": parse_value
    }
    
    return checklist, metrics, judge


def extract_ab_data():
    """Extrae datos A/B si existen."""
    ab_dir = TODAY_RAW_DIR / "ab_runs"
    if not ab_dir.exists():
        return None
    
    metrics_a = read_json(ab_dir / "A_pipeline_metrics.json")
    metrics_b = read_json(ab_dir / "B_pipeline_metrics.json")
    judge_a = read_json(ab_dir / "A_judge_report.json")
    judge_b = read_json(ab_dir / "B_judge_report.json")
    
    if not any([metrics_a, metrics_b, judge_a, judge_b]):
        return None
    
    return {
        "A": {
            "metrics": metrics_a,
            "judge": judge_a
        },
        "B": {
            "metrics": metrics_b,
            "judge": judge_b
        }
    }


def determine_daily_winner(ab_data):
    """Determina ganador del día si hay A/B."""
    if not ab_data:
        return None
    
    score_a = ab_data["A"]["judge"].get("judge_weighted_total", 0)
    score_b = ab_data["B"]["judge"].get("judge_weighted_total", 0)
    
    if score_a > score_b:
        return "A"
    elif score_b > score_a:
        return "B"
    else:
        return "TIE"


def generate_report():
    """Genera reporte diario con valores calculados."""
    logger.info("📋 Iniciando revisión operativa diaria...")
    
    checklist, metrics, judge = evaluate_daily_checklist()
    ab_data = extract_ab_data()
    daily_winner = determine_daily_winner(ab_data)
    
    report = {
        "date": TODAY,
        "checklist": checklist,
        "metrics": metrics,
        "judge": judge,
        "ab_data": ab_data,
        "daily_winner": daily_winner,
        "generated_at": datetime.now().isoformat()
    }
    
    # Guardar reporte
    TODAY_RAW_DIR.mkdir(parents=True, exist_ok=True)
    report_file = TODAY_RAW_DIR / "daily_review.json"
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"✓ Reporte guardado en {report_file}")
    
    return report


if __name__ == "__main__":
    try:
        report = generate_report()
        
        # Summary for Task Scheduler log
        fail_count = sum(1 for item in report["checklist"].values() if item.get("estado") == "FAIL")
        warn_count = sum(1 for item in report["checklist"].values() if item.get("estado") == "WARN")
        
        logger.info(f"📊 Checklist: {10 - fail_count - warn_count} OK, {warn_count} WARN, {fail_count} FAIL")
        
        if report["ab_data"]:
            logger.info(f"🏆 Ganador del día: {report['daily_winner']}")
        
        logger.info("✅ Revisión completada")
        
    except Exception as e:
        logger.error(f"❌ Error en revisión operativa: {e}", exc_info=True)
        exit(1)
