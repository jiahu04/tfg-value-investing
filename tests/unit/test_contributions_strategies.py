"""Tests de las estrategias de aportación (paso 2.3), con valores de referencia conocidos."""

import numpy as np
import pandas as pd
import pytest

from src.contributions import strategies

# Config de aportación de referencia para los tests (señal = amplitud de oportunidades).
_CFG = {
    "periodic_amount": 1000.0,
    "conditional_dca": {
        "base": 0.25,
        "suspend_below": 0.10,
        "max_scale_factor": 2.0,
    },
    "concentrated": {"min": 0.35, "multiplier": 3.0},
    "value_averaging": {"target_step": 1000.0, "growth": 0.0, "allow_selling": False},
    "drawdown_based": {"ref_drawdown": 0.10, "max_scale_factor": 3.0},
}

_ALL_LABELS = [
    "DCA fijo",
    "DCA condicional",
    "Concentrada",
    "Value averaging",
    "Drawdown-based",
]


# --- TIR / MWR (verificación principal del paso) ---------------------------------
def test_mwr_single_cashflow_ten_percent():
    # -1000 hoy, +1100 dentro de un año => TIR ~ 10 %
    cf = [(pd.Timestamp("2021-01-01"), -1000.0)]
    mwr = strategies.money_weighted_return(cf, 1100.0, pd.Timestamp("2022-01-01"))
    assert mwr == pytest.approx(0.10, abs=2e-3)


def test_mwr_two_contributions_known_value():
    # Dos aportaciones de 1000 (año 0 y año 1), valor final 2200 en el año 2.
    cf = [
        (pd.Timestamp("2020-01-01"), -1000.0),
        (pd.Timestamp("2021-01-01"), -1000.0),
    ]
    mwr = strategies.money_weighted_return(cf, 2200.0, pd.Timestamp("2022-01-01"))
    # VAN: -1000 - 1000/(1+r) + 2200/(1+r)^2 = 0 => x^2 + x - 2.2 = 0, x=1+r => r ~ 0.0652
    assert mwr == pytest.approx(0.0652, abs=3e-3)


def test_mwr_returns_nan_without_cashflows():
    assert np.isnan(strategies.money_weighted_return([], 1000.0, pd.Timestamp("2022-01-01")))


# --- Factor de escala del DCA condicional (señal = amplitud) ----------------------
def test_scale_factor_suspends_below_threshold():
    assert (
        strategies.scale_factor_conditional(
            0.05, base=0.25, suspend_below=0.10, max_scale_factor=2.0
        )
        == 0.0
    )


def test_scale_factor_is_one_at_base():
    assert strategies.scale_factor_conditional(
        0.25, base=0.25, suspend_below=0.10, max_scale_factor=2.0
    ) == pytest.approx(1.0)


def test_scale_factor_capped_at_max():
    assert strategies.scale_factor_conditional(
        0.90, base=0.25, suspend_below=0.10, max_scale_factor=2.0
    ) == pytest.approx(2.0)  # 0.90/0.25 = 3.6 -> tope 2.0


def test_scale_factor_monotonic_and_nan():
    f = strategies.scale_factor_conditional
    low = f(0.20, base=0.25, suspend_below=0.10, max_scale_factor=2.0)
    high = f(0.40, base=0.25, suspend_below=0.10, max_scale_factor=2.0)
    assert low < high
    assert f(np.nan, base=0.25, suspend_below=0.10, max_scale_factor=2.0) == 0.0


# --- Importe por estrategia ------------------------------------------------------
def test_amount_dca_fijo_is_constant():
    assert strategies.contribution_amount("dca_fijo", 0.01, 1000.0, _CFG) == 1000.0
    assert strategies.contribution_amount("dca_fijo", np.nan, 1000.0, _CFG) == 1000.0


