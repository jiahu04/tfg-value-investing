"""
strategies.py — Estrategias de aportación (paso 2.3).

Compara tres formas de inyectar dinero nuevo en la estrategia value a lo largo del
tiempo, sobre un índice de valor por unidad (NAV) ya construido y una señal de margen
de seguridad agregado. Todas las funciones son **puras** (no tocan red, pipeline ni
ficheros): operan sobre series y devuelven números o DataFrames, de modo que se pueden
probar de forma aislada.

Estrategias (config `contributions`):
  - "dca_fijo": aportación periódica constante (referencia / dollar-cost averaging).
  - "dca_condicional": la aportación escala con el margen de seguridad agregado; sube
    cuando el descuento se amplía y baja o se suspende cuando se estrecha.
  - "concentrada": concentra la potencia de fuego en el máximo descuento; aporta un
    múltiplo de la base solo cuando el margen supera un umbral, y nada en otro caso.

Métrica principal: rentabilidad ponderada por el dinero (MWR), es decir la **TIR**
anualizada de los flujos de caja (aportaciones negativas + valor final positivo), más
el **precio medio de adquisición** (total aportado / unidades compradas).
"""

from __future__ import annotations

import pandas as pd
from scipy.optimize import brentq

# Identificadores de las tres estrategias y su etiqueta para las tablas.
STRATEGIES: dict[str, str] = {
    "dca_fijo": "DCA fijo",
    "dca_condicional": "DCA condicional",
    "concentrada": "Concentrada",
}


def scale_factor_conditional(
    margin: float,
    *,
    base_margin: float,
    suspend_below_margin: float,
    max_scale_factor: float,
) -> float:
    """Multiplicador de la aportación del DCA condicional según el margen de seguridad.

    La aportación es proporcional al margen relativo al margen base y se suspende cuando
    el descuento es demasiado estrecho:

        scale = 0                                     si margin < suspend_below_margin
        scale = clamp(margin / base_margin, 0, max)   en otro caso

    De este modo la aportación vale exactamente 1× en `base_margin`, baja por debajo de 1×
    cuando el margen se estrecha (sin llegar a suspenderse hasta `suspend_below_margin`) y
    sube por encima de 1× cuando se amplía, con tope en `max_scale_factor`.

    Args:
        margin: Margen de seguridad agregado (p. ej. 0.30 = 30 % de descuento). NaN → 0.
        base_margin: Margen al que la aportación vale 1×.
        suspend_below_margin: Margen por debajo del cual se suspende la aportación.
        max_scale_factor: Tope del multiplicador.

    Returns:
        Multiplicador en [0, max_scale_factor].
    """
    if pd.isna(margin) or margin < suspend_below_margin or base_margin <= 0:
        return 0.0
    scale = margin / base_margin
    return float(min(max(scale, 0.0), max_scale_factor))


def contribution_amount(strategy: str, margin: float, base: float, cfg: dict) -> float:
    """Importe a aportar en una fecha según la estrategia y el margen de seguridad.

    Args:
        strategy: "dca_fijo", "dca_condicional" o "concentrada".
        margin: Margen de seguridad agregado vigente en la fecha (puede ser NaN).
        base: Aportación periódica de referencia (`contributions.periodic_amount`).
        cfg: Sub-config `contributions` (con `conditional_dca` y `concentrated`).

    Returns:
        Importe a aportar (>= 0).
    """
    if strategy == "dca_fijo":
        return float(base)

    if strategy == "dca_condicional":
        # Sin señal de margen (NaN) se aporta la base (comportamiento neutro).
        if pd.isna(margin):
            return float(base)
        cond = cfg.get("conditional_dca", {})
        factor = scale_factor_conditional(
            margin,
            base_margin=cond.get("base_margin", 0.30),
            suspend_below_margin=cond.get("suspend_below_margin", 0.05),
            max_scale_factor=cond.get("max_scale_factor", 2.0),
        )
        return float(base * factor)

    if strategy == "concentrada":
        conc = cfg.get("concentrated", {})
        min_margin = conc.get("min_margin", 0.45)
        multiplier = conc.get("multiplier", 3.0)
        if pd.isna(margin) or margin < min_margin:
            return 0.0
        return float(base * multiplier)

    raise ValueError(f"Estrategia desconocida: {strategy!r}")


