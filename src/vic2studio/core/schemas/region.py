"""Regiones (estados) de tierra (``map/region.txt``, wizard §16.5, §22). Contrato de la iteración 5.

``<REGION> = { <ids de provincia> }``: el bloque es la lista (``Values``). Vanilla: 549 regiones, ninguna vacía.
Una provincia de tierra debe estar en una región y solo en una (``land_province_without_region``,
``land_province_multiple_regions``); una de mar no puede estar en ninguna (``sea_in_region``). El nombre visible
es el texto de la clave ``<REGION>``.

Mover provincias entre regiones va por ``core.map.groups.ProvinceGroups`` (una transacción por gesto); el
esquema da la lista, la referencia y la creación de una región nueva. Nace con ``editable=False``: la cadena A
lo cambia cuando ``Values`` se pueda editar. Su página es la sección «Regiones» de la sala Mapa.
"""

from __future__ import annotations

from ..schema import EntitySchema, Int, LocSpec, SingleFile, Values
from ..vfs.rules import LoadMode

REGION = EntitySchema(
    kind="region",
    layout=SingleFile("map/region.txt", merge=LoadMode.MAP_BUNDLE),
    provides="region",
    fields=(Values(Int(1)),),
    loc=(LocSpec("{id}", "regions"),),
    unknown="keep",
    hall="map", section="regions", order=3, icon="layers",
    editable=False,
)

SCHEMAS = (REGION,)
