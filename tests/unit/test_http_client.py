"""Tests del cliente HTTP (`http_client.get_json`): reintentos sin red real.

Comprueban el back-off ante 429/503 y ante cortes de conexión transitorios
(ConnectionError/ChunkedEncodingError), usando una sesión falsa programable.
"""

import pytest
import requests

from src.ingest import http_client


class _FakeResponse:
    """Respuesta mínima compatible con lo que usa `get_json`."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


class _ScriptedSession:
    """Sesión falsa: cada `get` consume una acción (excepción a lanzar o status a devolver)."""

    def __init__(self, actions: list, payload):
        self.actions = list(actions)
        self.payload = payload
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        action = self.actions.pop(0) if self.actions else 200
        if isinstance(action, Exception):
            raise action
        return _FakeResponse(self.payload, status_code=action)


def test_retries_on_connection_error_then_succeeds():
    sess = _ScriptedSession([requests.ConnectionError("reset"), 200], {"ok": 1})
    out = http_client.get_json("http://x", sess, delay_seconds=0, max_retries=2)
    assert out == {"ok": 1}
    assert sess.calls == 2  # 1 corte + 1 éxito


def test_retries_on_chunked_encoding_error():
    sess = _ScriptedSession([requests.exceptions.ChunkedEncodingError("broken"), 200], {"ok": 2})
    out = http_client.get_json("http://x", sess, delay_seconds=0, max_retries=2)
    assert out == {"ok": 2}
    assert sess.calls == 2


def test_raises_after_exhausting_connection_retries():
    sess = _ScriptedSession(
        [
            requests.ConnectionError("a"),
            requests.ConnectionError("b"),
            requests.ConnectionError("c"),
        ],
        {"ok": 3},
    )
    with pytest.raises(requests.ConnectionError):
        http_client.get_json("http://x", sess, delay_seconds=0, max_retries=2)
    assert sess.calls == 3  # max_retries + 1 intentos, todos fallan


def test_still_retries_on_429():
    # Comprueba que el comportamiento previo (reintento ante 429) se conserva
    sess = _ScriptedSession([429, 200], {"ok": 4})
    out = http_client.get_json("http://x", sess, delay_seconds=0, max_retries=2)
    assert out == {"ok": 4}
    assert sess.calls == 2


def test_success_without_retries():
    sess = _ScriptedSession([200], {"ok": 5})
    out = http_client.get_json("http://x", sess, delay_seconds=0, max_retries=2)
    assert out == {"ok": 5}
    assert sess.calls == 1
