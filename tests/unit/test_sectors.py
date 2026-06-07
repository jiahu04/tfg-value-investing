"""Tests de sectors: agrupación de códigos SIC en sectores."""

from src.ingest.sectors import sic_to_sector

SIC_GROUPS = {
    "Manufacturing": [[2000, 3999]],
    "Utilities": [[4900, 4999]],
    "Banking": [[6000, 6199]],
    "Finance": [[6200, 6299], [6500, 6799]],
    "Insurance": [[6300, 6499]],
}


def test_excluded_sectors_mapped():
    # Las etiquetas deben coincidir con filters.excluded_sectors
    assert sic_to_sector(6021, SIC_GROUPS, "Other") == "Banking"
    assert sic_to_sector(6311, SIC_GROUPS, "Other") == "Insurance"
    assert sic_to_sector(4911, SIC_GROUPS, "Other") == "Utilities"


def test_manufacturing_range():
    assert sic_to_sector(3571, SIC_GROUPS, "Other") == "Manufacturing"


def test_multiple_ranges_per_sector():
    assert sic_to_sector(6200, SIC_GROUPS, "Other") == "Finance"
    assert sic_to_sector(6770, SIC_GROUPS, "Other") == "Finance"


def test_string_sic_accepted():
    assert sic_to_sector("6021", SIC_GROUPS, "Other") == "Banking"


def test_unknown_sic_returns_default():
    assert sic_to_sector(100, SIC_GROUPS, "Other") == "Other"


def test_none_and_invalid_return_default():
    assert sic_to_sector(None, SIC_GROUPS, "Other") == "Other"
    assert sic_to_sector("", SIC_GROUPS, "Other") == "Other"
    assert sic_to_sector("abc", SIC_GROUPS, "Other") == "Other"


def test_uses_config_when_args_omitted():
    # Sin pasar grupos, usa config.yaml (Banking 6000-6199)
    assert sic_to_sector(6021) == "Banking"
