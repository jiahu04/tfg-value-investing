"""Tests de sec_submissions: extracción de SIC, nombre y metadatos."""

from src.ingest.sec_submissions import parse_submissions


def test_parse_submissions_extracts_fields():
    data = {
        "cik": "320193",
        "name": "Apple Inc.",
        "sic": "3571",
        "sicDescription": "Electronic Computers",
    }
    meta = parse_submissions(data, ticker="aapl")
    assert meta["ticker"] == "AAPL"
    assert meta["cik"] == "0000320193"
    assert meta["sic"] == "3571"
    assert meta["sic_description"] == "Electronic Computers"
    assert meta["name"] == "Apple Inc."


def test_parse_submissions_missing_sic():
    meta = parse_submissions({"cik": "1", "name": "X"}, ticker="X")
    assert meta["sic"] == ""
    assert meta["sic_description"] == ""
