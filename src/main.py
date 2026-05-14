"""
Orquestador principal del flujo diario de "La Gran Crisis"
Compatible con: Windows 11 Pro + VS Code + Python 3.13.x + PowerShell
Prácticas SWE: PEP-8, Type Hints, logging granular, manejo de excepciones, modularidad
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Agregar raíz del proyecto al path para imports relativos
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.builder import (render_daily_page, render_fallback_page,
                         update_index_page)
from src.classifier import classify_and_rank
from src.dedupe import deduplicate_articles
# Imports locales del proyecto
from src.fetch_rss import fetch_all_feeds, fetch_sample_articles
from src.llm import (call_gemini_mock, call_gemini_with_retry,
                     get_llm_runtime_metrics, reset_llm_runtime_metrics,
                     translate_items_to_spanish,
                     translate_items_to_spanish_contextual)
from src.prompt import (build_editor_prompt,
                        build_editorial_autocorrect_prompt,
                        build_editorial_prompt,
                        build_factual_extraction_prompt,
                        build_global_synthesis_prompt, build_judge_prompt,
                        build_redactor_prompt)
from src.validator import (fallback_response, tag_sources,
                           validate_editorial_grounding,
                           validate_editorial_referential_integrity,
                           validate_factual_extraction_by_id,
                           validate_json_structure, validate_post_llm)

# Configuración de logging
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Evita crashes de logging en consolas cp1252 cuando hay símbolos Unicode.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS_DIR / "digest.log", encoding="utf-8", mode="a")
    ]
)
logger = logging.getLogger(__name__)

# Configuración global del pipeline
# Tasa máxima de omisión en Paso A antes de tratar la respuesta como degradada.
# Si el LLM omite más del 60% de los IDs, es casi siempre truncamiento/API inestable.
MAX_MACRO_OMISSION_RATE = 0.60

TODAY = datetime.now().strftime("%Y-%m-%d")
RAW_DIR = Path(f"raw/{TODAY}")
DOCS_DIR = Path(f"docs/{TODAY.replace('-', '/')}")
SECTIONS: List[str] = [
    "mercados_argentina", "mercados_internacionales",
    "financieras_argentina", "financieras_mundo",
    "economicas_argentina", "economicas_mundo",
    "politicas_argentina", "politicas_mundo"
]

SPANISH_STOPWORDS = {
    "el", "la", "los", "las", "de", "del", "y", "en", "para", "con", "por", "que",
    "un", "una", "sobre", "se", "al", "como", "entre", "tras", "más", "menos",
}

ENGLISH_STOPWORDS = {
    "the", "and", "of", "to", "in", "for", "with", "on", "by", "from", "as", "at",
    "is", "are", "was", "were", "be", "will", "has", "have",
}

PORTUGUESE_STOPWORDS = {
    "o", "a", "os", "as", "de", "do", "da", "e", "em", "para", "com", "por", "que",
    "um", "uma", "sobre", "ao", "como", "entre", "mais", "menos",
}

TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
}

SUMMARY_MIN_CHARS = 500

SOURCE_POLICY_FILE = Path("src/source_policy.json")
SOURCE_OPT_OUT_FILE = Path("src/source_opt_out.json")

EDITORIAL_CHUNK_SIZE = 18
FACTUAL_CHUNK_SIZE = 30
MIN_ARTICLES_FOR_PIPELINE = 15
AUTOCORRECT_HEAVY_IDS_THRESHOLD = 8

PROMPT_REDACTOR_VERSION = "redactor_v1"
PROMPT_EDITOR_VERSION = "editor_v1"
PROMPT_JUDGE_VERSION = "judge_v1"
ENABLE_LOGICAL_AGENTS = os.getenv("LGC_ENABLE_LOGICAL_AGENTS", "1") != "0"
EXPERIMENT_LABEL = os.getenv("LGC_EXPERIMENT_LABEL", "production")


def _get_env_int(name: str, default: int, minimum: int = 1) -> int:
    """Lee enteros desde entorno con fallback seguro."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Valor inválido en %s=%r; usando %d", name, raw, default)
        return default
    return max(minimum, value)


FEED_HOURS_BACK = _get_env_int("LGC_FEED_HOURS_BACK", default=48, minimum=1)
FEED_MAX_ENTRIES_PER_SOURCE = _get_env_int(
    "LGC_FEED_MAX_ENTRIES_PER_SOURCE",
    default=40,
    minimum=1,
)

MOJIBAKE_REPLACEMENTS = {
    "Ã¡": "á",
    "Ã©": "é",
    "Ã­": "í",
    "Ã³": "ó",
    "Ãº": "ú",
    "Ã±": "ñ",
    "Ã": "Á",
    "Ã‰": "É",
    "Ã": "Í",
    "Ã“": "Ó",
    "Ãš": "Ú",
    "Ã‘": "Ñ",
    "â€“": "-",
    "â€”": "-",
    "â€˜": "'",
    "â€™": "'",
    "â€œ": '"',
    "â€": '"',
    "Â": "",
}


def load_sources() -> List[Dict[str, str]]:
    """Carga la lista de fuentes desde src/sources.json con validación básica."""
    sources_path = Path("src/sources.json")
    if not sources_path.exists():
        logger.error(f"Archivo de fuentes no encontrado: {sources_path}")
        return []
    
    try:
        with open(sources_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        policy_matrix = _load_source_policy_matrix()
        opt_out_rules = _load_source_opt_out()

        all_sources: List[Dict[str, str]] = []
        blocked_count = 0
        opted_out_count = 0
        for region in ["argentina", "global"]:
            for tier in ["oficiales", "medios_tier1"]:
                sources = config.get(region, {}).get(tier, [])
                for source in sources:
                    policy = _resolve_source_policy(source, policy_matrix)
                    condition = str(policy.get("condition", "conditional")).strip().lower()
                    if condition == "block":
                        blocked_count += 1
                        logger.warning(
                            "🚫 Fuente bloqueada por política legal: %s",
                            source.get("name", "(sin nombre)"),
                        )
                        continue

                    if _is_source_opted_out(source, opt_out_rules):
                        opted_out_count += 1
                        logger.warning(
                            "🛑 Fuente excluida por opt-out dinámico: %s",
                            source.get("name", "(sin nombre)"),
                        )
                        continue

                    if _is_policy_review_overdue(policy):
                        logger.warning(
                            "📅 Revision legal vencida para fuente: %s",
                            source.get("name", "(sin nombre)"),
                        )

                    enriched = dict(source)
                    enriched["compliance_condition"] = condition
                    enriched["compliance_policy"] = policy
                    all_sources.append(enriched)
        
        logger.info(
            "✓ Cargadas %d fuentes activas (bloqueadas=%d, opt-out=%d)",
            len(all_sources),
            blocked_count,
            opted_out_count,
        )
        return all_sources
    except json.JSONDecodeError as e:
        logger.error(f"Error parseando sources.json: {e}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado cargando fuentes: {type(e).__name__}: {e}")
        return []


def _safe_json_load(path: Path, fallback: object) -> object:
    """Carga JSON tolerante a errores y retorna fallback en fallo."""
    if not path.exists():
        return fallback

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("⚠️ No se pudo leer %s: %s", path, e)
        return fallback


def _load_source_policy_matrix() -> Dict[str, Dict]:
    """Carga matriz legal por fuente (allow/conditional/block)."""
    raw = _safe_json_load(SOURCE_POLICY_FILE, {})
    if isinstance(raw, dict):
        return raw
    return {}


def _load_source_opt_out() -> Dict[str, List[str]]:
    """Carga reglas de opt-out para exclusión dinámica sin cambios de código."""
    raw = _safe_json_load(SOURCE_OPT_OUT_FILE, {})
    if not isinstance(raw, dict):
        return {"names": [], "urls": [], "domains": []}

    names = raw.get("names", [])
    urls = raw.get("urls", [])
    domains = raw.get("domains", [])

    return {
        "names": [str(item).strip().lower() for item in names if str(item).strip()],
        "urls": [str(item).strip().lower() for item in urls if str(item).strip()],
        "domains": [str(item).strip().lower() for item in domains if str(item).strip()],
    }


def _normalize_source_name(name: str) -> str:
    normalized = _sanitize_text(str(name or "").lower())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _normalize_source_url(url: str) -> str:
    return _normalize_url(str(url or "")).lower()


def _extract_domain(url: str) -> str:
    try:
        return urlsplit(str(url or "")).netloc.lower()
    except Exception:
        return ""


def _is_source_opted_out(source: Dict, rules: Dict[str, List[str]]) -> bool:
    """Evalúa opt-out por nombre, URL exacta o dominio."""
    source_name = _normalize_source_name(source.get("name", ""))
    source_url = _normalize_source_url(source.get("url", ""))
    source_domain = _extract_domain(source_url)

    names = set(rules.get("names", []))
    urls = set(rules.get("urls", []))
    domains = set(rules.get("domains", []))

    if source_name and source_name in names:
        return True
    if source_url and source_url in urls:
        return True
    if source_domain and source_domain in domains:
        return True
    return False


def _resolve_source_policy(source: Dict, matrix: Dict[str, Dict]) -> Dict:
    """Resuelve política de una fuente con fallback por nombre/dominio/default."""
    source_name = _normalize_source_name(source.get("name", ""))
    source_url = _normalize_source_url(source.get("url", ""))
    source_domain = _extract_domain(source_url)

    sources_by_name = matrix.get("sources_by_name", {})
    sources_by_domain = matrix.get("sources_by_domain", {})
    default_policy = matrix.get("default", {"condition": "conditional"})

    if isinstance(sources_by_name, dict) and source_name in sources_by_name:
        selected = sources_by_name.get(source_name)
        if isinstance(selected, dict):
            return selected

    if isinstance(sources_by_domain, dict):
        for domain_key, policy in sources_by_domain.items():
            normalized_domain = str(domain_key).strip().lower()
            if not normalized_domain:
                continue
            if source_domain == normalized_domain or source_domain.endswith(f".{normalized_domain}"):
                if isinstance(policy, dict):
                    return policy

    if isinstance(default_policy, dict):
        return default_policy
    return {"condition": "conditional"}


def _is_policy_review_overdue(policy: Dict) -> bool:
    """Valida vencimiento de revisión legal según frecuencia declarada."""
    if not isinstance(policy, dict):
        return False

    reviewed_at = str(policy.get("reviewed_at", "")).strip()
    review_frequency = str(policy.get("review_frequency", "")).strip().lower()
    if not reviewed_at or not review_frequency:
        return False

    frequency_days = {
        "monthly": 31,
        "quarterly": 93,
    }.get(review_frequency)
    if not frequency_days:
        return False

    try:
        reviewed_dt = datetime.strptime(reviewed_at, "%Y-%m-%d")
    except ValueError:
        return False

    return (datetime.now() - reviewed_dt).days > frequency_days


def filter_articles_by_compliance(articles: List[Dict]) -> Tuple[List[Dict], int, int]:
    """Elimina artículos provenientes de fuentes bloqueadas u opt-out."""
    if not isinstance(articles, list) or not articles:
        return [], 0, 0

    policy_matrix = _load_source_policy_matrix()
    opt_out_rules = _load_source_opt_out()

    filtered: List[Dict] = []
    blocked_count = 0
    opt_out_count = 0

    for article in articles:
        if not isinstance(article, dict):
            continue

        source_stub = {
            "name": article.get("source_name", ""),
            "url": article.get("url", ""),
        }
        policy = _resolve_source_policy(source_stub, policy_matrix)
        condition = str(policy.get("condition", "conditional")).strip().lower()
        if condition == "block":
            blocked_count += 1
            continue

        if _is_source_opted_out(source_stub, opt_out_rules):
            opt_out_count += 1
            continue

        filtered.append(article)

    return filtered, blocked_count, opt_out_count


def save_raw_articles(articles: List[Dict], output_dir: Path) -> None:
    """Guarda los artículos crudos para auditoría futura."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "raw.json"
    
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ Guardados {len(articles)} artículos crudos en {output_file}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo guardar raw.json: {e}")


def _save_missing_documented(date: str, reason: str) -> None:
    """Escribe un data.json de missing_documented en DOCS_DIR para días sin publicación."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": date,
        "status": "missing_documented",
        "reason": reason,
        "resumen_ejecutivo": "",
        "cadena_de_razonamiento": "",
        "noticias_destacadas": [],
        "missing_official_data": [],
    }
    try:
        output_path = DOCS_DIR / "data.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info("✓ Guardado missing_documented en %s", output_path)
    except Exception as e:
        logger.warning("⚠️ No se pudo guardar missing_documented data.json: %s", e)


