"""Tests de la puntuación de calidad (paso 1.4).

Incluye la **reproducción a mano del F-Score** sobre un caso conocido (requisito del
paso), los extremos 0/9, los dos complementos y la compuesta/ranking.
"""

import pandas as pd
import pytest

from src.pipeline.quality import (
    capex_intensity_component,
    margin_trend_component,
    piotroski_fscore,
    quality_score,
    score_universe,
)


def _panel(**cols) -> pd.DataFrame:
    """Panel de métricas sintético; cada kwarg es una columna (lista por año)."""
    n = len(next(iter(cols.values())))
    idx = pd.to_datetime([f"{2018 + i}-12-31" for i in range(n)])
    return pd.DataFrame(cols, index=idx)


# --- F-Score: reproducción a mano de un caso conocido ---------------------------
def test_fscore_reproduces_known_case():
    # Dos años (t-1=2018, t=2019). Cálculo manual de cada criterio abajo.
    panel = _panel(
        roa=[0.05, 0.06],  # >0 (1) y mejora (3)
        cfo=[100.0, 80.0],  # >0 (2); accruals: 80 > net_income 90? NO (4)
        net_income=[70.0, 90.0],
        total_debt=[300.0, 350.0],  # leverage 0.30 -> 0.35 sube: NO (5)
        total_assets=[1000.0, 1000.0],
        current_ratio=[1.0, 1.2],  # sube (6)
        shares=[500.0, 500.0],  # sin dilución, 500<=500 (7)
        gross_margin=[0.30, 0.30],  # 0.30>0.30 NO (8)
        revenue=[700.0, 750.0],  # rotación 0.70 -> 0.75 sube (9)
    )
    score, detail = piotroski_fscore(panel)
    assert detail == {
        "roa_positive": True,
        "cfo_positive": True,
        "roa_improved": True,
        "accruals": False,
        "leverage_down": False,
        "current_ratio_up": True,
        "no_dilution": True,
        "gross_margin_up": False,
        "asset_turnover_up": True,
    }
    assert score == 6


def test_fscore_all_nine():
    panel = _panel(
        roa=[0.05, 0.08],
        cfo=[100.0, 120.0],
        net_income=[70.0, 90.0],  # 120 > 90 accruals ok
        total_debt=[500.0, 400.0],  # leverage 0.5 -> 0.4 baja
        total_assets=[1000.0, 1000.0],
        current_ratio=[1.2, 1.5],
        shares=[1000.0, 1000.0],
        gross_margin=[0.40, 0.45],
        revenue=[800.0, 900.0],  # rotación 0.8 -> 0.9
    )
    score, _ = piotroski_fscore(panel)
    assert score == 9


def test_fscore_none():
    panel = _panel(
        roa=[0.08, -0.01],
        cfo=[120.0, -5.0],
        net_income=[70.0, 50.0],  # -5 > 50 NO
        total_debt=[400.0, 600.0],  # sube
        total_assets=[1000.0, 1000.0],
        current_ratio=[1.5, 1.2],  # baja
        shares=[1000.0, 1100.0],  # dilución
        gross_margin=[0.45, 0.40],  # baja
        revenue=[900.0, 800.0],  # rotación baja
    )
    score, _ = piotroski_fscore(panel)
    assert score == 0


def test_fscore_empty_panel():
    score, detail = piotroski_fscore(pd.DataFrame())
    assert score == 0
    assert all(v is False for v in detail.values())


# --- Complementos ----------------------------------------------------------------
def test_capex_intensity_component():
    panel = _panel(capex=[40.0, 40.0], cfo=[100.0, 100.0])
    assert capex_intensity_component(panel) == pytest.approx(0.6)  # 1 - 0.4


def test_capex_intensity_negative_cfo_is_zero():
    panel = _panel(capex=[40.0, 40.0], cfo=[-10.0, -10.0])
    assert capex_intensity_component(panel) == 0.0


def test_capex_intensity_clamped_when_capex_exceeds_cfo():
    panel = _panel(capex=[200.0, 200.0], cfo=[100.0, 100.0])
    assert capex_intensity_component(panel) == 0.0  # ratio clamp a 1 -> componente 0


def test_margin_trend_increasing():
    panel = _panel(operating_margin=[0.10, 0.12, 0.14])
    assert margin_trend_component(panel) == pytest.approx(1.0)


