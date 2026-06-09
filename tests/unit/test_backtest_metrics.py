"""Tests de las métricas del backtest (paso 2.2), con valores de referencia conocidos."""

import numpy as np
import pandas as pd
import pytest

from src.backtest import metrics


def _values_from_returns(returns) -> np.ndarray:
    """Serie de valor que arranca en 100 y aplica las rentabilidades dadas."""
    return 100.0 * np.concatenate([[1.0], np.cumprod(1.0 + np.asarray(returns))])


# --- CAGR ------------------------------------------------------------------------
def test_cagr_doubling_in_two_years():
    dates = [pd.Timestamp("2018-01-01"), pd.Timestamp("2020-01-01")]  # ~730 días
    assert metrics.cagr([100.0, 200.0], dates) == pytest.approx(0.4142, abs=5e-3)


# --- Máximo drawdown -------------------------------------------------------------
def test_max_drawdown():
    # 120 -> 90 es una caída del 25 %
    assert metrics.max_drawdown([100, 120, 90, 150]) == pytest.approx(-0.25)


# --- Tracking error --------------------------------------------------------------
def test_tracking_error_zero_when_portfolio_equals_index():
    values = _values_from_returns([0.01, -0.02, 0.015, 0.0, 0.03])
    assert metrics.tracking_error(values, values, 252) == pytest.approx(0.0)


# --- Sharpe ----------------------------------------------------------------------
def test_sharpe_matches_manual():
    returns = np.array([0.02, 0.0] * 10)
    values = _values_from_returns(returns)
    rf_aligned = [0.0] * len(values)
    expected = returns.mean() / returns.std(ddof=1) * np.sqrt(252)
    assert metrics.sharpe_ratio(values, rf_aligned, 252) == pytest.approx(expected)


# --- Alpha de Jensen y beta ------------------------------------------------------
def test_jensen_alpha_beta_recovers_parameters():
    ri = np.array([0.01, -0.02, 0.015, -0.01] * 5)
    rp = 2.0 * ri + 0.001  # exceso_cartera = 2 * exceso_índice + 0,001
    index_values = _values_from_returns(ri)
    portfolio_values = _values_from_returns(rp)
    rf_aligned = [0.0] * len(index_values)
    alpha, beta = metrics.jensen_alpha_beta(portfolio_values, index_values, rf_aligned, 252)
    assert beta == pytest.approx(2.0)
    assert alpha == pytest.approx(0.001 * 252)


# --- Tabla por periodos ----------------------------------------------------------
def test_metrics_table_structure():
    dates = pd.date_range("2017-01-01", "2021-01-01", freq="ME")
    curve = pd.DataFrame(
        {
            "date": dates,
            "portfolio_value": np.linspace(100, 160, len(dates)),
            "index_value": np.linspace(100, 150, len(dates)),
        }
    )
    table = metrics.metrics_table(curve, pd.DataFrame(columns=["date", "ticker", "close"]))
    assert list(table.columns) == ["Total", "Calibración", "Validación"]
    assert "CAGR cartera" in table.index
    assert "Alpha (Jensen)" in table.index
