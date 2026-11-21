"""
Pruebas de los arreglos del 21/11/2026 (paso a publicación automática en GitHub).

Se corren antes de cada edición en GitHub: si alguna falla, ese día no se publica.
"""

import importlib
import socket
import threading
import time

import pytest

from src import fetch_rss, llm
from src.main import _build_deterministic_synthesis


def test_error_de_api_no_llega_al_resumen_publico():
    error = "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota'}}"
    fallback = llm._build_fallback_from_error(error)
    assert "429" not in fallback["resumen_ejecutivo"]
    assert "RESOURCE_EXHAUSTED" not in fallback["resumen_ejecutivo"]
    assert fallback["_fallback"] is True


def test_sintesis_de_respaldo_no_inventa_contexto():
    noticias = [{"headline": "Riesgo país supera los 1.000 puntos"}, {"headline": "La Fed mantiene tasas"}]
    cadena, resumen = _build_deterministic_synthesis(noticias)
    assert "no pudo generarse" in resumen
    assert "Riesgo país supera los 1.000 puntos" in resumen
    for frase_inventada in ("geopolítico", "señales mixtas", "shocks externos"):
        assert frase_inventada not in resumen
        assert frase_inventada not in cadena


def test_modelos_configurables_por_variable(monkeypatch):
    monkeypatch.setenv("LGC_GEMINI_MODELS", " modelo-a , modelo-b,modelo-a ,, ")
    assert llm._load_gemini_models() == ["modelo-a", "modelo-b"]
    monkeypatch.setenv("LGC_GEMINI_MODELS", "")
    assert llm._load_gemini_models() == llm.DEFAULT_GEMINI_MODELS


def test_fuente_que_no_responde_no_cuelga_la_corrida(monkeypatch):
    # Servidor local que acepta la conexión y nunca contesta.
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(5)
    puerto = servidor.getsockname()[1]
    conexiones = []

    def aceptar():
        try:
            while True:
                conn, _ = servidor.accept()
                conexiones.append(conn)
        except OSError:
            pass

    threading.Thread(target=aceptar, daemon=True).start()
    monkeypatch.setenv("LGC_FEED_TIMEOUT_SECONDS", "5")

    fuentes = [{"name": "Fuente colgada", "url": f"http://127.0.0.1:{puerto}/rss.xml", "category": "test"}]
    inicio = time.monotonic()
    articulos = fetch_rss.fetch_all_feeds(fuentes, hours_back=48, max_entries_per_source=10)
    demora = time.monotonic() - inicio

    servidor.close()
    for conn in conexiones:
        conn.close()

    assert articulos == []
    assert demora < 20, f"la descarga tardó {demora:.0f} s: el tiempo de espera no se aplicó"
    assert socket.getdefaulttimeout() is None, "el tiempo de espera global debe restaurarse"
