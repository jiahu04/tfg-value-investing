"""Tests del context manager config_override (paso 2.2)."""

from src.utils.config_loader import config_override, get_config


def test_override_and_restore():
    original = get_config("portfolio.min_margin_of_safety")
    with config_override({"portfolio.min_margin_of_safety": 0.99}):
        assert get_config("portfolio.min_margin_of_safety") == 0.99
    assert get_config("portfolio.min_margin_of_safety") == original


def test_override_new_key_is_removed_on_exit():
    with config_override({"portfolio.__tmp__": 123}):
        assert get_config("portfolio.__tmp__") == 123
    assert get_config("portfolio.__tmp__") is None


def test_override_multiple_keys():
    with config_override({"portfolio.min_margin_of_safety": 0.1, "quality.min_quality_score": 0.9}):
        assert get_config("portfolio.min_margin_of_safety") == 0.1
        assert get_config("quality.min_quality_score") == 0.9
    # ambos restaurados
    assert get_config("portfolio.min_margin_of_safety") != 0.1
