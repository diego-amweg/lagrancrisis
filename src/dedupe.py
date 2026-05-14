# Archivo: src/dedupe.py
# Deduplicación de artículos por URL + similitud de título
# Usa rapidfuzz (más rápido y compatible con Windows sin compilación)

from typing import Dict, List

from rapidfuzz import fuzz, process


def deduplicate_articles(articles: List[Dict], title_threshold: int = 85) -> List[Dict]:
    """
    Elimina artículos duplicados usando dos criterios:
    1. URL exacta (duplicado exacto)
    2. Similitud de título > threshold (duplicado semántico)
    
    Args:
        articles: Lista de diccionarios con keys: title, url, content, source_name, etc.
        title_threshold: Puntuación de similitud (0-100) para considerar títulos iguales
        
    Returns:
        Lista de artículos únicos
    """
    if not articles:
        return []
    
    seen_urls = set()
    unique_articles = []
    seen_titles = []  # Para comparación fuzzy
    
    for article in articles:
        url = article.get('url', '').strip()
        title = article.get('title', '').strip()
        
        # Criterio 1: URL exacta ya vista → descartar
        if url in seen_urls:
            continue
        
        # Criterio 2: Título muy similar a uno ya procesado → descartar
        if title and seen_titles:
            # Buscar el título más similar en los ya procesados
            best_match = process.extractOne(title, seen_titles, scorer=fuzz.ratio)
            if best_match and best_match[1] >= title_threshold:
                continue  # Es un duplicado semántico
        
        # Artículo único → agregar a resultados
        seen_urls.add(url)
        if title:
            seen_titles.append(title)
        unique_articles.append(article)
    
    return unique_articles


def quick_dedupe_by_url(articles: List[Dict]) -> List[Dict]:
    """
    Deduplicación rápida solo por URL (sin comparación de títulos).
    Útil para pre-filtrado antes de la deduplicación completa.
    """
    seen = set()
    result = []
    for art in articles:
        url = art.get('url', '').strip()
        if url and url not in seen:
            seen.add(url)
            result.append(art)
    return result