# Archivo: src/test_gemini_minimal.py
"""Test mínimo para validar conexión con Gemini API sin dependencias del pipeline completo."""
import os
import logging
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_gemini_connection(api_key: str) -> bool:
    """Prueba de conectividad básica con Gemini Flash."""
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            contents=[types.Content(parts=[types.Part(text="Respondé solo con: OK")])],
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=50,
            )
        )
        text = response.text.strip()
        logger.info(f"Respuesta de Gemini: '{text}'")
        return text.upper() == "OK"
    except Exception as e:
        logger.error(f"Error en test de conexión: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY no configurada")
        exit(1)
    
    success = test_gemini_connection(api_key)
    logger.info(f"Test de conexión: {'✅ PASÓ' if success else '❌ FALLÓ'}")
    exit(0 if success else 1)