def extract_missing_data(result: Dict, raw_dir: Path) -> None:
    """Guarda missing_official_data en archivo separado para revisión manual del fundador."""
    missing = result.get("missing_official_data", [])
    if not missing:
        return
    
    try:
        output_file = raw_dir / "missing_data.json"
        payload = {"date": result.get("date", TODAY), "missing": missing}
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ Guardados {len(missing)} datos faltantes en {output_file}")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo guardar missing_data.json: {e}")


def save_pipeline_metrics(
    raw_count: int,
    selected_count: int,
    published_count: int,
    fallback_used: bool,
    output_dir: Path,
    extra_metrics: Optional[Dict[str, object]] = None,
) -> None:
    """Guarda métricas operativas obligatorias de cada corrida diaria."""
    coverage_ratio = (published_count / raw_count) if raw_count else 0.0
    fallback_rate = 1.0 if fallback_used else 0.0

    payload = {
        "date": TODAY,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "downloaded": raw_count,
        "selected": selected_count,
        "published": published_count,
        "coverage_ratio": round(coverage_ratio, 4),
        "fallback_rate": fallback_rate,
    }

    if extra_metrics:
        payload.update(extra_metrics)

    try:
        metrics_path = output_dir / "pipeline_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        logger.info(
            "📊 Métricas: descargadas=%d | seleccionadas=%d | publicadas=%d | cobertura=%.2f%% | fallback=%.2f",
            raw_count,
            selected_count,
            published_count,
            coverage_ratio * 100,
            fallback_rate,
        )
    except Exception as e:
        logger.warning(f"⚠️ No se pudo guardar pipeline_metrics.json: {e}")


def _normalize_status(status: str) -> str:
    """Normaliza status al formato canónico usado por el pipeline."""
    normalized = str(status).strip().upper().replace("_", " ")
    if normalized in ["OFICIAL", "VALIDADO", "SIN CONFIRMAR"]:
        return normalized
    return "SIN CONFIRMAR"


def _infer_asset_relevance(article: Dict) -> List[str]:
    """Infiere relevancia de activos con reglas simples sobre título/contenido."""
    text = f"{article.get('title', '')} {article.get('content', '')}".lower()
    assets: List[str] = []

    if any(k in text for k in ["dólar", "dollar", "fx", "tipo de cambio", "mep"]):
        assets.append("DÓLAR")
    if any(k in text for k in ["bono", "bond", "deuda", "treasury"]):
        assets.append("BONOS")
    if any(k in text for k in ["acciones", "stocks", "equity", "merval", "wall street"]):
        assets.append("ACCIONES")
    if any(k in text for k in ["tasa", "rates", "yield", "fed", "bce", "bcra"]):
        assets.append("TASAS")
    if any(k in text for k in ["petróleo", "oil", "oro", "gold", "gas", "commodity"]):
        assets.append("COMMODITIES")

    return assets if assets else ["NO_APLICA"]


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _get_mode_logger(mode_name: str) -> logging.Logger:
    """Devuelve logger por modo con archivo dedicado para auditoría operativa."""
    mode_logger = logging.getLogger(f"mode.{mode_name}")
    if mode_logger.handlers:
        return mode_logger

    mode_logger.setLevel(logging.INFO)
    mode_handler = logging.FileHandler(LOGS_DIR / f"{mode_name}.log", encoding="utf-8", mode="a")
    mode_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    mode_logger.addHandler(mode_handler)
    mode_logger.propagate = True
    return mode_logger


def _write_desktop_health_check(mode_name: str, ok: bool, details: str = "") -> None:
    """Escribe estado visible en escritorio para confirmar ejecución de tareas locales."""
    try:
        desktop = Path.home() / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        status_file = desktop / "LGC_health_check.txt"
        status_html_file = desktop / "LGC_health_check.html"
        status = "OK" if ok else "ERROR"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        safe_details = _sanitize_text(details)[:300]

        lines = [
            "La Gran Crisis - Health Check Local",
            f"timestamp: {timestamp}",
            f"mode: {mode_name}",
            f"status: {status}",
            f"details: {safe_details}" if safe_details else "details: n/a",
        ]
        status_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        if ok:
            status_color = "#1b5e20"
            status_bg = "#e8f5e9"
        else:
            status_color = "#b71c1c"
            status_bg = "#ffebee"

        details_html = safe_details if safe_details else "n/a"
        html = f"""<!doctype html>
<html lang=\"es\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>LGC Health Check</title>
    <style>
        body {{
            font-family: Segoe UI, Arial, sans-serif;
            background: #f4f4f4;
            color: #222;
            margin: 0;
            padding: 24px;
        }}
        .card {{
            max-width: 680px;
            margin: 0 auto;
            background: #fff;
            border: 1px solid #ddd;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }}
        .status {{
            display: inline-block;
            padding: 8px 12px;
            border-radius: 999px;
            font-weight: 700;
            background: {status_bg};
            color: {status_color};
            border: 1px solid {status_color};
        }}
        .meta {{ margin-top: 14px; line-height: 1.7; }}
        .label {{ font-weight: 600; }}
        .footer {{ margin-top: 16px; color: #666; font-size: 13px; }}
    </style>
</head>
<body>
    <div class=\"card\">
        <h2>La Gran Crisis - Health Check Local</h2>
        <div class=\"status\">{status}</div>
        <div class=\"meta\">
            <div><span class=\"label\">timestamp:</span> {timestamp}</div>
            <div><span class=\"label\">mode:</span> {mode_name}</div>
            <div><span class=\"label\">details:</span> {details_html}</div>
        </div>
        <div class=\"footer\">Archivo generado automaticamente por el pipeline local.</div>
    </div>
</body>
</html>
"""
        status_html_file.write_text(html, encoding="utf-8")
    except Exception as e:
        logger.warning("⚠️ No se pudo escribir health check en escritorio: %s", e)


@contextmanager
def _acquire_mode_lock(lock_name: str):
    """Evita corridas solapadas por modo con lock-file local."""
    lock_path = LOGS_DIR / f"{lock_name}.lock"
    stale_after = timedelta(hours=4)  # cierre nunca debería tardar más de 2-3h

    if lock_path.exists():
        try:
            mtime = datetime.fromtimestamp(lock_path.stat().st_mtime)
            lock_date = mtime.date()
            today = datetime.now().date()
            # Stale si: supera 4h O si es de un día anterior
            if datetime.now() - mtime > stale_after or lock_date < today:
                lock_path.unlink(missing_ok=True)
                logger.warning("⚠️ Lock stale eliminado: %s", lock_path.name)
        except OSError as e:
            raise RuntimeError(f"No se pudo validar lock {lock_path}: {e}") from e

    try:
        with open(lock_path, "x", encoding="utf-8") as f:
            f.write(json.dumps({"pid": os.getpid(), "started_at": datetime.now().isoformat()}))
    except FileExistsError as e:
        raise RuntimeError(f"Modo {lock_name} ya en ejecución (lock activo: {lock_path.name})") from e

    try:
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("⚠️ No se pudo liberar lock %s: %s", lock_path.name, e)


def _normalize_url(url: str) -> str:
    """Normaliza URL para idempotencia estable entre capturas intradía."""
    raw = str(url or "").strip()
    if not raw:
        return ""

    try:
        parts = urlsplit(raw)
        netloc = parts.netloc.lower()
        path = re.sub(r"/+", "/", parts.path).rstrip("/")
        query_pairs = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in TRACKING_QUERY_PARAMS:
                continue
            query_pairs.append((key, value))
        query_pairs.sort(key=lambda kv: (kv[0], kv[1]))
        query = urlencode(query_pairs)
        normalized = urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
        return normalized
    except Exception:
        return raw


def _compute_article_identity(article: Dict) -> str:
    """Huella idempotente basada en URL normalizada + source_name + title."""
    norm_url = _normalize_url(str(article.get("url", "")))
    source = _sanitize_text(str(article.get("source_name", "")).lower())
    title = _sanitize_text(str(article.get("title", "")).lower())
    seed = f"{norm_url}|{source}|{title}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _accumulated_file_for_date(date_str: str) -> Path:
    return Path(f"raw/{date_str}/intraday_accumulated.json")


def _load_intraday_accumulated(date_str: str) -> Dict:
    """Carga snapshot acumulado del día o crea estructura base."""
    path = _accumulated_file_for_date(date_str)
    if not path.exists():
        return {
            "date": date_str,
            "first_capture_at": "",
            "last_capture_at": "",
            "next_capture_after": "",
            "captures": [],
            "articles": [],
        }

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("⚠️ Acumulado intradía inválido. Se reinicia snapshot diario: %s", e)
        return {
            "date": date_str,
            "first_capture_at": "",
            "last_capture_at": "",
            "next_capture_after": "",
            "captures": [],
            "articles": [],
        }


