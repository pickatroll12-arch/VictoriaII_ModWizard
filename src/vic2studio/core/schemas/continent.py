"""Continentes (``map/continent.txt``, wizard §16.5, §22). Contrato de la iteración 5.

``<continente> = { provinces = { <ids> } <modificadores> }``: la lista va en la clave ``provinces`` y el resto
del bloque son efectos de modificador (catálogo abierto, como ``event_modifier``). Vanilla: 6 continentes.
Toda provincia de tierra debe estar en uno (``land_province_without_continent``). Las provincias se mueven con
``core.map.groups.ProvinceGroups(layout="provinces_key")``. Nace con ``editable=False``; su página es la
sección «Continentes y climas» de la sala Mapa.
"""

from __future__ import annotations

from ..schema import DynamicKeys, EntitySchema, Field, Float, Int, ListOf, LocSpec, Section, SingleFile
from ..schema.fields import OPEN_CATALOG
from ..vfs.rules import LoadMode

CONTINENT = EntitySchema(
    kind="continent",
    layout=SingleFile("map/continent.txt", merge=LoadMode.MAP_BUNDLE),
    provides="continent",
    fields=(
        Section("provinces", (Field("provinces", ListOf(Int(1), unique=True), required=True, ui="map_pick"),)),
        Section("effects", (DynamicKeys("effects", OPEN_CATALOG, Float(), widget="table"),)),
    ),
    loc=(LocSpec("{id}", "regions"),),
    unknown="keep",
    hall="map", section="climates", order=5, icon="climate",
    editable=False,
)

SCHEMAS = (CONTINENT,)
