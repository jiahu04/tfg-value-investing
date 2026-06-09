"""Tests de la regla de cartera (paso 1.6)."""

import pandas as pd
import pytest

from src.pipeline import portfolio
from src.pipeline.portfolio import build_portfolio, margin_of_safety, priority_score


# --- margin_of_safety ------------------------------------------------------------
def test_margin_of_safety_discount():
    # Compro a 70 algo que vale 100 -> 30 % de margen
    assert margin_of_safety(100.0, 70.0) == pytest.approx(0.30)


def test_margin_of_safety_negative_when_overpriced():
    assert margin_of_safety(100.0, 120.0) == pytest.approx(-0.20)


def test_margin_of_safety_invalid_value_is_nan():
    assert pd.isna(margin_of_safety(0.0, 70.0))
    assert pd.isna(margin_of_safety(-50.0, 70.0))
    assert pd.isna(margin_of_safety(float("nan"), 70.0))


# --- priority_score --------------------------------------------------------------
def test_priority_score_weighted():
    # 0.5*0.8 + 0.5*0.4 = 0.6
    assert priority_score(0.8, 0.4, 0.5, 0.5) == pytest.approx(0.6)


def test_priority_score_nan_propagates():
    assert pd.isna(priority_score(float("nan"), 0.4, 0.5, 0.5))


# --- build_portfolio -------------------------------------------------------------
def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # ticker, passed, quality, value, price, margin
            ("GOOD", True, 0.80, 100.0, 60.0, 0.40),  # elegible
            ("GOOD2", True, 0.70, 100.0, 65.0, 0.35),  # elegible (prioridad menor)
            ("CHEAPJUNK", True, 0.40, 100.0, 50.0, 0.50),  # calidad < 0.5 -> fuera
            ("EXPENSIVE", True, 0.90, 100.0, 95.0, 0.05),  # margen < 0.30 -> fuera
            ("DISCARDED", False, 0.90, 100.0, 30.0, 0.70),  # no pasa filtros -> fuera
        ],
        columns=["ticker", "passed", "quality_score", "value_central", "price", "margin_of_safety"],
    )


def test_build_portfolio_gates_and_ranks():
    out = build_portfolio(_candidates())
    selected = out[out["selected"]]
    # Solo GOOD y GOOD2 cumplen filtros + margen + calidad
    assert set(selected["ticker"]) == {"GOOD", "GOOD2"}
    # Ordenado por prioridad: GOOD (0.60) antes que GOOD2 (0.525)
    assert list(out["ticker"])[:2] == ["GOOD", "GOOD2"]
    # Equiponderación entre los dos seleccionados
    assert selected["weight"].tolist() == [pytest.approx(0.5), pytest.approx(0.5)]
    # Los no seleccionados pesan 0
    assert (out[~out["selected"]]["weight"] == 0.0).all()


def test_build_portfolio_respects_max_positions(monkeypatch):
    def fake_get_config(key, default=None):
        return {
            "portfolio.min_margin_of_safety": 0.30,
            "quality.min_quality_score": 0.50,
            "portfolio.max_positions": 1,  # tope de 1
            "portfolio.quality_weight": 0.50,
            "portfolio.margin_weight": 0.50,
        }.get(key, default)

    monkeypatch.setattr(portfolio, "get_config", fake_get_config)
    out = build_portfolio(_candidates())
    selected = out[out["selected"]]
    # Con tope 1, solo entra la de mayor prioridad (GOOD)
    assert list(selected["ticker"]) == ["GOOD"]
    assert selected["weight"].tolist() == [pytest.approx(1.0)]
