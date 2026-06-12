"""Tests de prices: normalización de los DataFrames de yfinance a formato tidy."""

import numpy as np
import pandas as pd

from src.ingest.prices import to_tidy_close

_COLS = ["date", "ticker", "close", "close_unadj"]


def test_to_tidy_close_multiindex():
    idx = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], name="Date")
    cols = pd.MultiIndex.from_product([["Close"], ["AAPL", "MSFT"]])
    raw = pd.DataFrame([[10.0, 20.0], [11.0, 21.0]], index=idx, columns=cols)

    tidy = to_tidy_close(raw)
    assert list(tidy.columns) == _COLS
    assert len(tidy) == 4
    aapl = tidy[tidy["ticker"] == "AAPL"].sort_values("date")
    assert aapl["close"].tolist() == [10.0, 11.0]
    # Sin "Adj Close": close cae a "Close" y close_unadj coincide.
    assert aapl["close_unadj"].tolist() == [10.0, 11.0]


def test_to_tidy_close_adjusted_and_unadjusted():
    # Sin splits: close = Adj Close; close_unadj = Close (factor de splits = 1).
    idx = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], name="Date")
    cols = pd.MultiIndex.from_tuples([("Close", "AAPL"), ("Adj Close", "AAPL")])
    raw = pd.DataFrame([[100.0, 25.0], [110.0, 27.5]], index=idx, columns=cols)

    tidy = to_tidy_close(raw).sort_values("date")
    assert tidy["close"].tolist() == [25.0, 27.5]  # ajustado (Adj Close)
    assert tidy["close_unadj"].tolist() == [100.0, 110.0]  # Close (sin splits que deshacer)


def test_to_tidy_close_undoes_future_splits():
    # El "Close" de Yahoo viene ajustado por splits (plano en 50); un split 2:1 en el
    # tercer día implica que el precio REAL antes del split era el doble (100).
    idx = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"], name="Date")
    raw = pd.DataFrame(
        {
            "Close": [50.0, 50.0, 50.0],
            "Adj Close": [48.0, 48.0, 49.0],
            "Stock Splits": [0.0, 0.0, 2.0],  # split 2:1 el día 3
        },
        index=idx,
    )

    tidy = to_tidy_close(raw, default_ticker="ZZZ").sort_values("date")
    assert tidy["close"].tolist() == [48.0, 48.0, 49.0]  # ajustado (backtest/beta)
    # Real: 100 antes del split (×2), 50 a partir del split.
    assert tidy["close_unadj"].tolist() == [100.0, 100.0, 50.0]


def test_to_tidy_close_single_ticker():
    idx = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], name="Date")
    raw = pd.DataFrame(
        {"Open": [1.0, 2.0], "Close": [1.5, 2.5], "Adj Close": [1.4, 2.4]}, index=idx
    )

    tidy = to_tidy_close(raw, default_ticker="^IRX")
    assert list(tidy.columns) == _COLS
    assert (tidy["ticker"] == "^IRX").all()
    assert tidy["close"].tolist() == [1.4, 2.4]  # Adj Close
    assert tidy["close_unadj"].tolist() == [1.5, 2.5]  # Close


def test_to_tidy_close_drops_nan():
    idx = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], name="Date")
    cols = pd.MultiIndex.from_product([["Close"], ["AAPL"]])
    raw = pd.DataFrame([[10.0], [np.nan]], index=idx, columns=cols)

    tidy = to_tidy_close(raw)
    assert len(tidy) == 1


def test_to_tidy_close_empty():
    tidy = to_tidy_close(pd.DataFrame())
    assert tidy.empty
    assert list(tidy.columns) == _COLS
