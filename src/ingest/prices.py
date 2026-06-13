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

# Campos de yfinance. OJO: el "Close" de Yahoo viene **ajustado por splits** aunque se
# use auto_adjust=False (solo los dividendos quedan sin ajustar). Para recuperar el
# precio REAL de mercado hay que **deshacer los splits posteriores** multiplicando por
# el factor acumulado de splits con fecha > la del dato (columna "Stock Splits").
_ADJ_FIELD = "Adj Close"  # ajustado por splits y dividendos: backtest y beta
_RAW_FIELD = "Close"  # ajustado por splits, sin dividendos
_SPLIT_FIELD = "Stock Splits"  # ratio de split en su fecha (0 si no hay)

_TIDY_COLUMNS = ["date", "ticker", "close", "close_unadj"]


def _has_field(raw: pd.DataFrame, field: str) -> bool:
    """¿Existe el campo en las columnas (simples o MultiIndex) de yfinance?"""
    if isinstance(raw.columns, pd.MultiIndex):
        return field in raw.columns.get_level_values(0)
    return field in raw.columns


def _extract_field(raw: pd.DataFrame, field: str, default_ticker: str | None) -> pd.DataFrame:
    """Aplana un campo de yfinance a formato largo (date, ticker, value)."""
    if isinstance(raw.columns, pd.MultiIndex):
        long = raw[field].stack().rename("value").reset_index()
        long.columns = ["date", "ticker", "value"]
    else:
        long = raw[field].reset_index()
        long.columns = ["date", "value"]
        long["ticker"] = default_ticker or ""
        long = long[["date", "ticker", "value"]]
    return long


def _future_split_factor(split: pd.Series) -> pd.Series:
    """Factor de splits POSTERIORES a cada fecha (para un ticker ya ordenado por fecha).

    `split` es el ratio del split en su fecha (1 si no hay). El factor en una fecha es el
    producto de los ratios estrictamente posteriores; multiplicar el Close (ajustado por
    splits) por este factor "deshace" esos splits y recupera el precio al que cotizó.
    """
    sp = split.fillna(1.0).replace(0.0, 1.0)
    # Producto acumulado desde el futuro (inclusive); se excluye el propio día con /sp.
    return sp[::-1].cumprod()[::-1] / sp


def to_tidy_close(raw: pd.DataFrame, default_ticker: str | None = None) -> pd.DataFrame:
    """Normaliza un DataFrame de yfinance a formato tidy (date, ticker, close, close_unadj).

    `close` es el precio **ajustado** (Adj Close: splits y dividendos; lo usan backtest y
    beta) y `close_unadj` es el precio **real de mercado**: el "Close" de Yahoo (ajustado
    por splits) multiplicado por el factor de **splits posteriores** para deshacerlos. Es
    lo que usa la valoración, para que sea comparable con el valor por acción del periodo.
    Si no hay "Adj Close", `close` cae a "Close"; si no hay "Stock Splits", el factor es 1.

    Acepta columnas MultiIndex (varios tickers) o simples (un ticker).

    Args:
        raw: DataFrame devuelto por yfinance, indexado por fecha.
        default_ticker: Ticker a usar cuando las columnas no lo indican (un único ticker).

    Returns:
        DataFrame tidy ordenado por ticker y fecha.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=_TIDY_COLUMNS)

    adj_field = _ADJ_FIELD if _has_field(raw, _ADJ_FIELD) else _RAW_FIELD
    adj = _extract_field(raw, adj_field, default_ticker).rename(columns={"value": "close"})
    raw_close = _extract_field(raw, _RAW_FIELD, default_ticker).rename(
        columns={"value": "raw_close"}
    )
    long = adj.merge(raw_close, on=["date", "ticker"], how="left")

    if _has_field(raw, _SPLIT_FIELD):
        splits = _extract_field(raw, _SPLIT_FIELD, default_ticker).rename(
            columns={"value": "split"}
        )
        long = long.merge(splits, on=["date", "ticker"], how="left")
    else:
        long["split"] = 1.0

    long["date"] = pd.to_datetime(long["date"])
    long["ticker"] = long["ticker"].astype(str).str.upper()
    long = long.sort_values(["ticker", "date"]).reset_index(drop=True)
    factor = long.groupby("ticker", group_keys=False)["split"].transform(_future_split_factor)
    long["close_unadj"] = long["raw_close"] * factor
    long = long.dropna(subset=["close"])
    return long[_TIDY_COLUMNS].reset_index(drop=True)


def download_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Descarga precios diarios con yfinance (separado para poder mockear).

    `auto_adjust=False` conserva "Close" (ajustado por splits) y "Adj Close" (ajustado por
    splits y dividendos); `actions=True` añade "Stock Splits" para poder deshacer los
    splits y recuperar el precio real en la valoración.
    """
    import yfinance as yf

    return yf.download(
        tickers=tickers,
        start=start,
        end=end,
        auto_adjust=False,
        actions=True,
        progress=False,
        group_by="column",
    )


def _download_end() -> str:
    """Fecha final de descarga: hasta **hoy** (no solo hasta `backtest_end`).

    Yahoo ajusta todo el histórico por los splits **recientes**; para poder deshacerlos
    (y recuperar el precio real) hay que descargar hasta su fecha, aunque sean posteriores
    a la ventana del backtest. El backtest ya recorta por su propia ventana.
    """
    end = str(get_config("universe.backtest_end"))
    today = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")
    return max(end, today)


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
    end = _download_end()
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
    end = _download_end()
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
    end = _download_end()
    raw = download_prices([ticker], start, end)
    tidy = to_tidy_close(raw, default_ticker=ticker)
    cache_io.write_parquet(tidy, cache_path)
    return tidy
