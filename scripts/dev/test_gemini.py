# Archivo: test_gemini.py
import os
import sys
from google import genai
from google.genai import types as genai_types
from dotenv import load_dotenv

load_dotenv()  # Carga GEMINI_API_KEY desde .env

GEMINI_MODEL = "gemini-2.5-flash"

def test_gemini_connection():
    """Test mínimo de conectividad con Gemini API (google-genai SDK)."""
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        print("❌ GEMINI_API_KEY no encontrada")
        return False

    try:
        client = genai.Client(api_key=api_key)
        config = genai_types.GenerateContentConfig(temperature=0.0, max_output_tokens=10)

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[genai_types.Content(parts=[genai_types.Part(text="Respondé solo con 'OK'")])],
            config=config,
        )

        if response.text and "ok" in response.text.strip().lower():
            print(f"✅ Gemini API ({GEMINI_MODEL}) funciona correctamente")
            return True
        else:
            print(f"⚠️ Respuesta inesperada: {response.text}")
            return False

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Test de conexión con Gemini API...")
    success = test_gemini_connection()
    sys.exit(0 if success else 1)