"""
Prueba Gemini contra Claude: compara las ediciones que cada uno armó con las MISMAS noticias.

Mide, sin opinar:
1. Cifras sin respaldo: cada número de 2 o más dígitos del titular y del resumen de cada
   noticia se busca en el texto del artículo original. Si no aparece, cuenta como cifra
   sin respaldo. (Se ignoran los años 2020-2030 y los números de un dígito, que suelen
   venir escritos con letras en el original.) Es una medición con ruido: un "18.300" que
   el original escribe "18,3 mil" cuenta como sin respaldo. El ruido es el mismo para los dos.
2. Lo mismo para el resumen ejecutivo, contra todos los artículos del día.
3. Noticias publicadas, noticias armadas sin IA, pedidos fallidos y costo.

Además arma una revisión a ciegas: 20 noticias al azar de cada modelo, mezcladas y sin
decir cuál es cuál, para que una persona marque las que dicen algo que el original no dice.

Uso: python scripts/comparar_prueba.py resultados_prueba insumos
     (resultados_prueba/<modelo>/<fecha>/data.json y pipeline_metrics.json; insumos/<fecha>.json)
"""

from __future__ import annotations

import html
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from resumen_corrida import PRECIOS_USD_POR_MILLON  # noqa: E402

NUMERO = re.compile(r"\d[\d.,]*\d|\d")
ETIQUETA_HTML = re.compile(r"<[^>]+>")
MUESTRA_POR_MODELO = 20
SEMILLA = 20261122


def _normalizar(numero: str) -> str:
    return re.sub(r"[.,]", "", numero)


def _cifras(texto: str) -> list[str]:
    cifras = []
    for crudo in NUMERO.findall(texto or ""):
        n = _normalizar(crudo)
        if len(n) < 2:
            continue
        if len(n) == 4 and 2020 <= int(n) <= 2030:
            continue
        cifras.append(n)
    return cifras


def _texto_fuente(articulo: dict) -> str:
    return ETIQUETA_HTML.sub(" ", f"{articulo.get('title', '')} {articulo.get('content', '')}")


def _cifras_en_fuente(texto: str) -> set[str]:
    return {_normalizar(c) for c in NUMERO.findall(texto)}


def analizar(resultados: Path, insumos: Path) -> tuple[dict, list[dict]]:
    informe: dict = {}
    noticias_para_revision: list[dict] = []
    for dir_modelo in sorted(p for p in resultados.iterdir() if p.is_dir()):
        modelo = dir_modelo.name
        tot = {"dias": 0, "noticias": 0, "cifras": 0, "sin_respaldo": 0, "sin_fuente": 0,
               "resumen_cifras": 0, "resumen_sin_respaldo": 0, "respaldo_sin_ia": 0,
               "resumen_no_generado": 0, "costo_usd": 0.0, "ejemplos": []}
        for dir_fecha in sorted(p for p in dir_modelo.iterdir() if p.is_dir()):
            fecha = dir_fecha.name
            data_path = dir_fecha / "data.json"
            insumo_path = insumos / f"{fecha}.json"
            if not data_path.exists() or not insumo_path.exists():
                continue
            data = json.loads(data_path.read_text(encoding="utf-8"))
            articulos = json.loads(insumo_path.read_text(encoding="utf-8"))
            por_url = {a.get("url", ""): a for a in articulos}
            todas_las_fuentes = " ".join(_texto_fuente(a) for a in articulos)
            cifras_del_dia = _cifras_en_fuente(todas_las_fuentes)
            tot["dias"] += 1

            for item in data.get("noticias_destacadas", []):
                tot["noticias"] += 1
                fuente = por_url.get(item.get("source_url", ""))
                if fuente is None:
                    tot["sin_fuente"] += 1
                    continue
                disponibles = _cifras_en_fuente(_texto_fuente(fuente))
                texto = f"{item.get('headline', '')} {item.get('summary', '')}"
                for cifra in _cifras(texto):
                    tot["cifras"] += 1
                    if cifra not in disponibles:
                        tot["sin_respaldo"] += 1
                        if len(tot["ejemplos"]) < 15:
                            tot["ejemplos"].append({"fecha": fecha, "cifra": cifra, "titular": item.get("headline", "")})
                noticias_para_revision.append({
                    "modelo": modelo, "fecha": fecha,
                    "titular": item.get("headline", ""), "resumen": item.get("summary", ""),
                    "fuente_titulo": fuente.get("title", ""),
                    "fuente_texto": _texto_fuente(fuente)[:1500],
                    "fuente_nombre": fuente.get("source_name", ""), "url": fuente.get("url", ""),
                })

            resumen = str(data.get("resumen_ejecutivo", ""))
            if resumen.startswith("El resumen ejecutivo de hoy no pudo generarse"):
                tot["resumen_no_generado"] += 1
            else:
                for cifra in _cifras(resumen):
                    tot["resumen_cifras"] += 1
                    if cifra not in cifras_del_dia:
                        tot["resumen_sin_respaldo"] += 1

            metricas_path = dir_fecha / "pipeline_metrics.json"
            if metricas_path.exists():
                m = json.loads(metricas_path.read_text(encoding="utf-8"))
                tot["respaldo_sin_ia"] += int(m.get("fallback_items_count", 0) or 0)
                for nombre, uso in (m.get("llm_token_usage") or {}).items():
                    precio = PRECIOS_USD_POR_MILLON.get(nombre, (0.0, 0.0))
                    tot["costo_usd"] += uso.get("input_tokens", 0) / 1e6 * precio[0] + uso.get("output_tokens", 0) / 1e6 * precio[1]
        informe[modelo] = tot
    return informe, noticias_para_revision


