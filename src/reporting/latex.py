"""
latex.py — Exportación de tablas a LaTeX (tabularx).

Convierte un DataFrame de resultados en una tabla LaTeX con entorno `tabularx` lista
para incluir en la memoria. Función pura (devuelve la cadena) + helper para guardarla.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Caracteres que hay que escapar en LaTeX (orden: la barra primero)
_LATEX_ESCAPE = [("\\", r"\textbackslash "), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#")]


def _escape(text: str) -> str:
    for char, replacement in _LATEX_ESCAPE:
        text = text.replace(char, replacement)
    return text


def to_latex_table(
    df: pd.DataFrame,
    *,
    caption: str,
    label: str,
    float_format: str = "{:.3f}",
    column_format: str | None = None,
    index_header: str = "",
) -> str:
    """Devuelve una tabla LaTeX (tabularx) a partir de un DataFrame.

    Args:
        df: tabla con índice (primera columna) y columnas de datos.
        caption, label: pie y etiqueta de la tabla.
        float_format: formato de los números.
        column_format: especificación de columnas; por defecto `l` + `X` por columna.
        index_header: cabecera de la columna del índice.
    """
    columns = list(df.columns)
    if column_format is None:
        column_format = "l" + "X" * len(columns)

    def cell(value) -> str:
        if isinstance(value, (int, float, np.floating)):
            return "" if pd.isna(value) else float_format.format(value)
        return "" if pd.isna(value) else _escape(str(value))

    header = " & ".join([_escape(index_header)] + [_escape(str(c)) for c in columns]) + r" \\"
    body = [
        " & ".join([_escape(str(idx))] + [cell(row[c]) for c in columns]) + r" \\"
        for idx, row in df.iterrows()
    ]

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        rf"\begin{{tabularx}}{{\textwidth}}{{{column_format}}}",
        r"\hline",
        header,
        r"\hline",
        *body,
        r"\hline",
        r"\end{tabularx}",
        r"\end{table}",
    ]
    return "\n".join(lines) + "\n"


def save_latex(text: str, path: Path) -> Path:
    """Guarda la tabla LaTeX en un fichero (UTF-8), creando el directorio si hace falta."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
