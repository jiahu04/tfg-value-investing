"""Tests de constituents: parseo del CSV histórico y acceso point-in-time.

El caso point-in-time es clave para mitigar el sesgo de supervivencia: el universo
de una fecha es la foto del último cambio con fecha anterior o igual.
"""

import pandas as pd

from src.ingest.constituents import (
    discover_constituents_url,
    members_on,
    parse_constituents,
)

# CSV sintético: tres fechas de cambio con composiciones distintas
CSV = (
    "date,tickers\n"
    '2015-01-01,"AAPL,MSFT,IBM"\n'
    '2018-06-01,"AAPL,MSFT,NVDA"\n'
    '2020-03-01,"AAPL,NVDA,TSLA"\n'
)


def test_parse_constituents_explodes_tickers():
    df = parse_constituents(CSV)
    assert list(df.columns) == ["date", "ticker"]
    # 3 fechas x 3 tickers
    assert len(df) == 9
    assert df["date"].nunique() == 3
    # Normaliza a mayúsculas y ordena
    assert set(df["ticker"].unique()) == {"AAPL", "MSFT", "IBM", "NVDA", "TSLA"}


def test_members_on_exact_change_date():
    df = parse_constituents(CSV)
    assert members_on(df, "2018-06-01") == ["AAPL", "MSFT", "NVDA"]


def test_members_on_between_changes_uses_previous_snapshot():
    df = parse_constituents(CSV)
    # Una fecha entre dos cambios devuelve la foto anterior (point-in-time)
    assert members_on(df, "2019-01-15") == ["AAPL", "MSFT", "NVDA"]
    assert members_on(df, "2016-07-01") == ["AAPL", "IBM", "MSFT"]


def test_members_on_after_last_change():
    df = parse_constituents(CSV)
    assert members_on(df, "2024-01-01") == ["AAPL", "NVDA", "TSLA"]


def test_members_on_before_first_change_is_empty():
    df = parse_constituents(CSV)
    # Antes de la primera foto no hay universo conocido (no se inventa futuro)
    assert members_on(df, "2010-01-01") == []


def test_members_on_accepts_timestamp():
    df = parse_constituents(CSV)
    assert members_on(df, pd.Timestamp("2018-06-01")) == ["AAPL", "MSFT", "NVDA"]


def test_parse_strips_disambiguation_suffix():
    # "BAC-199809" desambigua un símbolo reutilizado -> símbolo base "BAC"
    csv = 'date,tickers\n2010-01-01,"AAPL,BAC-199809,BAC"\n'
    df = parse_constituents(csv)
    # El sufijo se elimina y el duplicado resultante se colapsa
    assert sorted(df["ticker"]) == ["AAPL", "BAC"]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}

    def get(self, url, timeout=60):
        return _FakeResponse(self._payload)


def test_discover_picks_most_recent_file():
    listing = [
        {"name": "README.md", "download_url": "x"},
        {
            "name": "S&P 500 Historical Components & Changes(08-17-2024).csv",
            "download_url": "url-2024",
        },
        {
            "name": "S&P 500 Historical Components & Changes(01-17-2026).csv",
            "download_url": "url-2026",
        },
    ]
    url = discover_constituents_url(_FakeSession(listing))
    assert url == "url-2026"
