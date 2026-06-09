"""
portfolio.py — Margen de seguridad y construcción de cartera (Etapa 5, paso 1.6).

Cierra el pipeline de selección: a partir del valor intrínseco (1.5) y el precio,
calcula el margen de seguridad, aplica la regla de construcción de cartera y produce
la lista priorizada.

Regla (D-023): para entrar, una empresa debe (1) pasar los filtros (1.3), (2) tener un
margen de seguridad ≥ `portfolio.min_margin_of_safety` y (3) una calidad ≥
`quality.min_quality_score`. Las que cumplen se ordenan por una prioridad que combina
calidad y margen (pesos configurables), se aplica el tope `portfolio.max_positions` y se
equiponderan. Funciones puras y testeables.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils.config_loader import get_config


def margin_of_safety(value: float, price: float) -> float:
    """Margen de seguridad = (valor − precio) / valor (descuento sobre el valor).

    Devuelve NaN si el valor no es positivo o el precio no es válido. Positivo cuando
    el precio está por debajo del valor (1 − precio/valor).
    """
    if pd.isna(value) or pd.isna(price) or value <= 0:
        return np.nan
    return float((value - price) / value)


def priority_score(quality: float, margin: float, q_weight: float, m_weight: float) -> float:
    """Prioridad = q_weight·calidad + m_weight·margen. NaN si falta algún componente."""
    if pd.isna(quality) or pd.isna(margin):
        return np.nan
    return float(q_weight * quality + m_weight * margin)


def build_portfolio(candidates: pd.DataFrame) -> pd.DataFrame:
    """Aplica la regla de cartera a la tabla de candidatos y devuelve la lista priorizada.

    Espera columnas: ticker, passed (filtros), quality_score, value_central, price,
    margin_of_safety. Añade priority, selected y weight, y devuelve el DataFrame ordenado
    por priority descendente (NaN al final).

    Args:
        candidates: Tabla de candidatos con las señales de las etapas 2–5.

    Returns:
        DataFrame con priority/selected/weight. `selected` marca las empresas que cumplen
        los tres requisitos y caen dentro del tope; su `weight` es equiponderado (1/n).
    """
    min_margin = get_config("portfolio.min_margin_of_safety", 0.30)
    min_quality = get_config("quality.min_quality_score", 0.50)
    max_positions = get_config("portfolio.max_positions", 15)
    q_weight = get_config("portfolio.quality_weight", 0.50)
    m_weight = get_config("portfolio.margin_weight", 0.50)

    df = candidates.copy()
    df["priority"] = [
        priority_score(q, m, q_weight, m_weight)
        for q, m in zip(df["quality_score"], df["margin_of_safety"], strict=False)
    ]

    # Elegibles: pasan filtros, valor positivo, margen y calidad por encima del mínimo.
    # Se guarda como columna para que viaje con cada fila al ordenar.
    df["eligible"] = (
        df["passed"].fillna(False).astype(bool)
        & (df["value_central"] > 0)
        & (df["margin_of_safety"] >= min_margin)
        & (df["quality_score"] >= min_quality)
    )

    df = df.sort_values("priority", ascending=False, na_position="last").reset_index(drop=True)

    # Seleccionar hasta el tope, por orden de prioridad (ya ordenado).
    selected_idx = df.index[df["eligible"]].tolist()[:max_positions]
    df["selected"] = df.index.isin(selected_idx)

    n = len(selected_idx)
    df["weight"] = np.where(df["selected"], 1.0 / n if n > 0 else np.nan, 0.0)

    # Orden final: las seleccionadas primero (por prioridad), luego el resto.
    df = df.sort_values(
        ["selected", "priority"], ascending=[False, False], na_position="last"
    ).reset_index(drop=True)
    return df.drop(columns="eligible")
