"""Tests de los filtros de descarte (paso 1.3).

Empresas/paneles sintéticos diseñados para pasar o caer en cada filtro, con los
umbrales por defecto de config.filters (deuda 4x/cobertura 2x/sostenido 3; dilución
3 %/sostenido 3; rentabilidad máx 2 años de pérdidas o FCF<0 en ventana de 5; calidad
CFO/beneficio 0,5 sostenido 3).
"""

import numpy as np
import pandas as pd

from src.pipeline.filters import (
    FilterOutcome,
    _sustained_breach,
    apply_filters,
    check_accounting_quality,
    check_debt,
    check_dilution,
    check_profitability,
    check_sector,
    filter_universe,
)


def _metrics(**cols) -> pd.DataFrame:
    """Construye un panel de métricas sintético; cada kwarg es una columna (lista)."""
    n = len(next(iter(cols.values())))
    idx = pd.to_datetime([f"{2013 + i}-12-31" for i in range(n)])
    return pd.DataFrame(cols, index=idx)


# --- _sustained_breach ----------------------------------------------------------
def test_sustained_breach_last_n_all_breach():
    s = pd.Series([5.0, 5.0, 5.0])
    assert _sustained_breach(s, lambda x: x > 4, 3) is True


def test_sustained_breach_recovered_last_year():
    s = pd.Series([5.0, 5.0, 3.0])  # el último año ya no incumple
    assert _sustained_breach(s, lambda x: x > 4, 3) is False


def test_sustained_breach_nan_breaks_run():
    s = pd.Series([5.0, 5.0, np.nan])
    assert _sustained_breach(s, lambda x: x > 4, 3) is False


def test_sustained_breach_insufficient_history():
    s = pd.Series([5.0, 5.0])  # menos de 3 años
    assert _sustained_breach(s, lambda x: x > 4, 3) is False


# --- check_sector ----------------------------------------------------------------
def test_sector_excluded():
    assert check_sector("Banking") == ["sector_excluido"]


def test_sector_allowed():
    assert check_sector("Manufacturing") == []
    assert check_sector(None) == []


# --- check_debt ------------------------------------------------------------------
def test_debt_leverage_sustained_fails():
    m = _metrics(
        net_debt_to_ebitda=[5.0, 5.0, 5.0],
        interest_coverage=[10.0, 10.0, 10.0],
    )
    assert check_debt(m) == ["deuda_ebitda"]


def test_debt_coverage_sustained_fails():
    m = _metrics(
        net_debt_to_ebitda=[1.0, 1.0, 1.0],
        interest_coverage=[1.0, 1.0, 1.0],
    )
    assert check_debt(m) == ["cobertura_intereses"]


def test_debt_recovered_passes():
    m = _metrics(
        net_debt_to_ebitda=[5.0, 5.0, 2.0],  # se desapalanca el último año
        interest_coverage=[10.0, 10.0, 10.0],
    )
    assert check_debt(m) == []


# --- check_dilution --------------------------------------------------------------
def test_dilution_sustained_fails():
    m = _metrics(share_growth=[0.05, 0.05, 0.05])  # 5 % > 3 %
    assert check_dilution(m) == ["dilucion"]


def test_dilution_below_threshold_passes():
    m = _metrics(share_growth=[0.05, 0.05, 0.0])
    assert check_dilution(m) == []


# --- check_profitability ---------------------------------------------------------
def test_profitability_too_many_loss_years():
    # 3 años de pérdidas en la ventana (máx 2)
    m = _metrics(net_income=[-1.0, -1.0, -1.0, 5.0, 5.0], fcf=[10.0] * 5)
    assert "perdidas_recurrentes" in check_profitability(m)


def test_profitability_too_many_negative_fcf():
    m = _metrics(net_income=[5.0] * 5, fcf=[-1.0, -1.0, -1.0, 10.0, 10.0])
    assert "fcf_negativo_recurrente" in check_profitability(m)


def test_profitability_clean_passes():
    m = _metrics(net_income=[5.0] * 5, fcf=[10.0] * 5)
    assert check_profitability(m) == []