def test_amount_conditional_suspends_and_scales():
    amt = strategies.contribution_amount
    assert amt("dca_condicional", 0.25, 1000.0, _CFG) == pytest.approx(1000.0)  # 1× en base
    assert amt("dca_condicional", 0.05, 1000.0, _CFG) == 0.0  # suspendida (<0.10)
    assert amt("dca_condicional", np.nan, 1000.0, _CFG) == 1000.0  # sin señal -> base
    assert amt("dca_condicional", 0.60, 1000.0, _CFG) == pytest.approx(2000.0)  # 0.60/0.25 -> tope


def test_amount_concentrated_only_when_opportunities_abundant():
    amt = strategies.contribution_amount
    assert amt("concentrada", 0.50, 1000.0, _CFG) == pytest.approx(3000.0)  # >=0.35 -> dispara
    assert amt("concentrada", 0.30, 1000.0, _CFG) == 0.0  # <0.35 -> no
    assert amt("concentrada", np.nan, 1000.0, _CFG) == 0.0


def test_amount_unknown_strategy_raises():
    with pytest.raises(ValueError):
        strategies.contribution_amount("otra", 0.5, 1000.0, _CFG)


# --- Simulación ------------------------------------------------------------------
def test_simulate_constant_nav_avg_price_equals_nav():
    dates = pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"])
    nav = pd.Series(100.0, index=dates)
    signal = pd.Series(np.nan, index=dates)
    sim = strategies.simulate_strategy(
        nav, signal, dates, strategy="dca_fijo", base=1000.0, cfg=_CFG
    )
    assert sim["n_contributions"] == 3
    assert sim["invested"] == pytest.approx(3000.0)
    assert sim["avg_price"] == pytest.approx(100.0)
    assert sim["final_value"] == pytest.approx(3000.0)  # NAV plano => valor = aportado


def test_concentrated_buys_cheaper_than_dca_fijo():
    # NAV que cae; el descuento (señal) es profundo solo cuando el NAV está bajo.
    dates = pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"])
    nav = pd.Series([100.0, 80.0, 60.0, 50.0], index=dates)
    signal = pd.Series([0.10, 0.20, 0.50, 0.60], index=dates)  # supera 0.45 al final
    fijo = strategies.simulate_strategy(
        nav, signal, dates, strategy="dca_fijo", base=1000.0, cfg=_CFG
    )
    conc = strategies.simulate_strategy(
        nav, signal, dates, strategy="concentrada", base=1000.0, cfg=_CFG
    )
    assert conc["n_contributions"] < fijo["n_contributions"]
    assert conc["avg_price"] < fijo["avg_price"]


# --- Tabla comparativa -----------------------------------------------------------
def test_compare_strategies_table_shape():
    dates = pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"])
    nav = pd.Series([100.0, 110.0, 120.0], index=dates)
    signal = pd.Series([0.50, 0.50, 0.50], index=dates)
    table = strategies.compare_strategies(nav, signal, dates, cfg=_CFG)
    assert list(table.index) == _ALL_LABELS
    assert {"TIR (MWR)", "valor_final", "total_aportado", "n_aportaciones", "precio_medio"} <= set(
        table.columns
    )


def test_strategies_differentiate_with_varying_signal():
    # Regresión de C-006: con una señal que VARÍA, las tres estrategias deben dar
    # TIR y precio medio DISTINTOS (antes salían idénticas porque la señal saturaba).
    # Fechas anuales (span suficiente para que la TIR anualizada quede en rango).
    dates = pd.to_datetime(["2018-01-01", "2019-01-01", "2020-01-01", "2021-01-01"])
    nav = pd.Series([100.0, 80.0, 130.0, 150.0], index=dates)
    signal = pd.Series([0.05, 0.50, 0.20, 0.40], index=dates)  # amplitud variable
    table = strategies.compare_strategies(nav, signal, dates, cfg=_CFG)
    senal = table.loc[["DCA fijo", "DCA condicional", "Concentrada"]]
    assert senal["TIR (MWR)"].nunique() == 3
    assert senal["precio_medio"].nunique() == 3
    # El nº de aportaciones también difiere (fijo todas; concentrada solo cuando >=0.35).
    assert table.loc["DCA fijo", "n_aportaciones"] == 4
    assert table.loc["Concentrada", "n_aportaciones"] == 2  # señal >=0.35 en 2 fechas


