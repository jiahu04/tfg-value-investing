"""Tests de la mecánica del motor de backtesting (paso 2.1).

Usan una función de selección **falsa** (candidatos controlados) para probar el bucle
de forma aislada del pipeline: compra en la revisión, venta por convergencia,
redespliegue, liquidez remunerada y costes.
"""

import pandas as pd
import pytest

from src.backtest.engine import run_backtest

_SEL_COLS = ["ticker", "selected", "passed", "priority", "value_central", "quality_score"]


def _index(dates) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "ticker": "^SP500TR", "close": [1000.0] * len(dates)})


def _rf(dates, rate_pct=0.0) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "ticker": "^IRX", "close": [rate_pct] * len(dates)})


def test_liquidity_earns_risk_free_when_no_positions():
    dates = pd.date_range("2018-06-04", periods=10, freq="7D")
    # Sin candidatos -> nunca hay posiciones -> la cartera crece al tipo libre (5 %)
    result = run_backtest(
        "2018-01-01",
        "2019-01-01",
        prices_df=pd.DataFrame(columns=["date", "ticker", "close"]),
        index_df=_index(dates),
        rf_df=_rf(dates, rate_pct=5.0),
        select_fn=lambda asof: pd.DataFrame(columns=_SEL_COLS),
    )
    curve = result["equity_curve"]
    assert (curve["n_positions"] == 0).all()
    assert curve["portfolio_value"].iloc[-1] > curve["portfolio_value"].iloc[0]  # creció con el rf


def _convergence_scenario():
    dates = pd.date_range("2018-06-04", periods=20, freq="7D")
    # X: barata (50) las 10 primeras semanas, luego converge al valor (98); Y: barata constante (60)
    x_prices = [50.0] * 10 + [98.0] * 10
    rows = []
    for i, d in enumerate(dates):
        rows.append({"date": d, "ticker": "X", "close": x_prices[i]})
        rows.append({"date": d, "ticker": "Y", "close": 60.0})
    prices = pd.DataFrame(rows)

    def select_fn(asof):
        return pd.DataFrame(
            [
                # X seleccionada (entra en cartera); Y elegible pero no seleccionada (para redespliegue)
                ["X", True, True, 1.0, 100.0, 0.9],
                ["Y", False, True, 0.9, 100.0, 0.9],
            ],
            columns=_SEL_COLS,
        )

    return dates, prices, select_fn


def test_buy_convergence_sell_and_redeploy():
    dates, prices, select_fn = _convergence_scenario()
    result = run_backtest(
        "2018-01-01",
        "2019-12-31",
        prices_df=prices,
        index_df=_index(dates),
        rf_df=_rf(dates),
        select_fn=select_fn,
    )
    trades = result["trades"]

    def has(action, ticker, reason):
        return not trades[
            (trades["action"] == action)
            & (trades["ticker"] == ticker)
            & (trades["reason"] == reason)
        ].empty

    assert has("buy", "X", "review_rebalanceo")  # compra en la revisión
    assert has("sell", "X", "convergencia")  # venta cuando el precio alcanza el valor
    assert has("buy", "Y", "redespliegue")  # redespliegue de la caja liberada


def test_convergence_uses_unadjusted_price():
    # close (ajustado) bajo y constante; close_unadj (real) converge al valor 100.
    # La convergencia debe dispararse por el precio SIN ajustar, no por el ajustado.
    dates = pd.date_range("2018-06-04", periods=20, freq="7D")
    unadj = [50.0] * 10 + [98.0] * 10  # real: converge a 100
    rows = [
        {"date": d, "ticker": "X", "close": 10.0, "close_unadj": unadj[i]}
        for i, d in enumerate(dates)
    ]
    prices = pd.DataFrame(rows)

    def select_fn(asof):
        return pd.DataFrame([["X", True, True, 1.0, 100.0, 0.9]], columns=_SEL_COLS)

    result = run_backtest(
        "2018-01-01",
        "2019-12-31",
        prices_df=prices,
        index_df=_index(dates),
        rf_df=_rf(dates),
        select_fn=select_fn,
    )
    sell = result["trades"]
    sell = sell[(sell["action"] == "sell") & (sell["reason"] == "convergencia")]
    assert not sell.empty  # vendió por convergencia (solo posible mirando close_unadj)
    # La ejecución usa el precio ajustado (~10), no el real (~98)
    assert sell.iloc[0]["price"] == pytest.approx(10.0)


def test_transaction_cost_applied():
    dates, prices, select_fn = _convergence_scenario()
    result = run_backtest(
        "2018-01-01",
        "2019-12-31",
        prices_df=prices,
        index_df=_index(dates),
        rf_df=_rf(dates),
        select_fn=select_fn,
    )
    trades = result["trades"]
    first_buy = trades[trades["action"] == "buy"].iloc[0]
    # coste = nocional * 0,1 %
    assert first_buy["cost"] == pytest.approx(first_buy["notional"] * 0.001)


def test_index_series_normalized_to_initial_capital():
    dates = pd.date_range("2018-06-04", periods=6, freq="7D")
    result = run_backtest(
        "2018-01-01",
        "2019-01-01",
        prices_df=pd.DataFrame(columns=["date", "ticker", "close"]),
        index_df=_index(dates),
        rf_df=_rf(dates),
        select_fn=lambda asof: pd.DataFrame(columns=_SEL_COLS),
    )
    curve = result["equity_curve"]
    # El índice (constante en este test) arranca en el capital inicial
    assert curve["index_value"].iloc[0] == 100000.0
