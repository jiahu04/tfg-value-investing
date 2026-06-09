"""
sensitivity.py — Análisis de sensibilidad del backtest (paso 2.2).

Para cada umbral configurado en `backtest.sensitivity`, re-ejecuta el backtest variando
ese valor (vía `config_override`) y tabula las métricas titulares. Así se mide cómo de
robusto es el resultado ante distintas calibraciones (memoria 8.2).

El ejecutor del backtest es **inyectable** (`backtest_runner`), lo que permite probar la
orquestación con un doble que devuelve curvas controladas, sin correr el backtest real.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from src.backtest.metrics import compute_metrics
from src.utils.config_loader import config_override, get_config


def run_sensitivity(
    spec: list[dict],
    *,
    backtest_runner: Callable[[], pd.DataFrame],
    rf_df: pd.DataFrame,
) -> pd.DataFrame:
    """Ejecuta el barrido de sensibilidad y devuelve la tabla de métricas por variante.

    Args:
        spec: lista de barridos `{param: "ruta.config", values: [...]}`.
        backtest_runner: función sin argumentos que ejecuta el backtest (con la config
            vigente) y devuelve la `equity_curve`. Se llama con el override activo.
        rf_df: serie del tipo libre para las métricas.

    Returns:
        DataFrame con una fila por (parámetro, valor) y las métricas titulares.
    """
    trading_days = get_config("backtest.trading_days_per_year", 252)
    rows: list[dict] = []
    for entry in spec:
        param = entry["param"]
        for value in entry["values"]:
            with config_override({param: value}):
                curve = backtest_runner()
            metrics = compute_metrics(curve, rf_df, trading_days=trading_days)
            rows.append(
                {
                    "parámetro": param,
                    "valor": value,
                    "CAGR cartera": metrics["cagr_portfolio"],
                    "Alpha (Jensen)": metrics["alpha"],
                    "Beta": metrics["beta"],
                    "Ratio de Sharpe": metrics["sharpe"],
                    "Máximo drawdown": metrics["max_drawdown"],
                    "Tracking error": metrics["tracking_error"],
                }
            )
    return pd.DataFrame(rows)
