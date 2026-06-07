"""
test_config_loader.py — Paso 0.4: pruebas del cargador de configuración.

Ejecutar con:
    pytest tests/unit/test_config_loader.py -v
"""

from __future__ import annotations

import pytest

from src.utils.config_loader import get_config, load_config, reload_config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_config_cache():
    """Limpia la caché del config loader antes y después de cada test."""
    load_config.cache_clear()
    yield
    load_config.cache_clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_loads_default_config(self):
        """La configuración por defecto se carga sin errores."""
        cfg = load_config()
        assert isinstance(cfg, dict)
        assert len(cfg) > 0

    def test_required_sections_present(self):
        """Las secciones principales del sistema existen en config.yaml."""
        cfg = load_config()
        expected_sections = {"sec", "universe", "prices", "cache", "filters",
                             "quality", "valuation", "portfolio", "backtest",
                             "contributions", "outputs"}
        missing = expected_sections - set(cfg.keys())
        assert not missing, f"Secciones ausentes en config.yaml: {missing}"

    def test_file_not_found_raises(self, tmp_path):
        """FileNotFoundError si el fichero no existe."""
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "no_existe.yaml")

    def test_caching_returns_same_object(self):
        """Dos llamadas sucesivas devuelven el mismo objeto (cacheado)."""
        cfg1 = load_config()
        cfg2 = load_config()
        assert cfg1 is cfg2

    def test_reload_returns_fresh_object(self):
        """reload_config fuerza la relectura desde disco."""
        cfg1 = load_config()
        cfg2 = reload_config()
        # No es el mismo objeto (se ha recargado)
        assert cfg1 is not cfg2
        # Pero el contenido es idéntico
        assert cfg1 == cfg2


class TestGetConfig:
    def test_top_level_key(self):
        """Acceso a clave de primer nivel."""
        sec = get_config("sec")
        assert isinstance(sec, dict)

    def test_nested_key(self):
        """Acceso a clave anidada con notación de puntos."""
        url = get_config("sec.base_url")
        assert isinstance(url, str)
        assert url.startswith("https://")

    def test_missing_key_returns_default(self):
        """Una clave inexistente devuelve el valor por defecto."""
        result = get_config("clave.que.no.existe", default="fallback")
        assert result == "fallback"

    def test_missing_key_returns_none_by_default(self):
        """Sin default explícito, una clave inexistente devuelve None."""
        result = get_config("clave.inexistente")
        assert result is None

    def test_numeric_values(self):
        """Los valores numéricos se cargan como float/int, no como string."""
        max_pos = get_config("portfolio.max_positions")
        assert isinstance(max_pos, int)
        assert max_pos > 0

        mos = get_config("portfolio.min_margin_of_safety")
        assert isinstance(mos, float)
        assert 0.0 < mos < 1.0
