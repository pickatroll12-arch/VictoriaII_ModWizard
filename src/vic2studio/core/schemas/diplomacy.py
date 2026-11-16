"""Diplomacia de inicio (``history/diplomacy/*.txt``, wizard §14.2 «Diplomacia»). Iteración 6.

Bloques repetidos ``alliance``, ``vassal``, ``substate``, ``union`` y ``guarantee``, cada uno con ``first``,
``second``, ``start_date`` y ``end_date`` (vanilla: 4 archivos). El id de un registro es el nombre del archivo. La
sala Guerra › Diplomacia los enseña en una tabla filtrable por TAG y los añade o quita sin pérdidas
(``core.domain.war``).
"""

from __future__ import annotations

from ..schema import Date, EntitySchema, Field, Group, IdSpec, KeyedFiles, Ref, Section
from ..vfs.paths import VPath


def diplomacy_key(rel: VPath) -> str | None:
    name = VPath.of(rel).name
    return name[:-4] if name.lower().endswith(".txt") else None


def _relation(key: str) -> Group:
    return Group(key, (
        Field("first", Ref("tag"), required=True),
        Field("second", Ref("tag"), required=True),
        Field("start_date", Date()),
        Field("end_date", Date()),
    ), repeat=True, widget="table")


DIPLOMACY = EntitySchema(
    kind="diplomacy",
    layout=KeyedFiles("history/diplomacy", new_name="{name}.txt", key=diplomacy_key),
    ident=IdSpec.FILE("{id}.txt"),
    provides="diplomacy",
    fields=(Section("relations", tuple(_relation(key) for key in
                                       ("alliance", "vassal", "substate", "union", "guarantee"))),),
    unknown="keep",
    hall="war", section="diplomacy", order=3, icon="handshake",
    editable=True,
)

SCHEMAS = (DIPLOMACY,)
