"""Tests de las métricas derivadas (paso 1.2).

Comprueban los cálculos exactos sobre un panel sintético con números conocidos, el
respaldo de tags XBRL y el anti-look-ahead de extremo a extremo vía `annual_metrics`.
"""

import pandas as pd
import pytest

from src.pipeline import metrics

# Panel sintético: dos años fiscales con magnitudes conocidas (tags XBRL reales).
_PANEL = pd.DataFrame(
    {
        "Revenues": [1000.0, 1200.0],
        "CostOfRevenue": [600.0, 700.0],
        "GrossProfit": [400.0, 500.0],
        "OperatingIncomeLoss": [200.0, 250.0],
        "NetIncomeLoss": [150.0, 180.0],
        "InterestExpense": [20.0, 25.0],
        "IncomeTaxExpenseBenefit": [50.0, 60.0],
        "NetCashProvidedByUsedInOperatingActivities": [220.0, 260.0],
        "PaymentsToAcquirePropertyPlantAndEquipment": [50.0, 60.0],
        "DepreciationDepletionAndAmortization": [40.0, 45.0],
        "Assets": [2000.0, 2200.0],
        "AssetsCurrent": [800.0, 900.0],
        "LiabilitiesCurrent": [400.0, 450.0],
        "CashAndCashEquivalentsAtCarryingValue": [100.0, 120.0],
        "ShortTermInvestments": [30.0, 40.0],
        "LongTermDebtNoncurrent": [500.0, 480.0],
        "LongTermDebtCurrent": [50.0, 40.0],
        "StockholdersEquity": [900.0, 1000.0],
        "CommonStockSharesOutstanding": [1000.0, 1010.0],
    },
    index=pd.to_datetime(["2019-12-31", "2020-12-31"]),
)


def _last(series: pd.Series) -> float:
    """Valor del año más reciente (2020)."""
    return series.iloc[-1]


def test_ebit_and_ebitda():
    assert _last(metrics.ebit(_PANEL)) == 250.0
    assert _last(metrics.ebitda(_PANEL)) == 295.0  # 250 + 45


def test_free_cash_flow():
    assert _last(metrics.free_cash_flow(_PANEL)) == 200.0  # 260 - 60


def test_total_and_net_debt():
    assert _last(metrics.total_debt(_PANEL)) == 520.0  # 480 + 40
    assert _last(metrics.net_debt(_PANEL)) == 360.0  # 520 - 120 - 40


def test_margins():
    assert _last(metrics.gross_margin(_PANEL)) == pytest.approx(500 / 1200)
    assert _last(metrics.operating_margin(_PANEL)) == pytest.approx(250 / 1200)
    assert _last(metrics.net_margin(_PANEL)) == pytest.approx(180 / 1200)


def test_ratios_and_quality():
    assert _last(metrics.interest_coverage(_PANEL)) == pytest.approx(10.0)  # 250 / 25
    assert _last(metrics.current_ratio(_PANEL)) == pytest.approx(2.0)  # 900 / 450
    assert _last(metrics.cfo_to_net_income(_PANEL)) == pytest.approx(260 / 180)
    assert _last(metrics.roa(_PANEL)) == pytest.approx(180 / 2200)


def test_share_growth():
    sg = metrics.share_growth(_PANEL)
    assert pd.isna(sg.iloc[0])  # primer año: sin variación
    assert _last(sg) == pytest.approx(0.01)  # (1010 - 1000) / 1000


def test_compute_metrics_assembles_panel():
    out = metrics.compute_metrics(_PANEL)
    assert list(out.index) == list(_PANEL.index)
    row = out.iloc[-1]
    assert row["ebitda"] == 295.0
    assert row["net_debt"] == 360.0
    assert row["net_debt_to_ebitda"] == pytest.approx(360 / 295)


def test_revenue_tag_fallback():
    # Sin "Revenues": debe resolver desde RevenueFromContract...
    panel = pd.DataFrame(
        {"RevenueFromContractWithCustomerExcludingAssessedTax": [500.0]},
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics._resolve(panel, "revenue")) == 500.0


def test_resolve_coalesces_across_years():
    # Un tag cubre años antiguos y otro los recientes: se combinan año a año por prioridad
    panel = pd.DataFrame(
        {
            "Revenues": [float("nan"), 1200.0],
            "SalesRevenueNet": [1000.0, float("nan")],
        },
        index=pd.to_datetime(["2015-12-31", "2016-12-31"]),
    )
    resolved = metrics._resolve(panel, "revenue")
    assert resolved.iloc[0] == 1000.0  # de SalesRevenueNet
    assert resolved.iloc[1] == 1200.0  # de Revenues (mayor prioridad)


def test_total_debt_fallback_to_single_tag():
    # Sin tramos no corriente/corriente: usa el tag total LongTermDebt
    panel = pd.DataFrame(
        {"LongTermDebt": [700.0]},
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics.total_debt(panel)) == 700.0


def test_dep_amort_fallback_tag_feeds_ebitda():
    # Sin DepreciationDepletionAndAmortization: usa DepreciationAndAmortization
    panel = pd.DataFrame(
        {"OperatingIncomeLoss": [200.0], "DepreciationAndAmortization": [40.0]},
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics.ebitda(panel)) == 240.0


