"""Orden de batalla (``history/units/<TAG>_oob.txt`` y subcarpetas por fecha, wizard §14.2). Iteración 6.

``army = { name location regiment = { name type home } … }``, ``navy = { name location ship = { name type } … }``,
``leader = { name date type personality background picture }`` y relaciones (``relation``, ``military_access``).
La historia del país lo nombra con ``oob = "<archivo>"``. El editor de OOB de la ficha nacional (pestaña
«Ejército») lo edita; las reglas ``army_location_sea``, ``navy_location_inland`` y ``regiment_type_mismatch``
lo comprueban.
"""

from __future__ import annotations

from ..schema import EntitySchema, Field, Group, IdSpec, Int, KeyedFiles, Ref, Section, Text, Word
from ..vfs.paths import VPath


def oob_key(rel: VPath) -> str | None:
    """El id de un OOB es su ruta bajo ``history/units`` sin ``.txt`` (``PRU_oob``, ``1861/PRU_oob``)."""
    parts = VPath.of(rel).parts
    if len(parts) < 3 or not parts[-1].lower().endswith(".txt"):
        return None
    return "/".join(parts[2:])[:-4]


OOB = EntitySchema(
    kind="oob",
    layout=KeyedFiles("history/units", new_name="{name}.txt", key=oob_key),
    ident=IdSpec.FILE("{id}.txt"),
    provides="oob",
    fields=(
        Section("armies", (
            Group("army", (
                Field("name", Text(), required=True),
                Field("location", Ref("province"), required=True, ui="map_pick"),
                Group("regiment", (
                    Field("name", Text()),
                    Field("type", Ref("unit_type")),
                    Field("home", Ref("province")),
                ), repeat=True, widget="table"),
            ), repeat=True, id_field="name"),
        )),
        Section("navies", (
            Group("navy", (
                Field("name", Text(), required=True),
                Field("location", Ref("province"), required=True, ui="map_pick"),
                Group("ship", (Field("name", Text()), Field("type", Ref("unit_type"))), repeat=True,
                      widget="table"),
            ), repeat=True, id_field="name"),
        )),
        Section("leaders", (
            Group("leader", (
                Field("name", Text()),
                Field("date", Word()),
                Field("type", Word()),
                Field("personality", Word()),
                Field("background", Word()),
                Field("picture", Word(), advanced=True),
                Field("prestige", Int(0), advanced=True),
            ), repeat=True, id_field="name", widget="table"),
        ), collapsed=True),
    ),
    unknown="keep",
    hall="nations", section="countries", order=1, icon="countries",
    editable=True,
)

SCHEMAS = (OOB,)
