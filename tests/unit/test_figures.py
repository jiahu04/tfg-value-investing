"""Tests de las figuras de resultados (paso 3.1): sin display (backend Agg), datos sintéticos."""

import pandas as pd
from matplotlib.figure import Figure

from src.reporting import figures


def _curve() -> pd.DataFrame:
    dates = pd.date_range("2013-01-01", periods=156, freq="MS")
    n = len(dates)
    return pd.DataFrame(
        {
            "date": dates,
            "portfolio_value": [100000.0 * (1.010**i) for i in range(n)],
            "index_value": [100000.0 * (1.012**i) for i in range(n)],
            "cash": [0.0] * n,
            "invested": [0.0] * n,
            "n_positions": [15] * n,
        }
    )


def _reviews() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2014-06-01", "2015-06-01", "2016-06-01"]),
            "margin_of_safety": [0.55, 0.62, 0.48],
            "n_selected": [15, 15, 12],
        }
    )


def _contrib() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "estrategia": ["DCA fijo", "DCA condicional", "Concentrada"],
            "TIR (MWR)": [0.1138, 0.1151, 0.1257],
            "valor_final": [3.4e5, 4.0e5, 2.4e5],
            "total_aportado": [156000.0, 170091.0, 87000.0],
            "n_aportaciones": [156, 156, 29],
            "precio_medio": [228.27, 213.86, 180.89],
        }
    )


def test_plot_equity_curve_returns_figure():
    fig = figures.plot_equity_curve(_curve())
    assert isinstance(fig, Figure)
    assert len(fig.axes[0].get_lines()) >= 2  # cartera + índice


def test_plot_margin_evolution_returns_figure():
    fig = figures.plot_margin_evolution(_reviews())
    assert isinstance(fig, Figure)
    assert fig.axes


def test_plot_contributions_returns_figure():
    fig = figures.plot_contributions(_contrib())
    assert isinstance(fig, Figure)
    assert len(fig.axes) == 2  # dos paneles (TIR y precio medio)


def test_save_figure_writes_pdf_and_png(tmp_path, monkeypatch):
    monkeypatch.setattr(figures, "_figures_dir", lambda: tmp_path)
    paths = figures.save_figure(figures.plot_margin_evolution(_reviews()), "test_fig")
    assert len(paths) == 2
    for p in paths:
        assert p.exists() and p.stat().st_size > 0
    assert {p.suffix for p in paths} == {".pdf", ".png"}


def test_main_generates_present_and_skips_missing(tmp_path, monkeypatch, capsys):
    tables = tmp_path / "tables"
    tables.mkdir()
    figs = tmp_path / "figs"
    monkeypatch.setattr(figures, "_tables_dir", lambda: tables)
    monkeypatch.setattr(figures, "_figures_dir", lambda: figs)
    # Presentes: curva y aportación. Ausente: reviews -> debe omitirse sin romper.
    _curve().to_csv(tables / "backtest_equity_curve.csv", index=False)
    _contrib().to_csv(tables / "contributions_comparison.csv", index=False)

    figures.main()

    assert (figs / "equity_curve.pdf").exists()
    assert (figs / "contributions.png").exists()
    assert not (figs / "margin_evolution.pdf").exists()  # CSV ausente
    assert "omitida" in capsys.readouterr().out
