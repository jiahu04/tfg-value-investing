"""Tests del acceso point-in-time (paso 1.2).

Verifican la regla cardinal anti-look-ahead: en una fecha D solo se ven hechos con
`filed ≤ D`, y ante reexpresiones se toma la última versión conocida hasta D.
"""

import pandas as pd

from src.pipeline.point_in_time import annual_panel, latest_annual

_COLUMNS = ["ticker", "concept", "start", "end", "val", "form", "filed"]


def _fundamentals(rows: list[dict]) -> pd.DataFrame:
    """Construye una tabla de fundamentales sintética con fechas ya convertidas."""
    df = pd.DataFrame(rows, columns=_COLUMNS)
    for col in ("start", "end", "filed"):
        df[col] = pd.to_datetime(df[col])
    return df


def _annual_row(ticker, concept, year, val, filed, start=None):
    """Fila anual (10-K) cómoda para los tests."""
    return {
        "ticker": ticker,
        "concept": concept,
        "start": start or f"{year}-01-01",
        "end": f"{year}-12-31",
        "val": val,
        "form": "10-K",
        "filed": filed,
    }


def test_anti_look_ahead_hides_future_filings():
    df = _fundamentals([_annual_row("AAPL", "NetIncomeLoss", 2020, 1000, "2021-02-15")])
    # Antes de la publicación: no se ve nada
    assert annual_panel(df, "AAPL", "2021-01-01").empty
    # Después de la publicación: aparece
    panel = annual_panel(df, "AAPL", "2021-03-01")
    assert panel.loc[pd.Timestamp("2020-12-31"), "NetIncomeLoss"] == 1000


def test_restatement_takes_latest_known_version():
    df = _fundamentals(
        [
            _annual_row("AAPL", "NetIncomeLoss", 2020, 1000, "2021-02-15"),
            # Reexpresión del MISMO año fiscal, publicada un año después
            {
                "ticker": "AAPL",
                "concept": "NetIncomeLoss",
                "start": "2020-01-01",
                "end": "2020-12-31",
                "val": 1050,
                "form": "10-K",
                "filed": "2022-02-15",
            },
        ]
    )
    # En 2021 solo se conoce la versión original
    p2021 = annual_panel(df, "AAPL", "2021-06-01")
    assert p2021.loc[pd.Timestamp("2020-12-31"), "NetIncomeLoss"] == 1000
    # En 2022 ya se conoce la reexpresión
    p2022 = annual_panel(df, "AAPL", "2022-06-01")
    assert p2022.loc[pd.Timestamp("2020-12-31"), "NetIncomeLoss"] == 1050


def test_latest_annual_returns_most_recent_year():
    df = _fundamentals(
        [
            _annual_row("AAPL", "NetIncomeLoss", 2019, 900, "2020-02-15"),
            _annual_row("AAPL", "NetIncomeLoss", 2020, 1000, "2021-02-15"),
        ]
    )
    panel = annual_panel(df, "AAPL", "2021-06-01")
    assert list(panel.index) == [pd.Timestamp("2019-12-31"), pd.Timestamp("2020-12-31")]
    last = latest_annual(df, "AAPL", "2021-06-01")
    assert last["NetIncomeLoss"] == 1000


def test_tiebreak_prefers_longer_period():
    # Mismo concepto y fin de periodo, misma fecha de publicación: anual (12m) vs trimestre (3m)
    df = _fundamentals(
        [
            _annual_row("AAPL", "Revenues", 2020, 4000, "2021-02-15", start="2020-01-01"),
            {
                "ticker": "AAPL",
                "concept": "Revenues",
                "start": "2020-10-01",  # solo Q4
                "end": "2020-12-31",
                "val": 1100,
                "form": "10-K",
                "filed": "2021-02-15",
            },
        ]
    )
    panel = annual_panel(df, "AAPL", "2021-06-01")
    # Se queda con el periodo más largo (el anual)
    assert panel.loc[pd.Timestamp("2020-12-31"), "Revenues"] == 4000


def test_non_annual_forms_excluded():
    df = _fundamentals(
        [
            _annual_row("AAPL", "NetIncomeLoss", 2020, 1000, "2021-02-15"),
            {
                "ticker": "AAPL",
                "concept": "NetIncomeLoss",
                "start": "2020-01-01",
                "end": "2020-03-31",
                "val": 250,
                "form": "10-Q",  # trimestral: debe ignorarse
                "filed": "2020-04-30",
            },
        ]
    )
    panel = annual_panel(df, "AAPL", "2021-06-01")
    # Solo el dato anual; el 10-Q no entra
    assert len(panel) == 1
    assert panel.iloc[0]["NetIncomeLoss"] == 1000


def test_anchors_to_fiscal_year_ends():
    # Un 10-K trae también un trimestre y un instante con fecha de portada: ambos fuera.
    df = _fundamentals(
        [
            # Duración anual: define el cierre de año fiscal 2020-12-31
            _annual_row("AAPL", "Revenues", 2020, 4000, "2021-02-15", start="2020-01-01"),
            # Trimestre dentro del 10-K (periodo ~3 meses): excluido
            {
                "ticker": "AAPL",
                "concept": "Revenues",
                "start": "2020-07-01",
                "end": "2020-09-30",
                "val": 1000,
                "form": "10-K",
                "filed": "2021-02-15",
            },
            # Instante de balance en el cierre de año fiscal: se conserva
            {
                "ticker": "AAPL",
                "concept": "Assets",
                "start": None,
                "end": "2020-12-31",
                "val": 9000,
                "form": "10-K",
                "filed": "2021-02-15",
            },
            # Instante de acciones a fecha de portada (no es cierre fiscal): excluido
            {
                "ticker": "AAPL",
                "concept": "CommonStockSharesOutstanding",
                "start": None,
                "end": "2021-02-10",
                "val": 555,
                "form": "10-K",
                "filed": "2021-02-15",
            },
        ]
    )
    panel = annual_panel(df, "AAPL", "2021-06-01")
    assert list(panel.index) == [pd.Timestamp("2020-12-31")]
    assert panel.loc[pd.Timestamp("2020-12-31"), "Revenues"] == 4000
    assert panel.loc[pd.Timestamp("2020-12-31"), "Assets"] == 9000
    # El instante de portada no entra (su fecha no es un cierre de año fiscal)
    assert "CommonStockSharesOutstanding" not in panel.columns


def test_unknown_ticker_returns_empty():
    df = _fundamentals([_annual_row("AAPL", "NetIncomeLoss", 2020, 1000, "2021-02-15")])
    assert annual_panel(df, "MSFT", "2022-01-01").empty
    assert latest_annual(df, "MSFT", "2022-01-01").empty
