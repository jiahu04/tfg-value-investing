"""Integración del orquestador de aportación (paso 2.3): sin red, con mocks controlados."""

import pandas as pd
import pytest

from src.contributions import run
from src.contributions.strategies import compare_strategies
from src.reporting.latex import save_latex, to_latex_table

_CFG = {
    "periodic_amount": 1000.0,
    "conditional_dca": {"base_margin": 0.30, "suspend_below_margin": 0.05, "max_scale_factor": 2.0},
    "concentrated": {"min_margin": 0.45, "multiplier": 3.0},
}


def _fake_selection(asof: pd.Timestamp) -> pd.DataFrame:
    """Selección sintética: dos empresas seleccionadas con margen conocido (media 0.40)."""
    return pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "margin_of_safety": [0.30, 0.50],
            "selected": [True, True],
            "passed": [True, True],
        }
    )


def test_build_nav_base_100():
    curve = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-06-01", "2021-01-01"]),
            "portfolio_value": [100000.0, 110000.0, 120000.0],
        }
    )
    nav = run.build_nav(curve)
    assert nav.iloc[0] == 100.0
    assert nav.iloc[-1] == 120.0


def test_contribution_dates_monthly():
    index = pd.bdate_range("2020-01-01", "2020-12-31")
    dates = run.contribution_dates(index, "monthly")
    assert len(dates) == 12  # un día por mes
    assert dates[0] == index[0]


def test_margin_signal_forward_filled():
    index = pd.bdate_range("2020-01-01", "2021-12-31")
    signal = run.margin_signal(_fake_selection, index, review_month=6)
    assert signal.index.equals(index)
    # La media de la selección sintética es 0.40 y se propaga desde la primera revisión.
    assert signal.iloc[0] == pytest.approx(0.40)
    assert signal.notna().all()


def test_end_to_end_table_and_latex(tmp_path):
    index = pd.bdate_range("2020-01-01", "2021-12-31")
    nav = pd.Series(
        [100.0 * (1.0 + 0.0002 * i) for i in range(len(index))], index=index
    )  # NAV suavemente creciente
    signal = run.margin_signal(_fake_selection, index, review_month=6)
    dates = run.contribution_dates(index, "monthly")

    table = compare_strategies(nav, signal, dates, cfg=_CFG)
    assert list(table.index) == ["DCA fijo", "DCA condicional", "Concentrada"]
    # El DCA fijo aporta todos los meses; la concentrada no dispara (margen 0.40 < 0.45).
    assert table.loc["DCA fijo", "n_aportaciones"] == len(dates)
    assert table.loc["Concentrada", "n_aportaciones"] == 0

    out = save_latex(
        to_latex_table(table, caption="Aportación", label="tab:c", index_header="Estrategia"),
        tmp_path / "contributions.tex",
    )
    text = out.read_text(encoding="utf-8")
    assert "tabularx" in text
    assert "DCA fijo" in text
