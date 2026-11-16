"""Categorías de terreno (``map/terrain.txt`` → ``categories``, wizard §16.2, §22). Contrato de la iteración 5.

``categories = { <terreno> = { color = { r g b } is_water = yes <modificadores> } }`` (vanilla: 13 categorías).
El resto del archivo asocia los índices de la paleta de ``map/terrain.bmp`` a una categoría
(``<nombre> = { type = <terreno> color = { <índices> } priority has_texture }``; vanilla: 66 entradas, una con 191
índices): eso lo lee ``core.map.facts.terrain_types``, no este esquema. Solo lectura en la iteración 5
(``editable=False`` para siempre en este corte): alimenta el modo de mapa de terreno, la leyenda y el selector
``Ref("terrain")`` de la historia de provincia.
"""

from __future__ import annotations

from ..schema import Bool, Color, DynamicKeys, EntitySchema, Field, Float, LocSpec, NestedIn, Section
from ..schema.fields import OPEN_CATALOG
from ..vfs.rules import LoadMode

TERRAIN = EntitySchema(
    kind="terrain",
    layout=NestedIn("map/terrain.txt", "categories", "map/terrain.txt", merge=LoadMode.MAP_BUNDLE),
    provides="terrain",
    fields=(
        Section("general", (
            Field("color", Color()),
            Field("is_water", Bool()),
        )),
        Section("effects", (DynamicKeys("effects", OPEN_CATALOG, Float(), widget="table"),)),
    ),
    loc=(LocSpec("{id}", "terrain", required=False),),
    unknown="keep",
    hall="map", section="world", order=7, icon="map",
    editable=False,
)

SCHEMAS = (TERRAIN,)
