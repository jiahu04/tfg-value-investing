"""
sec_submissions.py — Metadatos de cada empresa desde la API `submissions` de la SEC.

De `submissions` se extrae el código SIC (para derivar el sector) y el nombre
oficial. El resultado se combina con la agrupación de `sectors.py` y se cachea en
`data/cache/sectors.csv`.

El parseo está separado de la descarga para poder probarlo sin red.
"""

from __future__ import annotations

import pandas as pd
import requests

from src.ingest import cache_io
from src.ingest.http_client import get_json
from src.ingest.sec_tickers import format_cik
from src.ingest.sectors import sic_to_sector
from src.utils.config_loader import get_config

_COLUMNS = ["ticker", "cik", "sic", "sic_description", "name", "sector"]


def parse_submissions(data: dict, *, ticker: str = "") -> dict:
    """Extrae sic, descripción y nombre del JSON de `submissions`.

    Returns:
        Diccionario con ticker, cik, sic (str), sic_description, name.
    """
    cik_raw = data.get("cik", "")
    sic = data.get("sic", "")
    return {
        "ticker": ticker.upper(),
        "cik": format_cik(cik_raw) if cik_raw != "" else "",
        "sic": str(sic) if sic not in (None, "") else "",
        "sic_description": data.get("sicDescription", ""),
        "name": data.get("name", ""),
    }


def download_submissions(cik: str, session: requests.Session) -> dict:
    """Descarga el JSON crudo de `submissions` para un CIK."""
    submissions_url = get_config("sec.submissions_url")
    url = f"{submissions_url}/CIK{format_cik(cik)}.json"
    return get_json(url, session)  # type: ignore[return-value]


def ingest_company_meta(
    cik: str,
    ticker: str,
    session: requests.Session,
    *,
    force: bool = False,
) -> dict | None:
    """Obtiene (descargando o desde crudo) los metadatos de una empresa.

    Returns:
        Diccionario con los campos de `_COLUMNS`, o None si no hay datos.
    """
    cik = format_cik(cik)
    raw_path = cache_io.raw_dir() / "sec" / "submissions" / f"CIK{cik}.json"

    if force or not raw_path.exists():
        try:
            data = download_submissions(cik, session)
        except requests.HTTPError:
            return None
        cache_io.write_json(data, raw_path)
    else:
        data = cache_io.read_json(raw_path)

    meta = parse_submissions(data, ticker=ticker)
    meta["sector"] = sic_to_sector(meta["sic"] or None)
    return meta


def ingest_sectors(
    tickers_df: pd.DataFrame,
    session: requests.Session,
    *,
    force: bool = False,
) -> pd.DataFrame:
    """Ingesta los metadatos (SIC y sector) de todas las empresas de `tickers_df`.

    Returns:
        DataFrame con columnas de `_COLUMNS`, persistido en `data/cache/sectors.csv`.
    """
    rows: list[dict] = []
    for row in tickers_df.itertuples(index=False):
        meta = ingest_company_meta(row.cik, row.ticker, session, force=force)
        if meta is not None:
            rows.append(meta)

    result = pd.DataFrame(rows, columns=_COLUMNS)
    cache_io.write_csv(result, cache_io.cache_dir() / "sectors.csv")
    return result
