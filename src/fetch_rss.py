# Archivo: src/fetch_rss.py
# Descarga y normaliza artículos desde feeds RSS
# Placeholder funcional: retorna datos de ejemplo para testing

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import feedparser
import requests

logger = logging.getLogger(__name__)


def _to_utc(dt: datetime) -> datetime:
    """Normaliza datetime a UTC aware para comparaciones consistentes."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _detect_language(source: Dict) -> str:
    """Detecta el idioma de una fuente basada en metadata disponible.

    Reglas en orden:
    1. Si la fuente define explicitamente `language` en sources.json, usarlo.
    2. Si la URL contiene ".ar", devolver "es".
    3. Si la categoría contiene "argentina", devolver "es".
    4. Si el nombre de la fuente está en el conjunto conocido de fuentes en español,
       devolver "es".
    5. En cualquier otro caso, devolver "en".
    """
    explicit = source.get("language")
    if explicit:
        return explicit

    url = source.get("url", "")
    if ".ar" in url:
        return "es"

    category = source.get("category", "").lower()
    if "argentina" in category:
        return "es"

    spanish_sources = {
        "ámbito financiero",
        "el cronista",
        "infobae economía",
        "la nación economía",
        "perfil economía",
        "cippec",
        "fiel",
        "ambito financiero",
    }
    name = source.get("name", "").lower()
    if name in spanish_sources:
        return "es"

    return "en"


def fetch_all_feeds(
    sources: List[Dict],
    hours_back: int = 24,
    max_entries_per_source: int = 10,
) -> List[Dict]:
    """
    Descarga artículos de todas las fuentes RSS configuradas.
    
    Args:
        sources: Lista de diccionarios con keys: name, url, category, tier
        hours_back: Solo incluir artículos publicados en las últimas N horas
        max_entries_per_source: Máximo de entries a considerar por feed.

    Returns:
        Lista de artículos normalizados con keys:
        - title, url, content, published, source_name, source_category, tier
    """
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    feed_limit = max_entries_per_source if max_entries_per_source > 0 else None

    for source in sources:
        try:
            # Solo procesamos fuentes RSS por ahora
            if source.get("type", "rss") != "rss":
                continue
                
            # Descargar y parsear feed
            feed = feedparser.parse(source["url"])
            
            for entry in feed.entries[:feed_limit]:
                # Usar published_parsed (struct_time) ya procesado por feedparser.
                # Si no está, intentar parsear el string con dateutil.
                published = _parse_date(entry, source.get("name", ""))
                published_utc = _to_utc(published) if published else None

                # Filtrar por antigüedad.
                if published_utc and published_utc < cutoff:
                    continue
                
                article = {
                    "title": entry.get("title", "Sin título"),
                    "url": entry.get("link", ""),
                    "content": entry.get("summary", entry.get("description", "")),
                    "published": published_utc.isoformat() if published_utc else "",
                    "source_name": source["name"],
                    "source_category": source.get("category", "general"),
                    "tier": source.get("tier", "unknown"),
                    "language": _detect_language(source)
                }
                articles.append(article)
                
        except Exception as e:
            logger.warning(f"Error al procesar {source['name']}: {e}")
            continue
    
    logger.info(f"Descargados {len(articles)} artículos de {len(sources)} fuentes")
    return articles


def _parse_date(entry, source_name: str = "") -> datetime | None:
    """Convierte la fecha de un entry de feedparser a datetime.
    
    feedparser 6 ya provee published_parsed como struct_time.
    Convertimos con datetime(*parsed[:6]). Si no está disponible,
    intentamos parsear el string con dateutil como fallback.
    """
    # Método primario: published_parsed ya es struct_time procesado por feedparser
    parsed = getattr(entry, 'published_parsed', None) or entry.get('published_parsed')
    if parsed:
        try:
            return datetime(*parsed[:6])
        except Exception:
            pass

    # Fallback: parsear string con dateutil
    date_str = ""
    if hasattr(entry, 'get'):
        date_str = entry.get('published', '') or entry.get('updated', '')

    if date_str:
        try:
            from dateutil import parser as dateutil_parser
            return dateutil_parser.parse(date_str)
        except Exception:
            pass

    # Fallback específico para feeds que omiten metadatos de fecha (ej. FIEL).
    title = entry.get('title', '') if hasattr(entry, 'get') else ''
    title_date = _parse_date_from_title(title)
    if title_date:
        return title_date

    return None


def _parse_date_from_title(title: str) -> datetime | None:
    text = str(title or "").strip()
    if not text:
        return None

    # Normaliza mojibake frecuente en algunos feeds legacy.
    text = (
        text.replace("�", "")
        .replace("N�mero", "Numero")
        .replace("N�", "N")
    )

    month_map = {
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "abril": 4,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "agosto": 8,
        "septiembre": 9,
        "setiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
    }

    # Formato: "22 de Abril de 2026"
    match = re.search(r"(\d{1,2})\s+de\s+([A-Za-záéíóúÁÉÍÓÚñÑ]+)\s+de\s+(\d{4})", text, re.IGNORECASE)
    if match:
        day = int(match.group(1))
        month_name = match.group(2).lower()
        year = int(match.group(3))
        month = month_map.get(month_name)
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                return None

    # Formato: "Abril 2026" (sin día explícito) -> usa día 1.
    match = re.search(r"([A-Za-záéíóúÁÉÍÓÚñÑ]+)\s+(\d{4})", text, re.IGNORECASE)
    if match:
        month_name = match.group(1).lower()
        year = int(match.group(2))
        month = month_map.get(month_name)
        if month:
            try:
                return datetime(year, month, 1)
            except ValueError:
                return None

    return None


# === FUNCIONES PARA TESTING LOCAL (sin API calls reales) ===

def fetch_sample_articles(count: int = 15) -> List[Dict]:
    """
    Genera artículos de ejemplo para testing sin llamar a APIs externas.
    Útil para desarrollar sin consumir cuota de RSS o LLM.
    """
    samples = [
        {
            "title": "BCRA mantiene tasa de política monetaria en 40% anual",
            "url": "https://www.bcra.gob.ar/Noticias/20260410_tasa.asp",
            "content": "El Banco Central informó que la tasa de referencia se mantiene sin cambios en su última reunión de política monetaria. La decisión fue unánime y considera el contexto inflacionario actual.",
            "published": datetime.now().isoformat(),
            "source_name": "BCRA",
            "source_category": "macro_argentina",
            "tier": "oficial",
            "language": "es"
        },
        {
            "title": "INDEC confirma inflación de marzo: 3.2% mensual",
            "url": "https://www.indec.gob.ar/indec/web/Nivel4-Tema-2-42",
            "content": "El Índice de Precios al Consumidor registró un aumento del 3.2% en marzo, ligeramente por debajo de las expectativas del mercado. El acumulado trimestral alcanza el 9.1%.",
            "published": datetime.now().isoformat(),
            "source_name": "INDEC",
            "source_category": "macro_argentina",
            "tier": "oficial",
            "language": "es"
        },
        {
            "title": "Federal Reserve mantiene tasas sin cambios, señala cautela",
            "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260410a.htm",
            "content": "La Reserva Federal de EE.UU. decidió mantener el rango de tasas de interés federal funds en 5.25%-5.50%. El comunicado destaca la necesidad de más datos antes de considerar recortes.",
            "published": datetime.now().isoformat(),
            "source_name": "Federal Reserve",
            "source_category": "internacional",
            "tier": "oficial",
            "language": "en"
        }
    ]
    
    # Repetir muestras para alcanzar el count solicitado
    result = []
    for i in range(count):
        result.append(samples[i % len(samples)].copy())
    
    return result