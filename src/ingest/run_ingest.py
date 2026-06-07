"""
run_ingest.py — Orquestador de la adquisición de datos (Etapa 1, paso 1.1).

Ejecuta la ingesta de todas las fuentes y puebla la caché local. Reejecutable: si
el crudo ya está en `data/raw`, reconstruye la caché sin volver a descargar (salvo
`--force`).

Uso:
    python -m src.ingest.run_ingest --step all
    python -m src.ingest.run_ingest --step all --limit 3      # prueba rápida
    python -m src.ingest.run_ingest --step fundamentals
    python -m src.ingest.run_ingest --step all --force        # re-descarga todo

Pasos disponibles: tickers, constituents, sectors, fundamentals, prices, all.
"""

from __future__ import annotations

import argparse

import pandas as pd

from src.ingest import (
    cache_io,
    constituents,
    prices,
    sec_facts,
    sec_submissions,
    sec_tickers,
)
from src.ingest.http_client import build_session

_STEPS = ["tickers", "constituents", "sectors", "fundamentals", "prices", "all"]


def _load_or_ingest_tickers(session, *, force: bool) -> pd.DataFrame:
    """Devuelve el mapa ticker<->CIK desde caché, o lo ingesta si no existe."""
    cache_path = cache_io.cache_dir() / "tickers.parquet"
    if not force and cache_path.exists():
        return cache_io.read_parquet(cache_path)
    return sec_tickers.ingest_tickers(session, force=force)


def _load_or_ingest_constituents(session, *, force: bool) -> pd.DataFrame:
    """Devuelve la composición histórica desde caché, o la ingesta si no existe."""
    cache_path = cache_io.cache_dir() / "constituents.parquet"
    if not force and cache_path.exists():
        return cache_io.read_parquet(cache_path)
    return constituents.ingest_constituents(session, force=force)


def build_universe(
    tickers_df: pd.DataFrame,
    constituents_df: pd.DataFrame,
    *,
    limit: int | None = None,
) -> pd.DataFrame:
    """Construye el universo a ingestar: tickers históricos con CIK conocido.

    Es la unión de todos los tickers que alguna vez estuvieron en el índice
    (point-in-time) que además existen en `company_tickers.json`. Ordenado para que
    `--limit` sea determinista.
    """
    historical = set(constituents_df["ticker"].unique())
    universe = tickers_df[tickers_df["ticker"].isin(historical)].copy()
    universe = universe.sort_values("ticker").reset_index(drop=True)
    if limit is not None:
        universe = universe.head(limit)
    return universe


def run(step: str, *, limit: int | None = None, force: bool = False) -> None:
    """Ejecuta el paso de ingesta indicado."""
    session = build_session()

    if step in ("tickers", "all"):
        df = sec_tickers.ingest_tickers(session, force=force)
        print(f"[tickers] {len(df)} tickers en el mapa ticker<->CIK")

    if step in ("constituents", "all"):
        df = constituents.ingest_constituents(session, force=force)
        n_dates = df["date"].nunique() if not df.empty else 0
        print(f"[constituents] {len(df)} filas, {n_dates} fechas de cambio")

    # Pasos que necesitan el universo (tickers historicos con CIK)
    if step in ("sectors", "fundamentals", "prices", "all"):
        tickers_df = _load_or_ingest_tickers(session, force=force)
        constituents_df = _load_or_ingest_constituents(session, force=force)
        universe = build_universe(tickers_df, constituents_df, limit=limit)
        print(
            f"[universo] {len(universe)} empresas a ingestar"
            + (f" (limit={limit})" if limit else "")
        )

        if step in ("sectors", "all"):
            df = sec_submissions.ingest_sectors(universe, session, force=force)
            print(f"[sectors] {len(df)} empresas con sector asignado")

        if step in ("fundamentals", "all"):
            df = sec_facts.ingest_fundamentals(universe, session, force=force)
            print(f"[fundamentals] {len(df)} hechos financieros (con fecha de publicación)")

        if step in ("prices", "all"):
            tidy = prices.ingest_prices(universe["ticker"].tolist(), force=force)
            print(f"[prices] {tidy['ticker'].nunique()} tickers con precios")
            idx = prices.ingest_index(force=force)
            print(f"[index] {len(idx)} cierres del índice")
            rf = prices.ingest_risk_free(force=force)
            print(f"[risk_free] {len(rf)} observaciones del tipo libre de riesgo")

    print("Ingesta completada.")


def main() -> None:
    """Punto de entrada de la CLI."""
    parser = argparse.ArgumentParser(description="Adquisición de datos (paso 1.1)")
    parser.add_argument(
        "--step",
        choices=_STEPS,
        default="all",
        help="Paso de ingesta a ejecutar (por defecto: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita el número de empresas (prueba rápida)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-descarga aunque exista el crudo en data/raw",
    )
    args = parser.parse_args()
    run(args.step, limit=args.limit, force=args.force)


if __name__ == "__main__":
    main()
