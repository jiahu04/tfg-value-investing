"""
filters.py — Filtros de descarte (Etapa 2, paso 1.3).

Cadena de filtros binarios que reduce el universo eliminando empresas que no
cumplen criterios mínimos de sector, deuda, dilución, rentabilidad y calidad
contable. Opera sobre el panel anual de métricas del paso 1.2 (`annual_metrics`),
así que es point-in-time por construcción: a una fecha D solo usa lo conocido
entonces. Devuelve, por empresa, si sobrevive y la traza de los filtros que falla.

Todos los umbrales salen de `config.filters`. Las funciones son puras y testeables.

Convención de "sostenido": un filtro descarta si los **últimos N años** del panel
incumplen todos (con N de la configuración). Un año sin dato (NaN) rompe la racha,
de modo que no se descarta por falta de información. Si hay menos de N años, tampoco.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from src.pipeline.metrics import annual_metrics
from src.utils.config_loader import get_config


@dataclass
class FilterOutcome:
    """Resultado de aplicar la cadena de filtros a una empresa."""

    passed: bool
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utilidades de evaluación
# ---------------------------------------------------------------------------
def _sustained_breach(
    series: pd.Series,
    predicate: Callable[[pd.Series], pd.Series],
    years: int,
) -> bool:
    """¿Incumplen `predicate` los últimos `years` valores (sin NaN ni huecos)?

    Devuelve True solo si hay al menos `years` valores, ninguno de los últimos
    `years` es NaN y todos cumplen el predicado (el incumplimiento del filtro).
    """
    recent = series.tail(years)
    if len(recent) < years or recent.isna().any():
        return False
    return bool(predicate(recent).all())


def _count_in_window(
    series: pd.Series,
    predicate: Callable[[pd.Series], pd.Series],
    window: int,
) -> int:
    """Cuenta cuántos de los últimos `window` valores cumplen `predicate` (NaN no cuenta)."""
    recent = series.tail(window)
    return int((predicate(recent) & recent.notna()).sum())


# ---------------------------------------------------------------------------
# Filtros individuales (cada uno devuelve la lista de motivos de descarte)
# ---------------------------------------------------------------------------
def check_sector(sector: str | None) -> list[str]:
    """Descarta si el sector está en `filters.excluded_sectors`."""
    excluded = get_config("filters.excluded_sectors", [])
    return ["sector_excluido"] if sector in excluded else []


def check_debt(metrics: pd.DataFrame) -> list[str]:
    """Descarta por apalancamiento (Deuda Neta/EBITDA) o cobertura de intereses sostenidos."""
    reasons: list[str] = []
    years = get_config("filters.debt.sustained_years", 3)

    max_ratio = get_config("filters.debt.max_net_debt_ebitda", 4.0)
    if _sustained_breach(metrics["net_debt_to_ebitda"], lambda s: s > max_ratio, years):
        reasons.append("deuda_ebitda")

    min_cov = get_config("filters.debt.min_interest_coverage", 2.0)
    if _sustained_breach(metrics["interest_coverage"], lambda s: s < min_cov, years):
        reasons.append("cobertura_intereses")

    return reasons


def check_dilution(metrics: pd.DataFrame) -> list[str]:
    """Descarta si las acciones crecen por encima del umbral de forma sostenida."""
    max_pct = get_config("filters.dilution.max_share_growth_pct", 3.0)
    years = get_config("filters.dilution.sustained_years", 3)
    threshold = max_pct / 100.0  # el umbral está en %, share_growth es fracción
    if _sustained_breach(metrics["share_growth"], lambda s: s > threshold, years):
        return ["dilucion"]
    return []


def check_profitability(metrics: pd.DataFrame) -> list[str]:
    """Descarta por pérdidas o FCF negativo recurrentes en la ventana de histórico."""
    reasons: list[str] = []
    window = get_config("filters.profitability.lookback_years", 5)

    max_loss = get_config("filters.profitability.max_loss_years", 2)
    if _count_in_window(metrics["net_income"], lambda s: s < 0, window) > max_loss:
        reasons.append("perdidas_recurrentes")

    max_neg_fcf = get_config("filters.profitability.max_negative_fcf_years", 2)
    if _count_in_window(metrics["fcf"], lambda s: s < 0, window) > max_neg_fcf:
        reasons.append("fcf_negativo_recurrente")

    return reasons


def check_accounting_quality(metrics: pd.DataFrame) -> list[str]:
    """Descarta si CFO/beneficio es bajo de forma sostenida (solo años con beneficio).

    Los años de pérdidas se enmascaran (los captura el filtro de rentabilidad), para
    no penalizar dos veces y porque el ratio no es interpretable con beneficio negativo.
    """
    min_ratio = get_config("filters.accounting_quality.min_cfo_to_net_income", 0.5)
    years = get_config("filters.accounting_quality.sustained_years", 3)
    ratio = metrics["cfo_to_net_income"].where(metrics["net_income"] > 0)
    if _sustained_breach(ratio, lambda s: s < min_ratio, years):
        return ["calidad_contable"]
    return []


# ---------------------------------------------------------------------------
# Cadena y aplicación al universo
# ---------------------------------------------------------------------------
def apply_filters(metrics: pd.DataFrame, sector: str | None) -> FilterOutcome:
    """Ejecuta la cadena de filtros y devuelve el resultado con todos los motivos.

    Args:
        metrics: Panel anual de métricas de la empresa (de `annual_metrics`).
        sector: Sector de la empresa (para el filtro de sector).

    Returns:
        FilterOutcome con `passed` (sobrevive) y la lista de motivos de descarte.
        Panel vacío → descartada con motivo `sin_datos`.
    """
    if metrics is None or metrics.empty:
        return FilterOutcome(passed=False, reasons=["sin_datos"])

    reasons: list[str] = []
    reasons += check_sector(sector)
    reasons += check_debt(metrics)
    reasons += check_dilution(metrics)
    reasons += check_profitability(metrics)
    reasons += check_accounting_quality(metrics)
    return FilterOutcome(passed=not reasons, reasons=reasons)


def filter_universe(
    fundamentals: pd.DataFrame,
    sectors_df: pd.DataFrame,
    tickers: list[str],
    asof: str | pd.Timestamp,
) -> pd.DataFrame:
    """Aplica los filtros a una lista de empresas a una fecha y devuelve la traza.

    Args:
        fundamentals: Tabla cruda de fundamentales (paso 1.1).
        sectors_df: Tabla ticker→sector (`data/cache/sectors.csv`).
        tickers: Empresas a evaluar.
        asof: Fecha de decisión D.

    Returns:
        DataFrame con columnas ticker, sector, passed y reasons (motivos unidos por ';').
    """
    sector_map = dict(zip(sectors_df["ticker"], sectors_df["sector"], strict=False))

    rows: list[dict] = []
    for ticker in tickers:
        ticker = ticker.upper()
        metrics = annual_metrics(fundamentals, ticker, asof)
        sector = sector_map.get(ticker)
        outcome = apply_filters(metrics, sector)
        rows.append(
            {
                "ticker": ticker,
                "sector": sector,
                "passed": outcome.passed,
                "reasons": ";".join(outcome.reasons),
            }
        )

    return pd.DataFrame(rows, columns=["ticker", "sector", "passed", "reasons"])
