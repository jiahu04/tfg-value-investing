"""
sec_tickers.py — Mapa ticker <-> CIK de la SEC.

La SEC publica `company_tickers.json`, que relaciona cada ticker bursátil con su
CIK (Central Index Key), el identificador necesario para pedir `companyfacts` y
`submissions`. Aquí se descarga, se parsea a un DataFrame y se cachea.

El parseo está separado de la descarga para poder probarlo sin red.
"""

from __future__ import annotations

import pandas as pd
import requests

from src.ingest import cache_io
from src.ingest.http_client import get_json
from src.utils.config_loader import get_config

# Fichero crudo cacheado
_RAW_NAME = "company_tickers.json"


def format_cik(cik: int | str) -> str:
    """Devuelve el CIK con 10 dígitos y ceros a la izquierda (formato de la SEC)."""
    return str(int(cik)).zfill(10)


def parse_company_tickers(data: dict) -> pd.DataFrame:
    """Convierte el JSON de `company_tickers.json` en un DataFrame.

    El JSON tiene forma {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}.

    Returns:
        DataFrame con columnas: ticker, cik (10 dígitos, str), title.
    """
    rows = [
        {
            "ticker": str(entry["ticker"]).upper(),
            "cik": format_cik(entry["cik_str"]),
            "title": entry.get("title", ""),
        }
        for entry in data.values()
    ]
    df = pd.DataFrame(rows, columns=["ticker", "cik", "title"])
    return df.drop_duplicates(subset="ticker").reset_index(drop=True)


def download_company_tickers(session: requests.Session) -> dict:
    """Descarga el JSON crudo `company_tickers.json` desde la SEC."""
    url = get_config("sec.tickers_url")
    return get_json(url, session)  # type: ignore[return-value]


def ingest_tickers(session: requests.Session, *, force: bool = False) -> pd.DataFrame:
    """Descarga (o reutiliza el crudo), parsea y cachea el mapa ticker<->CIK.

    Args:
        session: Sesión HTTP de la SEC.
        force: Si True, vuelve a descargar aunque exista el crudo en `data/raw`.

    Returns:
        DataFrame ticker/cik/title.
    """
    raw_path = cache_io.raw_dir() / "sec" / _RAW_NAME
    cache_path = cache_io.cache_dir() / "tickers.parquet"

    if force or not raw_path.exists():
        data = download_company_tickers(session)
        cache_io.write_json(data, raw_path)
    else:
        data = cache_io.read_json(raw_path)

    df = parse_company_tickers(data)
    cache_io.write_parquet(df, cache_path)
    return df
