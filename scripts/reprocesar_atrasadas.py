"""
Reprocesa las ediciones atrasadas (15/05/2026 en adelante) a partir de las noticias guardadas.

- Va en orden de fecha, para que cada edición use el resumen del día anterior.
- Saltea las fechas que ya tienen edición en docs/ y las que fallaron dos veces.
- Guarda cada edición como un cambio propio en git (sin subirlo); el proceso de GitHub
  sube todo junto al final, así un corte no pierde lo ya hecho.
- Se detiene al llegar al tiempo límite y deja anotado cuántas faltan.

Uso: python scripts/reprocesar_atrasadas.py --insumos CARPETA [--limite-minutos 300]
Escribe el estado en atrasadas_estado.json (en la raíz del repositorio).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESTADO = ROOT / "atrasadas_estado.json"
DESDE = "2026-05-15"


def _correr(cmd: list[str]) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def _carpeta(fecha: str) -> Path:
    return ROOT / "docs" / fecha.replace("-", "/")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--insumos", required=True)
    parser.add_argument("--limite-minutos", type=float, default=300)
    parser.add_argument("--mock", action="store_true", help="Solo para probar el circuito, sin IA")
    args = parser.parse_args()

    insumos = Path(args.insumos)
    estado = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {"fallidas": {}, "incompletas": []}
    fechas = sorted(p.stem for p in insumos.glob("20*.json") if p.stem >= DESDE)
    pendientes = [f for f in fechas if not (_carpeta(f) / "data.json").exists() and estado["fallidas"].get(f, 0) < 2]
    print(f"Fechas con noticias guardadas: {len(fechas)} · pendientes: {len(pendientes)}", flush=True)

    inicio = time.monotonic()
    hechas = 0
    for fecha in pendientes:
        if (time.monotonic() - inicio) / 60 > args.limite_minutos:
            print("Se alcanzó el tiempo límite de esta corrida.", flush=True)
            break
        codigo = _correr([sys.executable, "src/main.py", "--close", "--date", fecha, "--insumo", str(insumos / f"{fecha}.json")] + (["--mock"] if args.mock else []))
        if codigo != 0 or not (_carpeta(fecha) / "data.json").exists():
            estado["fallidas"][fecha] = estado["fallidas"].get(fecha, 0) + 1
            # Lo que haya quedado a medias no se guarda: se reintenta en la próxima corrida.
            subprocess.call(["git", "checkout", "--", "docs/"], cwd=ROOT)
            subprocess.call(["git", "clean", "-fdq", str(_carpeta(fecha))], cwd=ROOT)
            print(f"✗ {fecha} falló (vez {estado['fallidas'][fecha]})", flush=True)
            continue
        if _correr([sys.executable, "scripts/edicion_completa.py", fecha]) != 0:
            estado["incompletas"] = sorted(set(estado["incompletas"]) | {fecha})
        # La portada la actualiza la edición diaria; acá solo se guarda la carpeta del día.
        subprocess.call(["git", "checkout", "--", "docs/index.html"], cwd=ROOT)
        subprocess.call(["git", "add", str(_carpeta(fecha))], cwd=ROOT)
        subprocess.call(["git", "commit", "-q", "-m", f"Diario: edición atrasada {fecha} (reprocesada)"], cwd=ROOT)
        hechas += 1
        print(f"✓ {fecha} lista ({hechas} en esta corrida)", flush=True)

    restantes = [f for f in fechas if not (_carpeta(f) / "data.json").exists() and estado["fallidas"].get(f, 0) < 2]
    estado["pendientes"] = len(restantes)
    ESTADO.write_text(json.dumps(estado, indent=1, ensure_ascii=False), encoding="utf-8")
    subprocess.call(["git", "add", str(ESTADO)], cwd=ROOT)
    subprocess.call(["git", "commit", "-q", "-m", f"Diario: estado de atrasadas ({len(restantes)} pendientes)"], cwd=ROOT)
    print(f"RESTANTES={len(restantes)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