def test_margin_trend_decreasing():
    panel = _panel(operating_margin=[0.14, 0.12, 0.10])
    assert margin_trend_component(panel) == pytest.approx(0.0)


def test_margin_trend_mixed():
    panel = _panel(operating_margin=[0.10, 0.12, 0.11])  # sube, baja -> 1/2
    assert margin_trend_component(panel) == pytest.approx(0.5)


def test_margin_trend_insufficient_history_is_neutral():
    panel = _panel(operating_margin=[0.10])
    assert margin_trend_component(panel) == 0.5


# --- Compuesta -------------------------------------------------------------------
def test_quality_score_weighted_composite():
    panel = _panel(
        roa=[0.05, 0.08],
        cfo=[100.0, 120.0],
        net_income=[70.0, 90.0],
        total_debt=[500.0, 400.0],
        total_assets=[1000.0, 1000.0],
        current_ratio=[1.2, 1.5],
        shares=[1000.0, 1000.0],
        gross_margin=[0.40, 0.45],
        revenue=[800.0, 900.0],
        operating_margin=[0.10, 0.14],  # creciente -> 1.0
        capex=[40.0, 40.0],  # capex/cfo medio = 80/220 -> componente alto
    )
    out = quality_score(panel)
    # fscore 9 (mismos números que test_fscore_all_nine)
    assert out["fscore"] == 9
    expected = 0.6 * (9 / 9.0) + 0.2 * out["capex_component"] + 0.2 * out["margin_trend_component"]
    assert out["quality_score"] == pytest.approx(expected)


def test_quality_score_empty_is_nan():
    out = quality_score(pd.DataFrame())
    assert pd.isna(out["quality_score"])


# --- score_universe (integración con fundamentales crudos) -----------------------
def _fundamentals(specs: list[tuple]) -> pd.DataFrame:
    """specs: lista de (ticker, año, {concepto: valor})."""
    cols = ["ticker", "concept", "start", "end", "val", "form", "filed"]
    rows = []
    for ticker, year, vals in specs:
        for concept, val in vals.items():
            rows.append(
                [
                    ticker,
                    concept,
                    f"{year}-01-01",
                    f"{year}-12-31",
                    val,
                    "10-K",
                    f"{year + 1}-02-15",
                ]
            )
    df = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    return df


def _year_vals(net_income, cfo, revenue, oper, gross, ac, lc, debt, shares, capex, assets=1000.0):
    return {
        "NetIncomeLoss": net_income,
        "NetCashProvidedByUsedInOperatingActivities": cfo,
        "Revenues": revenue,
        "OperatingIncomeLoss": oper,
        "GrossProfit": gross,
        "AssetsCurrent": ac,
        "LiabilitiesCurrent": lc,
        "LongTermDebtNoncurrent": debt,
        "CommonStockSharesOutstanding": shares,
        "PaymentsToAcquirePropertyPlantAndEquipment": capex,
        "Assets": assets,
    }


def test_score_universe_orders_and_handles_missing():
    # GOOD mejora año a año, poco capex; POOR empeora, mucho capex y dilución
    specs = [
        ("GOOD", 2019, _year_vals(50, 60, 700, 80, 300, 200, 200, 400, 100, 20)),
        ("GOOD", 2020, _year_vals(80, 100, 800, 120, 360, 300, 200, 300, 100, 20)),
        ("POOR", 2019, _year_vals(80, 100, 800, 120, 360, 300, 200, 300, 100, 200)),
        ("POOR", 2020, _year_vals(-10, 5, 700, -5, 280, 200, 250, 500, 120, 200)),
    ]
    fundamentals = _fundamentals(specs)
    out = score_universe(fundamentals, ["POOR", "GOOD", "MISSING"], "2021-06-01")

    assert list(out.columns) == [
        "ticker",
        "fscore",
        "capex_component",
        "margin_trend_component",
        "quality_score",
    ]
    # GOOD por delante de POOR; MISSING (sin datos) al final con NaN
    assert out.iloc[0]["ticker"] == "GOOD"
    assert out.iloc[1]["ticker"] == "POOR"
    assert out.iloc[2]["ticker"] == "MISSING"
    assert pd.isna(out.iloc[2]["quality_score"])
    assert out.iloc[0]["quality_score"] > out.iloc[1]["quality_score"]
