"""
metrics.py — Métricas de rentabilidad y riesgo del backtest (paso 2.2).

A partir de la serie de valor de la cartera y del índice (`equity_curve` del paso 2.1),
calcula las métricas de la memoria (8.2): CAGR, alpha de Jensen (con beta), ratio de
Sharpe, máximo drawdown y tracking error; y la tabla por periodos (Total, Calibración,
Validación). Funciones puras y testeables con series de valor conocido.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils.config_loader import get_config

# Etiquetas (y orden) de las métricas en la tabla de resultados
_METRIC_LABELS = {
    "cagr_portfolio": "CAGR cartera",
    "cagr_index": "CAGR índice",
    "alpha": "Alpha (Jensen)",
    "beta": "Beta",
    "sharpe": "Ratio de Sharpe",
    "max_drawdown": "Máximo drawdown",
    "tracking_error": "Tracking error",
}


def _returns(values: pd.Series) -> pd.Series:
    """Rentabilidades periódicas (variación porcentual)."""
    return pd.Series(values).reset_index(drop=True).pct_change(fill_method=None)


def cagr(values, dates) -> float:
    """Tasa de crecimiento anual compuesta entre el primer y el último valor."""
    v = pd.Series(values).reset_index(drop=True)
    d = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    if len(v) < 2 or pd.isna(v.iloc[0]) or v.iloc[0] <= 0 or pd.isna(v.iloc[-1]):
        return float("nan")
    years = (d.iloc[-1] - d.iloc[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float((v.iloc[-1] / v.iloc[0]) ** (1.0 / years) - 1.0)


def max_drawdown(values) -> float:
    """Máxima caída desde un máximo previo (valor negativo)."""
    v = pd.Series(values).dropna()
    if v.empty:
        return float("nan")
    return float((v / v.cummax() - 1.0).min())


def sharpe_ratio(values, rf_aligned, trading_days) -> float:
    """Ratio de Sharpe anualizado (exceso sobre el tipo libre / volatilidad)."""
    ret = _returns(values)
    rf_daily = pd.Series(rf_aligned).reset_index(drop=True) / trading_days
    excess = (ret - rf_daily).dropna()
    std = excess.std(ddof=1)
    if excess.empty or pd.isna(std) or std == 0:
        return float("nan")
    return float(excess.mean() / std * np.sqrt(trading_days))


def tracking_error(portfolio_values, index_values, trading_days) -> float:
    """Tracking error anualizado (desviación de la rentabilidad relativa al índice)."""
    diff = (_returns(portfolio_values) - _returns(index_values)).dropna()
    if diff.empty:
        return float("nan")
    return float(diff.std(ddof=1) * np.sqrt(trading_days))


def jensen_alpha_beta(
    portfolio_values, index_values, rf_aligned, trading_days
) -> tuple[float, float]:
    """Alpha de Jensen (anualizado) y beta vía regresión de excesos sobre el índice.

    Regresión: exceso_cartera = alpha + beta · exceso_índice. Devuelve (alpha, beta).
    """
    rf_daily = pd.Series(rf_aligned).reset_index(drop=True) / trading_days
    ex_p = _returns(portfolio_values) - rf_daily
    ex_i = _returns(index_values) - rf_daily
    data = pd.concat([ex_p, ex_i], axis=1, keys=["p", "i"]).dropna()
    if len(data) < 2:
        return float("nan"), float("nan")
    var_i = data["i"].var(ddof=1)
    if pd.isna(var_i) or var_i == 0:
        return float("nan"), float("nan")
    beta = data["p"].cov(data["i"]) / var_i
    alpha_period = data["p"].mean() - beta * data["i"].mean()
    return float(alpha_period * trading_days), float(beta)


def _align_rf(rf_df: pd.DataFrame, dates: pd.Series) -> pd.Series:
    """Tipo libre de riesgo anual (^IRX/100) alineado posicionalmente a las fechas dadas."""
    target = pd.DatetimeIndex(pd.to_datetime(dates))
    if rf_df is None or rf_df.empty:
        return pd.Series([0.0] * len(target))
    series = rf_df.set_index("date")["close"].sort_index()
    aligned = series.reindex(series.index.union(target)).ffill().reindex(target)
    return (aligned / 100.0).reset_index(drop=True)


def compute_metrics(curve: pd.DataFrame, rf_df: pd.DataFrame, *, trading_days: int = 252) -> dict:
    """Calcula todas las métricas de un tramo de la curva de capital."""
    keys = [
        "cagr_portfolio",
        "cagr_index",
        "alpha",
        "beta",
        "sharpe",
        "max_drawdown",
        "tracking_error",
    ]
    if curve is None or len(curve) < 2:
        return dict.fromkeys(keys, float("nan"))

    curve = curve.sort_values("date").reset_index(drop=True)
    dates, pv, iv = curve["date"], curve["portfolio_value"], curve["index_value"]
    rf_aligned = _align_rf(rf_df, dates)
    alpha, beta = jensen_alpha_beta(pv, iv, rf_aligned, trading_days)
    return {
        "cagr_portfolio": cagr(pv, dates),
        "cagr_index": cagr(iv, dates),
        "alpha": alpha,
        "beta": beta,
        "sharpe": sharpe_ratio(pv, rf_aligned, trading_days),
        "max_drawdown": max_drawdown(pv),
        "tracking_error": tracking_error(pv, iv, trading_days),
    }


def metrics_table(curve: pd.DataFrame, rf_df: pd.DataFrame) -> pd.DataFrame:
    """Tabla de métricas por periodo: Total, Calibración (≤fecha) y Validación (≥fecha)."""
    trading_days = get_config("backtest.trading_days_per_year", 252)
    cal_end = pd.Timestamp(get_config("backtest.calibration_end", "2018-12-31"))
    val_start = pd.Timestamp(get_config("backtest.validation_start", "2019-01-01"))

    if curve is None or curve.empty:
        return pd.DataFrame()

    periods = {
        "Total": curve,
        "Calibración": curve[curve["date"] <= cal_end],
        "Validación": curve[curve["date"] >= val_start],
    }
    columns = {
        period: compute_metrics(sub, rf_df, trading_days=trading_days)
        for period, sub in periods.items()
    }
    table = pd.DataFrame(
        {
            period: {_METRIC_LABELS[k]: values[k] for k in _METRIC_LABELS}
            for period, values in columns.items()
        }
    )
    return table.reindex(list(_METRIC_LABELS.values()))
