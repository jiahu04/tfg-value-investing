"""
valuation.py — Valoración compuesta (Etapa 4, paso 1.5).

Estima el valor intrínseco por acción de una empresa a una fecha D con tres modelos
y los integra en un rango:
  - DCF: FCFF proyectado (EBIT·(1−t)+D&A−capex, sin ΔWC), WACC vía CAPM, valor
    terminal de Gordon, con análisis de sensibilidad sobre WACC y crecimiento.
  - Graham Number: filtro conservador.
  - Múltiplos relativos al sector: mediana sectorial de PER, EV/EBIT, EV/EBITDA, P/FCF.

Todo es point-in-time: las cuentas vienen de `annual_metrics` (filed ≤ D) y los precios
se toman a fecha ≤ D. Funciones puras (los datos entran como argumentos), testeables.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.pipeline.metrics import annual_metrics
from src.utils.config_loader import get_config

# Mínimo de observaciones para estimar beta por regresión; si no, beta por defecto.
_BETA_MIN_PERIODS = 30


# ---------------------------------------------------------------------------
# Acceso a datos de mercado (point-in-time)
# ---------------------------------------------------------------------------
def price_asof(
    prices_df: pd.DataFrame,
    ticker: str,
    asof: str | pd.Timestamp,
    *,
    field: str = "close_unadj",
) -> float:
    """Último precio de cierre con fecha ≤ asof. NaN si no hay.

    Por defecto usa el precio **sin ajustar** (`close_unadj`, precio real de mercado),
    para que sea comparable con el valor intrínseco por acción (que se calcula con el
    número de acciones del periodo, también sin ajustar). Si la columna no existe
    (cachés antiguas), cae a `close`. La beta, en cambio, usa `close` (ajustado).
    """
    asof = pd.Timestamp(asof)
    col = field if field in prices_df.columns else "close"
    sub = prices_df[(prices_df["ticker"] == ticker.upper()) & (prices_df["date"] <= asof)]
    if sub.empty:
        return np.nan
    return float(sub.sort_values("date")[col].iloc[-1])


def risk_free_asof(rf_df: pd.DataFrame, asof: str | pd.Timestamp) -> float:
    """Tipo libre de riesgo a fecha ≤ asof (la serie ^IRX viene en %, se divide entre 100)."""
    asof = pd.Timestamp(asof)
    sub = rf_df[rf_df["date"] <= asof]
    if sub.empty:
        return np.nan
    return float(sub.sort_values("date")["close"].iloc[-1]) / 100.0


def _periodic_returns(
    prices_df: pd.DataFrame,
    ticker: str,
    start: pd.Timestamp,
    asof: pd.Timestamp,
    freq: str,
) -> pd.Series:
    """Rentabilidades de la frecuencia dada en (start, asof] para un ticker."""
    sub = prices_df[
        (prices_df["ticker"] == ticker.upper())
        & (prices_df["date"] > start)
        & (prices_df["date"] <= asof)
    ]
    if sub.empty:
        return pd.Series(dtype="float64")
    closes = sub.sort_values("date").set_index("date")["close"].resample(freq).last()
    return closes.pct_change(fill_method=None).dropna()


def beta(
    prices_df: pd.DataFrame,
    index_df: pd.DataFrame,
    ticker: str,
    asof: str | pd.Timestamp,
) -> float:
    """Beta = cov(rent. acción, rent. índice) / var(índice) en la ventana hasta asof.

    Usa precios ya cacheados (sin look-ahead). Con menos de `_BETA_MIN_PERIODS`
    observaciones o varianza nula, devuelve `valuation.dcf.default_beta`.
    """
    asof = pd.Timestamp(asof)
    window = get_config("valuation.dcf.beta_window_years", 2)
    freq = get_config("valuation.dcf.beta_return_frequency", "W")
    default = get_config("valuation.dcf.default_beta", 1.0)
    index_ticker = get_config("prices.index_ticker")
    start = asof - pd.DateOffset(years=window)

    r_stock = _periodic_returns(prices_df, ticker, start, asof, freq)
    r_index = _periodic_returns(index_df, index_ticker, start, asof, freq)
    joined = pd.concat([r_stock, r_index], axis=1, keys=["stock", "index"]).dropna()
    if len(joined) < _BETA_MIN_PERIODS:
        return float(default)

    var_index = joined["index"].var()
    if pd.isna(var_index) or var_index == 0:
        return float(default)
    cov = joined["stock"].cov(joined["index"])
    return float(cov / var_index)


# ---------------------------------------------------------------------------
# Coste de capital (CAPM + WACC)
# ---------------------------------------------------------------------------
def cost_of_equity(rf: float, beta_value: float, erp: float, size_premium: float) -> float:
    """CAPM: rf + beta·prima de riesgo de mercado + prima de tamaño."""
    return rf + beta_value * erp + size_premium


def effective_tax_rate(metrics: pd.DataFrame) -> float:
    """Tipo impositivo efectivo = impuestos / beneficio antes de impuestos.

    Si no se puede derivar (datos ausentes, pérdidas, valor atípico), usa el tipo de
    `valuation.dcf.tax_rate`.
    """
    fallback = get_config("valuation.dcf.tax_rate", 0.21)
    if metrics is None or metrics.empty:
        return fallback
    net_income = metrics["net_income"].iloc[-1]
    tax = metrics["income_tax"].iloc[-1]
    if pd.isna(net_income) or pd.isna(tax):
        return fallback
    pretax = net_income + tax
    if pretax <= 0:
        return fallback
    rate = tax / pretax
    return float(rate) if 0.0 <= rate <= 0.6 else fallback


def cost_of_debt(metrics: pd.DataFrame, rf: float) -> float:
    """Coste de deuda efectivo = gastos financieros / deuda total.

    Fallback: rf + `valuation.dcf.cost_of_debt_spread` cuando no se puede calcular.
    """
    spread = get_config("valuation.dcf.cost_of_debt_spread", 0.02)
    if metrics is None or metrics.empty:
        return rf + spread
    interest = metrics["interest_expense"].iloc[-1]
    debt = metrics["total_debt"].iloc[-1]
    if pd.isna(interest) or pd.isna(debt) or debt <= 0:
        return rf + spread
    rd = interest / debt
    return float(rd) if 0.0 < rd <= 0.5 else rf + spread


def wacc(market_cap: float, total_debt: float, re: float, rd: float, tax: float) -> float:
    """WACC = E/V·Re + D/V·Rd·(1−t). Si no hay deuda/valor, devuelve Re."""
    equity = market_cap if (pd.notna(market_cap) and market_cap > 0) else 0.0
    debt = total_debt if (pd.notna(total_debt) and total_debt > 0) else 0.0
    total = equity + debt
    if total <= 0:
        return re
    return (equity / total) * re + (debt / total) * rd * (1.0 - tax)


# ---------------------------------------------------------------------------
# DCF
# ---------------------------------------------------------------------------
def fcff_base(metrics: pd.DataFrame, tax: float) -> float:
    """FCFF base = media de los últimos N años de EBIT·(1−t) + D&A − capex (sin ΔWC)."""
    n = get_config("valuation.dcf.fcff_normalization_years", 3)
    recent = metrics.tail(n)
    fcff = recent["ebit"] * (1.0 - tax) + recent["dep_amort"] - recent["capex"]
    value = fcff.mean()
    return float(value) if pd.notna(value) else np.nan


def revenue_cagr(metrics: pd.DataFrame) -> float:
    """CAGR histórico de ingresos, acotado a [terminal_growth_rate, growth_cap]."""
    g_terminal = get_config("valuation.dcf.terminal_growth_rate", 0.025)
    cap = get_config("valuation.dcf.growth_cap", 0.10)
    revenue = metrics["revenue"].dropna()
    if len(revenue) < 2:
        return g_terminal
    first, last = revenue.iloc[0], revenue.iloc[-1]
    if first <= 0 or last <= 0:
        return g_terminal
    cagr = (last / first) ** (1.0 / (len(revenue) - 1)) - 1.0
    return float(min(max(cagr, g_terminal), cap))


def dcf_enterprise_value(
    fcff0: float,
    g_initial: float,
    g_terminal: float,
    wacc_value: float,
    years: int,
) -> float:
    """Valor de empresa por DCF en dos fases (crecimiento que decae al terminal).

    El crecimiento pasa linealmente de `g_initial` (año 1) a `g_terminal` (año N). El
    valor terminal es de Gordon. Requiere `wacc_value > g_terminal` y `fcff0 > 0`.
    """
    if pd.isna(fcff0) or pd.isna(wacc_value) or fcff0 <= 0 or wacc_value <= g_terminal:
        return np.nan

    ev = 0.0
    fcff = fcff0
    for t in range(1, years + 1):
        g_t = (
            g_initial + (g_terminal - g_initial) * (t - 1) / (years - 1)
            if years > 1
            else g_terminal
        )
        fcff = fcff * (1.0 + g_t)
        ev += fcff / (1.0 + wacc_value) ** t

    terminal = fcff * (1.0 + g_terminal) / (wacc_value - g_terminal)
    ev += terminal / (1.0 + wacc_value) ** years
    return float(ev)


def dcf_value_per_share(
    metrics: pd.DataFrame,
    wacc_value: float,
    g_initial: float,
    tax: float,
    g_terminal: float | None = None,
) -> float:
    """Valor DCF por acción = (valor de empresa − deuda neta) / acciones."""
    if g_terminal is None:
        g_terminal = get_config("valuation.dcf.terminal_growth_rate", 0.025)
    years = get_config("valuation.dcf.projection_years", 10)

    ev = dcf_enterprise_value(fcff_base(metrics, tax), g_initial, g_terminal, wacc_value, years)
    if pd.isna(ev):
        return np.nan
    net_debt = metrics["net_debt"].iloc[-1]
    shares = metrics["shares"].iloc[-1]
    if pd.isna(shares) or shares <= 0:
        return np.nan
    equity_value = ev - (net_debt if pd.notna(net_debt) else 0.0)
    return float(equity_value / shares)


def dcf_sensitivity(
    metrics: pd.DataFrame,
    wacc_base: float,
    g_initial: float,
    tax: float,
) -> dict:
    """Sensibilidad del DCF: rejilla variando WACC y tasa terminal. Devuelve base/low/high."""
    wacc_range = get_config("valuation.dcf.wacc_sensitivity_range", 0.02)
    g_range = get_config("valuation.dcf.terminal_growth_sensitivity_range", 0.01)
    g_terminal = get_config("valuation.dcf.terminal_growth_rate", 0.025)

    base = dcf_value_per_share(metrics, wacc_base, g_initial, tax, g_terminal)
    values = []
    for w in (wacc_base - wacc_range, wacc_base, wacc_base + wacc_range):
        for g in (g_terminal - g_range, g_terminal, g_terminal + g_range):
            v = dcf_value_per_share(metrics, w, g_initial, tax, g)
            if pd.notna(v):
                values.append(v)
    if not values:
        return {"base": base, "low": np.nan, "high": np.nan}
    return {"base": base, "low": float(min(values)), "high": float(max(values))}


# ---------------------------------------------------------------------------
# Graham Number
# ---------------------------------------------------------------------------
def graham_number(metrics: pd.DataFrame) -> float:
    """Número de Graham = sqrt(mult · BPA · valor contable por acción). NaN si BPA o VCpA ≤ 0."""
    multiplier = get_config("valuation.graham_multiplier", 22.5)
    if metrics is None or metrics.empty:
        return np.nan
    net_income = metrics["net_income"].iloc[-1]
    equity = metrics["equity"].iloc[-1]
    shares = metrics["shares"].iloc[-1]
    if pd.isna(net_income) or pd.isna(equity) or pd.isna(shares) or shares <= 0:
        return np.nan
    eps = net_income / shares
    bvps = equity / shares
    if eps <= 0 or bvps <= 0:
        return np.nan
    return float(np.sqrt(multiplier * eps * bvps))


# ---------------------------------------------------------------------------
# Múltiplos relativos al sector
# ---------------------------------------------------------------------------
def _market_snapshot(
    fundamentals: pd.DataFrame,
    prices_df: pd.DataFrame,
    ticker: str,
    asof: str | pd.Timestamp,
) -> dict | None:
    """Foto a fecha D: market cap, EV y magnitudes del último año. None si falta lo esencial."""
    metrics = annual_metrics(fundamentals, ticker, asof)
    if metrics.empty:
        return None
    last = metrics.iloc[-1]
    price = price_asof(prices_df, ticker, asof)
    shares = last["shares"]
    if pd.isna(price) or pd.isna(shares) or shares <= 0:
        return None
    market_cap = price * shares
    net_debt = last["net_debt"] if pd.notna(last["net_debt"]) else 0.0
    return {
        "market_cap": market_cap,
        "ev": market_cap + net_debt,
        "net_debt": net_debt,
        "shares": shares,
        "net_income": last["net_income"],
        "ebit": last["ebit"],
        "ebitda": last["ebitda"],
        "fcf": last["fcf"],
    }


def multiples_value(
    fundamentals: pd.DataFrame,
    sectors_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    ticker: str,
    peers: list[str],
    asof: str | pd.Timestamp,
) -> dict:
    """Valor por acción implícito en la mediana sectorial de PER, EV/EBIT, EV/EBITDA, P/FCF.

    Para cada par del sector calcula los múltiplos con denominador positivo, toma la
    mediana (percentil `valuation.multiples.sector_percentile`) y la aplica al objetivo.
    Combina los cuatro valores implícitos por acción con la media.
    """
    quantile = get_config("valuation.multiples.sector_percentile", 50) / 100.0

    pe, ev_ebit, ev_ebitda, p_fcf = [], [], [], []
    for peer in peers:
        snap = _market_snapshot(fundamentals, prices_df, peer, asof)
        if snap is None:
            continue
        if pd.notna(snap["net_income"]) and snap["net_income"] > 0:
            pe.append(snap["market_cap"] / snap["net_income"])
        if pd.notna(snap["ebit"]) and snap["ebit"] > 0:
            ev_ebit.append(snap["ev"] / snap["ebit"])
        if pd.notna(snap["ebitda"]) and snap["ebitda"] > 0:
            ev_ebitda.append(snap["ev"] / snap["ebitda"])
        if pd.notna(snap["fcf"]) and snap["fcf"] > 0:
            p_fcf.append(snap["market_cap"] / snap["fcf"])

    def median(xs: list[float]) -> float:
        return float(np.quantile(xs, quantile)) if xs else np.nan

    m_pe, m_ev_ebit, m_ev_ebitda, m_p_fcf = (
        median(pe),
        median(ev_ebit),
        median(ev_ebitda),
        median(p_fcf),
    )

    target = _market_snapshot(fundamentals, prices_df, ticker, asof)
    result = {
        "multiples_value": np.nan,
        "pe": m_pe,
        "ev_ebit": m_ev_ebit,
        "ev_ebitda": m_ev_ebitda,
        "p_fcf": m_p_fcf,
    }
    if target is None:
        return result

    shares, net_debt = target["shares"], target["net_debt"]
    implied = []
    if pd.notna(m_pe) and pd.notna(target["net_income"]) and target["net_income"] > 0:
        implied.append(m_pe * target["net_income"] / shares)
    if pd.notna(m_ev_ebit) and pd.notna(target["ebit"]) and target["ebit"] > 0:
        implied.append((m_ev_ebit * target["ebit"] - net_debt) / shares)
    if pd.notna(m_ev_ebitda) and pd.notna(target["ebitda"]) and target["ebitda"] > 0:
        implied.append((m_ev_ebitda * target["ebitda"] - net_debt) / shares)
    if pd.notna(m_p_fcf) and pd.notna(target["fcf"]) and target["fcf"] > 0:
        implied.append(m_p_fcf * target["fcf"] / shares)

    if implied:
        result["multiples_value"] = float(np.mean(implied))
    return result


# ---------------------------------------------------------------------------
# Integración del rango de valor
# ---------------------------------------------------------------------------
def _weighted_central(values: dict[str, float], weights: dict[str, float]) -> float:
    """Media ponderada renormalizando sobre los componentes no NaN."""
    num, den = 0.0, 0.0
    for key, weight in weights.items():
        val = values.get(key, np.nan)
        if pd.notna(val):
            num += val * weight
            den += weight
    return num / den if den > 0 else np.nan


def intrinsic_value(
    fundamentals: pd.DataFrame,
    sectors_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    index_df: pd.DataFrame,
    rf_df: pd.DataFrame,
    ticker: str,
    peers: list[str],
    asof: str | pd.Timestamp,
) -> dict:
    """Estima el valor intrínseco por acción integrando DCF, múltiplos y Graham.

    Returns:
        dict con dcf, dcf_low/high, multiples, graham, wacc, beta, price y el rango
        integrado value_central/value_low/value_high. Todo NaN si no hay datos.
    """
    nan_result = {
        k: np.nan
        for k in (
            "dcf",
            "dcf_low",
            "dcf_high",
            "multiples",
            "graham",
            "wacc",
            "beta",
            "price",
            "value_central",
            "value_low",
            "value_high",
        )
    }
    metrics = annual_metrics(fundamentals, ticker, asof)
    if metrics.empty:
        return nan_result

    last = metrics.iloc[-1]
    price = price_asof(prices_df, ticker, asof)
    shares = last["shares"]
    market_cap = price * shares if (pd.notna(price) and pd.notna(shares) and shares > 0) else np.nan

    # Coste de capital
    rf = risk_free_asof(rf_df, asof)
    beta_value = beta(prices_df, index_df, ticker, asof)
    erp = get_config("valuation.dcf.equity_risk_premium", 0.055)
    size_premium = get_config("valuation.dcf.size_premium", 0.01)
    re = cost_of_equity(rf, beta_value, erp, size_premium)
    tax = effective_tax_rate(metrics)
    rd = cost_of_debt(metrics, rf)
    wacc_value = wacc(market_cap, last["total_debt"], re, rd, tax)

    # DCF y sensibilidad
    g_initial = revenue_cagr(metrics)
    sensitivity = dcf_sensitivity(metrics, wacc_value, g_initial, tax)
    dcf = sensitivity["base"]

    # Graham y múltiplos
    graham = graham_number(metrics)
    multiples = multiples_value(fundamentals, sectors_df, prices_df, ticker, peers, asof)[
        "multiples_value"
    ]

    weights = {
        "dcf": get_config("valuation.integration.dcf_weight", 0.60),
        "multiples": get_config("valuation.integration.multiples_weight", 0.30),
        "graham": get_config("valuation.integration.graham_weight", 0.10),
    }
    central = _weighted_central({"dcf": dcf, "multiples": multiples, "graham": graham}, weights)

    # El rango integrado bracketea los modelos disponibles (banda de sensibilidad del
    # DCF + múltiplos + Graham), de modo que value_central siempre cae dentro de él.
    bounds = [
        v for v in (sensitivity["low"], sensitivity["high"], multiples, graham) if pd.notna(v)
    ]
    value_low = float(min(bounds)) if bounds else np.nan
    value_high = float(max(bounds)) if bounds else np.nan

    return {
        "dcf": dcf,
        "dcf_low": sensitivity["low"],
        "dcf_high": sensitivity["high"],
        "multiples": multiples,
        "graham": graham,
        "wacc": wacc_value,
        "beta": beta_value,
        "price": price,
        "value_central": central,
        "value_low": value_low,
        "value_high": value_high,
    }
