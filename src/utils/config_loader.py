"""
config_loader.py — Cargador centralizado de la configuración del sistema.

Uso:
    from src.utils.config_loader import load_config, get_config

    cfg = load_config()                    # carga desde la ruta por defecto
    cfg = load_config("ruta/custom.yaml")  # carga desde una ruta concreta

    # Acceso por clave anidada (con punto como separador):
    email = get_config("sec.contact_email")
    max_pos = get_config("portfolio.max_positions")
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Ruta por defecto: config/config.yaml relativo a la raíz del proyecto
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


@lru_cache(maxsize=1)
def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Carga y devuelve la configuración como diccionario.

    La primera llamada lee el fichero YAML y lo cachea en memoria.
    Las llamadas sucesivas devuelven el objeto cacheado sin releer el disco.
    Para forzar una recarga (p. ej. en tests) llama a load_config.cache_clear()
    antes de volver a invocar load_config().

    Args:
        path: Ruta al fichero YAML. Si es None, usa config/config.yaml.

    Returns:
        Diccionario con la configuración completa.

    Raises:
        FileNotFoundError: Si el fichero no existe.
        yaml.YAMLError: Si el fichero tiene errores de sintaxis YAML.
    """
    resolved = Path(path) if path else _DEFAULT_CONFIG_PATH

    if not resolved.exists():
        raise FileNotFoundError(
            f"Fichero de configuración no encontrado: {resolved}\n"
            f"Asegúrate de que existe config/config.yaml en la raíz del proyecto."
        )

    with resolved.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if config is None:
        raise ValueError(f"El fichero de configuración está vacío: {resolved}")

    return config


def get_config(key: str, default: Any = None) -> Any:
    """Accede a un valor de la configuración por clave anidada con puntos.

    Ejemplo:
        get_config("sec.contact_email")
        get_config("portfolio.max_positions")
        get_config("backtest.transaction_cost_pct")

    Args:
        key: Clave en notación de puntos (p. ej. "sec.contact_email").
        default: Valor devuelto si la clave no existe.

    Returns:
        El valor correspondiente en la configuración, o `default` si no existe.
    """
    cfg = load_config()
    parts = key.split(".")
    value: Any = cfg
    for part in parts:
        if not isinstance(value, dict):
            return default
        value = value.get(part)
        if value is None:
            return default
    return value


def reload_config(path: str | Path | None = None) -> dict[str, Any]:
    """Fuerza una recarga del fichero de configuración desde disco.

    Útil en tests que necesitan probar distintas configuraciones.
    """
    load_config.cache_clear()
    return load_config(path)
