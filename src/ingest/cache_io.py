"""
cache_io.py — Persistencia local de la caché de datos (Parquet / CSV / JSON).

Centraliza la lectura y escritura de ficheros bajo `data/raw` y `data/cache`,
tomando las rutas de la sección `cache` de la configuración. El resto de los
módulos de ingesta no construye rutas a mano: las pide aquí.

Convención del proyecto (D-006): Parquet para tablas grandes, CSV para pequeñas;
los datos crudos descargados se guardan en `data/raw` para poder reconstruir la
caché sin volver a descargar.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from src.utils.config_loader import get_config

# Raíz del proyecto (config/config.yaml está en la raíz; este fichero, en src/ingest/)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve(relative: str) -> Path:
    """Convierte una ruta relativa de la config en absoluta respecto a la raíz."""
    return _PROJECT_ROOT / relative


def raw_dir() -> Path:
    """Directorio de datos crudos descargados (`cache.raw_dir`)."""
    return _resolve(get_config("cache.raw_dir", "data/raw"))


def cache_dir() -> Path:
    """Directorio de la caché procesada (`cache.cache_dir`)."""
    return _resolve(get_config("cache.cache_dir", "data/cache"))


def ensure_dir(path: Path) -> Path:
    """Crea el directorio (y padres) si no existe y lo devuelve."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_fresh(path: Path, max_age_days: float | None = None) -> bool:
    """Indica si un fichero existe y es más reciente que `max_age_days`.

    Args:
        path: Ruta del fichero a comprobar.
        max_age_days: Antigüedad máxima en días. Si es None, se usa
            `cache.max_age_days` de la configuración.

    Returns:
        True si el fichero existe y su antigüedad es menor o igual al límite.
    """
    if not path.exists():
        return False
    if max_age_days is None:
        max_age_days = get_config("cache.max_age_days", 7)
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds <= max_age_days * 86400


# ---------------------------------------------------------------------------
# Parquet
# ---------------------------------------------------------------------------
def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    """Escribe un DataFrame en Parquet, creando el directorio si hace falta."""
    ensure_dir(path.parent)
    df.to_parquet(path, index=False)
    return path


def read_parquet(path: Path) -> pd.DataFrame:
    """Lee un DataFrame desde Parquet."""
    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def write_csv(df: pd.DataFrame, path: Path) -> Path:
    """Escribe un DataFrame en CSV (UTF-8, sin índice)."""
    ensure_dir(path.parent)
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    """Lee un DataFrame desde CSV."""
    return pd.read_csv(path, **kwargs)


# ---------------------------------------------------------------------------
# JSON (datos crudos de la SEC)
# ---------------------------------------------------------------------------
def write_json(data: Any, path: Path) -> Path:
    """Escribe un objeto serializable como JSON (UTF-8)."""
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def read_json(path: Path) -> Any:
    """Lee un objeto desde un fichero JSON (UTF-8)."""
    with path.open(encoding="utf-8") as f:
        return json.load(f)
