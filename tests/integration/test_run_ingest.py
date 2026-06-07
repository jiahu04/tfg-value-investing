"""Test de integración del orquestador de ingesta con la red *mockeada*.

Cubre el criterio "Hecho cuando" del paso 1.1: una ejecución completa puebla la
caché y los ficheros se pueden recargar desde disco. No se hace red real: todas
las descargas se sustituyen por datos sintéticos.
"""

import numpy as np
import pandas as pd

from src.ingest import (
    cache_io,
    constituents,
    prices,
    run_ingest,
    sec_facts,
    sec_submissions,
    sec_tickers,
)

# --- Datos sintéticos que reemplazan a las descargas reales ---------------------

FAKE_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft"},
}

FAKE_CONSTITUENTS_CSV = 'date,tickers\n2015-01-01,"AAPL,MSFT,IBM"\n2020-03-01,"AAPL,MSFT,NVDA"\n'


def _fake_companyfacts(cik, session):
    return {
        "cik": int(cik),
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "start": "2019-01-01",
                                "end": "2019-12-31",
                                "val": 100,
                                "fy": 2019,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2020-02-01",
                                "accn": "a1",
                            }
                        ]
                    }
                }
            }
        },
    }


def _fake_submissions(cik, session):
    return {
        "cik": cik,
        "name": f"Co {cik}",
        "sic": "3571",
        "sicDescription": "Electronic Computers",
    }


def _fake_download_prices(tickers, start, end):
    idx = pd.DatetimeIndex(["2020-01-02", "2020-01-03"], name="Date")
    if len(tickers) > 1:
        cols = pd.MultiIndex.from_product([["Close"], list(tickers)])
        data = np.arange(len(idx) * len(tickers), dtype=float).reshape(len(idx), len(tickers))
        return pd.DataFrame(data + 1, index=idx, columns=cols)
    return pd.DataFrame({"Open": [1.0, 2.0], "Close": [1.5, 2.5]}, index=idx)


def _patch_all(monkeypatch, tmp_path):
    """Redirige caché a tmp_path y sustituye todas las descargas por datos falsos."""
    monkeypatch.setattr(cache_io, "raw_dir", lambda: tmp_path / "raw")
    monkeypatch.setattr(cache_io, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(run_ingest, "build_session", lambda: None)
    monkeypatch.setattr(sec_tickers, "download_company_tickers", lambda s: FAKE_TICKERS)
    monkeypatch.setattr(constituents, "download_constituents", lambda s=None: FAKE_CONSTITUENTS_CSV)
    monkeypatch.setattr(sec_facts, "download_companyfacts", _fake_companyfacts)
    monkeypatch.setattr(sec_submissions, "download_submissions", _fake_submissions)
    monkeypatch.setattr(prices, "download_prices", _fake_download_prices)


def test_run_all_populates_and_reloads_cache(monkeypatch, tmp_path):
    _patch_all(monkeypatch, tmp_path)

    run_ingest.run("all", force=True)

    cache = tmp_path / "cache"
    expected = [
        "tickers.parquet",
        "constituents.parquet",
        "sectors.csv",
        "fundamentals.parquet",
        "prices.parquet",
        "index_prices.parquet",
        "risk_free.parquet",
    ]
    for name in expected:
        assert (cache / name).exists(), f"falta {name}"

    # Recarga desde disco: los fundamentales conservan la fecha de publicación
    fundamentals = cache_io.read_parquet(cache / "fundamentals.parquet")
    assert not fundamentals.empty
    assert "filed" in fundamentals.columns
    assert fundamentals["filed"].notna().all()

    # Sectores asignados a partir del SIC
    sectors = cache_io.read_csv(cache / "sectors.csv")
    assert "sector" in sectors.columns
    assert (sectors["sector"] == "Manufacturing").all()  # SIC 3571

    # Precios de las dos empresas del universo
    px = cache_io.read_parquet(cache / "prices.parquet")
    assert set(px["ticker"]) == {"AAPL", "MSFT"}


def test_reload_from_raw_without_redownload(monkeypatch, tmp_path):
    """Tras una ingesta, reconstruir sin --force no debe llamar a la red."""
    _patch_all(monkeypatch, tmp_path)
    run_ingest.run("all", force=True)

    # Si se vuelve a llamar a las descargas, fallar el test
    def _boom(*args, **kwargs):
        raise AssertionError("no debería descargar de nuevo sin --force")

    monkeypatch.setattr(sec_tickers, "download_company_tickers", _boom)
    monkeypatch.setattr(constituents, "download_constituents", _boom)
    monkeypatch.setattr(sec_facts, "download_companyfacts", _boom)
    monkeypatch.setattr(sec_submissions, "download_submissions", _boom)

    # Reconstruye desde el crudo (sin red); los precios sí pueden recargarse de caché
    run_ingest.run("fundamentals", force=False)
    run_ingest.run("sectors", force=False)

    fundamentals = cache_io.read_parquet(tmp_path / "cache" / "fundamentals.parquet")
    assert not fundamentals.empty
