"""
quality.py — Puntuación de calidad (Etapa 3, paso 1.4).

Ordena por calidad las empresas que pasan los filtros (1.3). Sobre el panel anual de
métricas del paso 1.2 (point-in-time), calcula una **puntuación compuesta** en [0,1] y
un **ranking**. La compuesta combina, con los pesos de `config.quality`:
  - F-Score de Piotroski adaptado (9 criterios binarios) — peso `fscore_weight`.
  - Intensidad de capital (asset-light, capex/CFO) — peso `capex_intensity_weight`.
  - Tendencia del margen operativo — peso `margin_trend_weight`.

Funciones puras y testeables; sin red. El F-Score compara el último año fiscal con el
anterior, ambos tomados del panel point-in-time, por lo que no usa información futura.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.pipeline.metrics import annual_metrics
from src.utils.config_loader import get_config

# Nombres de los 9 criterios del F-Score (orden de Piotroski)
FSCORE_CRITERIA = [
    "roa_positive",
    "cfo_positive",
    "roa_improved",
    "accruals",
    "leverage_down",
    "current_ratio_up",
    "no_dilution",
    "gross_margin_up",
    "asset_turnover_up",
]


# ---------------------------------------------------------------------------
# Comparaciones seguras (NaN -> False: un dato ausente no otorga el punto)
# ---------------------------------------------------------------------------
def _pos(x) -> bool:
    return bool(pd.notna(x) and x > 0)


def _gt(a, b) -> bool:
    return bool(pd.notna(a) and pd.notna(b) and a > b)


def _lt(a, b) -> bool:
    return bool(pd.notna(a) and pd.notna(b) and a < b)


def _le(a, b) -> bool:
    return bool(pd.notna(a) and pd.notna(b) and a <= b)


# ---------------------------------------------------------------------------
# F-Score de Piotroski adaptado
# ---------------------------------------------------------------------------
def piotroski_fscore(metrics: pd.DataFrame) -> tuple[int, dict[str, bool]]:
    """Calcula el F-Score (0–9) y el detalle por criterio.

    Compara el último año fiscal (t) con el anterior (t-1). Los criterios de variación
    requieren el año previo; si falta, no se otorgan. Cada criterio suma 1 si se cumple
    y los datos no son NaN.

    Returns:
        (puntuación 0–9, dict criterio→bool). Panel vacío → (0, todos False).
    """
    detail = dict.fromkeys(FSCORE_CRITERIA, False)
    if metrics is None or metrics.empty:
        return 0, detail

    has_prev = len(metrics) >= 2

    def cur(col):
        return metrics[col].iloc[-1]

    def prev(col):
        return metrics[col].iloc[-2] if has_prev else np.nan

    # Series derivadas para apalancamiento y rotación de activos
    leverage = metrics["total_debt"] / metrics["total_assets"]
    turnover = metrics["revenue"] / metrics["total_assets"]
    lev_t, lev_p = leverage.iloc[-1], (leverage.iloc[-2] if has_prev else np.nan)
    turn_t, turn_p = turnover.iloc[-1], (turnover.iloc[-2] if has_prev else np.nan)

    # Rentabilidad
    detail["roa_positive"] = _pos(cur("roa"))
    detail["cfo_positive"] = _pos(cur("cfo"))
    detail["roa_improved"] = _gt(cur("roa"), prev("roa"))
    detail["accruals"] = _gt(cur("cfo"), cur("net_income"))  # CFO > beneficio
    # Apalancamiento / liquidez / financiación
    detail["leverage_down"] = _lt(lev_t, lev_p)
    detail["current_ratio_up"] = _gt(cur("current_ratio"), prev("current_ratio"))
    detail["no_dilution"] = _le(cur("shares"), prev("shares"))
    # Eficiencia operativa
    detail["gross_margin_up"] = _gt(cur("gross_margin"), prev("gross_margin"))
    detail["asset_turnover_up"] = _gt(turn_t, turn_p)

    return int(sum(detail.values())), detail


# ---------------------------------------------------------------------------
# Complementos (acotados en [0,1])
# ---------------------------------------------------------------------------
def capex_intensity_component(metrics: pd.DataFrame) -> float:
    """Puntúa lo asset-light que es la empresa: 1 − clamp(capex/CFO, 0, 1) en la ventana.

    Asset-light (poco capex respecto a la caja operativa) → cercano a 1. Si el CFO medio
    es ≤ 0 → 0 (genera poca caja). Datos ausentes → 0,5 (neutro).
    """
    window = get_config("quality.trend_window_years", 4)
    recent = metrics.tail(window)
    mean_capex = recent["capex"].mean()
    mean_cfo = recent["cfo"].mean()

    if pd.isna(mean_capex) or pd.isna(mean_cfo):
        return 0.5
    if mean_cfo <= 0:
        return 0.0
    ratio = min(max(mean_capex / mean_cfo, 0.0), 1.0)
    return 1.0 - ratio


def margin_trend_component(metrics: pd.DataFrame) -> float:
    """Fracción de incrementos interanuales del margen operativo en la ventana.

    Margen operativo siempre creciente → 1,0; decreciente → 0,0; histórico insuficiente
    (menos de 2 datos) → 0,5 (neutro).
    """
    window = get_config("quality.trend_window_years", 4)
    series = metrics["operating_margin"].tail(window).dropna()
    if len(series) < 2:
        return 0.5
    diffs = series.diff().dropna()
    return float((diffs > 0).sum() / len(diffs))


# ---------------------------------------------------------------------------
# Puntuación compuesta y ranking
# ---------------------------------------------------------------------------
def quality_score(metrics: pd.DataFrame) -> dict:
    """Compuesta de calidad en [0,1] y sus componentes.

    Returns:
        dict con fscore (0–9), capex_component, margin_trend_component y quality_score.
        Panel vacío → quality_score NaN.
    """
    if metrics is None or metrics.empty:
        return {
            "fscore": np.nan,
            "capex_component": np.nan,
            "margin_trend_component": np.nan,
            "quality_score": np.nan,
        }

    fscore, _ = piotroski_fscore(metrics)
    capex_comp = capex_intensity_component(metrics)
    margin_comp = margin_trend_component(metrics)

    w_fscore = get_config("quality.fscore_weight", 0.6)
    w_capex = get_config("quality.capex_intensity_weight", 0.2)
    w_margin = get_config("quality.margin_trend_weight", 0.2)

    composite = w_fscore * (fscore / 9.0) + w_capex * capex_comp + w_margin * margin_comp
    return {
        "fscore": fscore,
        "capex_component": capex_comp,
        "margin_trend_component": margin_comp,
        "quality_score": composite,
    }


def score_universe(
    fundamentals: pd.DataFrame,
    tickers: list[str],
    asof: str | pd.Timestamp,
) -> pd.DataFrame:
    """Puntúa y ordena por calidad una lista de empresas a una fecha.

    Returns:
        DataFrame con ticker, fscore, capex_component, margin_trend_component y
        quality_score, ordenado de mayor a menor `quality_score` (NaN al final).
    """
    columns = ["ticker", "fscore", "capex_component", "margin_trend_component", "quality_score"]
    rows: list[dict] = []
    for ticker in tickers:
        ticker = ticker.upper()
        metrics = annual_metrics(fundamentals, ticker, asof)
        rows.append({"ticker": ticker, **quality_score(metrics)})

    df = pd.DataFrame(rows, columns=columns)
    return df.sort_values("quality_score", ascending=False, na_position="last").reset_index(
        drop=True
    )
