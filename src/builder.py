# Archivo: src/builder.py
# Genera páginas HTML a partir de datos JSON usando Jinja2
# Compatible con Windows 11 + Python 3.13.x
# FIX: Usar paths relativos en lugar de absolutos para que funcionen localmente

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

# Configuración de templates
TEMPLATES_DIR = Path("templates")
STATIC_DIR = Path("static")
DOCS_DIR = Path("docs")


def _enrich_is_argentina(items: List[Dict]) -> List[Dict]:
    """Añade is_argentina si falta, inferido desde source_url y source_name."""
    enriched = []
    for item in items:
        if "is_argentina" not in item:
            url = str(item.get("source_url", "")).lower()
            name = str(item.get("source_name", "")).lower()
            item = dict(item)  # copia para no mutar el original
            item["is_argentina"] = (
                ".com.ar" in url
                or ".gob.ar" in url
                or ".ar/" in url
            or any(
              t in name
              for t in [
                "bcra",
                "indec",
                "argentina",
                "anses",
                "afip",
                "byma",
                "merval",
                "ministerio de economia",
              ]
            )
            )
        enriched.append(item)
    return enriched


def render_daily_page(data: Dict, output_path: Path) -> Path:
    """
    Renderiza la página HTML del día usando la plantilla diario.html.j2.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True
    )
    
    try:
        template = env.get_template("diario.html.j2")
    except TemplateNotFound:
        template = env.from_string(_MINIMAL_TEMPLATE)

    noticias_destacadas = _enrich_is_argentina(data.get("noticias_destacadas", []))
    source_urls_in_news = {
      str(item.get("source_url", "")).strip()
      for item in noticias_destacadas
      if isinstance(item, dict) and str(item.get("source_url", "")).strip()
    }
    sources_consulted_filtered = [
      str(url).strip()
      for url in data.get("sources_consulted", [])
      if str(url).strip() in source_urls_in_news
    ]
    
    context = {
        "date": data.get("date", datetime.now().strftime("%Y-%m-%d")),
        "summary": data.get("resumen_ejecutivo", ""),
      "cadena_de_razonamiento": data.get("cadena_de_razonamiento", ""),
      "noticias_destacadas": noticias_destacadas,
        "sections": data.get("sections", {}),
        "unverified": data.get("unverified_claims", []),
        "missing": data.get("missing_official_data", []),
      "sources_consulted": sources_consulted_filtered,
        "is_fallback": data.get("_fallback", False),
        "site_name": "La Gran Crisis",
        "tagline": "Los datos no entran en pánico"
    }
    
    html_output = template.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_output)
    
    return output_path


def update_index_page(today_date: str) -> Path:
    """
    Actualiza la página de índice (docs/index.html) con enlaces RELATIVOS.
    FIX: Sin barra inicial para que funcionen al abrir el archivo localmente.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True
    )
    
    try:
        template = env.get_template("index.html.j2")
    except TemplateNotFound:
        template = env.from_string(_MINIMAL_INDEX_TEMPLATE)
    
    history_entries = _scan_history()
    
    # FIX: Path relativo sin barra inicial
    # En lugar de "/2026/04/11/" usamos "2026/04/11/"
    today_url = f"{today_date.replace('-', '/')}/"
    
    context = {
        "latest": today_url,
      "history": [entry["url"] for entry in history_entries[:30]],
      "history_entries": history_entries[:30],
        "site_name": "La Gran Crisis",
        "tagline": "Los datos no entran en pánico"
    }
    
    html_output = template.render(**context)
    index_path = DOCS_DIR / "index.html"
    
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_output)
    
    return index_path


