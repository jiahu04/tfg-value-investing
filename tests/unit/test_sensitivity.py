"""Tests del análisis de sensibilidad (paso 2.2)."""

import pandas as pd

from src.backtest.sensitivity import run_sensitivity
from src.utils.config_loader import get_config


def test_sensitivity_applies_override_per_variant():
    spec = [{"param": "portfolio.min_margin_of_safety", "values": [0.20, 0.40]}]
    rf = pd.DataFrame(columns=["date", "ticker", "close"])

    def runner() -> pd.DataFrame:
        # La curva final depende del override activo -> prueba que se aplicó por variante
        margin = get_config("portfolio.min_margin_of_safety")
        dates = pd.date_range("2018-01-01", periods=3, freq="365D")
        return pd.DataFrame(
            {
                "date": dates,
                "portfolio_value": [100.0, 100.0, 100.0 * (1.0 + margin)],
                "index_value": [100.0, 100.0, 100.0],
            }
        )

    out = run_sensitivity(spec, backtest_runner=runner, rf_df=rf)
    assert list(out["valor"]) == [0.20, 0.40]
    assert list(out["parámetro"]) == ["portfolio.min_margin_of_safety"] * 2
    # El CAGR difiere entre variantes porque el runner usó el override
    assert out["CAGR cartera"].iloc[0] != out["CAGR cartera"].iloc[1]
