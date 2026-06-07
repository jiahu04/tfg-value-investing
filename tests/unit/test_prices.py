"""Tests de prices: normalización de los DataFrames de yfinance a formato tidy."""

import numpy as np
import pandas as pd

from src.ingest.prices import to_tidy_close


def test_to_tidy_close_multiindex():
    idx = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], name="Date")
    cols = pd.MultiIndex.from_product([["Close"], ["AAPL", "MSFT"]])
    raw = pd.DataFrame([[10.0, 20.0], [11.0, 21.0]], index=idx, columns=cols)

    tidy = to_tidy_close(raw)
    assert list(tidy.columns) == ["date", "ticker", "close"]
    assert len(tidy) == 4
    aapl = tidy[tidy["ticker"] == "AAPL"].sort_values("date")
    assert aapl["close"].tolist() == [10.0, 11.0]


def test_to_tidy_close_single_ticker():
    idx = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], name="Date")
    raw = pd.DataFrame({"Open": [1.0, 2.0], "Close": [1.5, 2.5]}, index=idx)

    tidy = to_tidy_close(raw, default_ticker="^IRX")
    assert list(tidy.columns) == ["date", "ticker", "close"]
    assert (tidy["ticker"] == "^IRX").all()
    assert tidy["close"].tolist() == [1.5, 2.5]


def test_to_tidy_close_drops_nan():
    idx = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], name="Date")
    cols = pd.MultiIndex.from_product([["Close"], ["AAPL"]])
    raw = pd.DataFrame([[10.0], [np.nan]], index=idx, columns=cols)

    tidy = to_tidy_close(raw)
    assert len(tidy) == 1


def test_to_tidy_close_empty():
    tidy = to_tidy_close(pd.DataFrame())
    assert tidy.empty
    assert list(tidy.columns) == ["date", "ticker", "close"]
