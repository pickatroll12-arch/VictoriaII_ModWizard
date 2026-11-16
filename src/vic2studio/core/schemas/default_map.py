"""Ajustes del mapa (``map/default.map``, wizard §16.1, §22). Contrato de la iteración 5.

Un archivo, un registro (``WholeFile``, id fijo ``default_map``). Vanilla: 18 claves; ``max_provinces = 3249``
(un id válido cumple ``1 ≤ id < max_provinces``) y ``sea_starts`` con 546 valores para 545 ids distintos (uno
está dos veces seguidas: ``sea_start_duplicate``, decisión 4 del informe). El resto son nombres de archivo de
``map/`` (los BMP, ``definition.csv``, ``positions.txt``…) y ajustes que el Studio conserva sin tocar.

La lista ``sea_starts`` y ``max_provinces`` se editan con ``core.map.default_map.DefaultMap``, que conserva el
orden y los duplicados; el esquema declara las claves para la referencia y la validación. ``editable=False``:
no tiene lista ni «Nuevo»; se ve desde «Mundo».
"""

from __future__ import annotations

from ..schema import EntitySchema, Field, Int, ListOf, Section, Text, WholeFile

IDENT = "default_map"
FILE_KEYS = ("definitions", "provinces", "positions", "terrain", "rivers", "terrain_definition", "tree_definition",
             "continent", "adjacencies", "region", "region_sea", "province_flag_sprite")

DEFAULT_MAP = EntitySchema(
    kind="default_map",
    layout=WholeFile("map/default.map", IDENT),
    fields=(
        Section("provinces", (
            Field("max_provinces", Int(2), required=True),
            Field("sea_starts", ListOf(Int(1)), required=True, ui="map_pick"),
        )),
        Section("files", tuple(Field(key, Text(), advanced=True) for key in FILE_KEYS), collapsed=True),
    ),
    unknown="keep",
    hall="map", section="world", order=8, icon="map",
    editable=False,
)

SCHEMAS = (DEFAULT_MAP,)
