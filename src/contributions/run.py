"""
run.py — CLI de la simulación de estrategias de aportación (paso 2.3).

Ensambla las series reales desde la caché local y compara las tres estrategias de
aportación (sección 8.3 de la memoria):

  1) Reutiliza el motor de backtesting (2.1) para obtener la curva de valor de la
     estrategia value y la convierte en un índice de valor por unidad (NAV).
  2) En cada revisión anual llama al pipeline de selección (1.6) y calcula el margen de
     seguridad agregado, que propaga (forward-fill) a las fechas de aportación.
  3) Simula DCA fijo, DCA condicional al valor y aportación concentrada, y exporta la
     tabla comparativa (TIR/MWR y precio medio de adquisición) a CSV y LaTeX.

    python -m src.contributions.run
    python -m src.contributions.run --start 2013-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.backtest.engine import _decision_dates, run_backtest
from src.contributions.strategies import compare_strategies
from src.ingest import cache_io
from src.pipeline.point_in_time import load_fundamentals
from src.pipeline.run import run_pipeline
from src.reporting.latex import save_latex, to_latex_table
from src.utils.config_loader import get_config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_or_empty(path: Path, columns: list[str]) -> pd.DataFrame:
    return cache_io.read_parquet(path) if path.exists() else pd.DataFrame(columns=columns)


def build_nav(equity_curve: pd.DataFrame) -> pd.Series:
    """Convierte la curva de valor del backtest en un NAV por unidad (base 100)."""
    curve = equity_curve.set_index("date")["portfolio_value"].sort_index()
    base = curve.iloc[0]
    return curve / base * 100.0 if base else curve


def opportunity_signal(
    select_fn,
    nav_index: pd.DatetimeIndex,
    review_month: int,
) -> pd.Series:
    """Serie de la señal de oportunidad (amplitud), point-in-time, sobre el calendario del NAV.

    En cada fecha de revisión anual se llama al pipeline y se calcula la **amplitud de
    oportunidades** (fracción del conjunto que pasa filtros con margen de seguridad por
    encima del umbral). El valor se mantiene (forward-fill) hasta la siguiente revisión.
    """
    review_dates, _ = _decision_dates(nav_index, review_month)
    values: dict[pd.Timestamp, float] = {}
    for date in sorted(review_dates):
        candidates = select_fn(date)
        values[date] = _opportunity_breadth(candidates)
    signal = pd.Series(values).sort_index()
    return signal.reindex(nav_index.union(signal.index)).ffill().reindex(nav_index)


def _opportunity_breadth(candidates: pd.DataFrame) -> float:
    """Amplitud de oportunidades: fracción de las empresas que pasan filtros (con margen
    válido) cuyo `margin_of_safety` alcanza `portfolio.min_margin_of_safety`.

    Es una señal en [0, 1] que **varía** con el mercado (alta cuando abundan las empresas
    baratas, baja cuando escasean). NaN si no hay base sobre la que medir.
    """
    if candidates is None or candidates.empty or "margin_of_safety" not in candidates.columns:
        return float("nan")
    if "passed" not in candidates.columns or "value_central" not in candidates.columns:
        return float("nan")
    investable = candidates[
        candidates["passed"].fillna(False).astype(bool)
        & (candidates["value_central"] > 0)
        & candidates["margin_of_safety"].notna()
    ]
    if investable.empty:
        return float("nan")
    min_margin = get_config("portfolio.min_margin_of_safety", 0.30)
    eligible = (investable["margin_of_safety"] >= min_margin).sum()
    return float(eligible / len(investable))


def contribution_dates(nav_index: pd.DatetimeIndex, frequency: str) -> pd.DatetimeIndex:
    """Primer día de mercado de cada periodo (mensual/anual) dentro del calendario del NAV."""
    if len(nav_index) == 0:
        return nav_index
    df = pd.DataFrame({"date": nav_index}, index=nav_index)
    if frequency == "monthly":
        keys = [(d.year, d.month) for d in nav_index]
    elif frequency == "annual":
        keys = [d.year for d in nav_index]
    else:
        raise ValueError(f"Frecuencia de aportación no soportada: {frequency!r}")
    df["key"] = keys
    first = df.groupby("key", sort=False)["date"].first()
    return pd.DatetimeIndex(sorted(first.values))


def main() -> None:
    """Punto de entrada de la CLI de la simulación de aportación."""
    parser = argparse.ArgumentParser(
        description="Simulación de estrategias de aportación (paso 2.3)"
    )
    parser.add_argument("--start", default=get_config("universe.backtest_start", "2013-01-01"))
    parser.add_argument("--end", default=get_config("universe.backtest_end", "2025-12-31"))
    args = parser.parse_args()

    cache = cache_io.cache_dir()
    fundamentals = load_fundamentals()
    sectors_path = cache / "sectors.csv"
    sectors_df = (
        cache_io.read_csv(sectors_path)
        if sectors_path.exists()
        else pd.DataFrame(columns=["ticker", "sector"])
    )
    prices_df = _read_or_empty(cache / "prices.parquet", ["date", "ticker", "close"])
    index_df = _read_or_empty(cache / "index_prices.parquet", ["date", "ticker", "close"])
    rf_df = _read_or_empty(cache / "risk_free.parquet", ["date", "ticker", "close"])
    constituents_df = _read_or_empty(cache / "constituents.parquet", ["date", "ticker"])

    def select_fn(asof: pd.Timestamp) -> pd.DataFrame:
        return run_pipeline(
            asof,
            fundamentals=fundamentals,
            sectors_df=sectors_df,
            prices_df=prices_df,
            index_df=index_df,
            rf_df=rf_df,
            constituents_df=constituents_df,
        )

    result = run_backtest(
        args.start,
        args.end,
        prices_df=prices_df,
        index_df=index_df,
        rf_df=rf_df,
        select_fn=select_fn,
    )
    curve = result["equity_curve"]

    print(f"Aportación {args.start} -> {args.end}")
    if curve.empty:
        print("  Sin datos de mercado en la ventana (falta la ingesta de precios?).")
        return

    nav = build_nav(curve)
    review_month = get_config("backtest.review_month", 6)
    frequency = get_config("contributions.frequency", "monthly")
    signal = opportunity_signal(select_fn, nav.index, review_month)
    dates = contribution_dates(nav.index, frequency)

    cfg = get_config("contributions", {})
    table = compare_strategies(nav, signal, dates, cfg=cfg)

    tables_dir = _PROJECT_ROOT / get_config("outputs.tables_dir", "outputs/tables")
    cache_io.ensure_dir(tables_dir)
    cache_io.write_csv(table.reset_index(), tables_dir / "contributions_comparison.csv")
    save_latex(
        to_latex_table(
            table,
            caption="Comparación de estrategias de aportación",
            label="tab:contributions",
            index_header="Estrategia",
        ),
        tables_dir / "contributions_comparison.tex",
    )

    print(f"  NAV: {nav.iloc[0]:.1f} -> {nav.iloc[-1]:.1f} | aportaciones: {len(dates)}")
    print("\nComparación de estrategias:")
    print(table.round(4).to_string())
    print(f"\nTablas guardadas en: {tables_dir}")


if __name__ == "__main__":
    main()