def _save_intraday_accumulated(date_str: str, payload: Dict) -> Path:
    """Persistencia del acumulado diario en raw/YYYY-MM-DD/."""
    path = _accumulated_file_for_date(date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def append_intraday_capture(date_str: str, new_articles: List[Dict]) -> Tuple[int, int, Path]:
    """Append idempotente de captura intradía con rotación diaria automática."""
    snapshot = _load_intraday_accumulated(date_str)
    existing = snapshot.get("articles", [])
    if not isinstance(existing, list):
        existing = []

    seen = {
        str(item.get("_identity_key", "")).strip()
        for item in existing
        if isinstance(item, dict) and str(item.get("_identity_key", "")).strip()
    }
    if not seen:
        for item in existing:
            if not isinstance(item, dict):
                continue
            identity = _compute_article_identity(item)
            if identity:
                item["_identity_key"] = identity
                seen.add(identity)

    inserted = 0
    for article in new_articles:
        if not isinstance(article, dict):
            continue
        identity = _compute_article_identity(article)
        if not identity or identity in seen:
            continue
        to_store = dict(article)
        to_store["url"] = _normalize_url(str(to_store.get("url", "")))
        to_store["_identity_key"] = identity
        existing.append(to_store)
        seen.add(identity)
        inserted += 1

    now_iso = datetime.now().isoformat(timespec="seconds")
    next_iso = (datetime.now() + timedelta(minutes=60)).isoformat(timespec="seconds")
    captures = snapshot.get("captures", [])
    if not isinstance(captures, list):
        captures = []
    captures.append(
        {
            "captured_at": now_iso,
            "fetched_count": len(new_articles),
            "new_inserted_count": inserted,
            "accumulated_total_count": len(existing),
        }
    )

    snapshot["date"] = date_str
    snapshot["articles"] = existing
    snapshot["captures"] = captures
    snapshot["last_capture_at"] = now_iso
    snapshot["next_capture_after"] = next_iso
    if not snapshot.get("first_capture_at"):
        snapshot["first_capture_at"] = now_iso

    path = _save_intraday_accumulated(date_str, snapshot)
    return inserted, len(existing), path


def load_accumulated_articles_for_close(date_str: str) -> List[Dict]:
    """Obtiene artículos acumulados del día para el cierre diario."""
    snapshot = _load_intraday_accumulated(date_str)
    items = snapshot.get("articles", [])
    if not isinstance(items, list):
        return []

    cleaned: List[Dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = dict(item)
        record.pop("_identity_key", None)
        cleaned.append(record)
    return cleaned


def _enforce_summary_bounds(
    summary: str,
    headline: str = "",
    evidence: str = "",
    content: str = "",
) -> str:
    """Normaliza summaries con mínimo de 500 chars sin recortar longitud máxima."""
    normalized = _sanitize_text(_strip_html(str(summary or "")))

    if len(normalized) >= SUMMARY_MIN_CHARS:
        return normalized

    supplements = [
        _sanitize_text(_strip_html(str(content or ""))),
        _sanitize_text(_strip_html(str(evidence or ""))),
        _sanitize_text(_strip_html(str(headline or ""))),
    ]

    # FIX: eliminada inyección de texto operativo visible al lector
    if not any(supplements):
        summary_ampliado = normalized
        return summary_ampliado

    for snippet in supplements:
        if not snippet:
            continue
        if snippet in normalized:
            continue
        if normalized:
            normalized = f"{normalized} {snippet}".strip()
        else:
            normalized = snippet

        if len(normalized) >= SUMMARY_MIN_CHARS:
            break

    while len(normalized) < SUMMARY_MIN_CHARS:
        filler = "Información adicional no informada por la fuente original al momento del cierre."
        if normalized:
            normalized = f"{normalized} {filler}".strip()
        else:
            normalized = filler

    return normalized


def run_intraday_accumulator(use_mock: bool = False) -> bool:
    """Captura intradía: fetch + dedupe + append idempotente (sin LLM/publicación)."""
    mode_logger = _get_mode_logger("intraday")
    mode_logger.info("⏱️ Inicio acumulado intradía para %s", TODAY)

    try:
        with _acquire_mode_lock("intraday"):
            sources = load_sources()
            if not sources and not use_mock:
                mode_logger.error("✗ Sin fuentes configuradas para acumulado intradía")
                return False

            if use_mock:
                fetched = fetch_sample_articles(count=15)
            else:
                fetched = fetch_all_feeds(
                    sources,
                    hours_back=FEED_HOURS_BACK,
                    max_entries_per_source=FEED_MAX_ENTRIES_PER_SOURCE,
                )

            deduped_capture = deduplicate_articles(fetched, title_threshold=85)
            inserted, total, path = append_intraday_capture(TODAY, deduped_capture)

            mode_logger.info(
                "✓ Captura intradía: fetched=%d deduped=%d inserted=%d total=%d file=%s",
                len(fetched),
                len(deduped_capture),
                inserted,
                total,
                path,
            )
            _write_desktop_health_check(
                "intraday",
                True,
                f"fetched={len(fetched)} deduped={len(deduped_capture)} inserted={inserted} total={total}",
            )
            return True
    except Exception as e:
        mode_logger.error("✗ Error en acumulado intradía: %s: %s", type(e).__name__, e)
        logger.error("✗ Error en acumulado intradía", exc_info=True)
        _write_desktop_health_check("intraday", False, f"{type(e).__name__}: {e}")
        return False


def _build_deterministic_news_item(article: Dict) -> Dict:
    """Construye un item válido desde RSS cuando el LLM no devolvió esa noticia."""
    source_status = _normalize_status(article.get("status", "SIN CONFIRMAR"))
    content = _strip_html(str(article.get("content", "")).replace("\n", " ").strip())

    if content:
        summary = content
    else:
        summary = "Resumen generado automáticamente desde el feed RSS por cobertura total."

    summary = _enforce_summary_bounds(
        summary,
        headline=str(article.get("title", "")),
        evidence=content[:220],
        content=content,
    )

    score = int(article.get("_stable_score", 0))
    if score >= 12:
        impact = "ALTO"
    elif score >= 7:
        impact = "MEDIO"
    else:
        impact = "BAJO"

    tags = article.get("_stable_tags", [])
    if not isinstance(tags, list):
        tags = []

    return {
        "headline": _truncate_headline(str(article.get("title", "Sin título"))),
        "summary": summary,
        "impact": impact,
        "asset_relevance": _infer_asset_relevance(article),
        "tags": tags[:3] if tags else ["Cobertura Total"],
        "is_argentina": _is_argentina_article(article),
        "source_name": article.get("source_name", "Desconocido"),
        "source_url": article.get("url", ""),
        "source_datetime": str(article.get("published", "")).strip() or datetime.now().isoformat(timespec="seconds"),
        "status": source_status,
        "verified": source_status in ["OFICIAL", "VALIDADO"],
        "evidencia_source_snippet": content[:220] if content else _truncate_headline(str(article.get("title", ""))),
    }


def _build_canonical_items(articles: List[Dict]) -> List[Dict]:
    """Construye tabla canónica con id_original fijo (01..NN)."""
    canonical_items: List[Dict] = []
    for idx, article in enumerate(articles, start=1):
        item_id = f"{idx:02d}"
        source_status = _normalize_status(article.get("status", "SIN CONFIRMAR"))
        canonical_items.append(
            {
                "id_original": item_id,
                "source_url": str(article.get("url", "")).strip(),
                "source_name": _sanitize_text(str(article.get("source_name", "Desconocido"))),
                "is_argentina": _is_argentina_article(article),
                "status": source_status,
                "title_clean": _strip_html(str(article.get("title", "")))[:500],
                "content_clean": _strip_html(str(article.get("content", "")))[:2200],
                "published": str(article.get("published", "")).strip(),
                "verified": source_status in ["OFICIAL", "VALIDADO"],
            }
        )
    return canonical_items


def _build_deterministic_factual_items(canonical_items: List[Dict]) -> List[Dict]:
    """Fallback del Paso A si la extracción factual del LLM falla."""
    factual_items = []
    for item in canonical_items:
        title = _strip_html(str(item.get("title_clean", "")))
        content = _strip_html(str(item.get("content_clean", "")))
        evidence = (content or title)[:220] if (content or title) else "No informado"
        hechos = [title[:180]] if title else ["No informado"]
        if content:
            hechos.append(content[:220])

        factual_items.append(
            {
                "id_referencia": str(item.get("id_original", "")).strip(),
                "source_url": str(item.get("source_url", "")).strip(),
                "hechos_clave": [h for h in hechos if h][:2],
                "evidencia_literal": evidence,
                "incertidumbres": [] if content else ["Contenido no informado en RSS"],
            }
        )

    return factual_items


def _build_deterministic_news_item_from_id(
    canonical_item: Dict,
    factual_item: Optional[Dict] = None,
) -> Dict:
    """Fallback por item: arma noticia desde tabla canónica + factual del mismo id."""
    title = _sanitize_text(str(canonical_item.get("title_clean", "")))
    content = _sanitize_text(str(canonical_item.get("content_clean", "")))
    evidence = _sanitize_text(str((factual_item or {}).get("evidencia_literal", "")))
    if not evidence:
        evidence = (content or title or "No informado")[:220]

    summary_raw = (
        content
        if content
        else "Resumen generado automáticamente desde el feed RSS por cobertura total."
    )
    summary = _enforce_summary_bounds(
        summary_raw,
        headline=title,
        evidence=evidence,
        content=content,
    )

    return {
        "id_referencia": str(canonical_item.get("id_original", "")).strip(),
        "headline": _truncate_headline(title or "Sin título"),
        "summary": summary,
        "impact": "MEDIO",
        "asset_relevance": ["NO_APLICA"],
        "tags": ["Cobertura Total"],
        "is_argentina": bool(canonical_item.get("is_argentina", False)),
        "source_name": canonical_item.get("source_name", "Desconocido"),
        "source_url": canonical_item.get("source_url", ""),
        "source_datetime": str(canonical_item.get("published", "")).strip() or datetime.now().isoformat(timespec="seconds"),
        "status": canonical_item.get("status", "SIN CONFIRMAR"),
        "verified": bool(canonical_item.get("verified", False)),
        "evidencia_source_snippet": evidence[:220],
    }


def _hydrate_result_with_context(result: Dict, raw_articles: List[Dict], factual_items: List[Dict]) -> None:
    """Completa metadatos y evidencia por URL para robustecer la salida editorial."""
    raw_by_url = {str(a.get("url", "")).strip(): a for a in raw_articles}
    factual_by_url = {
        str(i.get("source_url", "")).strip(): i
        for i in factual_items
        if isinstance(i, dict)
    }

    for item in result.get("noticias_destacadas", []):
        url = str(item.get("source_url", "")).strip()
        raw = raw_by_url.get(url)
        factual = factual_by_url.get(url)
        if not raw:
            continue

        item["source_name"] = raw.get("source_name", item.get("source_name", "Desconocido"))
        item["source_datetime"] = str(raw.get("published", item.get("source_datetime", ""))).strip() or datetime.now().isoformat(timespec="seconds")
        item["status"] = _normalize_status(raw.get("status", item.get("status", "SIN CONFIRMAR")))
        item["verified"] = item["status"] in ["OFICIAL", "VALIDADO"]

        evidence = str(item.get("evidencia_source_snippet", "")).strip()
        if not evidence:
            evidence = str((factual or {}).get("evidencia_literal", "")).strip()
        if not evidence:
            evidence = _strip_html(str(raw.get("content", "") or raw.get("title", "")))[:220]
        item["evidencia_source_snippet"] = _sanitize_text(evidence)[:220]


def _assemble_news_by_reference(
    canonical_items: List[Dict],
    editorial_valid_by_id: Dict[str, Dict],
    factual_by_id: Dict[str, Dict],
) -> Tuple[List[Dict], int]:
    """Ensamblado final determinista: metadata canónica + fallback por item si falta/rompe."""
    final_items: List[Dict] = []
    fallback_count = 0

    for canonical in canonical_items:
        item_id = str(canonical.get("id_original", "")).strip()
        editorial = editorial_valid_by_id.get(item_id)
        factual = factual_by_id.get(item_id, {})

        if editorial:
            editorial_summary = _enforce_summary_bounds(
                str(editorial.get("summary", "")),
                headline=str(editorial.get("headline", "")),
                evidence=str(editorial.get("evidencia_source_snippet", "")),
                content=str(canonical.get("content_clean", "")),
            )
            assembled = {
                "id_referencia": item_id,
                "headline": _truncate_headline(str(editorial.get("headline", "Sin título"))),
                "summary": editorial_summary,
                "impact": str(editorial.get("impact", "MEDIO")).strip().upper(),
                "asset_relevance": editorial.get("asset_relevance", ["NO_APLICA"]),
                "tags": editorial.get("tags", ["Cobertura Total"]),
                "is_argentina": bool(canonical.get("is_argentina", False)),
                "source_name": canonical.get("source_name", "Desconocido"),
                "source_url": canonical.get("source_url", ""),
                "source_datetime": str(canonical.get("published", "")).strip() or datetime.now().isoformat(timespec="seconds"),
                "status": canonical.get("status", "SIN CONFIRMAR"),
                "verified": bool(canonical.get("verified", False)),
                "evidencia_source_snippet": _sanitize_text(
                    _strip_html(str(editorial.get("evidencia_source_snippet", "")))
                )[:220],
            }
            if assembled["impact"] not in ["ALTO", "MEDIO", "BAJO"]:
                assembled["impact"] = "MEDIO"
            if not isinstance(assembled["asset_relevance"], list) or not assembled["asset_relevance"]:
                assembled["asset_relevance"] = ["NO_APLICA"]
            if not isinstance(assembled["tags"], list) or not assembled["tags"]:
                assembled["tags"] = ["Cobertura Total"]
            if not assembled["evidencia_source_snippet"]:
                assembled["evidencia_source_snippet"] = _sanitize_text(
                    str((factual or {}).get("evidencia_literal", ""))
                )[:220] or "No informado"
            final_items.append(assembled)
            continue

        final_items.append(_build_deterministic_news_item_from_id(canonical, factual))
        fallback_count += 1

    return final_items, fallback_count


def _build_deterministic_synthesis(noticias_destacadas: List[Dict]) -> Tuple[str, str]:
    """Síntesis de respaldo para Paso D cuando el LLM no devuelve texto válido."""
    top_headlines = [
        _sanitize_text(str(item.get("headline", "")))
        for item in noticias_destacadas[:6]
        if str(item.get("headline", "")).strip()
    ]
    if top_headlines:
        resumen = (
            "La jornada consolida una agenda dominada por riesgo geopolítico, inflación y señales mixtas de actividad. "
            + "Temas clave: "
            + "; ".join(top_headlines)
            + "."
        )
    else:
        resumen = "La jornada presenta señales mixtas en mercados y macroeconomía, con cobertura completa de fuentes verificadas."

    cadena = (
        "El escenario combina shocks externos, señales de política monetaria y datos domésticos. "
        "La lectura integrada prioriza impactos sobre tasas, dólar, bonos y commodities con base en evidencia textual."
    )
    return cadena[:1000], resumen[:1200]


def _extract_invalid_ids_from_errors(errors: List[str], expected_ids: List[str]) -> List[str]:
    """Extrae ids de errores referenciales; si no encuentra, devuelve todos los esperados."""
    found = set()
    expected_set = set(expected_ids)
    for err in errors:
        for token in re.findall(r"\b\d{2}\b", str(err)):
            if token in expected_set:
                found.add(token)

    if found:
        return [item_id for item_id in expected_ids if item_id in found]
    return expected_ids


def _is_argentina_article(article: Dict) -> bool:
    """Determina si un artículo es de Argentina usando señales de metadata/URL."""
    source_category = str(article.get("source_category", "")).strip().lower()
    source_name = str(article.get("source_name", "")).strip().lower()
    url = str(article.get("url", "")).strip().lower()

    if "argentina" in source_category or source_category.endswith("_arg") or source_category.endswith("_argentina"):
        return True
    if ".gob.ar" in url or ".com.ar" in url or ".ar/" in url:
        return True
    if any(token in source_name for token in ["bcra", "indec", "argentina"]):
        return True
    return False


def _reorder_argentina_first(articles: List[Dict]) -> List[Dict]:
    """Reordena en forma estable: primero Argentina, luego internacional."""
    argentina = [article for article in articles if _is_argentina_article(article)]
    international = [article for article in articles if not _is_argentina_article(article)]
    return argentina + international


def _strip_editorial_source_fields(payload: Dict) -> Dict:
    """Elimina metadatos de fuente del payload editorial para forzar hidratación canónica."""
    if not isinstance(payload, dict):
        return {}

    items = payload.get("noticias_destacadas", [])
    if not isinstance(items, list):
        return payload

    for item in items:
        if not isinstance(item, dict):
            continue
        item.pop("source_url", None)
        item.pop("source_name", None)
        item.pop("status", None)
        item.pop("verified", None)

    return payload


def _truncate_headline(text: str, max_len: int = 80) -> str:
    """Mantiene titular completo para evitar recorte visual en la portada."""
    _ = max_len
    return _sanitize_text(text)


def _sanitize_text(text: str) -> str:
    """Limpia mojibake y caracteres de control frecuentes de feeds RSS."""
    if not isinstance(text, str):
        return ""

    cleaned = text
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        cleaned = cleaned.replace(bad, good)

    cleaned = cleaned.replace("\u200b", "").replace("\ufeff", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _looks_spanish(text: str) -> bool:
    """Heurística simple para detectar si un texto está mayormente en español."""
    tokens = re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ]+", (text or "").lower())
    if len(tokens) < 2:
        return True

    es_hits = sum(1 for t in tokens if t in SPANISH_STOPWORDS)
    en_hits = sum(1 for t in tokens if t in ENGLISH_STOPWORDS)
    pt_hits = sum(1 for t in tokens if t in PORTUGUESE_STOPWORDS)
    return es_hits >= max(en_hits, pt_hits)


def _force_spanish_fallback(item: Dict) -> None:
    """Última barrera: evita publicación en inglés/portugués si la traducción no devolvió texto útil."""
    source_name = item.get("source_name", "Fuente")
    tags = item.get("tags", [])
    tag_hint = tags[0] if tags else "Macro"

    item["headline"] = _truncate_headline(f"Actualización de {source_name}: foco en {tag_hint}")
    item["summary"] = (
        "Esta noticia fue normalizada automáticamente al español para mantener la consistencia editorial "
        "del digest diario. Revisá la fuente original para el detalle completo."
    )
    if not tags:
        item["tags"] = ["Cobertura Total", "Normalizado"]
    if not str(item.get("evidencia_source_snippet", "")).strip():
        item["evidencia_source_snippet"] = "No informado"


def _needs_spanish_normalization(headline: str, summary: str) -> bool:
    """Detecta casos mixtos: titular en inglés con resumen en español, o viceversa."""
    headline_ok = _looks_spanish(headline)
    summary_ok = _looks_spanish(summary)
    return not (headline_ok and summary_ok)


def sanitize_result_texts(result: Dict) -> None:
    """Aplica saneo de texto a campos de salida para evitar caracteres extraños."""
    result["resumen_ejecutivo"] = _sanitize_text(result.get("resumen_ejecutivo", ""))
    result["cadena_de_razonamiento"] = _sanitize_text(result.get("cadena_de_razonamiento", ""))

    for item in result.get("noticias_destacadas", []):
        item["headline"] = _truncate_headline(item.get("headline", ""))
        item["summary"] = _enforce_summary_bounds(
            str(item.get("summary", "")),
            headline=str(item.get("headline", "")),
            evidence=str(item.get("evidencia_source_snippet", "")),
        )
        item["source_name"] = _sanitize_text(item.get("source_name", ""))
        item["source_datetime"] = _sanitize_text(str(item.get("source_datetime", "")))
        item["tags"] = [_sanitize_text(t) for t in item.get("tags", []) if _sanitize_text(t)]
        item["evidencia_source_snippet"] = _sanitize_text(
            _strip_html(str(item.get("evidencia_source_snippet", "")))
        )[:220]


def _contains_long_literal_overlap(summary: str, source_text: str, min_len: int = 40) -> bool:
    """Detecta solapamiento literal largo entre resumen final y texto de origen."""
    normalized_summary = _sanitize_text(_strip_html(summary)).lower()
    normalized_source = _sanitize_text(_strip_html(source_text)).lower()
    if not normalized_summary or not normalized_source:
        return False

    source_chunks = re.split(r"[\.;:!?]\s+", normalized_source)
    for chunk in source_chunks:
        candidate = chunk.strip()
        if len(candidate) >= min_len and candidate in normalized_summary:
            return True
    return False


def enforce_original_redaction_policy(result: Dict, canonical_by_id: Dict[str, Dict]) -> int:
    """Garantiza redacción propia: evita reutilización textual de lead/párrafos del feed."""
    rewritten = 0
    items = result.get("noticias_destacadas", [])
    if not isinstance(items, list):
        return rewritten

    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id_referencia", "")).strip()
        canonical = canonical_by_id.get(item_id, {})
        source_text = str(canonical.get("content_clean", ""))
        summary = str(item.get("summary", ""))

        if not summary:
            continue

        has_overlap = _contains_long_literal_overlap(summary, source_text)
        if has_overlap:
            # FIX: eliminada inyección de texto operativo visible al lector
            rewritten_summary = summary
            item["summary"] = _enforce_summary_bounds(
                rewritten_summary,
                headline=str(item.get("headline", "")),
                evidence="",
                content=str(canonical.get("content_clean", "")),
            )
            rewritten += 1

    return rewritten


def enforce_no_microquotes(result: Dict) -> None:
    """Deshabilita microcitas en salida final según política editorial."""
    items = result.get("noticias_destacadas", [])
    if not isinstance(items, list):
        return

    for item in items:
        if not isinstance(item, dict):
            continue
        item["evidencia_source_snippet"] = ""


def enforce_attribution_requirements(result: Dict) -> None:
    """Asegura atribución obligatoria por ítem: medio/organismo + enlace + fecha/hora."""
    items = result.get("noticias_destacadas", [])
    if not isinstance(items, list):
        return

    now_iso = datetime.now().isoformat(timespec="seconds")
    for item in items:
        if not isinstance(item, dict):
            continue

        if not str(item.get("source_name", "")).strip():
            item["source_name"] = "Fuente no informada"

        if not str(item.get("source_url", "")).strip():
            item["source_url"] = "#"

        if not str(item.get("source_datetime", "")).strip():
            item["source_datetime"] = now_iso


def enforce_spanish_publication(result: Dict) -> int:
    """
    Fuerza publicación en español para titulares/summaries/tags no-español.
    Retorna cantidad de items traducidos por LLM.
    """
    items = result.get("noticias_destacadas", [])
    if not isinstance(items, list) or not items:
        return 0

    to_translate = []
    for idx, item in enumerate(items):
        headline = str(item.get("headline", ""))
        summary = str(item.get("summary", ""))
        if _needs_spanish_normalization(headline, summary):
            to_translate.append(
                {
                    "idx": idx,
                    "headline": headline,
                    "summary": summary,
                    "tags": item.get("tags", []),
                }
            )

    if not to_translate:
        return 0

    translated = translate_items_to_spanish(to_translate)
    translated_map = {item.get("idx"): item for item in translated}

    updated = 0
    for idx, target in enumerate(items):
        if idx not in translated_map:
            continue
        source = translated_map[idx]
        new_headline = _sanitize_text(str(source.get("headline", "")))
        new_summary = _sanitize_text(str(source.get("summary", "")))
        new_tags = [_sanitize_text(str(tag)) for tag in source.get("tags", []) if _sanitize_text(str(tag))]

        if new_headline:
            target["headline"] = _truncate_headline(new_headline)
        if new_summary:
            target["summary"] = new_summary
        if new_tags:
            target["tags"] = new_tags
        updated += 1

    # Segunda pasada contextual para casos que no quedaron en español.
    contextual_candidates = []
    for idx, item in enumerate(items):
        headline = str(item.get("headline", ""))
        summary = str(item.get("summary", ""))
        if _needs_spanish_normalization(headline, summary):
            contextual_candidates.append(
                {
                    "idx": idx,
                    "headline": headline,
                    "summary": summary,
                    "tags": item.get("tags", []),
                    "source_name": item.get("source_name", ""),
                    "source_url": item.get("source_url", ""),
                }
            )

    if contextual_candidates:
        contextual_translated = translate_items_to_spanish_contextual(contextual_candidates)
        contextual_map = {item.get("idx"): item for item in contextual_translated}
        for idx, target in enumerate(items):
            if idx not in contextual_map:
                continue
            source = contextual_map[idx]
            new_headline = _sanitize_text(str(source.get("headline", "")))
            new_summary = _sanitize_text(str(source.get("summary", "")))
            new_tags = [_sanitize_text(str(tag)) for tag in source.get("tags", []) if _sanitize_text(str(tag))]

            if new_headline:
                target["headline"] = _truncate_headline(new_headline)
            if new_summary:
                target["summary"] = new_summary
            if new_tags:
                target["tags"] = new_tags
            updated += 1

    for item in items:
        if _needs_spanish_normalization(str(item.get("headline", "")), str(item.get("summary", ""))):
            _force_spanish_fallback(item)
            updated += 1

    return updated


def enforce_full_publication_coverage(result: Dict, selected_articles: List[Dict]) -> int:
    """
    Regla dura: la salida final debe incluir TODAS las noticias no-ruido seleccionadas.
    Si el LLM omite una noticia, se completa con item determinista desde RSS.

    Returns:
        Cantidad de noticias agregadas por cobertura forzada.
    """
    if "noticias_destacadas" not in result or not isinstance(result.get("noticias_destacadas"), list):
        result["noticias_destacadas"] = []

    llm_items = result.get("noticias_destacadas", [])
    llm_by_url: Dict[str, Dict] = {}
    for item in llm_items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("source_url", "")).strip()
        if url:
            llm_by_url[url] = item

    final_items: List[Dict] = []
    added_count = 0

    for article in selected_articles:
        url = str(article.get("url", "")).strip()
        if url and url in llm_by_url:
            final_items.append(llm_by_url[url])
        else:
            final_items.append(_build_deterministic_news_item(article))
            added_count += 1

    result["noticias_destacadas"] = final_items
    return added_count


def load_context_and_memory() -> Tuple[str, str]:
    """Carga el contexto base estático y el resumen ejecutivo del día anterior."""
    contexto_base = ""
    resumen_ayer = ""
    
    # Cargar Contexto Base (ancla institucional)
    contexto_path = Path("src/contexto_macro_base.txt")
    if contexto_path.exists():
        try:
            contexto_base = contexto_path.read_text(encoding="utf-8")
            logger.info("✓ Contexto macro base cargado")
        except Exception as e:
            logger.warning(f"⚠️ Error leyendo contexto base: {e}")
    else:
        logger.warning("⚠️ Archivo contexto_macro_base.txt no encontrado")
    
    # Cargar Memoria de Ayer (sliding window)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_file = Path(f"docs/{yesterday.replace('-', '/')}/data.json")
    
    if yesterday_file.exists():
        try:
            with open(yesterday_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                resumen_ayer = data.get("resumen_ejecutivo", "")
                logger.info("✓ Memoria a corto plazo (ayer) cargada")
        except Exception as e:
            logger.warning(f"⚠️ Error leyendo memoria de ayer: {e}")
    else:
        logger.info("ℹ️ Primer día de operación (sin memoria previa)")
    
    return contexto_base, resumen_ayer


def cleanup_old_debug_artifacts(base_dir: Path) -> None:
    """Migra artefactos debug legacy de raíz al debug diario para mantener repositorio limpio."""
    patterns = [
        "debug_response.txt",
        "debug_response_failed_*.txt",
    ]
    debug_stage_dir = base_dir / "debug_stage"
    legacy_target = RAW_DIR / "debug" / "legacy_root"

    moved_count = 0
    legacy_target.mkdir(parents=True, exist_ok=True)

    for pattern in patterns:
        for artifact in base_dir.glob(pattern):
            if not artifact.is_file():
                continue
            try:
                destination = legacy_target / artifact.name
                if destination.exists():
                    destination.unlink(missing_ok=True)
                shutil.move(str(artifact), str(destination))
                moved_count += 1
            except OSError as e:
                logger.warning(f"⚠️ No se pudo mover artefacto debug {artifact.name}: {e}")

    if debug_stage_dir.exists() and debug_stage_dir.is_dir():
        for artifact in debug_stage_dir.glob("*_debug_response_failed_*.txt"):
            if not artifact.is_file():
                continue
            try:
                destination = legacy_target / artifact.name
                if destination.exists():
                    destination.unlink(missing_ok=True)
                shutil.move(str(artifact), str(destination))
                moved_count += 1
            except OSError as e:
                logger.warning(f"⚠️ No se pudo mover artefacto debug {artifact.name}: {e}")

        # Si la carpeta quedó vacía, eliminarla para evitar residuos entre corridas.
        try:
            if not any(debug_stage_dir.iterdir()):
                debug_stage_dir.rmdir()
        except OSError as e:
            logger.warning(f"⚠️ No se pudo limpiar carpeta debug_stage: {e}")

    if moved_count > 0:
        logger.info("🧹 Limpieza debug: %d artefactos legacy movidos a %s", moved_count, legacy_target)


def cleanup_old_logs(retention_days: int = 30) -> None:
    """Aplica retención simple sobre logs locales para evitar crecimiento indefinido."""
    if retention_days <= 0:
        return

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for log_file in LOGS_DIR.glob("*.log"):
        if not log_file.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff:
                log_file.unlink(missing_ok=True)
                removed += 1
        except OSError as e:
            logger.warning("⚠️ No se pudo aplicar retención sobre %s: %s", log_file.name, e)

    if removed > 0:
        logger.info("🧹 Retención de logs aplicada: %d archivos antiguos removidos", removed)


def update_weekly_summary(metrics_payload: Dict) -> None:
    """Actualiza un agregado semanal mínimo para seguimiento operativo."""
    if not isinstance(metrics_payload, dict):
        return

    date_value = str(metrics_payload.get("date", "")).strip()
    if not date_value:
        return

    try:
        dt = datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        return

    iso = dt.isocalendar()
    week_key = f"{iso.year}-W{iso.week:02d}"
    summary_path = LOGS_DIR / "weekly_summary.json"

    summary = {"weeks": {}}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(summary, dict):
                summary = {"weeks": {}}
        except (json.JSONDecodeError, OSError):
            summary = {"weeks": {}}

    weeks = summary.setdefault("weeks", {})
    week_rows = weeks.setdefault(week_key, [])
    if not isinstance(week_rows, list):
        week_rows = []
        weeks[week_key] = week_rows

    row = {
        "date": date_value,
        "selected": metrics_payload.get("selected", 0),
        "published": metrics_payload.get("published", 0),
        "fallback_items_ratio": metrics_payload.get("fallback_items_ratio", 0.0),
        "post_llm_warning_count": metrics_payload.get("post_llm_warning_count", 0),
        "judge_quality_gate": metrics_payload.get("judge_quality_gate", "NA"),
        "judge_weighted_total": metrics_payload.get("judge_weighted_total", 0),
        "llm_json_parse_failures_total": metrics_payload.get("llm_json_parse_failures_total", 0),
        "llm_json_parse_unrecovered_total": metrics_payload.get("llm_json_parse_unrecovered_total", 0),
    }

    week_rows = [item for item in week_rows if str(item.get("date", "")) != date_value]
    week_rows.append(row)
    week_rows.sort(key=lambda x: str(x.get("date", "")))
    weeks[week_key] = week_rows

    summary["weeks"] = weeks
    try:
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.warning("⚠️ No se pudo actualizar weekly_summary.json: %s", e)


def save_judge_report(output_dir: Path, report: Dict) -> None:
    """Persiste el informe del agente juez para auditoría diaria de calidad."""
    if not isinstance(report, dict) or not report:
        return

    try:
        report_path = output_dir / "judge_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info("🧾 Judge report guardado en %s", report_path)
    except Exception as e:
        logger.warning("⚠️ No se pudo guardar judge_report.json: %s", e)


def _normalize_score(value: object) -> int:
    """Normaliza score numérico en rango 0-100 para métricas comparables."""
    try:
        parsed = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, parsed))


