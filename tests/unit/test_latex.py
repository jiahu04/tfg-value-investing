"""Tests de la exportación a LaTeX (paso 2.2)."""

import pandas as pd

from src.reporting.latex import save_latex, to_latex_table


def test_to_latex_table_structure_and_values():
    df = pd.DataFrame({"Total": [0.1234, 1.5]}, index=["CAGR cartera", "Beta"])
    tex = to_latex_table(df, caption="Métricas", label="tab:m", index_header="Métrica")
    assert "\\begin{tabularx}{\\textwidth}{lX}" in tex
    assert "\\caption{Métricas}" in tex
    assert "\\label{tab:m}" in tex
    assert "Métrica & Total" in tex
    assert "0.123" in tex  # float_format por defecto {:.3f}
    assert "CAGR cartera" in tex


def test_to_latex_escapes_special_chars():
    df = pd.DataFrame({"a_b": ["50%"]}, index=["x_y"])
    tex = to_latex_table(df, caption="c", label="l")
    assert "a\\_b" in tex
    assert "50\\%" in tex
    assert "x\\_y" in tex


def test_save_latex(tmp_path):
    path = save_latex("contenido", tmp_path / "sub" / "t.tex")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "contenido"
