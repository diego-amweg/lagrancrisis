# src/test_deps.py
import sys

def check_deps():
    # Dependencias con su forma correcta de import
    deps = {
        "feedparser": "feedparser",
        "jinja2": "jinja2",
        "rapidfuzz": "rapidfuzz",
        "python-dateutil": "dateutil",
        "google-genai": None,   # import especial, ver abajo
    }

    ok = True
    for display_name, import_name in deps.items():
        try:
            if import_name:
                __import__(import_name)
            else:
                # google-genai usa namespace: from google import genai
                from google import genai  # noqa: F401
            print(f"✓ {display_name}")
        except ImportError:
            print(f"✗ {display_name} FALTA")
            ok = False
    return ok

if __name__ == "__main__":
    sys.exit(0 if check_deps() else 1)