def simulate_strategy(
    nav: pd.Series,
    signal: pd.Series,
    dates: pd.DatetimeIndex,
    *,
    strategy: str,
    base: float,
    cfg: dict,
) -> dict:
    """Simula una estrategia de aportación sobre el NAV en las fechas dadas.

    En cada fecha de aportación se decide el importe (según la estrategia y el margen
    vigente), se compran `importe / nav` unidades y se acumulan. Al final se valora la
    posición al último NAV disponible.

    Args:
        nav: Índice de valor por unidad de la estrategia value, indexado por fecha.
        signal: Margen de seguridad agregado, indexado por fecha (mismo calendario o
            reindexable a `dates`).
        dates: Fechas de aportación (subconjunto del calendario de `nav`).
        strategy: Identificador de la estrategia.
        base: Aportación periódica de referencia.
        cfg: Sub-config `contributions`.

    Returns:
        dict con cashflows (lista de (fecha, importe negativo)), units, invested,
        final_value, avg_price y n_contributions.
    """
    units = 0.0
    invested = 0.0
    n_contributions = 0
    cashflows: list[tuple[pd.Timestamp, float]] = []

    for date in dates:
        price = nav.get(date)
        if price is None or pd.isna(price) or price <= 0:
            continue
        margin = signal.get(date, float("nan"))
        amount = contribution_amount(strategy, margin, base, cfg)
        if amount <= 0:
            continue
        units += amount / price
        invested += amount
        n_contributions += 1
        cashflows.append((date, -amount))

    final_date = nav.index[-1]
    final_price = float(nav.iloc[-1])
    final_value = units * final_price
    avg_price = invested / units if units > 0 else float("nan")

    return {
        "strategy": strategy,
        "cashflows": cashflows,
        "final_date": final_date,
        "final_value": final_value,
        "units": units,
        "invested": invested,
        "avg_price": avg_price,
        "n_contributions": n_contributions,
    }


def money_weighted_return(
    cashflows: list[tuple[pd.Timestamp, float]],
    final_value: float,
    final_date: pd.Timestamp,
) -> float:
    """Rentabilidad ponderada por el dinero (TIR anualizada) de un flujo de caja.

    Resuelve la tasa anual r que anula el valor actual neto:

        VAN(r) = Σ_i cf_i / (1 + r)^t_i + final_value / (1 + r)^t_final = 0

    donde t_i son los años transcurridos desde la primera aportación (admite intervalos
    irregulares). Se resuelve por bisección (`scipy.optimize.brentq`) sobre un intervalo
    amplio de tasas.

    Args:
        cashflows: lista de (fecha, importe) con las aportaciones (importes negativos).
        final_value: valor final de la posición (positivo).
        final_date: fecha de valoración final.

    Returns:
        TIR anual (p. ej. 0.10 = 10 %), o NaN si no hay flujos o no converge.
    """
    if not cashflows or final_value <= 0:
        return float("nan")

    origin = cashflows[0][0]
    years = [(date - origin).days / 365.25 for date, _ in cashflows]
    amounts = [amount for _, amount in cashflows]
    t_final = (final_date - origin).days / 365.25

    def npv(rate: float) -> float:
        factor = 1.0 + rate
        total = sum(cf / factor**t for cf, t in zip(amounts, years, strict=False))
        return total + final_value / factor**t_final

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:  # sin cambio de signo: no hay raíz en el intervalo
        return float("nan")
    return float(brentq(npv, lo, hi, maxiter=200))


def compare_strategies(
    nav: pd.Series,
    signal: pd.Series,
    dates: pd.DatetimeIndex,
    *,
    cfg: dict,
) -> pd.DataFrame:
    """Simula las tres estrategias y devuelve la tabla comparativa (8.3).

    Args:
        nav: Índice de valor por unidad de la estrategia value.
        signal: Margen de seguridad agregado por fecha.
        dates: Fechas de aportación.
        cfg: Sub-config `contributions` (incluye `periodic_amount`).

    Returns:
        DataFrame indexado por estrategia con columnas: TIR (MWR), valor final, total
        aportado, nº aportaciones y precio medio de adquisición.
    """
    base = cfg.get("periodic_amount", 1000.0)
    rows = []
    for key, label in STRATEGIES.items():
        sim = simulate_strategy(nav, signal, dates, strategy=key, base=base, cfg=cfg)
        mwr = money_weighted_return(sim["cashflows"], sim["final_value"], sim["final_date"])
        rows.append(
            {
                "estrategia": label,
                "TIR (MWR)": mwr,
                "valor_final": sim["final_value"],
                "total_aportado": sim["invested"],
                "n_aportaciones": sim["n_contributions"],
                "precio_medio": sim["avg_price"],
            }
        )
    return pd.DataFrame(rows).set_index("estrategia")
