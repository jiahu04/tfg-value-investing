"""Test de integración del pipeline de selección completo (paso 1.6).

Ejecuta `run_pipeline` de extremo a extremo con datos sintéticos (sin red) y comprueba
que una empresa barata y de calidad entra en la cartera, mientras que una cara y una de
sector excluido quedan fuera, y la lista sale ordenada por prioridad.
"""

import pandas as pd

from src.pipeline.run import run_pipeline

# Perfil financiero sano y en mejora (mismas cuentas para todas; difieren en precio/sector)
_PROFILE = {
    2017: {
        "Revenues": 1000,
        "GrossProfit": 400,
        "OperatingIncomeLoss": 150,
        "NetIncomeLoss": 100,
        "IncomeTaxExpenseBenefit": 30,
        "NetCashProvidedByUsedInOperatingActivities": 140,
        "DepreciationDepletionAndAmortization": 40,
        "PaymentsToAcquirePropertyPlantAndEquipment": 30,
        "Assets": 2000,
        "AssetsCurrent": 600,
        "LiabilitiesCurrent": 300,
        "CashAndCashEquivalentsAtCarryingValue": 100,
        "LongTermDebtNoncurrent": 400,
        "StockholdersEquity": 1000,
        "CommonStockSharesOutstanding": 100,
    },
    2018: {
        "Revenues": 1100,
        "GrossProfit": 450,
        "OperatingIncomeLoss": 170,
        "NetIncomeLoss": 115,
        "IncomeTaxExpenseBenefit": 33,
        "NetCashProvidedByUsedInOperatingActivities": 160,
        "DepreciationDepletionAndAmortization": 42,
        "PaymentsToAcquirePropertyPlantAndEquipment": 31,
        "Assets": 2050,
        "AssetsCurrent": 650,
        "LiabilitiesCurrent": 300,
        "CashAndCashEquivalentsAtCarryingValue": 120,
        "LongTermDebtNoncurrent": 380,
        "StockholdersEquity": 1100,
        "CommonStockSharesOutstanding": 100,
    },
    2019: {
        "Revenues": 1210,
        "GrossProfit": 500,
        "OperatingIncomeLoss": 190,
        "NetIncomeLoss": 130,
        "IncomeTaxExpenseBenefit": 36,
        "NetCashProvidedByUsedInOperatingActivities": 180,
        "DepreciationDepletionAndAmortization": 44,
        "PaymentsToAcquirePropertyPlantAndEquipment": 32,
        "Assets": 2100,
        "AssetsCurrent": 700,
        "LiabilitiesCurrent": 300,
        "CashAndCashEquivalentsAtCarryingValue": 150,
        "LongTermDebtNoncurrent": 360,
        "StockholdersEquity": 1200,
        "CommonStockSharesOutstanding": 100,
    },
}


def _fundamentals(tickers: list[str]) -> pd.DataFrame:
    cols = ["ticker", "concept", "start", "end", "val", "form", "filed"]
    rows = []
    for tk in tickers:
        for year, concepts in _PROFILE.items():
            for concept, val in concepts.items():
                rows.append(
                    [
                        tk,
                        concept,
                        f"{year}-01-01",
                        f"{year}-12-31",
                        val,
                        "10-K",
                        f"{year + 1}-02-15",
                    ]
                )
    df = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    return df


def test_run_pipeline_end_to_end_selects_cheap_quality():
    fundamentals = _fundamentals(["CHEAP", "PRICEY", "BANK"])
    sectors = pd.DataFrame(
        {
            "ticker": ["CHEAP", "PRICEY", "BANK"],
            "sector": ["Manufacturing", "Manufacturing", "Banking"],  # BANK excluido
        }
    )
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-05-01", "2020-05-01"]),
            "ticker": ["CHEAP", "PRICEY"],  # CHEAP muy barata, PRICEY muy cara
            "close": [1.0, 1000.0],
        }
    )
    index = pd.DataFrame(
        {"date": pd.to_datetime(["2020-05-01"]), "ticker": ["^SP500TR"], "close": [3000.0]}
    )
    rf = pd.DataFrame({"date": pd.to_datetime(["2020-05-01"]), "ticker": ["^IRX"], "close": [2.0]})

    out = run_pipeline(
        "2020-06-01",
        fundamentals=fundamentals,
        sectors_df=sectors,
        prices_df=prices,
        index_df=index,
        rf_df=rf,
        constituents_df=None,
        universe=["CHEAP", "PRICEY", "BANK"],
    )

    assert len(out) == 3
    row = {r["ticker"]: r for _, r in out.iterrows()}

    # CHEAP: barata y de calidad -> seleccionada, margen alto, peso 1 (única)
    assert row["CHEAP"]["selected"]
    assert row["CHEAP"]["margin_of_safety"] >= 0.30
    assert row["CHEAP"]["weight"] == 1.0

    # PRICEY: misma calidad pero carísima -> margen negativo -> fuera
    assert not row["PRICEY"]["selected"]

    # BANK: sector excluido -> no pasa filtros -> fuera
    assert not row["BANK"]["passed"]
    assert not row["BANK"]["selected"]

    # La lista sale ordenada por prioridad: CHEAP arriba (BANK, con prioridad NaN, al final)
    assert out.iloc[0]["ticker"] == "CHEAP"
    assert out.iloc[-1]["ticker"] == "BANK"
