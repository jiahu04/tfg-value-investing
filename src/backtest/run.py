"""
run.py — CLI del backtesting (paso 2.1).

Ejecuta el motor de backtesting sobre la caché local: usa el pipeline de selección
(1.6) como función de selección a cada fecha de revisión y produce las series de valor
de la cartera y del índice, más los registros de operaciones.

    python -m src.backtest.run
    python -m src.backtest.run --start 2013-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.backtest.engine import run_backtest
from src.ingest import cache_io
from src.pipeline.point_in_time import load_fundamentals
from src.pipeline.run import run_pipeline
from src.utils.config_loader import get_config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_or_empty(path: Path, columns: list[str]) -> pd.DataFrame:
    return cache_io.read_parquet(path) if path.exists() else pd.DataFrame(columns=columns)


def main() -> None:
    """Punto de entrada de la CLI del backtesting."""
    parser = argparse.ArgumentParser(description="Backtesting de la estrategia value (paso 2.1)")
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

    # La selección a una fecha reutiliza el pipeline completo con los datos ya cargados.
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
    trades = result["trades"]
    tables_dir = _PROJECT_ROOT / get_config("outputs.tables_dir", "outputs/tables")
    cache_io.ensure_dir(tables_dir)
    cache_io.write_csv(curve, tables_dir / "backtest_equity_curve.csv")
    cache_io.write_csv(trades, tables_dir / "backtest_trades.csv")

    print(f"Backtest {args.start} -> {args.end}")
    if curve.empty:
        print("  Sin datos de mercado en la ventana (falta la ingesta de precios?).")
        return
    first, last = curve.iloc[0], curve.iloc[-1]
    pf_ret = last["portfolio_value"] / first["portfolio_value"] - 1.0
    idx_ret = (
        last["index_value"] / first["index_value"] - 1.0
        if pd.notna(first["index_value"])
        else float("nan")
    )
    print(
        f"  cartera: {first['portfolio_value']:.0f} -> {last['portfolio_value']:.0f} ({pf_ret:+.1%})"
    )
    print(f"  indice : {first['index_value']:.0f} -> {last['index_value']:.0f} ({idx_ret:+.1%})")
    print(f"  operaciones: {len(trades)} | puntos de la serie: {len(curve)}")
    print(f"  series guardadas en: {tables_dir}")


if __name__ == "__main__":
    main()
