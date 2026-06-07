"""Tests de sec_tickers: formato de CIK y parseo de company_tickers.json."""

from src.ingest.sec_tickers import format_cik, parse_company_tickers


def test_format_cik_pads_to_10_digits():
    assert format_cik(320193) == "0000320193"
    assert format_cik("789019") == "0000789019"


def test_parse_company_tickers():
    data = {
        "0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft"},
    }
    df = parse_company_tickers(data)
    assert list(df.columns) == ["ticker", "cik", "title"]
    assert df.loc[df["ticker"] == "AAPL", "cik"].iloc[0] == "0000320193"
    # Los tickers se normalizan a mayúsculas
    assert set(df["ticker"]) == {"AAPL", "MSFT"}


def test_parse_company_tickers_drops_duplicate_tickers():
    data = {
        "0": {"cik_str": 1, "ticker": "DUP", "title": "A"},
        "1": {"cik_str": 2, "ticker": "DUP", "title": "B"},
    }
    df = parse_company_tickers(data)
    assert len(df) == 1
