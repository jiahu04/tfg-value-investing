"""
http_client.py — Cliente HTTP para las peticiones a la SEC.

La SEC exige identificar las peticiones con un User-Agent que incluya un correo de
contacto y limita el ritmo a unas 10 peticiones por segundo. Este módulo encapsula
esas reglas: una sesión reutilizable con el User-Agent correcto, una pausa
configurable entre peticiones y reintentos ante errores transitorios (429/503).

No se ejecuta red en las pruebas: los módulos que usan este cliente reciben sus
funciones de descarga por inyección o se *mockean* (ver tests).
"""

from __future__ import annotations

import time

import requests

from src.utils.config_loader import get_config

# Errores HTTP que justifican un reintento (rate limit / servicio no disponible)
_RETRIABLE_STATUS = {429, 503}


def build_session() -> requests.Session:
    """Crea una sesión `requests` con el User-Agent que exige la SEC.

    El User-Agent incluye el correo de contacto de `sec.contact_email`. La SEC no
    usa claves de API: este correo es el único identificador requerido.
    """
    email = get_config("sec.contact_email", "")
    if not email or "@" not in email:
        raise ValueError(
            "Configura un correo válido en sec.contact_email (lo exige la SEC "
            "para identificar las peticiones; no es una clave de API)."
        )
    session = requests.Session()
    session.headers.update({"User-Agent": f"TFG value-investing {email}"})
    return session


def get_json(
    url: str,
    session: requests.Session,
    *, #Significa que los siguientes parámetros solo pueden pasarse por nombre (keyword-only).
    delay_seconds: float | None = None,
    max_retries: int | None = None,
) -> dict | list:
    """Descarga una URL y devuelve su contenido JSON, respetando el rate limit.

    Aplica una pausa antes de cada intento (para no superar el límite de la SEC) y
    reintenta ante errores 429/503 con espera creciente.

    Args:
        url: URL a descargar.
        session: Sesión `requests` (de `build_session`).
        delay_seconds: Pausa entre peticiones. Si es None, usa
            `sec.request_delay_seconds`.
        max_retries: Reintentos ante 429/503. Si es None, usa `sec.max_retries`.

    Returns:
        El cuerpo de la respuesta deserializado (dict o list).

    Raises:
        requests.HTTPError: Si la respuesta es un error no recuperable o se agotan
            los reintentos.
    """
    if delay_seconds is None:
        delay_seconds = get_config("sec.request_delay_seconds", 0.15)
    if max_retries is None:
        max_retries = get_config("sec.max_retries", 3)

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        time.sleep(delay_seconds)
        response = session.get(url, timeout=30)
        if response.status_code in _RETRIABLE_STATUS and attempt < max_retries:
            # Espera creciente antes de reintentar (back-off lineal sencillo).
            time.sleep(delay_seconds * (attempt + 1))
            last_error = requests.HTTPError(f"{response.status_code} en {url}")
            continue
        response.raise_for_status()
        return response.json()

    # Solo se llega aquí si se agotaron los reintentos por 429/503.
    raise last_error if last_error else requests.HTTPError(f"Fallo al descargar {url}")
