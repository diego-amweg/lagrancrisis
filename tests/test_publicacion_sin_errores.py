"""
Pruebas de los arreglos del 21 y 22/11/2026 (paso a publicación automática en GitHub).

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
    monkeypatch.delenv("LGC_MODELS", raising=False)
    assert llm._load_gemini_models() == llm.DEFAULT_MODELS
    monkeypatch.setenv("LGC_MODELS", "claude-haiku-5-5,gemini-2.5-flash")
    assert llm._load_gemini_models() == ["claude-haiku-5-5", "gemini-2.5-flash"]


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


# --- Cambio de modelo entre empresas y chequeo previo (22/11/2026) ---

def _falso_generate(comportamiento):
    """Reemplaza la llamada real: cada modelo responde, falla o queda sin cuota según la tabla."""
    llamados = []

    def generate(model_name, prompt, max_output_tokens=12000, json_mode=True):
        llamados.append(model_name)
        accion = comportamiento[model_name]
        if isinstance(accion, int):
            raise llm.ModelCallError(model_name, accion, f"error {accion}")
        llm._record_usage(model_name, 100, 50)
        return accion

    return generate, llamados


def test_si_gemini_se_queda_sin_cuota_responde_claude(monkeypatch):
    generate, llamados = _falso_generate({
        "gemini-2.5-flash-lite": 429,
        "gemini-2.5-flash": 429,
        "claude-haiku-5-5": '{"resumen_ejecutivo": "ok"}',
    })
    monkeypatch.setattr(llm, "_generate", generate)
    monkeypatch.setattr(llm, "ACTIVE_MODELS", ["gemini-2.5-flash-lite", "gemini-2.5-flash", "claude-haiku-5-5"])
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    resultado = llm.call_gemini_with_retry("prompt", debug_label="test")
    assert resultado == {"resumen_ejecutivo": "ok"}
    # Sin cuota no se reintenta el mismo modelo: un solo intento por modelo de Gemini.
    assert llamados == ["gemini-2.5-flash-lite", "gemini-2.5-flash", "claude-haiku-5-5"]
    assert llm.ACTIVE_MODELS == ["claude-haiku-5-5"]


def test_saturado_se_reintenta_y_despues_cambia(monkeypatch):
    generate, llamados = _falso_generate({
        "gemini-2.5-flash-lite": 503,
        "claude-haiku-5-5": '{"x": 1}',
    })
    monkeypatch.setattr(llm, "_generate", generate)
    monkeypatch.setattr(llm, "ACTIVE_MODELS", ["gemini-2.5-flash-lite", "claude-haiku-5-5"])
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    assert llm.call_gemini_with_retry("prompt", max_retries=3) == {"x": 1}
    assert llamados.count("gemini-2.5-flash-lite") == 3
    assert "gemini-2.5-flash-lite" in llm.ACTIVE_MODELS  # saturado no se descarta


def test_chequeo_previo_ordena_por_los_que_responden(monkeypatch):
    generate, _ = _falso_generate({
        "gemini-2.5-flash-lite": 503,
        "gemini-2.5-flash": 404,
        "claude-haiku-5-5": "OK",
    })
    monkeypatch.setattr(llm, "_generate", generate)
    monkeypatch.setattr(llm, "GEMINI_MODELS", ["gemini-2.5-flash-lite", "gemini-2.5-flash", "claude-haiku-5-5"])
    monkeypatch.setattr(llm, "ACTIVE_MODELS", [])
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    orden = llm.preflight_models()
    assert orden == ["claude-haiku-5-5", "gemini-2.5-flash-lite"]
    assert llm.LLM_PREFLIGHT["gemini-2.5-flash"] == "error 404"


def test_modelo_sin_clave_se_saltea(monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_MODELS", ["gemini-2.5-flash-lite", "claude-haiku-5-5"])
    monkeypatch.setattr(llm, "ACTIVE_MODELS", [])
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    generate, _ = _falso_generate({"gemini-2.5-flash-lite": "OK"})
    monkeypatch.setattr(llm, "_generate", generate)
    assert llm.preflight_models() == ["gemini-2.5-flash-lite"]
    assert llm.LLM_PREFLIGHT["claude-haiku-5-5"] == "sin clave"


def test_registro_de_uso_por_modelo(monkeypatch):
    llm.reset_llm_runtime_metrics()
    llm._record_usage("claude-haiku-5-5", 1000, 200)
    llm._record_usage("claude-haiku-5-5", 500, 100)
    uso = llm.get_llm_usage_report()["llm_token_usage"]["claude-haiku-5-5"]
    assert uso == {"calls": 2, "input_tokens": 1500, "output_tokens": 300}


def test_memoria_de_ayer_usa_la_fecha_de_la_edicion(monkeypatch, tmp_path):
    import src.main as main_mod
    (tmp_path / "docs/2026/06/09").mkdir(parents=True)
    (tmp_path / "docs/2026/06/09/data.json").write_text('{"resumen_ejecutivo": "resumen del 9 de junio"}', encoding="utf-8")
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main_mod, "TODAY", "2026-06-10")
    _, resumen_ayer = main_mod.load_context_and_memory()
    assert resumen_ayer == "resumen del 9 de junio"


def test_portada_no_retrocede_al_reprocesar_un_dia_viejo(monkeypatch, tmp_path):
    from src import builder
    for fecha in ("2026/11/22", "2026/06/10"):
        (tmp_path / "docs" / fecha).mkdir(parents=True)
        (tmp_path / "docs" / fecha / "index.html").write_text("x", encoding="utf-8")
    monkeypatch.setattr(builder, "DOCS_DIR", tmp_path / "docs")
    capturado = {}
    monkeypatch.setattr(builder, "Environment", lambda **kw: type("E", (), {
        "get_template": lambda self, name: type("T", (), {"render": lambda self, **ctx: capturado.update(ctx) or ""})()
    })())
    builder.update_index_page("2026-06-10")
    assert capturado["latest"] == "2026/11/22/"
