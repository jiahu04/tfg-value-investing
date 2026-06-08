"""
point_in_time.py — Acceso point-in-time a los fundamentales (paso 1.2).

A partir de la tabla cruda `data/cache/fundamentals.parquet` (paso 1.1), ofrece,
para una empresa y una fecha de consulta D, las cuentas **tal como se conocían
entonces**: solo se usan hechos con fecha de publicación `filed ≤ D` y, si un mismo
periodo se reexpresó varias veces, la última versión conocida hasta D. Es la
materialización de la regla cardinal del TFG (no usar información futura).

El sistema trabaja con un panel **anual** (formularios 10-K): una fila por año
fiscal. La lógica es pura y se prueba con datos sintéticos, sin red.
"""

from __future__ import annotations

import pandas as pd

from src.ingest import cache_io
from src.utils.config_loader import get_config


def load_fundamentals(path: str | None = None) -> pd.DataFrame:
    """Carga la tabla de fundamentales cacheada en el paso 1.1.

    Args:
        path: Ruta alternativa al Parquet. Si es None, usa
            `data/cache/fundamentals.parquet`.

    Returns:
        DataFrame tidy de hechos financieros (con la columna `filed`).
    """
    cache_path = path if path is not None else cache_io.cache_dir() / "fundamentals.parquet"
    return cache_io.read_parquet(cache_path)


def annual_panel(
    fundamentals: pd.DataFrame,
    ticker: str,
    asof: str | pd.Timestamp,
) -> pd.DataFrame:
    """Construye el panel anual point-in-time de una empresa a una fecha.

    Selecciona, sin usar información futura, el valor anual de cada concepto tal
    como se conocía en `asof`.

    Args:
        fundamentals: Tabla cruda de fundamentales (de `load_fundamentals`).
        ticker: Ticker de la empresa.
        asof: Fecha de consulta D.

    Returns:
        DataFrame indexado por fin de año fiscal (`end`, ascendente), con una columna
        por concepto XBRL y el valor (`val`) correspondiente. Vacío si no hay datos.
    """
    asof = pd.Timestamp(asof)
    prefix = get_config("fundamentals.annual_form_prefix", "10-K")
    pmin = get_config("fundamentals.annual_period_days_min", 300)
    pmax = get_config("fundamentals.annual_period_days_max", 400)

    df = fundamentals[fundamentals["ticker"] == ticker.upper()]
    # Solo formularios anuales (10-K, 10-K/A) y solo lo publicado hasta D (anti-look-ahead).
    df = df[df["form"].astype(str).str.startswith(prefix)]
    df = df[df["filed"].notna() & (df["filed"] <= asof)]
    df = df.dropna(subset=["end"])
    if df.empty:
        return pd.DataFrame()

    # Un 10-K también reporta trimestres y algún instante con fecha de portada. Para
    # quedarnos solo con lo anual:
    #   - duraciones (cuenta de resultados/flujos): periodo de ~1 año.
    #   - instantes (balance): solo si su fecha coincide con un cierre de año fiscal,
    #     definido por las duraciones anuales (descarta, p. ej., acciones a fecha de portada).
    df = df.assign(_period_days=(df["end"] - df["start"]).dt.days)
    is_duration = df["start"].notna()
    is_annual_duration = is_duration & df["_period_days"].between(pmin, pmax)
    fiscal_year_ends = set(df.loc[is_annual_duration, "end"].unique())
    keep = is_annual_duration | (~is_duration & df["end"].isin(fiscal_year_ends))
    df = df[keep]
    if df.empty:
        return pd.DataFrame()

    # Por cada (concepto, año fiscal) quedarse con la última publicación conocida a D
    # (reexpresiones); desempate por periodo más largo.
    df = df.sort_values(["filed", "_period_days"])
    df = df.groupby(["concept", "end"], as_index=False).tail(1)

    panel = df.pivot(index="end", columns="concept", values="val").sort_index()
    panel.columns.name = None
    return panel


def latest_annual(
    fundamentals: pd.DataFrame,
    ticker: str,
    asof: str | pd.Timestamp,
) -> pd.Series:
    """Devuelve el último año fiscal del panel conocido a `asof`.

    Returns:
        Serie (índice = conceptos) con los valores del año fiscal más reciente, o
        una Serie vacía si no hay datos.
    """
    panel = annual_panel(fundamentals, ticker, asof)
    if panel.empty:
        return pd.Series(dtype="float64")
    return panel.iloc[-1]