# --- Estrategias clásicas: value averaging y drawdown-based -----------------------
def test_drawdown_scale_base_and_cap():
    f = strategies.drawdown_scale
    assert f(0.0, ref_drawdown=0.10, max_scale_factor=3.0) == pytest.approx(1.0)  # en máximos
    assert f(0.10, ref_drawdown=0.10, max_scale_factor=3.0) == pytest.approx(2.0)  # dd=ref -> 2×
    assert f(0.50, ref_drawdown=0.10, max_scale_factor=3.0) == pytest.approx(3.0)  # tope
    assert f(np.nan, ref_drawdown=0.10, max_scale_factor=3.0) == pytest.approx(1.0)


def test_nav_drawdown_is_point_in_time():
    # El drawdown en una fecha NO puede cambiar por un NAV futuro (anti-look-ahead).
    idx = pd.date_range("2020-01-01", periods=5, freq="MS")
    nav_full = pd.Series([100.0, 120.0, 90.0, 150.0, 50.0], index=idx)
    dd_full = strategies.nav_drawdown(nav_full)
    dd_prefix = strategies.nav_drawdown(nav_full.iloc[:4])
    # Los 4 primeros drawdowns son idénticos con o sin el dato futuro (el de 50).
    pd.testing.assert_series_equal(dd_full.iloc[:4], dd_prefix)
    assert dd_full.iloc[2] == pytest.approx(0.25)  # 90 desde un máximo de 120


def test_value_target_linear_and_growth():
    assert strategies.value_target(3, target_step=1000.0, growth=0.0) == pytest.approx(3000.0)
    # growth compuesto: 1000 * ((1.1^2 - 1)/0.1) = 2100
    assert strategies.value_target(2, target_step=1000.0, growth=0.1) == pytest.approx(2100.0)
    assert strategies.value_target(0, target_step=1000.0, growth=0.0) == 0.0


def test_value_averaging_amount_buy_only_vs_selling():
    f = strategies.value_averaging_amount
    assert f(3000.0, 1000.0, allow_selling=False) == pytest.approx(2000.0)  # falta -> compra
    assert f(1000.0, 1500.0, allow_selling=False) == 0.0  # exceso, solo-compra -> no vende
    assert f(1000.0, 1500.0, allow_selling=True) == pytest.approx(-500.0)  # VA puro -> vende


def test_simulate_value_averaging_follows_target():
    # NAV que baja y vuelve: VA compra más en la caída para seguir la senda objetivo.
    dates = pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"])
    nav = pd.Series([100.0, 50.0, 100.0], index=dates)
    signal = pd.Series(np.nan, index=dates)
    sim = strategies.simulate_strategy(
        nav, signal, dates, strategy="value_averaging", base=1000.0, cfg=_CFG
    )
    # t1: objetivo 1000, valor 0 -> aporta 1000 (10 uds). t2: objetivo 2000, valor 500 ->
    # aporta 1500 (30 uds). t3: objetivo 3000, valor 4000 -> exceso, solo-compra -> 0.
    assert sim["invested"] == pytest.approx(2500.0)
    assert sim["n_contributions"] == 2
    assert sim["units"] == pytest.approx(40.0)
    assert sim["final_value"] == pytest.approx(4000.0)


def test_simulate_drawdown_buys_more_in_the_dip():
    dates = pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"])
    nav = pd.Series([100.0, 80.0, 100.0], index=dates)  # drawdown del 20% en el medio
    signal = pd.Series(np.nan, index=dates)
    dd = strategies.simulate_strategy(
        nav, signal, dates, strategy="drawdown_based", base=1000.0, cfg=_CFG
    )
    fijo = strategies.simulate_strategy(
        nav, signal, dates, strategy="dca_fijo", base=1000.0, cfg=_CFG
    )
    # En la caída (dd=0.2, ref=0.1) aporta 3× la base -> más invertido y menor precio medio.
    assert dd["invested"] > fijo["invested"]
    assert dd["avg_price"] < fijo["avg_price"]
