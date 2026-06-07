"""Tests de sec_facts: parseo de companyfacts conservando la fecha de publicación.

Cubre la base anti-look-ahead del TFG: cada hecho conserva su `filed` y las
reexpresiones (mismo concepto/periodo publicado dos veces) se mantienen ambas.
"""

import pandas as pd

from src.ingest.sec_facts import parse_companyfacts

# Conceptos de prueba (incluye un tag us-gaap y uno dei)
CONCEPTS = [
    {"tag": "NetIncomeLoss", "unit": "USD"},
    {"tag": "EntityCommonStockSharesOutstanding", "unit": "shares", "taxonomy": "dei"},
]


def _facts_with_restatement():
    """companyfacts sintético con una reexpresión de NetIncomeLoss del FY2020."""
    return {
        "cik": 320193,
        "entityName": "Test Co",
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "start": "2020-01-01",
                                "end": "2020-12-31",
                                "val": 1000,
                                "fy": 2020,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2021-02-15",
                                "accn": "0001",
                            },
                            {
                                # Misma cuenta/periodo, republicada más tarde con otro valor
                                "start": "2020-01-01",
                                "end": "2020-12-31",
                                "val": 1050,
                                "fy": 2021,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2022-02-15",
                                "accn": "0002",
                            },
                        ]
                    }
                },
                # Concepto que NO está en CONCEPTS: debe ignorarse
                "Goodwill": {"units": {"USD": [{"end": "2020-12-31", "val": 999}]}},
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "end": "2021-01-31",
                                "val": 5000,
                                "form": "10-K",
                                "filed": "2021-02-15",
                                "accn": "0001",
                            }
                        ]
                    }
                }
            },
        },
    }


def test_preserves_filed_date():
    df = parse_companyfacts(_facts_with_restatement(), CONCEPTS, ticker="AAPL")
    assert "filed" in df.columns
    assert df["filed"].notna().all()
    assert pd.Timestamp("2021-02-15") in set(df["filed"])


def test_keeps_both_restatements():
    df = parse_companyfacts(_facts_with_restatement(), CONCEPTS, ticker="AAPL")
    ni = df[df["concept"] == "NetIncomeLoss"]
    # Las dos publicaciones del mismo periodo se conservan
    assert len(ni) == 2
    assert set(ni["val"]) == {1000, 1050}
    assert set(ni["filed"]) == {pd.Timestamp("2021-02-15"), pd.Timestamp("2022-02-15")}


def test_ignores_unconfigured_concepts():
    df = parse_companyfacts(_facts_with_restatement(), CONCEPTS, ticker="AAPL")
    assert "Goodwill" not in set(df["concept"])


def test_extracts_dei_taxonomy():
    df = parse_companyfacts(_facts_with_restatement(), CONCEPTS, ticker="AAPL")
    dei = df[df["concept"] == "EntityCommonStockSharesOutstanding"]
    assert len(dei) == 1
    assert dei["taxonomy"].iloc[0] == "dei"
    assert dei["val"].iloc[0] == 5000


def test_metadata_columns_filled():
    df = parse_companyfacts(_facts_with_restatement(), CONCEPTS, ticker="aapl")
    assert (df["ticker"] == "AAPL").all()
    assert (df["cik"] == "0000320193").all()


def test_empty_facts_returns_empty_frame():
    df = parse_companyfacts({"cik": 1, "facts": {}}, CONCEPTS)
    assert df.empty
