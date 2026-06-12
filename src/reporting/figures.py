"""
figures.py — Figuras de los capítulos de resultados (paso 3.1).

Genera, a partir de los CSV ya producidos por el backtest y la simulación de aportación,
las figuras del capítulo 8: **curva de capital** (cartera vs índice), **evolución del
margen de seguridad** y **comparación de estrategias de aportación**. Se exportan en
**PDF** (vectorial, para LaTeX) y **PNG** (para verlas al vuelo).

Las funciones `plot_*` son puras (reciben un DataFrame, devuelven una `Figure`) y no
muestran nada en pantalla; `main()` lee los CSV de `outputs/tables/` y guarda las figuras.

    python -m src.reporting.figures
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

from src.ingest import cache_io
from src.utils.config_loader import get_config

plt.switch_backend("Agg")  # backend sin display (apto para CLI y tests)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _tables_dir() -> Path:
    return _PROJECT_ROOT / get_config("outputs.tables_dir", "outputs/tables")


def _figures_dir() -> Path:
    return _PROJECT_ROOT / get_config("outputs.figures_dir", "outputs/figures")


# ---------------------------------------------------------------------------
# Figuras (funciones puras: DataFrame -> Figure)
# ---------------------------------------------------------------------------
def plot_equity_curve(curve_df: pd.DataFrame) -> Figure:
    """Curva de capital: cartera vs índice, con el corte calibración/validación."""
    df = curve_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(df["date"], df["portfolio_value"], label="Cartera value", color="#1f77b4")
    ax.plot(
        df["date"],
        df["index_value"],
        label="Índice (S&P 500 TR)",
        color="#888888",
        linestyle="--",
    )
    split = pd.Timestamp(get_config("backtest.validation_start", "2019-01-01"))
    if df["date"].min() <= split <= df["date"].max():
        ax.axvline(split, color="#d62728", linestyle=":", linewidth=1)
        ymax = max(df["portfolio_value"].max(), df["index_value"].max())
        ax.text(split, ymax, " Validación", color="#d62728", va="top", ha="left", fontsize=9)
        ax.text(split, ymax, "Calibración ", color="#555555", va="top", ha="right", fontsize=9)
    ax.set_title("Curva de capital: cartera value vs índice")
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Valor de la inversión")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_margin_evolution(reviews_df: pd.DataFrame) -> Figure:
    """Evolución del margen de seguridad medio de la cartera por revisión anual."""
    df = reviews_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.step(df["date"], df["margin_of_safety"], where="post", color="#2ca02c", marker="o")
    min_margin = get_config("portfolio.min_margin_of_safety", 0.30)
    ax.axhline(
        min_margin,
        color="#888888",
        linestyle="--",
        linewidth=1,
        label=f"Margen mínimo ({min_margin:.0%})",
    )
    ax.set_title("Evolución del margen de seguridad de la cartera")
    ax.set_xlabel("Fecha de revisión")
    ax.set_ylabel("Margen de seguridad medio")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_contributions(comparison_df: pd.DataFrame) -> Figure:
    """Comparación de estrategias de aportación: TIR (MWR) y precio medio de adquisición."""
    df = comparison_df.copy()
    if "estrategia" in df.columns:
        df = df.set_index("estrategia")
    strategies = list(df.index)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))
    ax1.bar(strategies, df["TIR (MWR)"] * 100.0, color="#1f77b4")
    ax1.set_title("Rentabilidad ponderada por el dinero (TIR)")
    ax1.set_ylabel("TIR anual (%)")
    ax1.tick_params(axis="x", rotation=15)
    ax1.grid(True, axis="y", alpha=0.3)
    ax2.bar(strategies, df["precio_medio"], color="#ff7f0e")
    ax2.set_title("Precio medio de adquisición")
    ax2.set_ylabel("Precio medio (NAV)")
    ax2.tick_params(axis="x", rotation=15)
    ax2.grid(True, axis="y", alpha=0.3)
    fig.suptitle("Estrategias de aportación")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Guardado y CLI
# ---------------------------------------------------------------------------
def save_figure(fig: Figure, name: str) -> list[Path]:
    """Guarda la figura como PDF (vectorial) y PNG en `outputs.figures_dir`.

    Devuelve las rutas creadas y cierra la figura.
    """
    figures_dir = cache_io.ensure_dir(_figures_dir())
    fmt = get_config("outputs.figure_format", "pdf")
    dpi = get_config("outputs.figure_dpi", 150)
    paths: list[Path] = []
    for ext, extra in ((fmt, {}), ("png", {"dpi": dpi})):
        path = figures_dir / f"{name}.{ext}"
        fig.savefig(path, bbox_inches="tight", **extra)
        paths.append(path)
    plt.close(fig)
    return paths


def _read_csv_or_none(name: str) -> pd.DataFrame | None:
    path = _tables_dir() / name
    return cache_io.read_csv(path) if path.exists() else None


def main() -> None:
    """Genera las figuras de resultados a partir de los CSV de `outputs/tables/`."""
    jobs = [
        (
            "backtest_equity_curve.csv",
            plot_equity_curve,
            "equity_curve",
            "falta el backtest: corre 'python -m src.backtest.run'.",
        ),
        (
            "backtest_reviews.csv",
            plot_margin_evolution,
            "margin_evolution",
            "falta backtest_reviews.csv: corre 'python -m src.backtest.run'.",
        ),
        (
            "contributions_comparison.csv",
            plot_contributions,
            "contributions",
            "falta la aportación: corre 'python -m src.contributions.run'.",
        ),
    ]
    print("Generando figuras de resultados...")
    generated = []
    for csv_name, plot_fn, fig_name, missing_msg in jobs:
        df = _read_csv_or_none(csv_name)
        if df is None or df.empty:
            print(f"  [omitida] {fig_name}: {missing_msg}")
            continue
        paths = save_figure(plot_fn(df), fig_name)
        generated.append(fig_name)
        print(f"  [ok] {fig_name} -> {paths[0].name} + {paths[1].name}")
    if generated:
        print(f"\nFiguras guardadas en: {_figures_dir()}")
    else:
        print("\nNo se generó ninguna figura (faltan los CSV de resultados).")


if __name__ == "__main__":
    main()
