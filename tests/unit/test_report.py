"""Tests del resumen de resultados en consola (report.py): CSV sintéticos, sin red."""

import pandas as pd

from src.reporting import report


def _setup_tables(tables):
    pd.DataFrame(
        {
            "date": pd.date_range("2013-01-01", periods=3, freq="YS"),
            "portfolio_value": [100000.0, 120000.0, 150000.0],
            "index_value": [100000.0, 110000.0, 130000.0],
            "cash": [0.0, 0.0, 0.0],
            "invested": [0.0, 0.0, 0.0],
            "n_positions": [15, 15, 15],
        }
    ).to_csv(tables / "backtest_equity_curve.csv", index=False)
    pd.DataFrame(
        {
            "metrica": ["CAGR cartera", "Beta"],
            "Total": [0.13, 0.96],
            "Calibración": [0.15, 0.95],
            "Validación": [0.11, 0.96],
        }
    ).to_csv(tables / "backtest_metrics.csv", index=False)
    pd.DataFrame(
        {
            "estrategia": ["DCA fijo", "Concentrada"],
            "TIR (MWR)": [0.1138, 0.1257],
            "valor_final": [3.4e5, 2.4e5],
            "total_aportado": [156000.0, 87000.0],
            "n_aportaciones": [156, 29],
            "precio_medio": [228.3, 180.9],
        }
    ).to_csv(tables / "contributions_comparison.csv", index=False)
    pd.DataFrame(
        {
            "ticker": ["KLAC", "WDC"],
            "sector": ["Manufacturing", "Manufacturing"],
            "quality_score": [0.92, 0.76],
            "margin_of_safety": [0.93, 0.80],
            "priority": [0.93, 0.78],
            "selected": [True, True],
        }
    ).to_csv(tables / "seleccion_2019-06-01.csv", index=False)


def test_report_prints_all_sections(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(report, "_tables_dir", lambda: tmp_path)
    _setup_tables(tmp_path)

    report.main()
    out = capsys.readouterr().out

    assert "BACKTEST" in out and "+50.0%" in out  # 100k -> 150k
    assert "SELECCIÓN" in out and "KLAC" in out
    assert "APORTACIÓN" in out and "11.38 %" in out


def test_report_handles_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(report, "_tables_dir", lambda: tmp_path)
    report.main()
    assert "No hay resultados" in capsys.readouterr().out
