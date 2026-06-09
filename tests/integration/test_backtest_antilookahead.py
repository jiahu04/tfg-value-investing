"""Test anti-look-ahead del backtesting (paso 2.1) — la verificación clave.

Ejecuta el backtest con unos datos y, de nuevo, con los **mismos datos más filas cuya
fecha de publicación (`filed`) es posterior al fin del backtest**. Si la simulación
respeta la regla cardinal, ambas ejecuciones deben producir **exactamente** la misma
serie de valor y los mismos registros: el dato futuro no puede filtrarse.
"""

import pandas as pd

from src.backtest.engine import run_backtest
from src.pipeline.run import run_pipeline

# Perfil de una empresa sana (3 años conocidos antes del backtest)
_PROFILE = {
    2015: (1000, 400, 150, 100, 30, 140, 40, 30, 2000, 600, 300, 100, 400, 1000, 100),
    2016: (1100, 450, 170, 115, 33, 160, 42, 31, 2050, 650, 300, 120, 380, 1100, 100),
    2017: (1210, 500, 190, 130, 36, 180, 44, 32, 2100, 700, 300, 150, 360, 1200, 100),
}
_CONCEPTS = [
    "Revenues",
    "GrossProfit",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "IncomeTaxExpenseBenefit",
    "NetCashProvidedByUsedInOperatingActivities",
    "DepreciationDepletionAndAmortization",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "Assets",
    "AssetsCurrent",
    "LiabilitiesCurrent",
    "CashAndCashEquivalentsAtCarryingValue",
    "LongTermDebtNoncurrent",
    "StockholdersEquity",
    "CommonStockSharesOutstanding",
]


def _fundamentals(extra_rows=None) -> pd.DataFrame:
    cols = ["ticker", "concept", "start", "end", "val", "form", "filed"]
    rows = []
    for year, vals in _PROFILE.items():
        for concept, val in zip(_CONCEPTS, vals, strict=True):
            rows.append(
                ["CO", concept, f"{year}-01-01", f"{year}-12-31", val, "10-K", f"{year + 1}-02-15"]
            )
    if extra_rows:
        rows.extend(extra_rows)
    df = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    return df


def _market():
    dates = pd.date_range("2018-06-04", periods=80, freq="7D")
    prices = pd.DataFrame({"date": dates, "ticker": "CO", "close": 10.0})
    index = pd.DataFrame({"date": dates, "ticker": "^SP500TR", "close": 1000.0})
    rf = pd.DataFrame({"date": dates, "ticker": "^IRX", "close": 2.0})
    sectors = pd.DataFrame({"ticker": ["CO"], "sector": ["Manufacturing"]})
    return dates, prices, index, rf, sectors


def _run(fundamentals, prices, index, rf, sectors):
    def select_fn(asof):
        return run_pipeline(
            asof,
            fundamentals=fundamentals,
            sectors_df=sectors,
            prices_df=prices,
            index_df=index,
            rf_df=rf,
            constituents_df=None,
            universe=["CO"],
        )

    return run_backtest(
        "2018-01-01",
        "2020-01-01",
        prices_df=prices,
        index_df=index,
        rf_df=rf,
        select_fn=select_fn,
    )


def test_future_filings_do_not_change_the_backtest():
    _dates, prices, index, rf, sectors = _market()

    base = _run(_fundamentals(), prices, index, rf, sectors)

    # Datos que, de filtrarse, cambiarían las decisiones: un beneficio enorme de un año
    # futuro publicado en 2030 (posterior a toda fecha de decisión del backtest).
    future_rows = [
        ["CO", "NetIncomeLoss", "2019-01-01", "2019-12-31", 10**9, "10-K", "2030-01-01"],
        ["CO", "Revenues", "2019-01-01", "2019-12-31", 10**10, "10-K", "2030-01-01"],
    ]
    with_future = _run(_fundamentals(future_rows), prices, index, rf, sectors)

    # Idénticos: el dato futuro no se ha usado en ninguna decisión.
    pd.testing.assert_frame_equal(base["equity_curve"], with_future["equity_curve"])
    pd.testing.assert_frame_equal(base["trades"], with_future["trades"])
