"""
constituents.py — Composición histórica del S&P 500 (universo point-in-time).

Para no analizar el pasado solo con las empresas que sobreviven hoy (sesgo de
supervivencia, D-004), se usa un CSV público con la composición histórica del
índice. Cada fila es una **fecha de cambio** con la lista completa de tickers
vigentes a partir de ese día.

La función `members_on(df, fecha)` devuelve el universo vigente en una fecha: la
foto del último cambio con fecha anterior o igual. Es lógica *point-in-time* pura
y se prueba sin red.
"""

from __future__ import annotations

import io
import re
from datetime import datetime

import pandas as pd
import requests

from src.ingest import cache_io
from src.utils.config_loader import get_config

# Sufijo de desambiguación del dataset (p. ej. "BAC-199809"): marca el mes en que esa
# empresa dejó el índice, para distinguir símbolos reutilizados. Se elimina para obtener
# el símbolo base que mapea con SEC/yfinance. Solo afecta a empresas antiguas reutilizadas.
_DISAMBIGUATION_SUFFIX = re.compile(r"-\d{6}$")


def _normalize_ticker(token: str) -> str:
    """Limpia un token de ticker: mayúsculas y sin sufijo de desambiguación."""
    return _DISAMBIGUATION_SUFFIX.sub("", token.strip().upper())


def parse_constituents(csv_text: str) -> pd.DataFrame:
    """Convierte el CSV histórico en una tabla tidy (date, ticker).

    El CSV de origen tiene una columna de fecha y otra con los tickers vigentes ese
    día separados por comas. Cada fila es una foto completa del índice en esa fecha.

    Returns:
        DataFrame con columnas date (datetime) y ticker (str, mayúsculas, sin sufijo
        de desambiguación), una fila por (fecha de cambio, ticker), ordenado por fecha.
    """
    date_col = get_config("constituents.date_column", "date")
    tickers_col = get_config("constituents.tickers_column", "tickers")
    separator = get_config("constituents.tickers_separator", ",")

    raw = pd.read_csv(io.StringIO(csv_text))
    raw[date_col] = pd.to_datetime(raw[date_col], errors="coerce")
    raw = raw.dropna(subset=[date_col])

    rows: list[dict] = []
    for record in raw.itertuples(index=False):
        date = getattr(record, date_col)
        cell = getattr(record, tickers_col)
        if pd.isna(cell):
            continue
        seen: set[str] = set()
        for token in str(cell).split(separator):
            ticker = _normalize_ticker(token)
            # Dedup por fecha: el sufijo puede colapsar dos símbolos iguales.
            if ticker and ticker not in seen:
                seen.add(ticker)
                rows.append({"date": date, "ticker": ticker})

    df = pd.DataFrame(rows, columns=["date", "ticker"])
    return df.sort_values(["date", "ticker"]).reset_index(drop=True)


def members_on(df: pd.DataFrame, date: str | pd.Timestamp) -> list[str]:
    """Devuelve los tickers del índice vigentes en una fecha (point-in-time).

    Toma la foto del último cambio con fecha anterior o igual a `date`.

    Args:
        df: Tabla tidy de `parse_constituents`.
        date: Fecha de consulta.

    Returns:
        Lista ordenada de tickers vigentes; vacía si `date` es anterior a la primera
        foto disponible.
    """
    query = pd.Timestamp(date)
    available = df.loc[df["date"] <= query, "date"]
    if available.empty:
        return []
    snapshot_date = available.max()
    members = df.loc[df["date"] == snapshot_date, "ticker"].tolist()
    return sorted(members)


def discover_constituents_url(session: requests.Session) -> str:
    """Localiza, vía la API de GitHub, la URL del CSV histórico más reciente.

    Lista el contenido del repositorio y elige el fichero cuyo nombre cumple
    `constituents.file_pattern` con la fecha más alta. Así el proyecto sigue siendo
    reproducible aunque el mantenedor renombre el fichero con una fecha nueva.

    Raises:
        RuntimeError: Si ningún fichero del repo cumple el patrón.
    """
    api_url = get_config("constituents.repo_contents_url")
    pattern = re.compile(get_config("constituents.file_pattern"))

    response = session.get(api_url, timeout=60)
    response.raise_for_status()
    listing = response.json()

    candidates: list[tuple[datetime, str]] = []
    for item in listing:
        match = pattern.fullmatch(item.get("name", ""))
        if match:
            file_date = datetime.strptime(match.group(1), "%m-%d-%Y")
            candidates.append((file_date, item["download_url"]))

    if not candidates:
        raise RuntimeError(
            "No se encontró ningún CSV histórico de constituyentes que cumpla "
            f"el patrón en {api_url}. Revisa constituents.file_pattern o usa "
            "constituents.url para fijar una URL directa."
        )
    return max(candidates, key=lambda c: c[0])[1]


def download_constituents(session: requests.Session | None = None) -> str:
    """Descarga el CSV histórico de constituyentes y devuelve su texto.

    Usa `constituents.url` si está definido (override); en caso contrario localiza
    dinámicamente el fichero más reciente en el repo.
    """
    sess = session or requests.Session()
    # GitHub exige User-Agent; la sesión de la SEC ya lo trae, pero el fallback no.
    sess.headers.setdefault("User-Agent", "TFG value-investing")

    url = get_config("constituents.url") or discover_constituents_url(sess)
    response = sess.get(url, timeout=60)
    response.raise_for_status()
    return response.text


def ingest_constituents(
    session: requests.Session | None = None,
    *,
    force: bool = False,
) -> pd.DataFrame:
    """Descarga (o reutiliza el crudo), parsea y cachea la composición histórica.

    Returns:
        DataFrame tidy (date, ticker), persistido en
        `data/cache/constituents.parquet`.
    """
    raw_name = get_config("constituents.raw_file", "sp500_historical.csv")
    raw_path = cache_io.raw_dir() / "constituents" / raw_name
    cache_path = cache_io.cache_dir() / "constituents.parquet"

    if force or not raw_path.exists():
        csv_text = download_constituents(session)
        cache_io.ensure_dir(raw_path.parent)
        raw_path.write_text(csv_text, encoding="utf-8")
    else:
        csv_text = raw_path.read_text(encoding="utf-8")

    df = parse_constituents(csv_text)
    cache_io.write_parquet(df, cache_path)
    return df
