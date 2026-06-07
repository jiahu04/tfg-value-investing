"""
sec_facts.py — Fundamentales desde la API `companyfacts` de SEC EDGAR.

Es el módulo más sensible del paso 1.1: descarga los hechos financieros XBRL de
cada empresa y los aplana a una tabla *tidy* **conservando la fecha de publicación
(`filed`) de cada dato**. Esa fecha es lo que permite, más adelante (paso 1.2),
consultar las cuentas tal como se conocían en una fecha pasada sin incurrir en
look-ahead (regla cardinal del TFG).

Diseño:
- Solo se extraen los conceptos declarados en `sec.concepts` (lista curada).
- Si un mismo concepto/periodo se publica varias veces (reexpresión de cuentas),
  se **conservan todas** las filas, cada una con su `filed`. No se deduplica aquí.
- El parseo (`parse_companyfacts`) es puro y se prueba con JSON sintético, sin red.
"""

from __future__ import annotations

import pandas as pd
import requests

from src.ingest import cache_io
from src.ingest.http_client import get_json
from src.ingest.sec_tickers import format_cik
from src.utils.config_loader import get_config

# Columnas (y orden) de la tabla tidy de fundamentales
_COLUMNS = [
    "cik",
    "ticker",
    "taxonomy",
    "concept",
    "unit",
    "start",
    "end",
    "val",
    "fy",
    "fp",
    "form",
    "filed",
    "accn",
    "frame",
]


def _concept_list() -> list[dict]:
    """Devuelve la lista de conceptos a extraer desde la configuración."""
    return get_config("sec.concepts", [])


def parse_companyfacts(
    data: dict,
    concepts: list[dict],
    *,
    ticker: str = "",
) -> pd.DataFrame:
    """Aplana el JSON de `companyfacts` a una tabla tidy con la fecha de publicación.

    Args:
        data: JSON tal como lo devuelve la API `companyfacts`.
        concepts: Lista de conceptos a extraer; cada uno {tag, unit, taxonomy?}.
        ticker: Ticker de la empresa (se añade como columna; opcional).

    Returns:
        DataFrame con una fila por hecho (concepto, periodo, publicación). Conserva
        todas las publicaciones, incluidas las reexpresiones. Vacío si no hay datos.
    """
    cik_raw = data.get("cik", "")
    cik = format_cik(cik_raw) if cik_raw != "" else ""
    facts = data.get("facts", {})

    rows: list[dict] = []
    for concept in concepts:
        tag = concept["tag"]
        unit = concept["unit"]
        taxonomy = concept.get("taxonomy", "us-gaap")

        entries = facts.get(taxonomy, {}).get(tag, {}).get("units", {}).get(unit, [])
        for entry in entries:
            rows.append(
                {
                    "cik": cik,
                    "ticker": ticker.upper(),
                    "taxonomy": taxonomy,
                    "concept": tag,
                    "unit": unit,
                    "start": entry.get("start"),
                    "end": entry.get("end"),
                    "val": entry.get("val"),
                    "fy": entry.get("fy"),
                    "fp": entry.get("fp"),
                    "form": entry.get("form"),
                    "filed": entry.get("filed"),
                    "accn": entry.get("accn"),
                    "frame": entry.get("frame"),
                }
            )

    df = pd.DataFrame(rows, columns=_COLUMNS)
    # Tipos de fecha homogéneos (conservando NaT donde no haya valor)
    for col in ("start", "end", "filed"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def download_companyfacts(cik: str, session: requests.Session) -> dict:
    """Descarga el JSON crudo de `companyfacts` para un CIK."""
    facts_url = get_config("sec.facts_url")
    url = f"{facts_url}/CIK{format_cik(cik)}.json"
    return get_json(url, session)  # type: ignore[return-value]


def ingest_company(
    cik: str,
    ticker: str,
    session: requests.Session,
    *,
    force: bool = False,
) -> pd.DataFrame:
    """Obtiene (descargando o desde crudo) y parsea los fundamentales de una empresa.

    Guarda el JSON crudo en `data/raw/sec/companyfacts/` para poder reconstruir la
    caché sin red. Devuelve la tabla tidy de esa empresa.
    """
    cik = format_cik(cik)
    raw_path = cache_io.raw_dir() / "sec" / "companyfacts" / f"CIK{cik}.json"

    if force or not raw_path.exists():
        try:
            data = download_companyfacts(cik, session)
        except requests.HTTPError:
            # Algunas empresas no tienen companyfacts (p. ej. filers extranjeros).
            return pd.DataFrame(columns=_COLUMNS)
        cache_io.write_json(data, raw_path)
    else:
        data = cache_io.read_json(raw_path)

    return parse_companyfacts(data, _concept_list(), ticker=ticker)


def ingest_fundamentals(
    tickers_df: pd.DataFrame,
    session: requests.Session,
    *,
    force: bool = False,
) -> pd.DataFrame:
    """Ingesta los fundamentales de todas las empresas de `tickers_df`.

    Args:
        tickers_df: DataFrame con columnas ticker y cik (de `sec_tickers`).
        session: Sesión HTTP de la SEC.
        force: Si True, re-descarga aunque exista el crudo.

    Returns:
        DataFrame tidy con los fundamentales de todas las empresas, persistido en
        `data/cache/fundamentals.parquet`.
    """
    frames: list[pd.DataFrame] = []
    for row in tickers_df.itertuples(index=False):
        df = ingest_company(row.cik, row.ticker, session, force=force)
        if not df.empty:
            frames.append(df)

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLUMNS)
    cache_io.write_parquet(result, cache_io.cache_dir() / "fundamentals.parquet")
    return result
