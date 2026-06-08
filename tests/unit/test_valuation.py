"""Tests de la valoración compuesta (paso 1.5).

Incluye los valores de referencia del DCF y del Graham Number, y la comprobación de
que los múltiplos usan la mediana sectorial (requisitos del paso).
"""

import numpy as np
import pandas as pd
import pytest

from src.pipeline import valuation


def _panel(**cols) -> pd.DataFrame:
    """Panel de métricas sintético; cada kwarg es una columna (lista por año)."""
    n = len(next(iter(cols.values())))
    idx = pd.to_datetime([f"{2017 + i}-12-31" for i in range(n)])
    return pd.DataFrame(cols, index=idx)


# --- Graham Number (valor de referencia) ----------------------------------------
def test_graham_number_reference():
    # EPS=3, BVPS=20 -> sqrt(22.5 * 3 * 20) = sqrt(1350) = 36.7423
    panel = _panel(net_income=[30.0], equity=[200.0], shares=[10.0])
    assert valuation.graham_number(panel) == pytest.approx(36.7423, abs=1e-3)


def test_graham_number_negative_eps_is_nan():
    panel = _panel(net_income=[-30.0], equity=[200.0], shares=[10.0])
    assert pd.isna(valuation.graham_number(panel))


# --- CAPM / WACC -----------------------------------------------------------------
def test_cost_of_equity():
    # 0.03 + 1.2*0.055 + 0.01 = 0.106
    assert valuation.cost_of_equity(0.03, 1.2, 0.055, 0.01) == pytest.approx(0.106)


def test_wacc_weighted():
    # E=800, D=200 -> E/V=0.8, D/V=0.2; 0.8*0.10 + 0.2*0.05*(1-0.21) = 0.0879
    assert valuation.wacc(800.0, 200.0, 0.10, 0.05, 0.21) == pytest.approx(0.0879)


def test_wacc_no_debt_returns_cost_of_equity():
    assert valuation.wacc(800.0, 0.0, 0.10, 0.05, 0.21) == pytest.approx(0.10)


# --- DCF (valor de referencia: perpetuidad con g=0) ------------------------------
def test_dcf_enterprise_value_zero_growth_is_perpetuity():
    # g=0, WACC=10% -> EV = FCFF / WACC = 100 / 0.10 = 1000
    ev = valuation.dcf_enterprise_value(100.0, 0.0, 0.0, 0.10, 10)
    assert ev == pytest.approx(1000.0, abs=1e-6)


def test_dcf_enterprise_value_requires_wacc_above_terminal():
    assert pd.isna(valuation.dcf_enterprise_value(100.0, 0.0, 0.05, 0.05, 10))


def test_dcf_value_per_share_reference():
    # FCFF base 100 (EBIT*(1-0) + 0 - 0), EV=1000, deuda neta 200, 10 acciones -> 80
    panel = _panel(
        ebit=[100.0, 100.0, 100.0],
        dep_amort=[0.0, 0.0, 0.0],
        capex=[0.0, 0.0, 0.0],
        net_debt=[200.0, 200.0, 200.0],
        shares=[10.0, 10.0, 10.0],
    )
    value = valuation.dcf_value_per_share(
        panel, wacc_value=0.10, g_initial=0.0, tax=0.0, g_terminal=0.0
    )
    assert value == pytest.approx(80.0, abs=1e-3)


def test_dcf_sensitivity_brackets_base():
    panel = _panel(
        revenue=[800.0, 900.0],
        ebit=[100.0, 110.0],
        dep_amort=[10.0, 10.0],
        capex=[20.0, 20.0],
        net_debt=[200.0, 200.0],
        shares=[10.0, 10.0],
    )
    sens = valuation.dcf_sensitivity(panel, wacc_base=0.10, g_initial=0.05, tax=0.21)
    assert sens["low"] < sens["base"] < sens["high"]


# --- Crecimiento -----------------------------------------------------------------
def test_revenue_cagr_clamped():
    # (110.25/100)^(1/2) - 1 = 0.05, dentro de [0.025, 0.10]
    panel = _panel(revenue=[100.0, 105.0, 110.25])
    assert valuation.revenue_cagr(panel) == pytest.approx(0.05, abs=1e-4)


def test_revenue_cagr_capped():
    # 21% anual -> se acota al tope (0.10)
    panel = _panel(revenue=[100.0, 121.0])
    assert valuation.revenue_cagr(panel) == pytest.approx(0.10)


# --- Beta por regresión ----------------------------------------------------------
def test_beta_regression_recovers_two():
    # La acción replica 2x las rentabilidades del índice -> beta = 2
    dates = pd.date_range("2017-01-01", periods=80, freq="7D")
    r = np.array([0.02, -0.01, 0.015, -0.005] * 20)
    index_close = 100 * np.cumprod(1.0 + r)
    stock_close = 100 * np.cumprod(1.0 + 2.0 * r)
    index_df = pd.DataFrame({"date": dates, "ticker": "^SP500TR", "close": index_close})
    prices_df = pd.DataFrame({"date": dates, "ticker": "XYZ", "close": stock_close})
    b = valuation.beta(prices_df, index_df, "XYZ", dates[-1])
    assert b == pytest.approx(2.0, abs=0.05)


