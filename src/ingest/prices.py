"""
prices.py — Precios históricos, índice y tipo libre de riesgo (yfinance).

Descarga y cachea:
- Precios diarios (ajustados) de las acciones del universo.
- El índice de referencia con dividendos (`^SP500TR`).
- La serie del tipo libre de riesgo (letra del Tesoro a 13 semanas, `^IRX`),
  usada para el ratio de Sharpe y para remunerar la liquidez.

Los precios no sufren look-ahead, así que basta con cachearlos. La descarga
(yfinance) está separada de la normalización para poder probar esta última con
DataFrames sintéticos, sin red.
"""

from __future__ import annotations

import pandas as pd

from src.ingest import cache_io
from src.utils.config_loader import get_config

# Campo de precio que se conserva (con auto_adjust=True, "Close" ya viene ajustado)
_PRICE_FIELD = "Close"


def to_tidy_close(raw: pd.DataFrame, default_ticker: str | None = None) -> pd.DataFrame:
    """Normaliza un DataFrame de yfinance a formato tidy (date, ticker, close).

    Acepta dos formas:
    - Columnas MultiIndex (campo, ticker), como cuando se piden varios tickers.
    - Columnas simples con un campo "Close", como cuando se pide un único ticker.

    Args:
        raw: DataFrame devuelto por yfinance, indexado por fecha.
        default_ticker: Ticker a usar cuando las columnas no lo indican (caso de
            un único ticker).

    Returns:
        DataFrame tidy con columnas date, ticker, close, ordenado por ticker y fecha.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "ticker", "close"])

    if isinstance(raw.columns, pd.MultiIndex):
        # (campo, ticker) -> nos quedamos con el campo de precio y apilamos por ticker
        close = raw[_PRICE_FIELD]
        long = close.stack().rename("close").reset_index()
        long.columns = ["date", "ticker", "close"]
    else:
        series = raw[_PRICE_FIELD]
        long = series.reset_index()
        long.columns = ["date", "close"]
        long["ticker"] = default_ticker or ""
        long = long[["date", "ticker", "close"]]

    long["date"] = pd.to_datetime(long["date"])
    long["ticker"] = long["ticker"].astype(str).str.upper()
    long = long.dropna(subset=["close"])
    return long.sort_values(["ticker", "date"]).reset_index(drop=True)


def download_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Descarga precios diarios ajustados con yfinance (separado para poder mockear)."""
    import yfinance as yf

    return yf.download(
        tickers=tickers,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        group_by="column",
    )


def ingest_prices(tickers: list[str], *, force: bool = False) -> pd.DataFrame:
    """Descarga y cachea los precios de las acciones del universo.

    Returns:
        DataFrame tidy (date, ticker, close) persistido en
        `data/cache/prices.parquet`.
    """
    cache_path = cache_io.cache_dir() / "prices.parquet"
    if not force and cache_io.is_fresh(cache_path):
        return cache_io.read_parquet(cache_path)

    start = get_config("universe.backtest_start")
    end = get_config("universe.backtest_end")
    raw = download_prices(tickers, start, end)
    tidy = to_tidy_close(raw)
    cache_io.write_parquet(tidy, cache_path)
    return tidy


def ingest_index(*, force: bool = False) -> pd.DataFrame:
    """Descarga y cachea el índice de referencia (`prices.index_ticker`)."""
    ticker = get_config("prices.index_ticker")
    cache_path = cache_io.cache_dir() / "index_prices.parquet"
    if not force and cache_io.is_fresh(cache_path):
        return cache_io.read_parquet(cache_path)

    start = get_config("universe.backtest_start")
    end = get_config("universe.backtest_end")
    raw = download_prices([ticker], start, end)
    tidy = to_tidy_close(raw, default_ticker=ticker)
    cache_io.write_parquet(tidy, cache_path)
    return tidy


def ingest_risk_free(*, force: bool = False) -> pd.DataFrame:
    """Descarga y cachea la serie del tipo libre de riesgo (`prices.risk_free_ticker`)."""
    ticker = get_config("prices.risk_free_ticker")
    cache_path = cache_io.cache_dir() / "risk_free.parquet"
    if not force and cache_io.is_fresh(cache_path):
        return cache_io.read_parquet(cache_path)

    start = get_config("universe.backtest_start")
    end = get_config("universe.backtest_end")
    raw = download_prices([ticker], start, end)
    tidy = to_tidy_close(raw, default_ticker=ticker)
    cache_io.write_parquet(tidy, cache_path)
    return tidy
