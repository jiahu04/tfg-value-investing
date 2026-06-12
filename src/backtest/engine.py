"""
engine.py — Motor de backtesting (paso 2.1).

Simula la estrategia value en el pasado, día a día, sin información futura. Reutiliza
el pipeline de selección (1.6) a través de una función de selección **inyectable**
(`select_fn(asof) → tabla de candidatos`), lo que permite probar el bucle de forma
aislada con candidatos controlados.

Modelo (D-008…D-013, D-024):
  - Calendario diario de mercado (fechas del índice).
  - Revisión ANUAL (mes configurable): recalcula la selección, rebalancea a
    equiponderación (altas y bajas por deterioro).
  - Vigilancia SEMANAL: venta por convergencia (el precio alcanza el valor); la caja
    liberada se redespliega en la siguiente candidata elegible.
  - Liquidez remunerada al tipo a corto cuando hay pocas oportunidades.
  - Costes de transacción configurables; rentabilidad total (precios ajustados + índice TR).

Salidas: serie de valor de la cartera y del índice, registro de operaciones y composición.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from src.utils.config_loader import get_config


# ---------------------------------------------------------------------------
# Estado de la cartera (caja, posiciones y registro de operaciones)
# ---------------------------------------------------------------------------
class _Portfolio:
    """Cartera simulada: caja, posiciones (ticker→acciones) y traza de operaciones."""

    def __init__(self, cash: float, transaction_cost: float):
        self.cash = cash
        self.tc = transaction_cost
        self.positions: dict[str, float] = {}
        self.ref_value: dict[str, float] = {}  # valor intrínseco de referencia por posición
        self.trades: list[dict] = []

    def invested_value(self, price_of: Callable[[str], float]) -> float:
        return sum(sh * price_of(t) for t, sh in self.positions.items())

    def total_value(self, price_of: Callable[[str], float]) -> float:
        return self.cash + self.invested_value(price_of)

    def _record(self, date, ticker, action, shares, price, reason):
        notional = shares * price
        self.trades.append(
            {
                "date": date,
                "ticker": ticker,
                "action": action,
                "shares": shares,
                "price": price,
                "notional": notional,
                "cost": notional * self.tc,
                "reason": reason,
            }
        )

    def buy_value(self, date, ticker, target_value, price, reason):
        """Compra por importe objetivo (acotado por la caja disponible tras costes)."""
        if pd.isna(price) or price <= 0 or target_value <= 0:
            return
        affordable = self.cash / (1.0 + self.tc)
        buy_value = min(target_value, affordable)
        if buy_value <= 0:
            return
        shares = buy_value / price
        notional = shares * price
        self.cash -= notional * (1.0 + self.tc)
        self.positions[ticker] = self.positions.get(ticker, 0.0) + shares
        self._record(date, ticker, "buy", shares, price, reason)

    def sell_shares(self, date, ticker, shares, price, reason):
        """Vende un número de acciones (acotado a lo que se tiene)."""
        shares = min(shares, self.positions.get(ticker, 0.0))
        if shares <= 0 or pd.isna(price) or price <= 0:
            return
        notional = shares * price
        self.cash += notional * (1.0 - self.tc)
        self.positions[ticker] -= shares
        if self.positions[ticker] <= 1e-9:
            self.positions.pop(ticker, None)
            self.ref_value.pop(ticker, None)
        self._record(date, ticker, "sell", shares, price, reason)

    def sell_all(self, date, ticker, price, reason):
        self.sell_shares(date, ticker, self.positions.get(ticker, 0.0), price, reason)

    def adjust_to(self, date, ticker, target_value, price, reason):
        """Compra o vende hasta que la posición valga `target_value`."""
        if pd.isna(price) or price <= 0:
            return
        current = self.positions.get(ticker, 0.0) * price
        delta = target_value - current
        if delta > 0:
            self.buy_value(date, ticker, delta, price, reason)
        elif delta < 0:
            self.sell_shares(date, ticker, (-delta) / price, price, reason)


# ---------------------------------------------------------------------------
# Calendario y series de mercado
# ---------------------------------------------------------------------------
def _wide_prices(
    prices_df: pd.DataFrame, master: pd.DatetimeIndex, field: str = "close"
) -> pd.DataFrame:
    """Panel ancho (fecha × ticker) de cierres, alineado al calendario y *forward-filled*.

    `field` elige la columna de precio: "close" (ajustado, para operaciones y valor de
    la cartera) o "close_unadj" (sin ajustar, para comparar con el valor intrínseco).
    Si la columna pedida no existe, cae a "close".
    """
    if prices_df.empty:
        return pd.DataFrame(index=master)
    col = field if field in prices_df.columns else "close"
    wide = prices_df.pivot_table(index="date", columns="ticker", values=col).sort_index()
    return wide.reindex(wide.index.union(master)).ffill().reindex(master)


def _aligned_series(df: pd.DataFrame, master: pd.DatetimeIndex, scale: float = 1.0) -> pd.Series:
    """Serie de cierre (un único ticker) alineada al calendario y *forward-filled*."""
    if df.empty:
        return pd.Series(index=master, dtype="float64")
    series = df.set_index("date")["close"].sort_index()
    return series.reindex(series.index.union(master)).ffill().reindex(master) * scale


def _decision_dates(master: pd.DatetimeIndex, review_month: int) -> tuple[set, set]:
    """Devuelve (fechas de revisión anual, fechas de vigilancia semanal)."""
    review_dates = {master[0]} if len(master) else set()
    reviewed_years: set[int] = set()
    for d in master:
        if d.month >= review_month and d.year not in reviewed_years:
            review_dates.add(d)
            reviewed_years.add(d.year)

    weekly_dates: set = set()
    seen_weeks: set = set()
    for d in master:
        week = (d.isocalendar().year, d.isocalendar().week)
        if week not in seen_weeks:
            seen_weeks.add(week)
            weekly_dates.add(d)
    return review_dates, weekly_dates


# ---------------------------------------------------------------------------
# Motor
# ---------------------------------------------------------------------------
def run_backtest(
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    *,
    prices_df: pd.DataFrame,
    index_df: pd.DataFrame,
    rf_df: pd.DataFrame,
    select_fn: Callable[[pd.Timestamp], pd.DataFrame],
) -> dict:
    """Ejecuta el backtest entre start y end.

    Args:
        start, end: ventana de la simulación.
        prices_df, index_df, rf_df: precios de acciones, índice y tipo libre (date/ticker/close).
        select_fn: función de selección a una fecha (p. ej. `run_pipeline`), que devuelve la
            tabla de candidatos con columnas ticker, selected, passed, priority, value_central,
            quality_score.

    Returns:
        dict con equity_curve, trades y holdings (DataFrames).
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    initial_capital = get_config("backtest.initial_capital", 100000.0)
    review_month = get_config("backtest.review_month", 6)
    sell_threshold = get_config("backtest.sell_threshold_margin", 0.05)
    transaction_cost = get_config("backtest.transaction_cost_pct", 0.001)
    cash_yield = get_config("backtest.cash_yield", "risk_free")
    max_positions = get_config("portfolio.max_positions", 15)
    min_margin = get_config("portfolio.min_margin_of_safety", 0.30)
    min_quality = get_config("quality.min_quality_score", 0.50)

    # Calendario maestro (días de mercado del índice dentro de la ventana)
    idx_dates = (
        pd.DatetimeIndex(sorted(index_df["date"].unique()))
        if not index_df.empty
        else pd.DatetimeIndex([])
    )
    master = idx_dates[(idx_dates >= start) & (idx_dates <= end)]
    if len(master) == 0:
        empty = pd.DataFrame()
        return {"equity_curve": empty, "trades": empty, "holdings": empty}

    wide = _wide_prices(prices_df, master)  # ajustado: operaciones y valor de la cartera
    wide_unadj = _wide_prices(prices_df, master, field="close_unadj")  # real: valor↔precio
    index_series = _aligned_series(index_df, master)
    rf_series = _aligned_series(rf_df, master, scale=1.0 / 100.0)

    review_dates, weekly_dates = _decision_dates(master, review_month)

    pf = _Portfolio(initial_capital, transaction_cost)
    last_selection: pd.DataFrame | None = None
    holdings_rows: list[dict] = []
    curve_rows: list[dict] = []

    def price_of(ticker: str) -> float:
        """Precio ajustado vigente (operaciones y valor de la cartera)."""
        if ticker in wide.columns:
            value = wide.at[current_date, ticker]
            return float(value) if pd.notna(value) else float("nan")
        return float("nan")

    def price_unadj_of(ticker: str) -> float:
        """Precio sin ajustar vigente (para comparar con el valor intrínseco)."""
        if ticker in wide_unadj.columns:
            value = wide_unadj.at[current_date, ticker]
            return float(value) if pd.notna(value) else float("nan")
        return price_of(ticker)

    index_base = index_series.iloc[0] if pd.notna(index_series.iloc[0]) else None
    prev_date: pd.Timestamp | None = None

    for current_date in master:
        # 1) Remuneración de la liquidez entre fechas
        if prev_date is not None and cash_yield == "risk_free" and pf.cash > 0:
            rf = rf_series.get(current_date)
            if pd.notna(rf):
                days = (current_date - prev_date).days
                pf.cash *= (1.0 + rf) ** (days / 365.0)

        # 2) Decisiones
        if current_date in review_dates:
            last_selection = _annual_review(pf, current_date, select_fn, price_of)
            _snapshot_holdings(holdings_rows, pf, current_date, price_of)
        elif current_date in weekly_dates:
            _weekly_monitor(
                pf,
                current_date,
                last_selection,
                price_of,
                price_unadj_of,
                sell_threshold,
                max_positions,
                min_margin,
                min_quality,
            )
            _snapshot_holdings(holdings_rows, pf, current_date, price_of)

        # 3) Registro diario
        invested = pf.invested_value(price_of)
        index_value = (
            initial_capital * index_series.get(current_date) / index_base
            if index_base
            else float("nan")
        )
        curve_rows.append(
            {
                "date": current_date,
                "portfolio_value": pf.cash + invested,
                "index_value": index_value,
                "cash": pf.cash,
                "invested": invested,
                "n_positions": len(pf.positions),
            }
        )
        prev_date = current_date

    return {
        "equity_curve": pd.DataFrame(curve_rows),
        "trades": pd.DataFrame(
            pf.trades,
            columns=["date", "ticker", "action", "shares", "price", "notional", "cost", "reason"],
        ),
        "holdings": pd.DataFrame(holdings_rows, columns=["date", "ticker", "shares", "weight"]),
    }