def escribir_informe(informe: dict, destino: Path) -> None:
    lineas = ["# Prueba Gemini contra Claude: resultado automático", ""]
    lineas += ["| Dato | " + " | ".join(informe) + " |", "|---|" + "---|" * len(informe)]

    def fila(nombre, valor):
        lineas.append(f"| {nombre} | " + " | ".join(valor(t) for t in informe.values()) + " |")

    def tasa(a, b):
        return f"{a}/{b} ({a / b:.1%})" if b else "0/0"

    fila("Días procesados", lambda t: str(t["dias"]))
    fila("Noticias publicadas", lambda t: str(t["noticias"]))
    fila("Cifras sin respaldo en las noticias", lambda t: tasa(t["sin_respaldo"], t["cifras"]))
    fila("Cifras sin respaldo en el resumen ejecutivo", lambda t: tasa(t["resumen_sin_respaldo"], t["resumen_cifras"]))
    fila("Días sin resumen ejecutivo", lambda t: str(t["resumen_no_generado"]))
    fila("Noticias armadas sin IA (respaldo)", lambda t: str(t["respaldo_sin_ia"]))
    fila("Noticias sin artículo original identificable", lambda t: str(t["sin_fuente"]))
    fila("Costo aproximado (USD)", lambda t: f"{t['costo_usd']:.2f}")
    lineas += ["", "## Ejemplos de cifras sin respaldo (para revisar a mano si son errores o ruido)", ""]
    for modelo, t in informe.items():
        lineas.append(f"**{modelo}**")
        for e in t["ejemplos"]:
            lineas.append(f"- {e['fecha']} · cifra {e['cifra']} · {e['titular']}")
        lineas.append("")
    destino.write_text("\n".join(lineas), encoding="utf-8")


def escribir_revision_ciega(noticias: list[dict], destino_html: Path, destino_clave: Path) -> None:
    azar = random.Random(SEMILLA)
    muestra = []
    for modelo in sorted({n["modelo"] for n in noticias}):
        del_modelo = [n for n in noticias if n["modelo"] == modelo]
        muestra += azar.sample(del_modelo, min(MUESTRA_POR_MODELO, len(del_modelo)))
    azar.shuffle(muestra)
    clave = {str(i + 1): n["modelo"] for i, n in enumerate(muestra)}
    destino_clave.write_text(json.dumps(clave, indent=1), encoding="utf-8")

    bloques = []
    for i, n in enumerate(muestra, 1):
        bloques.append(f"""
<section>
  <h2>Noticia {i}</h2>
  <p class="meta">{html.escape(n['fecha'])} · {html.escape(n['fuente_nombre'])} · <a href="{html.escape(n['url'])}">original</a></p>
  <div class="cols">
    <div><h3>Lo que publicó el Diario</h3><p><b>{html.escape(n['titular'])}</b></p><p>{html.escape(n['resumen'])}</p></div>
    <div><h3>Lo que decía el original</h3><p><b>{html.escape(n['fuente_titulo'])}</b></p><p>{html.escape(n['fuente_texto'])}</p></div>
  </div>
  <p class="pregunta">¿El Diario dice algo que el original no dice, o lo cambia? Anotá el número si es así.</p>
</section>""")
    destino_html.write_text(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Revisión a ciegas</title>
<style>body{{font-family:Georgia,serif;max-width:1000px;margin:0 auto;padding:16px;background:#fdfbf6;color:#222}}
section{{border-top:1px solid #ccc;padding:12px 0}} .cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:700px){{.cols{{grid-template-columns:1fr}}}} .meta{{color:#666;font-size:14px}}
.pregunta{{font-style:italic;color:#444}}</style></head><body>
<h1>Revisión a ciegas: {len(muestra)} noticias</h1>
<p>Cada noticia la escribió uno de los dos modelos, mezcladas al azar. No abras el archivo de clave hasta terminar.
Anotá los números de las noticias donde el Diario agrega, cambia o inventa algo respecto del original.</p>
{''.join(bloques)}</body></html>""", encoding="utf-8")


def main() -> int:
    resultados, insumos = Path(sys.argv[1]), Path(sys.argv[2])
    informe, noticias = analizar(resultados, insumos)
    escribir_informe(informe, resultados / "INFORME_AUTOMATICO.md")
    escribir_revision_ciega(noticias, resultados / "revision_ciega.html", resultados / "clave_revision_NO_ABRIR.json")
    print((resultados / "INFORME_AUTOMATICO.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
