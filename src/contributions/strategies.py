"""
strategies.py — Estrategias de aportación (paso 2.3).

Compara tres formas de inyectar dinero nuevo en la estrategia value a lo largo del
tiempo, sobre un índice de valor por unidad (NAV) ya construido y una **señal de
oportunidad agregada** (la amplitud del conjunto de oportunidades: qué fracción de las
empresas ofrece margen de seguridad en cada fecha). Todas las funciones son **puras** (no
tocan red, pipeline ni ficheros): operan sobre series y devuelven números o DataFrames,
de modo que se pueden probar de forma aislada.

Estrategias (config `contributions`). Las tres primeras son las del trabajo (guiadas por la
**amplitud de oportunidades** value); las dos últimas son líneas base clásicas de la
literatura, para comparar:
  - "dca_fijo": aportación periódica constante (referencia / dollar-cost averaging).
  - "dca_condicional": la aportación escala con la **amplitud de oportunidades**; sube
    cuando hay más value disponible y baja o se suspende cuando hay poco.
  - "concentrada": concentra la potencia de fuego cuando abundan las oportunidades; aporta
    un múltiplo de la base solo cuando la señal supera un umbral, y nada en otro caso.
  - "value_averaging" (Edleson): aporta lo necesario para que el valor de la cartera siga
    una **senda objetivo** creciente (variante solo-compra por defecto).
  - "drawdown_based" (*buy-the-dip*): aporta más cuanto más cae el NAV desde su máximo.

Métrica principal: rentabilidad ponderada por el dinero (MWR), es decir la **TIR**
anualizada de los flujos de caja (aportaciones negativas + valor final positivo), más
el **precio medio de adquisición** (total aportado / unidades compradas).
"""

from __future__ import annotations

import pandas as pd
from scipy.optimize import brentq

# Identificadores de las estrategias y su etiqueta para las tablas.
# Las tres primeras son las del trabajo (señal = amplitud de oportunidades); las dos
# últimas son líneas base clásicas de la literatura (value averaging y buy-the-dip).
STRATEGIES: dict[str, str] = {
    "dca_fijo": "DCA fijo",
    "dca_condicional": "DCA condicional",
    "concentrada": "Concentrada",
    "value_averaging": "Value averaging",
    "drawdown_based": "Drawdown-based",
}


def scale_factor_conditional(
    signal: float,
    *,
    base: float,
    suspend_below: float,
    max_scale_factor: float,
) -> float:
    """Multiplicador de la aportación del DCA condicional según la señal de oportunidad.

    La señal es la **amplitud de oportunidades** (fracción del conjunto que ofrece margen
    de seguridad). La aportación es proporcional a la señal relativa a su valor base y se
    suspende cuando hay muy pocas oportunidades:

        scale = 0                                  si signal < suspend_below
        scale = clamp(signal / base, 0, max)       en otro caso

    De este modo la aportación vale exactamente 1× en `base`, baja por debajo de 1× cuando
    la señal se estrecha (sin suspenderse hasta `suspend_below`) y sube por encima de 1×
    cuando se amplía, con tope en `max_scale_factor`.

    Args:
        signal: Señal de oportunidad agregada (amplitud, en [0, 1]). NaN → 0.
        base: Valor de la señal al que la aportación vale 1×.
        suspend_below: Señal por debajo de la cual se suspende la aportación.
        max_scale_factor: Tope del multiplicador.

    Returns:
        Multiplicador en [0, max_scale_factor].
    """
    if pd.isna(signal) or signal < suspend_below or base <= 0:
        return 0.0
    scale = signal / base
    return float(min(max(scale, 0.0), max_scale_factor))


# ---------------------------------------------------------------------------
# Estrategias clásicas (líneas base): value averaging y drawdown-based
# ---------------------------------------------------------------------------
def nav_drawdown(nav: pd.Series) -> pd.Series:
    """Drawdown del NAV respecto a su máximo previo: `1 − nav / nav.cummax()`.

    Es **point-in-time**: el máximo acumulado (`cummax`) solo mira al pasado, así que el
    drawdown en una fecha no depende de NAV futuros (no hay look-ahead). En [0, 1].
    """
    if nav.empty:
        return nav
    drawdown = 1.0 - nav / nav.cummax()
    return drawdown.clip(lower=0.0)


def drawdown_scale(drawdown: float, *, ref_drawdown: float, max_scale_factor: float) -> float:
    """Multiplicador *buy-the-dip*: `1 + drawdown / ref`, acotado a `[1, max]`.

    En máximos (drawdown 0) vale 1× (aporta la base); cuanto más profunda la caída, más
    aporta, con tope en `max_scale_factor`. NaN o caída no positiva → 1× (base).
    """
    if pd.isna(drawdown) or drawdown <= 0 or ref_drawdown <= 0:
        return 1.0
    scale = 1.0 + drawdown / ref_drawdown
    return float(min(scale, max_scale_factor))