def _annual_review(pf, date, select_fn, price_of) -> pd.DataFrame:
    """Recalcula la selección y rebalancea a equiponderación del conjunto seleccionado."""
    candidates = select_fn(date)
    if candidates is None or candidates.empty or "selected" not in candidates.columns:
        target = candidates.iloc[0:0] if candidates is not None else pd.DataFrame()
    else:
        target = candidates[candidates["selected"].astype(bool)]
    target_tickers = list(target["ticker"]) if "ticker" in target.columns else []

    # Bajas por deterioro: vender lo que ya no está en el objetivo
    for ticker in list(pf.positions):
        if ticker not in target_tickers:
            pf.sell_all(date, ticker, price_of(ticker), "review_baja")

    # Equiponderar el objetivo
    n = len(target_tickers)
    if n > 0:
        equity = pf.total_value(price_of)
        slot = equity / n
        value_by_ticker = dict(zip(target["ticker"], target["value_central"], strict=False))
        for ticker in target_tickers:
            pf.adjust_to(date, ticker, slot, price_of(ticker), "review_rebalanceo")
            if ticker in pf.positions:
                pf.ref_value[ticker] = value_by_ticker.get(ticker, float("nan"))
    return candidates


def _weekly_monitor(
    pf,
    date,
    last_selection,
    price_of,
    price_unadj_of,
    sell_threshold,
    max_positions,
    min_margin,
    min_quality,
):
    """Ventas por convergencia y redespliegue de la caja liberada.

    La decisión (¿sigue barata respecto al valor intrínseco?) compara el valor con el
    precio **sin ajustar** (misma base); la **ejecución** usa el precio ajustado.
    """
    # Ventas por convergencia: el precio ha alcanzado el valor de referencia
    for ticker in list(pf.positions):
        price_cmp = price_unadj_of(ticker)
        ref = pf.ref_value.get(ticker, float("nan"))
        if pd.notna(ref) and ref > 0 and pd.notna(price_cmp):
            margin = (ref - price_cmp) / ref
            if margin < sell_threshold:
                pf.sell_all(date, ticker, price_of(ticker), "convergencia")

    # Redespliegue: recomprar las siguientes candidatas elegibles al precio actual
    if last_selection is None or last_selection.empty:
        return
    ordered = last_selection.sort_values("priority", ascending=False, na_position="last")
    for row in ordered.itertuples(index=False):
        equity = pf.total_value(price_of)
        slot = equity / max_positions
        if pf.cash < slot:
            break
        ticker = row.ticker
        if ticker in pf.positions or not bool(row.passed):
            continue
        value = row.value_central
        if pd.isna(value) or value <= 0:
            continue
        if pd.isna(row.quality_score) or row.quality_score < min_quality:
            continue
        price_exec = price_of(ticker)
        price_cmp = price_unadj_of(ticker)
        if pd.isna(price_exec) or price_exec <= 0 or pd.isna(price_cmp):
            continue
        if (value - price_cmp) / value < min_margin:  # ya no cumple el margen al precio actual
            continue
        pf.buy_value(date, ticker, slot, price_exec, "redespliegue")
        if ticker in pf.positions:
            pf.ref_value[ticker] = value


def _snapshot_holdings(holdings_rows, pf, date, price_of):
    """Registra la composición de la cartera en una fecha de decisión."""
    total = pf.total_value(price_of)
    for ticker, shares in pf.positions.items():
        value = shares * price_of(ticker)
        holdings_rows.append(
            {
                "date": date,
                "ticker": ticker,
                "shares": shares,
                "weight": value / total if total > 0 else float("nan"),
            }
        )