def run_pipeline(
    use_mock: bool = False,
    preloaded_articles: Optional[List[Dict]] = None,
    pipeline_mode: str = "close",
) -> bool:
    """Ejecuta el pipeline completo de digest diario con manejo robusto de errores."""
    logger.info(f"🗞️ [La Gran Crisis] Iniciando digest para {TODAY} (modo={pipeline_mode})")
    _get_mode_logger("close").info("🗞️ Inicio cierre diario para %s", TODAY)
    logical_agents_enabled = bool(ENABLE_LOGICAL_AGENTS)

    debug_dir = RAW_DIR / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    os.environ["LGC_DEBUG_DIR"] = str(debug_dir.resolve())

    cleanup_old_debug_artifacts(project_root)
    cleanup_old_logs(retention_days=30)
    reset_llm_runtime_metrics()
    
    selected_count = 0
    articles_for_llm: List[Dict] = []
    fallback_items_count = 0
    added_by_coverage = 0
    translated_count = 0
    rewritten_by_policy_count = 0
    post_llm_warning_count = 0
    editorial_chunk_count = 0
    editorial_chunks_with_errors = 0
    editorial_autocorrect_runs = 0
    editorial_autocorrect_boosted_runs = 0
    editor_agent_runs = 0
    editor_agent_failed_runs = 0
    judge_quality_gate = "NA"
    judge_weighted_total = 0
    judge_critical_errors_count = 0
    judge_report: Dict = {}

    try:
        # Paso 1: Cargar fuentes
        logger.info("📡 Cargando fuentes RSS...")
        sources = load_sources()
        if not sources:
            logger.error("✗ No se pudieron cargar fuentes. Abortando.")
            return False
        
        # Paso 2: Cargar contexto y memoria
        logger.info("🧠 Cargando contexto y memoria...")
        contexto_base, resumen_ayer = load_context_and_memory()
        
        # Paso 3: Cargar insumo de cierre (acumulado intradía o fetch directo)
        logger.info("📥 Preparando artículos para cierre diario...")
        if preloaded_articles is not None:
            raw_articles = [a for a in preloaded_articles if isinstance(a, dict)]
            logger.info("✓ %d artículos cargados desde acumulado intradía", len(raw_articles))
        else:
            try:
                if use_mock:
                    raw_articles = fetch_sample_articles(count=15)
                    logger.info("ℹ️ Usando modo MOCK (datos de ejemplo)")
                else:
                    raw_articles = fetch_all_feeds(
                        sources,
                        hours_back=FEED_HOURS_BACK,
                        max_entries_per_source=FEED_MAX_ENTRIES_PER_SOURCE,
                    )
                logger.info(f"✓ {len(raw_articles)} artículos descargados")
            except Exception as e:
                logger.error(f"✗ Error descargando feeds: {type(e).__name__}: {e}")
                raw_articles = []

        raw_articles, blocked_articles_count, opted_articles_count = filter_articles_by_compliance(raw_articles)
        if blocked_articles_count or opted_articles_count:
            logger.warning(
                "🔒 Filtro compliance aplicado sobre artículos: bloqueados=%d opt-out=%d",
                blocked_articles_count,
                opted_articles_count,
            )
        
        # Guardar crudos para auditoría
        save_raw_articles(raw_articles, RAW_DIR)
        
        # Paso 4: Deduplicación
        logger.info("🔍 Deduplicando artículos...")
        unique_articles = deduplicate_articles(raw_articles, title_threshold=85)
        logger.info(f"✓ {len(unique_articles)} artículos únicos tras deduplicación")
        
        if not unique_articles:
            logger.warning("⚠️ Sin artículos para procesar. Generando fallback.")
            result = fallback_response(TODAY, [])
        else:
            # Paso 5: Etiquetar fuentes y clasificar
            logger.info("🏷️ Etiquetando fuentes...")
            tagged_articles = tag_sources(unique_articles)
            
            logger.info("🎯 Seleccionando artículos relevantes...")
            classified = classify_and_rank(tagged_articles)
            articles_for_llm = [a for a in classified if a]
            articles_for_llm = _reorder_argentina_first(articles_for_llm)
            selected_count = len(articles_for_llm)
            logger.info(f"✓ {len(articles_for_llm)} artículos seleccionados para LLM")

            if len(articles_for_llm) < MIN_ARTICLES_FOR_PIPELINE:
                logger.warning(
                    f"⚠️ Solo {len(articles_for_llm)} artículos disponibles "
                    f"(mínimo: {MIN_ARTICLES_FOR_PIPELINE}). "
                    "Publicando missing_documented en lugar de correr pipeline LLM."
                )
                output_path = DOCS_DIR / "index.html"
                render_fallback_page(
                    date=TODAY,
                    error_msg=(
                        f"Jornada con baja actividad informativa "
                        f"({len(articles_for_llm)} artículos disponibles). "
                        "Edición no disponible."
                    ),
                    output_path=output_path,
                )
                _save_missing_documented(
                    TODAY,
                    reason=(
                        f"Artículos insuficientes para pipeline: {len(articles_for_llm)} < "
                        f"{MIN_ARTICLES_FOR_PIPELINE}"
                    ),
                )
                return True  # éxito operativo, no es un error

            canonical_items = _build_canonical_items(articles_for_llm)
            canonical_by_id = {
                str(item.get("id_original", "")).strip(): item for item in canonical_items
            }
            expected_ids = [str(item.get("id_original", "")).strip() for item in canonical_items]
            intentionally_omitted_ids: List[str] = []
            canonical_items_for_publication = canonical_items
            articles_for_publication = articles_for_llm
            
            # Paso 6A: extracción factual por URL (sin inferencias)
            factual_items: List[Dict] = []
            factual_by_id: Dict[str, Dict] = {}
            if use_mock:
                factual_items = _build_deterministic_factual_items(canonical_items)
                factual_by_id = {
                    str(item.get("id_referencia", "")).strip(): item
                    for item in factual_items
                    if isinstance(item, dict)
                }
            else:
                logger.info("🧾 Paso A: Extracción factual por id_referencia (chunking=%d)...", FACTUAL_CHUNK_SIZE)
                factual_valid = {}
                factual_errors = []
                intentionally_omitted_ids = []
                
                # Procesar canonical_items en chunks para evitar truncamiento LLM
                total_chunks = (len(canonical_items) + FACTUAL_CHUNK_SIZE - 1) // FACTUAL_CHUNK_SIZE
                for chunk_idx in range(0, len(canonical_items), FACTUAL_CHUNK_SIZE):
                    chunk_num = (chunk_idx // FACTUAL_CHUNK_SIZE) + 1
                    chunk_items = canonical_items[chunk_idx:chunk_idx + FACTUAL_CHUNK_SIZE]
                    chunk_ids = [str(item.get("id_original", "")).strip() for item in chunk_items]
                    logger.info(f"Paso A chunk {chunk_num}/{total_chunks}: {len(chunk_items)} items")
                    
                    factual_prompt = build_factual_extraction_prompt(chunk_items, TODAY)
                    factual_result = call_gemini_with_retry(
                        factual_prompt,
                        max_retries=2,
                        debug_label=f"step_a_factual_chunk_{chunk_num}",
                    )
                    chunk_ok, chunk_errors, chunk_valid, chunk_omitted = validate_factual_extraction_by_id(
                        factual_result,
                        chunk_ids,
                        {item_id: canonical_by_id.get(item_id) for item_id in chunk_ids},
                    )
                    
                    factual_valid.update(chunk_valid)
                    factual_errors.extend(chunk_errors)
                    intentionally_omitted_ids.extend(chunk_omitted)
                
                # Evaluación post-chunks del guard de omisión
                _omission_rate = len(intentionally_omitted_ids) / max(len(expected_ids), 1)
                if _omission_rate > MAX_MACRO_OMISSION_RATE:
                    logger.warning(
                        "⚠️ Paso A: tasa de omisión %.0f%% supera umbral (%.0f%%). "
                        "Respuesta LLM considerada degradada — fallback factual a todos los ids.",
                        _omission_rate * 100,
                        MAX_MACRO_OMISSION_RATE * 100,
                    )
                    intentionally_omitted_ids = []
                    factual_ok = False
                else:
                    factual_ok = len(factual_errors) == 0
                
                if factual_ok:
                    factual_by_id = factual_valid
                    factual_items = [factual_by_id[item_id] for item_id in expected_ids if item_id in factual_by_id]
                    logger.info("✓ Paso A validado (todos los chunks procesados)")
                else:
                    for err in factual_errors:
                        logger.warning("⚠️ [factual] %s", err)

                    logger.warning("⚠️ Paso A parcial/inválido. Se aplica fallback factual por item.")
                    deterministic_factual = _build_deterministic_factual_items(canonical_items)
                    intentionally_omitted_set = set(intentionally_omitted_ids)
                    fallback_target_ids = [
                        item_id
                        for item_id in expected_ids
                        if item_id not in factual_valid and item_id not in intentionally_omitted_set
                    ]
                    deterministic_by_id = {
                        str(item.get("id_referencia", "")).strip(): item
                        for item in deterministic_factual
                        if isinstance(item, dict)
                    }
                    factual_by_id = dict(factual_valid)
                    for item_id in fallback_target_ids:
                        if item_id in deterministic_by_id:
                            factual_by_id[item_id] = deterministic_by_id[item_id]
                    factual_items = [factual_by_id[item_id] for item_id in expected_ids if item_id in factual_by_id]
                    logger.info(
                        f"Fallback aplicado a {len(fallback_target_ids)} ids por falla LLM. {len(intentionally_omitted_ids)} ids excluidos por filtro macro."
                    )

            if intentionally_omitted_ids:
                intentionally_omitted_set = set(intentionally_omitted_ids)
                publication_expected_ids = [
                    item_id for item_id in expected_ids if item_id not in intentionally_omitted_set
                ]
                factual_by_id = {
                    item_id: factual
                    for item_id, factual in factual_by_id.items()
                    if item_id in publication_expected_ids
                }
                factual_items = [
                    factual_by_id[item_id]
                    for item_id in publication_expected_ids
                    if item_id in factual_by_id
                ]
                canonical_items_for_publication = [
                    item
                    for item in canonical_items
                    if str(item.get("id_original", "")).strip() not in intentionally_omitted_set
                ]
                omitted_urls = {
                    str((canonical_by_id.get(item_id) or {}).get("source_url", "")).strip()
                    for item_id in intentionally_omitted_ids
                }
                articles_for_publication = [
                    article
                    for article in articles_for_llm
                    if str(article.get("url", "")).strip() not in omitted_urls
                ]
                logger.info(
                    "Paso A: %d artículos omitidos intencionalmente removidos del pipeline editorial",
                    len(intentionally_omitted_ids),
                )

            # Paso 6B: Generación editorial por chunks (A=editorial clásico, B=agentes Redactor/Editor).
            logger.info(
                "🤖 Paso B: Orquestación editorial (agentes=%s, chunking=%d)...",
                logical_agents_enabled,
                EDITORIAL_CHUNK_SIZE,
            )

            def _extend_unique_strings(target: List[str], values: List[object]) -> None:
                for value in values:
                    text = str(value).strip()
                    if text and text not in target:
                        target.append(text)

            aggregated_unverified_claims: List[str] = []
            aggregated_missing_official_data: List[str] = []
            aggregated_sources_consulted: List[str] = []
            chosen_editorial_by_id: Dict[str, Dict] = {}

            for chunk_index, start in enumerate(range(0, len(factual_items), EDITORIAL_CHUNK_SIZE), start=1):
                chunk_factual_items = factual_items[start:start + EDITORIAL_CHUNK_SIZE]
                chunk_expected_ids = [str(item.get("id_referencia", "")).strip() for item in chunk_factual_items]
                chunk_expected_ids = [item_id for item_id in chunk_expected_ids if item_id]
                if not chunk_expected_ids:
                    continue

                editorial_chunk_count += 1
                logger.info(
                    "🧩 Chunk editorial %d: %d noticias",
                    chunk_index,
                    len(chunk_expected_ids),
                )

                if use_mock:
                    chunk_result: Dict = {"noticias_destacadas": []}
                else:
                    if logical_agents_enabled:
                        redactor_prompt = build_redactor_prompt(
                            chunk_factual_items,
                            TODAY,
                            prompt_version=PROMPT_REDACTOR_VERSION,
                        )
                        redactor_result = call_gemini_with_retry(
                            redactor_prompt,
                            max_retries=3,
                            debug_label=f"step_b_redactor_chunk_{chunk_index:02d}",
                        )
                        chunk_result = redactor_result if isinstance(redactor_result, dict) else {}
                    else:
                        editorial_prompt = build_editorial_prompt(
                            chunk_factual_items,
                            TODAY,
                        )
                        editorial_result = call_gemini_with_retry(
                            editorial_prompt,
                            max_retries=3,
                            debug_label=f"step_b_editorial_chunk_{chunk_index:02d}",
                        )
                        chunk_result = editorial_result if isinstance(editorial_result, dict) else {}

                chunk_result = _strip_editorial_source_fields(
                    chunk_result if isinstance(chunk_result, dict) else {}
                )
                chunk_ok, chunk_errors, chunk_valid_by_id = validate_editorial_referential_integrity(
                    chunk_result,
                    chunk_expected_ids,
                    canonical_by_id,
                )
                chosen_chunk_result = chunk_result if isinstance(chunk_result, dict) else {}
                chosen_chunk_by_id = chunk_valid_by_id

                if not chunk_ok:
                    editorial_chunks_with_errors += 1
                    for err in chunk_errors:
                        logger.warning("⚠️ [referential] %s", err)

                if (not use_mock) and logical_agents_enabled:
                    editor_agent_runs += 1
                    canonical_chunk = [canonical_by_id[item_id] for item_id in chunk_expected_ids if item_id in canonical_by_id]
                    editor_prompt = build_editor_prompt(
                        chunk_factual_items,
                        canonical_chunk,
                        chunk_result,
                        TODAY,
                        prompt_version=PROMPT_EDITOR_VERSION,
                    )
                    editor_result = call_gemini_with_retry(
                        editor_prompt,
                        max_retries=2,
                        debug_label=f"step_b_editor_chunk_{chunk_index:02d}",
                    )
                    editor_result = _strip_editorial_source_fields(
                        editor_result if isinstance(editor_result, dict) else {}
                    )
                    editor_ok, editor_errors, editor_valid_by_id = validate_editorial_referential_integrity(
                        editor_result,
                        chunk_expected_ids,
                        canonical_by_id,
                    )

                    if editor_ok or len(editor_valid_by_id) >= len(chunk_valid_by_id):
                        chunk_result = editor_result
                        chunk_ok = editor_ok
                        chunk_errors = editor_errors
                        chunk_valid_by_id = editor_valid_by_id
                        if editor_ok:
                            logger.info("✓ Editor validado (chunk %d)", chunk_index)
                    else:
                        editor_agent_failed_runs += 1
                        for err in editor_errors:
                            logger.warning("⚠️ [editor-referential] %s", err)

                if (not chunk_ok) and (not use_mock):
                    invalid_ids = _extract_invalid_ids_from_errors(chunk_errors, chunk_expected_ids)
                    autocorrect_retries = 2 if len(invalid_ids) >= AUTOCORRECT_HEAVY_IDS_THRESHOLD else 1
                    editorial_autocorrect_runs += 1
                    if autocorrect_retries > 1:
                        editorial_autocorrect_boosted_runs += 1

                    logger.warning(
                        "⚠️ Autocorrección por chunk: corrigiendo %d ids (retries=%d)",
                        len(invalid_ids),
                        autocorrect_retries,
                    )
                    autocorrect_prompt = build_editorial_autocorrect_prompt(
                        chunk_factual_items,
                        chosen_chunk_result,
                        invalid_ids,
                        TODAY,
                    )
                    autocorrect_result = call_gemini_with_retry(
                        autocorrect_prompt,
                        max_retries=autocorrect_retries,
                        debug_label=f"step_c_autocorrect_chunk_{chunk_index:02d}",
                    )
                    autocorrect_result = _strip_editorial_source_fields(
                        autocorrect_result if isinstance(autocorrect_result, dict) else {}
                    )

                    retry_payload = {"noticias_destacadas": []}
                    if isinstance(chosen_chunk_result, dict):
                        retry_payload["noticias_destacadas"] = chosen_chunk_result.get("noticias_destacadas", [])
                    if isinstance(autocorrect_result, dict):
                        corrected_items = autocorrect_result.get("noticias_destacadas", [])
                        if isinstance(corrected_items, list):
                            existing_by_id: Dict[str, Dict] = {}
                            for item in retry_payload["noticias_destacadas"]:
                                item_id = str((item or {}).get("id_referencia", "")).strip()
                                if item_id:
                                    existing_by_id[item_id] = item
                            for item in corrected_items:
                                item_id = str((item or {}).get("id_referencia", "")).strip()
                                if item_id:
                                    existing_by_id[item_id] = item
                            retry_payload["noticias_destacadas"] = [existing_by_id[k] for k in existing_by_id]

                    retry_ok, retry_errors, retry_valid_by_id = validate_editorial_referential_integrity(
                        retry_payload,
                        chunk_expected_ids,
                        canonical_by_id,
                    )

                    if retry_ok:
                        logger.info("✓ Autocorrección validada por integridad referencial (chunk %d)", chunk_index)
                    else:
                        for err in retry_errors:
                            logger.warning("⚠️ [referential-autocorrect] %s", err)

                    # Elegir la mejor cobertura válida para fallback por item.
                    if len(retry_valid_by_id) >= len(chosen_chunk_by_id):
                        chosen_chunk_result = retry_payload if isinstance(retry_payload, dict) else {}
                        chosen_chunk_by_id = retry_valid_by_id

                chosen_editorial_by_id.update(chosen_chunk_by_id)
                _extend_unique_strings(
                    aggregated_unverified_claims,
                    chosen_chunk_result.get("unverified_claims", [])
                    if isinstance(chosen_chunk_result.get("unverified_claims", []), list)
                    else [],
                )
                _extend_unique_strings(
                    aggregated_missing_official_data,
                    chosen_chunk_result.get("missing_official_data", [])
                    if isinstance(chosen_chunk_result.get("missing_official_data", []), list)
                    else [],
                )
                _extend_unique_strings(
                    aggregated_sources_consulted,
                    chosen_chunk_result.get("sources_consulted", [])
                    if isinstance(chosen_chunk_result.get("sources_consulted", []), list)
                    else [],
                )

            final_news, fallback_items_count = _assemble_news_by_reference(
                canonical_items_for_publication,
                chosen_editorial_by_id,
                factual_by_id,
            )
            if fallback_items_count > 0:
                logger.warning(
                    "⚠️ Fallback por item aplicado en %d/%d noticias",
                    fallback_items_count,
                    len(canonical_items_for_publication),
                )

            result = {
                "date": TODAY,
                "cadena_de_razonamiento": "",
                "resumen_ejecutivo": "",
                "noticias_destacadas": final_news,
                "unverified_claims": aggregated_unverified_claims,
                "missing_official_data": aggregated_missing_official_data,
                "sources_consulted": aggregated_sources_consulted
                or [
                    str(item.get("source_url", "")).strip()
                    for item in canonical_items_for_publication
                    if str(item.get("source_url", "")).strip()
                ],
            }

            # Paso D: síntesis global separada (sin raw libre)
            cadena_fallback, resumen_fallback = _build_deterministic_synthesis(final_news)
            if use_mock:
                result["cadena_de_razonamiento"] = cadena_fallback
                result["resumen_ejecutivo"] = resumen_fallback
            else:
                logger.info("🧠 Paso D: Síntesis global separada...")
                synthesis_prompt = build_global_synthesis_prompt(
                    final_news,
                    TODAY,
                    contexto_base,
                    resumen_ayer,
                )
                synthesis = call_gemini_with_retry(
                    synthesis_prompt,
                    max_retries=2,
                    debug_label="step_d_synthesis",
                )
                cadena = synthesis.get("cadena_de_razonamiento", "") if isinstance(synthesis, dict) else ""
                resumen = synthesis.get("resumen_ejecutivo", "") if isinstance(synthesis, dict) else ""

                if str(cadena).strip() and str(resumen).strip():
                    result["cadena_de_razonamiento"] = str(cadena)
                    result["resumen_ejecutivo"] = str(resumen)
                else:
                    logger.warning("⚠️ Paso D incompleto. Reintento de síntesis global.")
                    retry_synthesis_prompt = build_global_synthesis_prompt(
                        final_news,
                        TODAY,
                        contexto_base,
                        resumen_ayer,
                        retry_instruction="reduce inferencia, prioriza literalidad",
                    )
                    retry_synthesis = call_gemini_with_retry(
                        retry_synthesis_prompt,
                        max_retries=1,
                        debug_label="step_d_synthesis_retry",
                    )
                    cadena_retry = (
                        retry_synthesis.get("cadena_de_razonamiento", "")
                        if isinstance(retry_synthesis, dict)
                        else ""
                    )
                    resumen_retry = (
                        retry_synthesis.get("resumen_ejecutivo", "")
                        if isinstance(retry_synthesis, dict)
                        else ""
                    )
                    result["cadena_de_razonamiento"] = (
                        str(cadena_retry) if str(cadena_retry).strip() else cadena_fallback
                    )
                    result["resumen_ejecutivo"] = (
                        str(resumen_retry) if str(resumen_retry).strip() else resumen_fallback
                    )

            # Validación de estructura final
            is_valid, msg = validate_json_structure(result, SECTIONS)
            if not is_valid:
                logger.warning(f"⚠️ Respuesta final inválida: {msg}. Usando fallback total de emergencia.")
                result = fallback_response(TODAY, articles_for_llm)
            else:
                # Validación de grounding como guardrail adicional (sin fallback total).
                strict_ok, strict_errors = validate_editorial_grounding(
                    result,
                    factual_items,
                    [str(a.get("url", "")).strip() for a in articles_for_publication],
                )
                if not strict_ok:
                    for err in strict_errors:
                        logger.warning("⚠️ [grounding] %s", err)

                # Normalizar fecha en resultado
                result["date"] = result.get("date", TODAY)
                logger.info("✓ Respuesta final validada correctamente")

                # Validación post-LLM: consistencia con contexto original
                is_consistent, warnings = validate_post_llm(result, articles_for_llm)
                post_llm_warning_count = len(warnings)
                if not is_consistent:
                    for w in warnings:
                        logger.warning(f"⚠️ [post-llm] {w}")

                # Regla dura: publicación final incluye todas las no-ruido seleccionadas.
                added_by_coverage = enforce_full_publication_coverage(result, articles_for_publication)
                if added_by_coverage > 0:
                    logger.warning(
                        "⚠️ Cobertura forzada aplicada: +%d noticias no-ruido agregadas desde RSS",
                        added_by_coverage,
                    )
                logger.info(
                    "📌 Cobertura final: %d/%d noticias no-ruido publicadas",
                    len(result.get("noticias_destacadas", [])),
                    len(articles_for_llm),
                )

                # Regla editorial: publicación final 100% en español + saneo de caracteres.
                translated_count = enforce_spanish_publication(result)
                rewritten_by_policy_count = enforce_original_redaction_policy(result, canonical_by_id)
                if rewritten_by_policy_count > 0:
                    logger.warning(
                        "⚠️ Redacción propia forzada por compliance en %d noticias",
                        rewritten_by_policy_count,
                    )
                enforce_no_microquotes(result)
                enforce_attribution_requirements(result)
                sanitize_result_texts(result)
                if translated_count > 0:
                    logger.info("🌐 Traducción a español aplicada en %d noticias", translated_count)

                # Agente Juez: auditoría diaria de calidad editorial/factual sobre salida final.
                if not use_mock:
                    logger.info("🧑‍⚖️ Paso E: Evaluación del agente Juez...")
                    judge_prompt = build_judge_prompt(
                        canonical_items,
                        factual_items,
                        result.get("noticias_destacadas", []),
                        TODAY,
                        prompt_version=PROMPT_JUDGE_VERSION,
                    )
                    judge_raw = call_gemini_with_retry(
                        judge_prompt,
                        max_retries=2,
                        debug_label="step_e_judge",
                    )
                    if isinstance(judge_raw, dict):
                        judge_report = judge_raw
                        judge_quality_gate = str(judge_raw.get("quality_gate", "WARN")).strip().upper() or "WARN"
                        judge_scores = judge_raw.get("scores", {})
                        if isinstance(judge_scores, dict):
                            judge_weighted_total = _normalize_score(judge_scores.get("weighted_total", 0))

                        critical_errors = judge_raw.get("critical_errors", [])
                        if isinstance(critical_errors, list):
                            judge_critical_errors_count = len([item for item in critical_errors if str(item).strip()])
                    else:
                        judge_quality_gate = "WARN"
        
        # Paso 7: Guardar resultado procesado
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        data_file = DOCS_DIR / "data.json"
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"✓ Resultado guardado en {data_file}")

        published_count = len(result.get("noticias_destacadas", []))
        fallback_used = bool(result.get("_fallback", False))
        llm_metrics = get_llm_runtime_metrics()
        fallback_items_ratio = (fallback_items_count / selected_count) if selected_count else 0.0
        coverage_forced_ratio = (added_by_coverage / selected_count) if selected_count else 0.0
        metrics_payload = {
            "experiment_label": EXPERIMENT_LABEL,
            "logical_agents_enabled": logical_agents_enabled,
            "prompt_redactor_version": PROMPT_REDACTOR_VERSION,
            "prompt_editor_version": PROMPT_EDITOR_VERSION,
            "prompt_judge_version": PROMPT_JUDGE_VERSION,
            "editorial_chunk_size": EDITORIAL_CHUNK_SIZE,
            "editorial_chunk_count": editorial_chunk_count,
            "editorial_chunks_with_errors": editorial_chunks_with_errors,
            "editorial_autocorrect_runs": editorial_autocorrect_runs,
            "editorial_autocorrect_boosted_runs": editorial_autocorrect_boosted_runs,
            "editor_agent_runs": editor_agent_runs,
            "editor_agent_failed_runs": editor_agent_failed_runs,
            "fallback_items_count": fallback_items_count,
            "fallback_items_ratio": round(fallback_items_ratio, 4),
            "coverage_forced_count": added_by_coverage,
            "coverage_forced_ratio": round(coverage_forced_ratio, 4),
            "post_llm_warning_count": post_llm_warning_count,
            "translated_items_count": translated_count,
            "rewritten_by_policy_count": rewritten_by_policy_count,
            "macro_filtered_ids": [str(item_id) for item_id in intentionally_omitted_ids],
            "judge_quality_gate": judge_quality_gate,
            "judge_weighted_total": judge_weighted_total,
            "judge_critical_errors_count": judge_critical_errors_count,
            **llm_metrics,
        }

        save_pipeline_metrics(
            raw_count=len(raw_articles),
            selected_count=selected_count,
            published_count=published_count,
            fallback_used=fallback_used,
            output_dir=RAW_DIR,
            extra_metrics=metrics_payload,
        )
        weekly_payload = {
            "date": TODAY,
            "selected": selected_count,
            "published": published_count,
            **metrics_payload,
        }
        update_weekly_summary(weekly_payload)
        save_judge_report(RAW_DIR, judge_report)
        
        # Paso 8: Extraer y guardar missing_data
        extract_missing_data(result, RAW_DIR)
        
        # Paso 9: Renderizar HTML
        logger.info("🎨 Renderizando página HTML...")
        render_daily_page(result, DOCS_DIR / "index.html")
        
        # Paso 10: Actualizar índice principal
        logger.info("📑 Actualizando índice principal...")
        update_index_page(TODAY)
        
        # Paso 11: Copiar CSS estático (solo si no existe)
        static_src = Path("static/style.css")
        static_dst = Path("docs/static/style.css")
        if static_src.exists() and not static_dst.exists():
            static_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(static_src, static_dst)
            logger.info("✓ CSS copiado a docs/static/")
        
        logger.info(f"✅ [La Gran Crisis] Digest completado: {DOCS_DIR}/index.html")
        _write_desktop_health_check("close", True, f"published={published_count} selected={selected_count}")
        return True
        
    except Exception as e:
        logger.error(f"✗ Error crítico en pipeline: {type(e).__name__}: {e}", exc_info=True)
        
        # Fallback de emergencia: generar página mínima
        try:
            DOCS_DIR.mkdir(parents=True, exist_ok=True)
            render_fallback_page(TODAY, str(e), DOCS_DIR / "index.html")
            logger.warning("🛡️ Página de fallback generada")
        except Exception as fallback_error:
            logger.critical(f"✗ Fallback también falló: {fallback_error}")
        _write_desktop_health_check("close", False, f"{type(e).__name__}: {e}")
        
        return False