def _scan_history() -> List[Dict]:
    """
    Escanea el directorio docs/ para encontrar ediciones históricas.
    Retorna entradas con url relativa y bandera de faltante documentado.
    """
    history: List[Dict] = []
    
    if not DOCS_DIR.exists():
        return history
    
    for year in DOCS_DIR.iterdir():
        if not year.is_dir() or not year.name.isdigit() or len(year.name) != 4:
            continue
        for month in year.iterdir():
            if not month.is_dir() or not month.name.isdigit() or len(month.name) != 2:
                continue
            for day in month.iterdir():
                if not day.is_dir() or not (day / "index.html").exists():
                    continue

                # FIX: Path relativo sin barra inicial
                url = f"{year.name}/{month.name}/{day.name}/"
                missing_documented = False
                data_path = day / "data.json"
                if data_path.exists():
                    try:
                        payload = json.loads(data_path.read_text(encoding="utf-8"))
                        missing_documented = payload.get("status") == "missing_documented"
                    except (json.JSONDecodeError, OSError):
                        missing_documented = False

                history.append({
                    "url": url,
                    "missing_documented": missing_documented,
                })
    
        history.sort(key=lambda x: x.get("url", ""), reverse=True)
    return history


def render_fallback_page(date: str, error_msg: str, output_path: Path) -> Path:
    """
    Genera página de fallback minimalista cuando todo falla.
    """
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>La Gran Crisis | {date}</title>
  <link rel="stylesheet" href="../../../static/style.css">
</head>
<body>
  <header class="masthead">
    <h1>LA GRAN CRISIS</h1>
    <p class="tagline">Los datos no entran en pánico</p>
    <time datetime="{date}" class="date">{date}</time>
    <span class="badge fallback">⚠️ Modo fallback</span>
  </header>
  <main>
    <section class="executive-summary">
      <h2>⚠️ Procesamiento temporalmente no disponible</h2>
      <p>Detalles técnicos: <code>{error_msg[:200]}</code></p>
      <p>La página se actualiza automáticamente. Volvé en unos minutos o consultá el <a href="../index.html">inicio</a>.</p>
    </section>
  </main>
  <footer>
    <p><a href="../index.html">← Inicio</a> | <a href="../index.html">Historial</a></p>
  </footer>
</body>
</html>"""
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    return output_path


# === Plantillas mínimas de fallback ===

_MINIMAL_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>{{ site_name }} | {{ date }}</title>
  <link rel="stylesheet" href="../../../static/style.css">
</head>
<body>
  <header class="masthead">
    <h1>{{ site_name }}</h1>
    <p class="tagline">{{ tagline }}</p>
    <time datetime="{{ date }}" class="date">{{ date }}</time>
  </header>
  {% if summary %}
  <section class="executive-summary">
    <h2>📋 Resumen Ejecutivo</h2>
    <p>{{ summary }}</p>
  </section>
  {% endif %}
  <main>
    {% for section_name, items in sections.items() %}
      {% if items %}
      <section class="news-section">
        <h3>{{ section_name.replace('_', ' ').title() }}</h3>
        {% for item in items %}
        <article class="card {{ 'verified' if item.verified else 'unverified' }}">
          <h4>{{ item.headline }}</h4>
          <p class="summary">{{ item.summary }}</p>
          <div class="meta">
            <span class="impact {{ item.impact|lower }}">● {{ item.impact }}</span>
            <span class="source">📎 <a href="{{ item.source_url }}">{{ item.source_name }}</a></span>
            <time class="item-time">{{ item.source_datetime }}</time>
          </div>
        </article>
        {% endfor %}
      </section>
      {% endif %}
    {% endfor %}
  </main>
</body>
</html>"""

_MINIMAL_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>{{ site_name }} — Archivo</title>
  <link rel="stylesheet" href="static/style.css">
</head>
<body>
  <header class="masthead">
    <h1>{{ site_name }}</h1>
    <p class="tagline">{{ tagline }}</p>
  </header>
  <main>
    <p><a href="{{ latest }}">→ Ir al último resumen</a></p>
    <h2>Ediciones recientes</h2>
    <ul>
    {% for entry in history_entries %}
      <li>
        <a href="{{ entry.url }}">{{ entry.url }}</a>
        {% if entry.missing_documented %}
          <span class="badge fallback">Faltante documentado</span>
        {% endif %}
      </li>
    {% endfor %}
    </ul>
  </main>
</body>
</html>"""