"""
verify_imports.py — Paso 0.3: comprueba que todas las librerías se importan correctamente.

Ejecutar con:
    python scripts/verify_imports.py

Si termina sin errores, el entorno está correctamente configurado.
"""

import sys

REQUIRED = [
    ("pandas", "pd"),
    ("numpy", "np"),
    ("scipy", None),
    ("scipy.stats", None),
    ("requests", None),
    ("yaml", None),  # PyYAML
    ("pyarrow", None),
    ("yfinance", "yf"),
    ("numpy_financial", "npf"),
    ("matplotlib", None),
    ("matplotlib.pyplot", "plt"),
    ("pytest", None),
    ("ruff", None),
]


def check_imports() -> bool:
    """Intenta importar todas las librerías y reporta el resultado."""
    all_ok = True
    max_len = max(len(mod) for mod, _ in REQUIRED)

    print("Verificando importaciones...\n")
    for module_name, _alias in REQUIRED:
        try:
            mod = __import__(module_name)
            version = getattr(mod, "__version__", "?")
            status = f"OK  (v{version})"
        except ImportError as e:
            status = f"ERROR — {e}"
            all_ok = False

        print(f"  {module_name:<{max_len}}  {status}")

    print()

    # Comprobación adicional: el config_loader del propio proyecto
    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
        from src.utils.config_loader import load_config

        cfg = load_config()
        print(f"  {'config_loader':<{max_len}}  OK  (config.yaml leído, {len(cfg)} secciones)")
    except Exception as e:
        print(f"  {'config_loader':<{max_len}}  ERROR — {e}")
        all_ok = False

    print()
    if all_ok:
        print("[OK] Todo correcto. El entorno está listo.")
    else:
        print("[ERROR] Hay errores. Revisa los mensajes anteriores y ejecuta:")
        print("    pip install -r requirements.txt")

    return all_ok


if __name__ == "__main__":
    success = check_imports()
    sys.exit(0 if success else 1)