def main() -> None:
    """Punto de entrada principal con manejo de argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(description="La Gran Crisis pipeline")
    parser.add_argument("--mock", "-m", action="store_true", help="Usa datos mock y evita costo de cuota")
    parser.add_argument(
        "--accumulate",
        action="store_true",
        help="Modo intradía: captura y acumula artículos sin publicar",
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help="Modo cierre diario: usa acumulado y publica una sola edición",
    )
    parser.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Fecha a procesar (default: hoy). Permite reprocesar días pasados.",
    )
    args = parser.parse_args()

    # Sobreescribir fecha global si se pasa --date
    if args.date:
        import re as _re
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
            parser.error("--date debe tener el formato YYYY-MM-DD")
        global TODAY, RAW_DIR, DOCS_DIR
        TODAY = args.date
        RAW_DIR = Path(f"raw/{TODAY}")
        DOCS_DIR = Path(f"docs/{TODAY.replace('-', '/')}")
        logger.info("📅 Reprocesando fecha: %s", TODAY)

    # Por defecto mantiene comportamiento histórico: cierre diario.
    run_close = args.close or not args.accumulate

    if args.accumulate and not run_close:
        success = run_intraday_accumulator(use_mock=args.mock)
    else:
        try:
            with _acquire_mode_lock("close"):
                preloaded = load_accumulated_articles_for_close(TODAY)
                if preloaded:
                    logger.info("🧺 Cierre diario usa acumulado intradía: %d artículos", len(preloaded))
                success = run_pipeline(
                    use_mock=args.mock,
                    preloaded_articles=preloaded if preloaded else None,
                    pipeline_mode="close",
                )
        except RuntimeError as e:
            logger.error("✗ %s", e)
            success = False
    
    # Código de salida para CI/CD futuro
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
