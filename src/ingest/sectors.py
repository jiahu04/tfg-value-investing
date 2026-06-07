"""
sectors.py — Agrupación de códigos SIC en sectores.

La SEC asocia a cada empresa un código SIC (Standard Industrial Classification).
Aquí se traduce ese código numérico al sector del proyecto según los rangos
definidos en `sectors.sic_groups` de la configuración. Las etiquetas de los
sectores excluidos (Banking, Insurance, Utilities) deben coincidir con
`filters.excluded_sectors`.

Función pura y testeable; no accede a red.
"""

from __future__ import annotations

from src.utils.config_loader import get_config


def sic_to_sector(
    sic: int | str | None,
    sic_groups: dict[str, list] | None = None,
    default: str | None = None,
) -> str:
    """Traduce un código SIC a su sector según los rangos configurados.

    Args:
        sic: Código SIC (int o str). Si es None o no es numérico, se devuelve `default`.
        sic_groups: Mapa sector -> lista de rangos [desde, hasta] (inclusive). Si es
            None, se toma de `sectors.sic_groups`.
        default: Sector para los SIC que no caen en ningún rango. Si es None, se toma
            de `sectors.default`.

    Returns:
        Nombre del sector.
    """
    if sic_groups is None:
        sic_groups = get_config("sectors.sic_groups", {})
    if default is None:
        default = get_config("sectors.default", "Other")

    try:
        code = int(sic)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

    for sector, ranges in sic_groups.items():
        for low, high in ranges:
            if low <= code <= high:
                return sector
    return default
