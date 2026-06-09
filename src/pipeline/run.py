"""
run.py — Orquestador del pipeline de selección (Etapas 1–5, paso 1.6).

Ejecuta de principio a fin, sobre una fecha D, las cinco etapas del pipeline value y
devuelve la **lista priorizada** de empresas:
  1. Datos (caché del paso 1.1).
  2. Filtros de descarte (1.3).
  3. Puntuación de calidad (1.4).
  4. Valoración compuesta (1.5).
  5. Margen de seguridad y construcción de cartera (1.6).

Todo es point-in-time: a la fecha D solo se usa lo conocido entonces (filed ≤ D,
precios ≤ D). Una sola orden lo ejecuta:

    python -m src.pipeline.run --date 2019-06-01
    python -m src.pipeline.run                 # fecha por defecto: hoy
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from src.ingest import cache_io
from src.ingest.constituents import members_on
from src.pipeline.filters import filter_universe
from src.pipeline.metrics import annual_metrics
from src.pipeline.point_in_time import load_fundamentals
from src.pipeline.portfolio import build_portfolio, margin_of_safety
from src.pipeline.quality import quality_score
from src.pipeline.valuation import intrinsic_value
from src.utils.config_loader import get_config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_CANDIDATE_COLUMNS = [
    "ticker",
    "sector",
    "passed",
    "reasons",
    "fscore",
    "quality_score",
    "value_central",
    "value_low",
    "value_high",
    "price",
    "margin_of_safety",
]


def _read_or_empty(path: Path, columns: list[str]) -> pd.DataFrame:
    """Lee un Parquet si existe; si no, un DataFrame vacío con las columnas dadas."""
    if path.exists():
        return cache_io.read_parquet(path)
    return pd.DataFrame(columns=columns)


def _build_universe(
    fundamentals: pd.DataFrame,
    constituents_df: pd.DataFrame | None,
    asof: pd.Timestamp,
    limit: int | None,
) -> list[str]:
    """Universo point-in-time: constituyentes vigentes ∩ tickers con fundamentales.

    Si la intersección queda vacía (p. ej. caché parcial), usa los tickers con
    fundamentales como fallback.
    """
    fund_tickers = set(fundamentals["ticker"].unique())
    if constituents_df is not None and not constituents_df.empty:
        members = set(members_on(constituents_df, asof))
        universe = sorted(fund_tickers & members) or sorted(fund_tickers)
    else:
        universe = sorted(fund_tickers)
    return universe[:limit] if limit else universe


def run_pipeline(
    asof: str | pd.Timestamp,
    *,
    fundamentals: pd.DataFrame | None = None,
    sectors_df: pd.DataFrame | None = None,
    prices_df: pd.DataFrame | None = None,
    index_df: pd.DataFrame | None = None,
    rf_df: pd.DataFrame | None = None,
    constituents_df: pd.DataFrame | None = None,
    universe: list[str] | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Ejecuta las cinco etapas sobre una fecha y devuelve la tabla de candidatos priorizada.

    Los datos se inyectan (tests) o se cargan de la caché. Devuelve un DataFrame con las
    señales de cada etapa más priority/selected/weight (de `build_portfolio`).
    """
    asof = pd.Timestamp(asof)
    cache = cache_io.cache_dir()

    # Etapa 1 — datos
    if fundamentals is None:
        fundamentals = load_fundamentals()
    if sectors_df is None:
        sectors_path = cache / "sectors.csv"
        sectors_df = (
            cache_io.read_csv(sectors_path)
            if sectors_path.exists()
            else pd.DataFrame(columns=["ticker", "sector"])
        )
    if prices_df is None:
        prices_df = _read_or_empty(cache / "prices.parquet", ["date", "ticker", "close"])
    if index_df is None:
        index_df = _read_or_empty(cache / "index_prices.parquet", ["date", "ticker", "close"])
    if rf_df is None:
        rf_df = _read_or_empty(cache / "risk_free.parquet", ["date", "ticker", "close"])
    if constituents_df is None:
        constituents_df = _read_or_empty(cache / "constituents.parquet", ["date", "ticker"])

    if universe is None:
        universe = _build_universe(fundamentals, constituents_df, asof, limit)
    else:
        universe = sorted({t.upper() for t in universe})

    sector_map = dict(zip(sectors_df["ticker"], sectors_df["sector"], strict=False))

    # Etapa 2 — filtros (traza de todo el universo)
    trace = filter_universe(fundamentals, sectors_df, universe, asof)

    # Etapas 3–5 — solo para los supervivientes
    rows: list[dict] = []
    for record in trace.itertuples(index=False):
        row = {
            "ticker": record.ticker,
            "sector": record.sector,
            "passed": record.passed,
            "reasons": record.reasons,
            "fscore": float("nan"),
            "quality_score": float("nan"),
            "value_central": float("nan"),
            "value_low": float("nan"),
            "value_high": float("nan"),
            "price": float("nan"),
            "margin_of_safety": float("nan"),
        }
        if record.passed:
            metrics = annual_metrics(fundamentals, record.ticker, asof)
            quality = quality_score(metrics)
            peers = [t for t in universe if sector_map.get(t) == record.sector]
            value = intrinsic_value(
                fundamentals, sectors_df, prices_df, index_df, rf_df, record.ticker, peers, asof
            )
            row["fscore"] = quality["fscore"]
            row["quality_score"] = quality["quality_score"]
            row["value_central"] = value["value_central"]
            row["value_low"] = value["value_low"]
            row["value_high"] = value["value_high"]
            row["price"] = value["price"]
            row["margin_of_safety"] = margin_of_safety(value["value_central"], value["price"])
        rows.append(row)

    candidates = pd.DataFrame(rows, columns=_CANDIDATE_COLUMNS)
    return build_portfolio(candidates)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _save_outputs(result: pd.DataFrame, asof: pd.Timestamp) -> Path:
    """Guarda la tabla completa de candidatos en outputs/ y devuelve la ruta."""
    tables_dir = _PROJECT_ROOT / get_config("outputs.tables_dir", "outputs/tables")
    cache_io.ensure_dir(tables_dir)
    path = tables_dir / f"seleccion_{asof.date()}.csv"
    cache_io.write_csv(result, path)
    return path


def main() -> None:
    """Punto de entrada de la CLI del pipeline de selección."""
    parser = argparse.ArgumentParser(description="Pipeline de selección value (Etapas 1–5)")
    parser.add_argument("--date", default=date.today().isoformat(), help="Fecha D (YYYY-MM-DD)")
    parser.add_argument(
        "--limit", type=int, default=None, help="Limita el universo (prueba rápida)"
    )
    args = parser.parse_args()

    asof = pd.Timestamp(args.date)
    result = run_pipeline(asof, limit=args.limit)

    n_universe = len(result)
    n_survivors = int(result["passed"].fillna(False).sum())
    selected = result[result["selected"]]

    print(f"Pipeline de selección — fecha {asof.date()}")
    print(
        f"  universo: {n_universe} | pasan filtros: {n_survivors} | seleccionadas: {len(selected)}"
    )
    if not selected.empty:
        cols = ["ticker", "sector", "quality_score", "margin_of_safety", "priority", "weight"]
        print("\nLista priorizada:")
        print(selected[cols].round(3).to_string(index=False))
    else:
        print("\nNinguna empresa cumple los criterios a esta fecha.")

    out_path = _save_outputs(result, asof)
    print(f"\nTabla completa guardada en: {out_path}")


if __name__ == "__main__":
    main()