# --- check_accounting_quality ----------------------------------------------------
def test_quality_low_cash_conversion_fails():
    m = _metrics(
        cfo_to_net_income=[0.3, 0.3, 0.3],
        net_income=[100.0, 100.0, 100.0],
    )
    assert check_accounting_quality(m) == ["calidad_contable"]


def test_quality_loss_year_breaks_run():
    # Un año de pérdidas enmascara el ratio -> NaN en la ventana -> no descarta
    m = _metrics(
        cfo_to_net_income=[0.3, 0.3, 0.3],
        net_income=[100.0, -5.0, 100.0],
    )
    assert check_accounting_quality(m) == []


# --- apply_filters ---------------------------------------------------------------
def _clean_metrics() -> pd.DataFrame:
    return _metrics(
        net_debt_to_ebitda=[1.0, 1.0, 1.0],
        interest_coverage=[10.0, 10.0, 10.0],
        share_growth=[0.0, 0.0, 0.0],
        net_income=[100.0, 100.0, 100.0],
        fcf=[50.0, 50.0, 50.0],
        cfo_to_net_income=[1.2, 1.2, 1.2],
    )


def test_apply_filters_clean_company_passes():
    out = apply_filters(_clean_metrics(), "Manufacturing")
    assert out.passed is True
    assert out.reasons == []


def test_apply_filters_collects_all_reasons():
    m = _metrics(
        net_debt_to_ebitda=[5.0, 5.0, 5.0],  # deuda
        interest_coverage=[10.0, 10.0, 10.0],
        share_growth=[0.05, 0.05, 0.05],  # dilución
        net_income=[100.0, 100.0, 100.0],
        fcf=[50.0, 50.0, 50.0],
        cfo_to_net_income=[1.2, 1.2, 1.2],
    )
    out = apply_filters(m, "Banking")  # + sector
    assert out.passed is False
    assert set(out.reasons) == {"sector_excluido", "deuda_ebitda", "dilucion"}


def test_apply_filters_empty_is_sin_datos():
    out = apply_filters(pd.DataFrame(), "Manufacturing")
    assert out == FilterOutcome(passed=False, reasons=["sin_datos"])


# --- filter_universe (integración con fundamentales crudos) ----------------------
def _fundamentals(tickers: list[str]) -> pd.DataFrame:
    cols = ["ticker", "concept", "start", "end", "val", "form", "filed"]
    rows = []
    for tk in tickers:
        for year in (2015, 2016, 2017):
            rows.append(
                [
                    tk,
                    "NetIncomeLoss",
                    f"{year}-01-01",
                    f"{year}-12-31",
                    100,
                    "10-K",
                    f"{year + 1}-02-15",
                ]
            )
            rows.append(
                [
                    tk,
                    "NetCashProvidedByUsedInOperatingActivities",
                    f"{year}-01-01",
                    f"{year}-12-31",
                    120,
                    "10-K",
                    f"{year + 1}-02-15",
                ]
            )
    df = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    return df


def test_filter_universe_traces_survivors_and_discards():
    fundamentals = _fundamentals(["GOOD", "BANKX"])
    sectors = pd.DataFrame({"ticker": ["GOOD", "BANKX"], "sector": ["Manufacturing", "Banking"]})
    out = filter_universe(fundamentals, sectors, ["GOOD", "BANKX"], "2018-06-01")

    good = out[out["ticker"] == "GOOD"].iloc[0]
    bank = out[out["ticker"] == "BANKX"].iloc[0]
    assert good["passed"]
    assert good["reasons"] == ""
    assert not bank["passed"]
    assert bank["reasons"] == "sector_excluido"


def test_filter_universe_unknown_ticker_sin_datos():
    fundamentals = _fundamentals(["GOOD"])
    sectors = pd.DataFrame({"ticker": ["GOOD"], "sector": ["Manufacturing"]})
    out = filter_universe(fundamentals, sectors, ["MISSING"], "2018-06-01")
    assert not out.iloc[0]["passed"]
    assert out.iloc[0]["reasons"] == "sin_datos"
