"""Regiones de mar (``map/region_sea.txt``, wizard §16.5, §22). Contrato de la iteración 5.

Misma forma que ``map/region.txt``, pero el archivo de vanilla solo trae 3 regiones y las 3 están vacías (y sus
saltos de línea son CR solos): el juego no exige que una provincia de mar esté en una región. Aquí una región
vacía no avisa (``region_empty`` es solo de las de tierra). Se editan con ``core.map.groups.ProvinceGroups``.
Nace con ``editable=False``; su página es la sección «Regiones» de la sala Mapa, junto a las de tierra.
"""

from __future__ import annotations

from ..schema import EntitySchema, Int, LocSpec, SingleFile, Values
from ..vfs.rules import LoadMode

REGION_SEA = EntitySchema(
    kind="region_sea",
    layout=SingleFile("map/region_sea.txt", merge=LoadMode.MAP_BUNDLE),
    provides="sea_region",
    fields=(Values(Int(1)),),
    loc=(LocSpec("{id}", "regions", required=False),),
    unknown="keep",
    hall="map", section="regions", order=4, icon="layers",
    editable=False,
)

SCHEMAS = (REGION_SEA,)
