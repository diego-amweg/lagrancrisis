# Archivo: src/classifier.py
# Filtro de ruido + ranking por autoridad + compatibilidad de tags estables
# Compatible con Windows 11 + Python 3.13.x

import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)

# Lista negra de ruido (NUNCA crece, solo se ajusta ocasionalmente)
NOISE_KEYWORDS = {
    "fútbol", "gran hermano", "horóscopo", "promo", "sorteo",
    "espectáculos", "farándula", "celebridades", "lifestyle",
    "receta", "tutorial", "entretenimiento", "viral", "meme"
}

# Tags estables con sus disparadores (conceptos que cambian poco).
STABLE_TAG_KEYWORDS: Dict[str, Set[str]] = {
    "Inflación": {"inflación", "inflation", "ipc", "precios", "cpi", "pce"},
    "Tarifas": {"tarifas", "servicios públicos", "regulados", "transporte"},
    "BCRA": {"bcra", "banco central", "reservas", "cepo", "brecha cambiaria"},
    "Fed": {"fed", "fomc", "federal reserve", "tasas de descuento"},
    "Tasas": {"tasas", "yield", "interest rates"},
    "Dólar": {"dólar", "dollar", "fx", "tipo de cambio", "mep"},
    "Bonos": {"bonos", "bonds", "deuda", "treasury"},
    "Commodities": {"commodities", "petróleo", "oil", "gas", "oro", "gold"},
    "Geopolítica": {"geopolítica", "guerra", "iran", "ormuz", "sanciones"},
    "Actividad": {"pib", "recesión", "desempleo", "producción", "actividad"},
}

ALL_STABLE_KEYWORDS = {
    keyword for values in STABLE_TAG_KEYWORDS.values() for keyword in values
}

def is_noise(title: str, content: str) -> bool:
    """Determina si un artículo es ruido obvio (lista negra)."""
    text = f"{title} {content}".lower()
    return any(kw in text for kw in NOISE_KEYWORDS)


def infer_stable_tags(article: Dict) -> List[str]:
    """Infere tags estables desde título + contenido con reglas deterministas."""
    text = f"{article.get('title', '')} {article.get('content', '')}".lower()
    tags = []
    for tag, keywords in STABLE_TAG_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            tags.append(tag)
    return tags[:4]

def calculate_stable_score(article: Dict) -> int:
    """Calcula score por fuente + keywords estables (sin eventos efímeros)."""
    score = 0
    
    # Factor 1: Autoridad de fuente (peso principal)
    tier = article.get("tier", "unknown")
    if tier == "oficial":
        score += 10
    elif tier == "t1":
        score += 5
    
    # Factor 2: Keywords macro estables en título/contenido
    text = f"{article.get('title', '')} {article.get('content', '')}".lower()
    stable_matches = sum(1 for kw in ALL_STABLE_KEYWORDS if kw in text)
    score += min(stable_matches * 2, 6)  # Tope de 6 puntos para evitar sesgo

    # Factor 3: Bonus si hay tags detectadas (señal estructural más fuerte)
    score += min(len(infer_stable_tags(article)), 3)
    
    return score

def classify_and_rank(
    articles: List[Dict], 
    max_per_section: int = 3,
    max_total: int = 15
) -> List[Dict]:
    """
    Filtra ruido, rankea por estabilidad y devuelve TODAS las no-ruido.
    
    Args:
        articles: Lista de artículos con keys: title, content, tier, source_name
        max_per_section: Parámetro legado (no usado en esquema plano).
        max_total: Parámetro legado (no usado en política de cobertura total).
        
    Returns:
        Lista ordenada de artículos no-ruido (sin truncamiento por cantidad)
    """
    del max_per_section, max_total  # cobertura total no-ruido (política explícita)

    # Paso 1: Filtrar ruido obvio
    filtered = [a for a in articles if not is_noise(a.get("title", ""), a.get("content", ""))]
    logger.info(f"Filtro de ruido: {len(articles)} → {len(filtered)} artículos")
    
    # Paso 2: Calcular score estable y tags para cada artículo
    for article in filtered:
        article["_stable_score"] = calculate_stable_score(article)
        article["_stable_tags"] = infer_stable_tags(article)
    
    # Paso 3: Orden base por score descendente + frescura
    ranked = sorted(
        filtered, 
        key=lambda x: (x.get("_stable_score", 0), x.get("published", "")), 
        reverse=True
    )

    # Paso 4: Reordenar para diversidad de fuente + compatibilidad de tags.
    diversified: List[Dict] = []
    source_count: Dict[str, int] = {}

    while ranked:
        best_index = 0
        best_score = float("-inf")
        last_tags = set(diversified[-1].get("_stable_tags", [])) if diversified else set()

        for index, article in enumerate(ranked):
            source = article.get("source_name", "Desconocido")
            source_penalty = source_count.get(source, 0) * 2.0

            current_tags = set(article.get("_stable_tags", []))
            compatibility_bonus = len(current_tags & last_tags) * 1.5
            novelty_bonus = len(current_tags - last_tags) * 0.5

            composite = (
                article.get("_stable_score", 0) * 10
                + compatibility_bonus
                + novelty_bonus
                - source_penalty
            )

            if composite > best_score:
                best_score = composite
                best_index = index

        selected = ranked.pop(best_index)
        source = selected.get("source_name", "Desconocido")
        source_count[source] = source_count.get(source, 0) + 1
        diversified.append(selected)

    logger.info(f"Ranking estable: {len(diversified)} artículos no-ruido para LLM")
    return diversified