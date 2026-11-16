"""Guerras de inicio (``history/wars/<Nombre>.txt``, wizard §14.8). Iteración 6.

Un archivo por guerra; su id es el nombre del archivo. ``name = "…"`` y bloques fechados que son **sucesos**
(``HistorySpec("log")``): ``add_attacker``, ``add_defender``, ``rem_attacker``, ``rem_defender`` y
``war_goal = { casus_belli actor receiver [state_province_id] [country] }``. Vanilla trae 5. La sala Guerra ›
Guerras de inicio las enseña en una línea temporal y el asistente «Nueva guerra» (``core.domain.war``) las crea.
"""

from __future__ import annotations

from ..schema import EntitySchema, Field, HistorySpec, IdSpec, KeyedFiles, Section, Text
from ..vfs.paths import VPath


def war_key(rel: VPath) -> str | None:
    name = VPath.of(rel).name
    return name[:-4] if name.lower().endswith(".txt") else None


WAR = EntitySchema(
    kind="war",
    layout=KeyedFiles("history/wars", new_name="{name}.txt", key=war_key),
    ident=IdSpec.FILE("{id}.txt"),
    provides="war",
    history=HistorySpec("log"),
    fields=(Section("general", (Field("name", Text()),)),),
    unknown="keep",
    hall="war", section="wars", order=2, icon="swords",
    editable=True,
)

SCHEMAS = (WAR,)
