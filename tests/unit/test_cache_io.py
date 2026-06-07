"""Tests de cache_io: ida y vuelta de Parquet/CSV/JSON y frescura de ficheros."""

import os
import time

import pandas as pd

from src.ingest import cache_io


def test_parquet_round_trip(tmp_path):
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    path = tmp_path / "sub" / "data.parquet"
    cache_io.write_parquet(df, path)
    assert path.exists()  # crea el directorio padre
    loaded = cache_io.read_parquet(path)
    pd.testing.assert_frame_equal(df, loaded)


def test_csv_round_trip(tmp_path):
    df = pd.DataFrame({"ticker": ["AAPL"], "sector": ["Manufacturing"]})
    path = tmp_path / "sectors.csv"
    cache_io.write_csv(df, path)
    loaded = cache_io.read_csv(path)
    pd.testing.assert_frame_equal(df, loaded)


def test_json_round_trip(tmp_path):
    data = {"cik": 320193, "facts": {"us-gaap": {}}}
    path = tmp_path / "raw.json"
    cache_io.write_json(data, path)
    assert cache_io.read_json(path) == data


def test_is_fresh_recent_file(tmp_path):
    path = tmp_path / "f.txt"
    path.write_text("x", encoding="utf-8")
    assert cache_io.is_fresh(path, max_age_days=1) is True


def test_is_fresh_old_file(tmp_path):
    path = tmp_path / "f.txt"
    path.write_text("x", encoding="utf-8")
    # Envejecer el fichero 10 días
    old = time.time() - 10 * 86400
    os.utime(path, (old, old))
    assert cache_io.is_fresh(path, max_age_days=7) is False


def test_is_fresh_missing_file(tmp_path):
    assert cache_io.is_fresh(tmp_path / "noexiste.txt", max_age_days=7) is False
