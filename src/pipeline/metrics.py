"""
metrics.py — Métricas derivadas point-in-time (paso 1.2).

A partir del panel anual de conceptos crudos (`point_in_time.annual_panel`), calcula
las magnitudes que consumirán los filtros (1.3), la calidad (1.4) y la valoración
(1.5): FCF, deuda neta, EBIT/EBITDA, márgenes, cobertura de intereses, ratio
corriente, variación de acciones, CFO/beneficio y ROA.

Dos capas:
- El **mapa de tags** (`fundamentals.concept_map`) resuelve cada magnitud canónica a
  partir del primer tag XBRL disponible (las empresas usan etiquetas distintas).
- Las **fórmulas** (EBITDA = EBIT + D&A, deuda neta = deuda − caja, ...) viven aquí.
  Los umbrales NO: siguen en `filters`/`valuation`.

Todo es puro y se prueba con paneles sintéticos, sin red.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.pipeline.point_in_time import annual_panel
from src.utils.config_loader import get_config


def _nan_series(panel: pd.DataFrame) -> pd.Series:
    """Serie de NaN alineada con el índice (años) del panel."""
    return pd.Series(np.nan, index=panel.index, dtype="float64")


def _resolve(panel: pd.DataFrame, magnitude: str) -> pd.Series:
    """Resuelve la serie de la magnitud canónica coalesciendo los tags por prioridad.

    Recorre `fundamentals.concept_map[magnitude]` en orden y, **año a año**, toma el
    valor del primer tag con dato. Así un tag clásico (p. ej. `SalesRevenueNet`) cubre
    los años antiguos y uno moderno (`RevenueFromContract...`) los recientes, sin que
    uno con datos parciales tape al siguiente. NaN donde ningún tag tenga valor.
    """
    candidates = get_config(f"fundamentals.concept_map.{magnitude}", [])
    result: pd.Series | None = None
    for tag in candidates:
        if tag in panel.columns:
            col = panel[tag].astype("float64")
            result = col if result is None else result.combine_first(col)
    return result if result is not None else _nan_series(panel)


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """División protegida: denominador 0 o infinitos → NaN."""
    result = num / den.replace(0, np.nan)
    return result.replace([np.inf, -np.inf], np.nan)


def _scale_shares(value: float, floor: float, step: float) -> float:
    """Normaliza la escala de un número de acciones a unidades.

    Algunas empresas reportan las acciones en miles o millones. Si el valor es positivo
    pero cae por debajo del mínimo plausible, se multiplica por `step` hasta alcanzarlo.
    NaN/0 pasan tal cual; `step <= 1` desactiva la normalización (evita bucles).
    """
    if pd.isna(value) or value <= 0 or step <= 1:
        return value
    while value < floor:
        value *= step
    return float(value)


def shares_outstanding(panel: pd.DataFrame) -> pd.Series:
    """Acciones en circulación (magnitud `shares`) con la escala normalizada a unidades."""
    floor = get_config("fundamentals.min_plausible_shares", 1_000_000)
    step = get_config("fundamentals.shares_scale_step", 1000)
    return _resolve(panel, "shares").map(lambda v: _scale_shares(v, floor, step))


# ---------------------------------------------------------------------------
# Magnitudes derivadas (cada una opera sobre el panel y devuelve una serie anual)
# ---------------------------------------------------------------------------
def ebit(panel: pd.DataFrame) -> pd.Series:
    """Resultado de explotación. Respaldo: beneficio neto + intereses + impuestos."""
    operating = _resolve(panel, "operating_income")
    fallback = (
        _resolve(panel, "net_income")
        + _resolve(panel, "interest_expense")
        + _resolve(panel, "income_tax")
    )
    return operating.where(operating.notna(), fallback)


def ebitda(panel: pd.DataFrame) -> pd.Series:
    """EBIT + depreciación y amortización."""
    return ebit(panel) + _resolve(panel, "dep_amort")


def free_cash_flow(panel: pd.DataFrame) -> pd.Series:
    """Flujo de caja libre = CFO − capex (el capex viene positivo y se resta)."""
    return _resolve(panel, "cfo") - _resolve(panel, "capex")


def total_debt(panel: pd.DataFrame) -> pd.Series:
    """Deuda total. Suma tramo no corriente + corriente; si no, usa el tag total."""
    noncurrent = _resolve(panel, "long_term_debt_noncurrent")
    current = _resolve(panel, "current_debt")
    combined = noncurrent.add(current, fill_value=0)
    total_tag = _resolve(panel, "long_term_debt_total")
    has_tranches = noncurrent.notna() | current.notna()
    return combined.where(has_tranches, total_tag)


def net_debt(panel: pd.DataFrame) -> pd.Series:
    """Deuda neta = deuda total − efectivo − inversiones a corto.

    El efectivo y las inversiones a corto ausentes se tratan como 0.
    """
    cash = _resolve(panel, "cash").fillna(0)
    sti = _resolve(panel, "short_term_investments").fillna(0)
    return total_debt(panel) - cash - sti


def gross_profit(panel: pd.DataFrame) -> pd.Series:
    """Margen bruto absoluto. Respaldo: ingresos − coste de ventas."""
    gp = _resolve(panel, "gross_profit")
    fallback = _resolve(panel, "revenue") - _resolve(panel, "cost_of_revenue")
    return gp.where(gp.notna(), fallback)


def gross_margin(panel: pd.DataFrame) -> pd.Series:
    return _safe_div(gross_profit(panel), _resolve(panel, "revenue"))


def operating_margin(panel: pd.DataFrame) -> pd.Series:
    return _safe_div(ebit(panel), _resolve(panel, "revenue"))


def net_margin(panel: pd.DataFrame) -> pd.Series:
    return _safe_div(_resolve(panel, "net_income"), _resolve(panel, "revenue"))


def interest_coverage(panel: pd.DataFrame) -> pd.Series:
    """Cobertura de intereses = EBIT / gastos financieros."""
    return _safe_div(ebit(panel), _resolve(panel, "interest_expense"))


def current_ratio(panel: pd.DataFrame) -> pd.Series:
    """Ratio corriente = activo corriente / pasivo corriente."""
    return _safe_div(_resolve(panel, "current_assets"), _resolve(panel, "current_liabilities"))


def share_growth(panel: pd.DataFrame) -> pd.Series:
    """Variación interanual de las acciones en circulación (dilución).

    `fill_method=None` evita rellenar huecos: un año sin dato queda NaN en lugar de
    fabricar una variación del 0 %.
    """
    return shares_outstanding(panel).pct_change(fill_method=None)


def cfo_to_net_income(panel: pd.DataFrame) -> pd.Series:
    """Calidad contable = flujo de caja operativo / beneficio neto."""
    return _safe_div(_resolve(panel, "cfo"), _resolve(panel, "net_income"))


def roa(panel: pd.DataFrame) -> pd.Series:
    """Rentabilidad sobre activos = beneficio neto / activo total."""
    return _safe_div(_resolve(panel, "net_income"), _resolve(panel, "total_assets"))


# ---------------------------------------------------------------------------
# Ensamblado del panel de métricas
# ---------------------------------------------------------------------------
def compute_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    """Construye el panel anual de niveles + métricas derivadas a partir del panel crudo.

    Args:
        panel: Panel anual de conceptos crudos (de `annual_panel`).

    Returns:
        DataFrame indexado por fin de año fiscal (ascendente), con una columna por
        magnitud canónica y métrica derivada. Vacío si el panel de entrada lo está.
    """
    if panel.empty:
        return pd.DataFrame()

    ebit_s = ebit(panel)
    ebitda_s = ebitda(panel)
    net_debt_s = net_debt(panel)

    data = {
        # Niveles canónicos
        "revenue": _resolve(panel, "revenue"),
        "gross_profit": gross_profit(panel),
        "operating_income": _resolve(panel, "operating_income"),
        "net_income": _resolve(panel, "net_income"),
        "interest_expense": _resolve(panel, "interest_expense"),
        "income_tax": _resolve(panel, "income_tax"),
        "cfo": _resolve(panel, "cfo"),
        "capex": _resolve(panel, "capex"),
        "dep_amort": _resolve(panel, "dep_amort"),
        "total_assets": _resolve(panel, "total_assets"),
        "current_assets": _resolve(panel, "current_assets"),
        "current_liabilities": _resolve(panel, "current_liabilities"),
        "cash": _resolve(panel, "cash"),
        "short_term_investments": _resolve(panel, "short_term_investments"),
        "equity": _resolve(panel, "equity"),
        "shares": shares_outstanding(panel),
        # Métricas derivadas
        "ebit": ebit_s,
        "ebitda": ebitda_s,
        "fcf": free_cash_flow(panel),
        "total_debt": total_debt(panel),
        "net_debt": net_debt_s,
        "net_debt_to_ebitda": _safe_div(net_debt_s, ebitda_s),
        "gross_margin": gross_margin(panel),
        "operating_margin": operating_margin(panel),
        "net_margin": net_margin(panel),
        "interest_coverage": interest_coverage(panel),
        "current_ratio": current_ratio(panel),
        "share_growth": share_growth(panel),
        "cfo_to_net_income": cfo_to_net_income(panel),
        "roa": roa(panel),
    }
    return pd.DataFrame(data, index=panel.index)


def annual_metrics(
    fundamentals: pd.DataFrame,
    ticker: str,
    asof: str | pd.Timestamp,
) -> pd.DataFrame:
    """Panel anual point-in-time de métricas para una empresa y fecha.

    Atajo que combina `annual_panel` (acceso point-in-time) con `compute_metrics`.

    Returns:
        DataFrame indexado por fin de año fiscal (ascendente). Vacío si no hay datos.
    """
    panel = annual_panel(fundamentals, ticker, asof)
    return compute_metrics(panel)


def metrics_asof(
    fundamentals: pd.DataFrame,
    ticker: str,
    asof: str | pd.Timestamp,
) -> pd.Series:
    """Métricas del último año fiscal conocido a `asof` (Serie). Vacía si no hay datos."""
    metrics = annual_metrics(fundamentals, ticker, asof)
    if metrics.empty:
        return pd.Series(dtype="float64")
    return metrics.iloc[-1]