def test_beta_insufficient_history_uses_default():
    dates = pd.date_range("2020-01-01", periods=5, freq="7D")
    index_df = pd.DataFrame(
        {"date": dates, "ticker": "^SP500TR", "close": [100, 101, 102, 103, 104]}
    )
    prices_df = pd.DataFrame({"date": dates, "ticker": "XYZ", "close": [10, 11, 12, 13, 14]})
    assert valuation.beta(prices_df, index_df, "XYZ", dates[-1]) == 1.0


# --- Múltiplos: mediana sectorial ------------------------------------------------
def _peer_fundamentals() -> pd.DataFrame:
    cols = ["ticker", "concept", "start", "end", "val", "form", "filed"]
    rows = []
    # Tres pares con beneficio 100 y 10 acciones; EBIT negativo para aislar el PER
    for tk in ("P1", "P2", "P3"):
        for concept, val in [
            ("NetIncomeLoss", 100.0),
            ("OperatingIncomeLoss", -1.0),
            ("CommonStockSharesOutstanding", 10.0),
        ]:
            rows.append([tk, concept, "2020-01-01", "2020-12-31", val, "10-K", "2021-02-15"])
    df = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    return df


def test_multiples_use_sector_median():
    fundamentals = _peer_fundamentals()
    # Precios -> PER = market_cap/beneficio = price*10/100: 100->10, 200->20, 300->30 (mediana 20)
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2021-05-01"] * 3),
            "ticker": ["P1", "P2", "P3"],
            "close": [100.0, 200.0, 300.0],
        }
    )
    sectors = pd.DataFrame({"ticker": ["P1", "P2", "P3"], "sector": ["Manufacturing"] * 3})
    out = valuation.multiples_value(
        fundamentals, sectors, prices, "P2", ["P1", "P2", "P3"], "2021-06-01"
    )
    assert out["pe"] == pytest.approx(20.0)
    # PER mediana 20 aplicado al beneficio 100 / 10 acciones = 200 por acción
    assert out["multiples_value"] == pytest.approx(200.0)


# --- Integración -----------------------------------------------------------------
def test_weighted_central_renormalizes_over_non_nan():
    # graham NaN -> renormaliza sobre dcf+multiples: (0.6*100 + 0.3*80)/0.9 = 93.33
    values = {"dcf": 100.0, "multiples": 80.0, "graham": np.nan}
    weights = {"dcf": 0.6, "multiples": 0.3, "graham": 0.1}
    assert valuation._weighted_central(values, weights) == pytest.approx(84 / 0.9)


def test_weighted_central_all_nan_is_nan():
    values = {"dcf": np.nan, "multiples": np.nan, "graham": np.nan}
    weights = {"dcf": 0.6, "multiples": 0.3, "graham": 0.1}
    assert pd.isna(valuation._weighted_central(values, weights))


def _healthy_company() -> pd.DataFrame:
    """Fundamentales de una empresa sana (4 años) para probar intrinsic_value."""
    by_year = {
        2016: (1000, 150, 100, 50, 40, 160, 2000, 600, 300, 200, 300, 1000, 100),
        2017: (1080, 165, 110, 52, 42, 175, 2100, 650, 320, 220, 280, 1080, 100),
        2018: (1160, 180, 120, 55, 45, 190, 2200, 700, 330, 240, 260, 1160, 100),
        2019: (1250, 200, 135, 58, 48, 210, 2300, 750, 340, 260, 240, 1250, 100),
    }
    concepts = [
        "Revenues",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
        "DepreciationDepletionAndAmortization",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "NetCashProvidedByUsedInOperatingActivities",
        "Assets",
        "AssetsCurrent",
        "LiabilitiesCurrent",
        "CashAndCashEquivalentsAtCarryingValue",
        "LongTermDebtNoncurrent",
        "StockholdersEquity",
        "CommonStockSharesOutstanding",
    ]
    cols = ["ticker", "concept", "start", "end", "val", "form", "filed"]
    rows = []
    for year, vals in by_year.items():
        for concept, val in zip(concepts, vals, strict=True):
            rows.append(
                ["CO", concept, f"{year}-01-01", f"{year}-12-31", val, "10-K", f"{year + 1}-02-15"]
            )
    df = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    return df


def test_intrinsic_value_range_brackets_central():
    fundamentals = _healthy_company()
    prices = pd.DataFrame(
        {"date": pd.to_datetime(["2020-05-01"]), "ticker": ["CO"], "close": [20.0]}
    )
    index = pd.DataFrame(
        {"date": pd.to_datetime(["2020-05-01"]), "ticker": ["^SP500TR"], "close": [3000.0]}
    )
    rf = pd.DataFrame({"date": pd.to_datetime(["2020-05-01"]), "ticker": ["^IRX"], "close": [2.0]})
    sectors = pd.DataFrame({"ticker": ["CO"], "sector": ["Manufacturing"]})

    out = valuation.intrinsic_value(
        fundamentals, sectors, prices, index, rf, "CO", ["CO"], "2020-06-01"
    )
    assert pd.notna(out["value_central"])
    assert out["value_low"] <= out["value_central"] <= out["value_high"]
    assert pd.notna(out["dcf"]) and pd.notna(out["graham"])