def value_target(period: int, *, target_step: float, growth: float) -> float:
    """Valor objetivo acumulado del *value averaging* tras `period` aportaciones (1-based).

    Con `growth = 0` la senda es lineal (`target_step · period`); con `growth > 0` crece de
    forma compuesta (suma geométrica), modelando una senda de valor objetivo creciente.
    """
    if period <= 0:
        return 0.0
    if growth and growth > 0:
        return float(target_step * ((1.0 + growth) ** period - 1.0) / growth)
    return float(target_step * period)


def value_averaging_amount(target: float, current_value: float, *, allow_selling: bool) -> float:
    """Aportación del *value averaging*: lo necesario para alcanzar la senda objetivo.

    `amount = target − current_value`. Si el valor actual supera el objetivo el importe es
    negativo (vender el exceso); en la variante **solo-compra** (`allow_selling=False`) se
    devuelve 0 en ese caso.
    """
    amount = target - current_value
    if amount < 0 and not allow_selling:
        return 0.0
    return float(amount)


def contribution_amount(strategy: str, signal: float, base: float, cfg: dict) -> float:
    """Importe a aportar en una fecha según la estrategia y la señal de oportunidad.

    Args:
        strategy: "dca_fijo", "dca_condicional" o "concentrada".
        signal: Señal de oportunidad agregada (amplitud) vigente en la fecha (puede ser NaN).
        base: Aportación periódica de referencia (`contributions.periodic_amount`).
        cfg: Sub-config `contributions` (con `conditional_dca` y `concentrated`).

    Returns:
        Importe a aportar (>= 0).
    """
    if strategy == "dca_fijo":
        return float(base)

    if strategy == "dca_condicional":
        # Sin señal (NaN) se aporta la base (comportamiento neutro).
        if pd.isna(signal):
            return float(base)
        cond = cfg.get("conditional_dca", {})
        factor = scale_factor_conditional(
            signal,
            base=cond.get("base", 0.25),
            suspend_below=cond.get("suspend_below", 0.10),
            max_scale_factor=cond.get("max_scale_factor", 2.0),
        )
        return float(base * factor)

    if strategy == "concentrada":
        conc = cfg.get("concentrated", {})
        min_signal = conc.get("min", 0.35)
        multiplier = conc.get("multiplier", 3.0)
        if pd.isna(signal) or signal < min_signal:
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

    En cada fecha de aportación se decide el importe y se compran `importe / nav` unidades
    (importe negativo = venta del exceso, solo en value averaging con `allow_selling`). Al
    final se valora la posición al último NAV disponible. El importe se decide según la
    familia de estrategia:
      - señal (dca_fijo/condicional/concentrada): `contribution_amount` con la amplitud.
      - value_averaging: lo necesario para alcanzar la senda de valor objetivo.
      - drawdown_based: la base escalada por el drawdown del NAV (*buy-the-dip*).

    Args:
        nav: Índice de valor por unidad de la estrategia value, indexado por fecha.
        signal: Señal de oportunidad agregada (amplitud), indexada por fecha (mismo
            calendario o reindexable a `dates`).
        dates: Fechas de aportación (subconjunto del calendario de `nav`).
        strategy: Identificador de la estrategia.
        base: Aportación periódica de referencia.
        cfg: Sub-config `contributions`.

    Returns:
        dict con cashflows (lista de (fecha, importe negativo)), units, invested,
        final_value, avg_price y n_contributions. `invested`/`avg_price` se miden sobre las
        **compras** (el precio medio es de adquisición); las ventas se reflejan en la TIR.
    """
    units = 0.0
    invested = 0.0
    units_bought = 0.0
    n_contributions = 0
    cashflows: list[tuple[pd.Timestamp, float]] = []
    drawdown = nav_drawdown(nav)
    va_cfg = cfg.get("value_averaging", {})
    dd_cfg = cfg.get("drawdown_based", {})
    period = 0

    for date in dates:
        price = nav.get(date)
        if price is None or pd.isna(price) or price <= 0:
            continue
        period += 1
        if strategy == "value_averaging":
            target = value_target(
                period,
                target_step=va_cfg.get("target_step", 1000.0),
                growth=va_cfg.get("growth", 0.0),
            )
            amount = value_averaging_amount(
                target, units * price, allow_selling=va_cfg.get("allow_selling", False)
            )
        elif strategy == "drawdown_based":
            amount = base * drawdown_scale(
                float(drawdown.get(date, 0.0)),
                ref_drawdown=dd_cfg.get("ref_drawdown", 0.10),
                max_scale_factor=dd_cfg.get("max_scale_factor", 3.0),
            )
        else:
            amount = contribution_amount(strategy, signal.get(date, float("nan")), base, cfg)
        if amount == 0:
            continue
        units += amount / price
        cashflows.append((date, -amount))
        if amount > 0:  # solo las compras cuentan para el precio medio de adquisición
            invested += amount
            units_bought += amount / price
            n_contributions += 1

    final_date = nav.index[-1]
    final_price = float(nav.iloc[-1])
    final_value = units * final_price
    avg_price = invested / units_bought if units_bought > 0 else float("nan")

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
