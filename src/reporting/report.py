"""
report.py — Resumen de resultados en consola (paso 3.1, complemento).

Lee los CSV ya generados en `outputs/tables/` (backtest, selección, aportación,
sensibilidad) y los imprime como **tablas legibles**, sin re-ejecutar nada. Es el
equivalente "en tabla" de `figures.py` (lo mismo, pero en imagen): un único sitio para
ver de un vistazo todos los resultados ya calculados.

    python -m src.reporting.report
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingest import cache_io
from src.utils.config_loader import get_config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _tables_dir() -> Path:
    return _PROJECT_ROOT / get_config("outputs.tables_dir", "outputs/tables")


def _read(name: str) -> pd.DataFrame | None:
    path = _tables_dir() / name
    return cache_io.read_csv(path) if path.exists() else None


def _latest_selection() -> pd.DataFrame | None:
    files = sorted(_tables_dir().glob("seleccion_*.csv"))
    return cache_io.read_csv(files[-1]) if files else None


def _indent(text: str, n: int = 2) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in text.splitlines())


def _rule(title: str) -> str:
    return f"\n{'=' * 72}\n{title}\n{'=' * 72}"


# ---------------------------------------------------------------------------
# Secciones del resumen (cada una devuelve líneas de texto)
# ---------------------------------------------------------------------------
def report_backtest(curve: pd.DataFrame, metrics: pd.DataFrame | None) -> list[str]:
    """Rentabilidad cartera vs índice (de la curva de capital) y tabla de métricas."""
    lines = [_rule("BACKTEST — cartera vs índice")]
    first, last = curve.iloc[0], curve.iloc[-1]
    pf_ret = last["portfolio_value"] / first["portfolio_value"] - 1.0
    has_idx = pd.notna(first["index_value"]) and first["index_value"]
    idx_ret = (last["index_value"] / first["index_value"] - 1.0) if has_idx else float("nan")
    lines.append(
        f"  Cartera: {first['portfolio_value']:>12,.0f} -> {last['portfolio_value']:>12,.0f}  ({pf_ret:+.1%})"
    )
    lines.append(
        f"  Índice : {first['index_value']:>12,.0f} -> {last['index_value']:>12,.0f}  ({idx_ret:+.1%})"
    )
    if metrics is not None and not metrics.empty:
        lines.append("\n  Métricas (CAGR/alpha/drawdown/tracking son fracciones; ×100 = %):")
        lines.append(_indent(metrics.round(4).to_string(index=False)))
    return lines


def report_selection(sel: pd.DataFrame) -> list[str]:
    """Empresas seleccionadas en la última fecha calculada."""
    lines = [_rule("SELECCIÓN (última fecha calculada)")]
    if "selected" in sel.columns:
        sel = sel[sel["selected"].astype(bool)]
    cols = [
        c
        for c in ["ticker", "sector", "quality_score", "margin_of_safety", "priority"]
        if c in sel.columns
    ]
    lines.append(f"  Seleccionadas: {len(sel)}")
    lines.append(_indent(sel[cols].round(3).to_string(index=False)))
    return lines


def report_contributions(contrib: pd.DataFrame) -> list[str]:
    """Comparación de las estrategias de aportación (TIR, precio medio…)."""
    lines = [_rule("APORTACIÓN — comparación de estrategias")]
    df = contrib.copy()
    if "TIR (MWR)" in df.columns:
        df["TIR (MWR)"] = (df["TIR (MWR)"] * 100).round(2).astype(str) + " %"
    for c in ("valor_final", "total_aportado", "precio_medio"):
        if c in df.columns:
            df[c] = df[c].round(1)
    lines.append(_indent(df.to_string(index=False)))
    return lines


def report_sensitivity(sens: pd.DataFrame) -> list[str]:
    """Tabla de sensibilidad (una fila por parámetro/valor)."""
    lines = [_rule("SENSIBILIDAD (robustez ante distintos umbrales)")]
    lines.append(_indent(sens.round(4).to_string(index=False)))
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    """Imprime un resumen de todos los resultados ya generados en `outputs/tables/`."""
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)

    out: list[str] = ["RESUMEN DE RESULTADOS  (lee outputs/tables/, sin re-ejecutar nada)"]
    any_data = False

    curve = _read("backtest_equity_curve.csv")
    if curve is not None and not curve.empty:
        any_data = True
        out += report_backtest(curve, _read("backtest_metrics.csv"))

    sel = _latest_selection()
    if sel is not None and not sel.empty:
        any_data = True
        out += report_selection(sel)

    contrib = _read("contributions_comparison.csv")
    if contrib is not None and not contrib.empty:
        any_data = True
        out += report_contributions(contrib)

    sens = _read("backtest_sensitivity.csv")
    if sens is not None and not sens.empty:
        any_data = True
        out += report_sensitivity(sens)

    if not any_data:
        out.append(
            "\n  (No hay resultados en outputs/tables/. Corre antes el backtest/aportación.)"
        )
    print("\n".join(out))


if __name__ == "__main__":
    main()