def test_capex_fallback_tag_feeds_fcf():
    # Sin PaymentsToAcquirePropertyPlantAndEquipment: usa PaymentsToAcquireProductiveAssets
    panel = pd.DataFrame(
        {
            "NetCashProvidedByUsedInOperatingActivities": [300.0],
            "PaymentsToAcquireProductiveAssets": [90.0],
        },
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics.free_cash_flow(panel)) == 210.0


def test_net_income_fallback_to_profit_loss():
    # Sin NetIncomeLoss: usa ProfitLoss (incluye minoritarios) como respaldo
    panel = pd.DataFrame(
        {"ProfitLoss": [175.0]},
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics._resolve(panel, "net_income")) == 175.0


def test_net_income_prefers_net_income_loss_over_profit_loss():
    # Con ambos presentes, gana el preferente (beneficio atribuible a la matriz)
    panel = pd.DataFrame(
        {"NetIncomeLoss": [150.0], "ProfitLoss": [175.0]},
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics._resolve(panel, "net_income")) == 150.0


def test_revenue_fallback_including_assessed_tax():
    # Sin los preferentes: usa la variante RevenueFromContract...IncludingAssessedTax
    panel = pd.DataFrame(
        {"RevenueFromContractWithCustomerIncludingAssessedTax": [800.0]},
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics._resolve(panel, "revenue")) == 800.0


def test_cfo_fallback_continuing_operations_feeds_fcf():
    # Sin el CFO principal: usa la variante ...ContinuingOperations (y alimenta el FCF)
    panel = pd.DataFrame(
        {
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations": [300.0],
            "PaymentsToAcquirePropertyPlantAndEquipment": [70.0],
        },
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics._resolve(panel, "cfo")) == 300.0
    assert _last(metrics.free_cash_flow(panel)) == 230.0  # 300 - 70


def test_capex_fallback_other_productive_assets_feeds_fcf():
    # Sin los capex preferentes: usa PaymentsToAcquireOtherProductiveAssets
    panel = pd.DataFrame(
        {
            "NetCashProvidedByUsedInOperatingActivities": [300.0],
            "PaymentsToAcquireOtherProductiveAssets": [85.0],
        },
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics.free_cash_flow(panel)) == 215.0  # 300 - 85


def test_total_debt_from_capital_lease_tranches():
    # Tramos con obligaciones de leasing (aerolíneas/industriales)
    panel = pd.DataFrame(
        {
            "LongTermDebtAndCapitalLeaseObligations": [800.0],
            "LongTermDebtAndCapitalLeaseObligationsCurrent": [120.0],
        },
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics.total_debt(panel)) == 920.0


def test_total_debt_from_combined_amount_tag():
    # Sin tramos: cae al tag total combinado
    panel = pd.DataFrame(
        {"DebtLongtermAndShorttermCombinedAmount": [650.0]},
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics.total_debt(panel)) == 650.0


def test_ebit_fallback_when_no_operating_income():
    # Sin OperatingIncomeLoss: EBIT = beneficio + intereses + impuestos
    panel = pd.DataFrame(
        {
            "NetIncomeLoss": [100.0],
            "InterestExpense": [20.0],
            "IncomeTaxExpenseBenefit": [30.0],
        },
        index=pd.to_datetime(["2020-12-31"]),
    )
    assert _last(metrics.ebit(panel)) == 150.0


def test_safe_div_handles_zero():
    num = pd.Series([10.0, 5.0])
    den = pd.Series([0.0, 2.0])
    out = metrics._safe_div(num, den)
    assert pd.isna(out.iloc[0])  # división por cero → NaN
    assert out.iloc[1] == 2.5


def test_compute_metrics_empty_panel():
    assert metrics.compute_metrics(pd.DataFrame()).empty


def test_annual_metrics_end_to_end_anti_look_ahead():
    # Construye fundamentales crudos y comprueba el anti-look-ahead vía annual_metrics
    cols = ["ticker", "concept", "start", "end", "val", "form", "filed"]
    rows = [
        ["AAPL", "Revenues", "2020-01-01", "2020-12-31", 1200, "10-K", "2021-02-15"],
        ["AAPL", "NetIncomeLoss", "2020-01-01", "2020-12-31", 180, "10-K", "2021-02-15"],
    ]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])

    assert metrics.annual_metrics(df, "AAPL", "2021-01-01").empty  # aún no publicado
    out = metrics.annual_metrics(df, "AAPL", "2021-03-01")
    assert _last(out["net_margin"]) == pytest.approx(180 / 1200)


def test_metrics_asof_returns_latest_row():
    cols = ["ticker", "concept", "start", "end", "val", "form", "filed"]
    rows = [
        ["AAPL", "NetIncomeLoss", "2019-01-01", "2019-12-31", 150, "10-K", "2020-02-15"],
        ["AAPL", "NetIncomeLoss", "2020-01-01", "2020-12-31", 180, "10-K", "2021-02-15"],
    ]
    df = pd.DataFrame(rows, columns=cols)
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    snapshot = metrics.metrics_asof(df, "AAPL", "2021-06-01")
    assert snapshot["net_income"] == 180.0
