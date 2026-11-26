"""
Prueba de recuperación de noticias para días que la PC no capturó.

Para cada fecha D busca lo que habría descargado la edición de las 05:00 de ese día:
noticias publicadas entre D-2 05:00 y D 05:00 de Argentina (08:00 UTC), de las mismas
fuentes RSS de src/sources.json. Las busca en dos lugares:

1. Copias viejas de cada feed guardadas por el Internet Archive (Wayback Machine).
2. El feed tal como está hoy (sirve para fuentes que publican poco y guardan meses de noticias).

No usa IA ni publica nada. Escribe:
- un informe con cuántas noticias aparecen por día y por fuente, comparado con los días vecinos
  que sí se capturaron (si se pasa la carpeta de insumos guardados);
- un archivo de noticias por fecha en el mismo formato que los insumos guardados, listo para
  el reproceso si el resultado alcanza.

Uso: python scripts/recuperar_dias.py --fechas 2026-08-15,2026-08-16 --salida CARPETA [--insumos CARPETA]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.fetch_rss import _detect_language, _parse_date, _to_utc  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("recuperar")

CDX = "https://web.archive.org/cdx/search/cdx"
COPIA = "https://web.archive.org/web/{ts}id_/{url}"
CABECERA = {"User-Agent": "diario-lagrancrisis-recuperacion/1.0 (+https://daily.lagrancrisis.com)"}
COPIAS_POR_FECHA = 6
PAUSA = 1.5


def _pedir(url: str, params: dict | None = None, intentos: int = 4) -> requests.Response | None:
    espera = 5.0
    for _ in range(intentos):
        try:
            r = requests.get(url, params=params, headers=CABECERA, timeout=60)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 502, 503, 504):
                time.sleep(espera)
                espera *= 2
                continue
            return None
        except requests.RequestException:
            time.sleep(espera)
            espera *= 2
    return None


def _ventana(fecha: date) -> tuple[datetime, datetime]:
    fin = datetime(fecha.year, fecha.month, fecha.day, 8, 0, tzinfo=timezone.utc)
    return fin - timedelta(hours=48), fin


def _fuentes() -> list[dict]:
    config = json.loads((ROOT / "src" / "sources.json").read_text(encoding="utf-8"))
    return [s for region in ("argentina", "global") for tier in ("oficiales", "medios_tier1")
            for s in config.get(region, {}).get(tier, [])]


def _copias(url: str, desde: datetime, hasta: datetime) -> list[str]:
    r = _pedir(CDX, {"url": url, "from": desde.strftime("%Y%m%d%H%M%S"), "to": hasta.strftime("%Y%m%d%H%M%S"),
                     "output": "json", "filter": "statuscode:200", "collapse": "digest", "fl": "timestamp"})
    time.sleep(PAUSA)
    if r is None:
        return []
    try:
        filas = r.json()
    except ValueError:
        return []
    return [f[0] for f in filas[1:]]


def _elegir(marcas: list[str], cantidad: int) -> list[str]:
    if len(marcas) <= cantidad:
        return marcas
    paso = (len(marcas) - 1) / (cantidad - 1)
    return sorted({marcas[round(i * paso)] for i in range(cantidad)})


def _articulos(texto: bytes, fuente: dict, inicio: datetime, fin: datetime) -> list[dict]:
    feed = feedparser.parse(texto)
    salida = []
    for entry in feed.entries:
        publicado = _parse_date(entry, fuente.get("name", ""))
        if not publicado:
            continue
        publicado = _to_utc(publicado)
        if not (inicio <= publicado < fin):
            continue
        salida.append({
            "title": entry.get("title", "Sin título"),
            "url": entry.get("link", ""),
            "content": entry.get("summary", entry.get("description", "")),
            "published": publicado.isoformat(),
            "source_name": fuente["name"],
            "source_category": fuente.get("category", "general"),
            "tier": fuente.get("tier", "unknown"),
            "language": _detect_language(fuente),
        })
    return salida


def recuperar(fechas: list[date]) -> tuple[dict, dict]:
    fuentes = _fuentes()
    por_fecha: dict[str, dict[str, dict]] = {f.isoformat(): {} for f in fechas}
    origen: dict[str, Counter] = {f.isoformat(): Counter() for f in fechas}
    ventanas = {f.isoformat(): _ventana(f) for f in fechas}
    cache: dict[str, bytes] = {}

    def sumar(clave: str, arts: list[dict], de_donde: str) -> None:
        for a in arts:
            llave = (a["url"] or a["title"], a["source_name"])
            if llave not in por_fecha[clave]:
                por_fecha[clave][llave] = a
                origen[clave][de_donde] += 1

    for fuente in fuentes:
        url = fuente["url"]
        log.info("Fuente: %s", fuente["name"])
        # Copias del archivo: desde el inicio de la primera ventana hasta 36 h después del cierre de la última.
        desde = min(v[0] for v in ventanas.values())
        hasta = max(v[1] for v in ventanas.values()) + timedelta(hours=36)
        if url not in cache:
            cache[url] = json.dumps(_copias(url, desde, hasta)).encode()
        marcas = json.loads(cache[url])
        for clave, (inicio, fin) in ventanas.items():
            limite = fin + timedelta(hours=36)
            candidatas = [m for m in marcas
                          if inicio <= datetime.strptime(m, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) <= limite]
            for marca in _elegir(candidatas, COPIAS_POR_FECHA):
                clave_copia = f"{marca}|{url}"
                if clave_copia not in cache:
                    r = _pedir(COPIA.format(ts=marca, url=url))
                    time.sleep(PAUSA)
                    cache[clave_copia] = r.content if r is not None else b""
                if cache[clave_copia]:
                    sumar(clave, _articulos(cache[clave_copia], fuente, inicio, fin), "archivo")
        # El feed de hoy.
        clave_hoy = f"hoy|{url}"
        if clave_hoy not in cache:
            r = _pedir(url)
            cache[clave_hoy] = r.content if r is not None else b""
        if cache[clave_hoy]:
            for clave, (inicio, fin) in ventanas.items():
                sumar(clave, _articulos(cache[clave_hoy], fuente, inicio, fin), "feed_de_hoy")

    return {k: list(v.values()) for k, v in por_fecha.items()}, origen


def _conteo_insumo(insumos: Path | None, fecha: date) -> tuple[int, Counter] | None:
    if insumos is None:
        return None
    archivo = insumos / f"{fecha.isoformat()}.json"
    if not archivo.exists():
        return None
    articulos = json.loads(archivo.read_text(encoding="utf-8"))
    return len(articulos), Counter(a.get("source_name", "") for a in articulos)


def _vecino(insumos: Path | None, fecha: date, paso: int) -> tuple[str, tuple[int, Counter]] | None:
    for i in range(1, 8):
        otra = fecha + timedelta(days=paso * i)
        conteo = _conteo_insumo(insumos, otra)
        if conteo:
            return otra.isoformat(), conteo
    return None


def informe(resultado: dict, origen: dict, insumos: Path | None) -> str:
    lineas = ["# Prueba de recuperación de días sin captura", "",
              "Ventana de cada fecha: noticias publicadas entre D-2 05:00 y D 05:00 (Argentina).",
              "Mínimo para armar una edición: 15 noticias.", "",
              "| Fecha | Recuperadas | Del archivo | Del feed de hoy | Día capturado anterior | Día capturado siguiente | ¿Alcanza para edición? |",
              "|---|---|---|---|---|---|---|"]
    detalle = ["", "## Por fuente (recuperadas · vecino anterior · vecino siguiente)", ""]
    for clave in sorted(resultado):
        fecha = date.fromisoformat(clave)
        arts = resultado[clave]
        ant, sig = _vecino(insumos, fecha, -1), _vecino(insumos, fecha, 1)
        fmt = lambda v: f"{v[1][0]} ({v[0]})" if v else "—"  # noqa: E731
        lineas.append(f"| {clave} | {len(arts)} | {origen[clave]['archivo']} | {origen[clave]['feed_de_hoy']} | "
                      f"{fmt(ant)} | {fmt(sig)} | {'sí' if len(arts) >= 15 else 'no'} |")
        por_fuente = Counter(a["source_name"] for a in arts)
        nombres = sorted(set(por_fuente) | set(ant[1][1] if ant else {}) | set(sig[1][1] if sig else {}))
        detalle.append(f"**{clave}**")
        for n in nombres:
            detalle.append(f"- {n}: {por_fuente.get(n, 0)} · {ant[1][1].get(n, 0) if ant else '—'} · "
                           f"{sig[1][1].get(n, 0) if sig else '—'}")
        detalle.append("")
    return "\n".join(lineas + detalle)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fechas", required=True)
    p.add_argument("--salida", required=True)
    p.add_argument("--insumos", default="")
    args = p.parse_args()
    fechas = [date.fromisoformat(f.strip()) for f in args.fechas.split(",") if f.strip()]
    salida = Path(args.salida)
    (salida / "insumos").mkdir(parents=True, exist_ok=True)
    insumos = Path(args.insumos) if args.insumos else None

    resultado, origen = recuperar(fechas)
    for clave, arts in resultado.items():
        (salida / "insumos" / f"{clave}.json").write_text(json.dumps(arts, ensure_ascii=False, indent=1), encoding="utf-8")
    texto = informe(resultado, origen, insumos)
    (salida / "INFORME_RECUPERACION.md").write_text(texto, encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
