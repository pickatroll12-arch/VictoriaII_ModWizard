"""Modificadores de evento (``common/event_modifiers.txt``): ``<id> = { icon = N <efecto> = <valor> … }``.

Vanilla trae 124, todos con valores sueltos. Los efectos (``prestige``, ``research_points_modifier``…) no los
cataloga el índice: son un ``DynamicKeys`` de catálogo abierto. La sección (Eventos › Modificadores) sale sola
del registro: este archivo no toca nada de ``ui/`` (criterio 6 de la iteración 4).
"""

from __future__ import annotations

from ..schema import DynamicKeys, EntitySchema, Field, Float, Int, LocSpec, Section, SingleFile
from ..schema.fields import OPEN_CATALOG

EVENT_MODIFIER = EntitySchema(
    kind="event_modifier",
    layout=SingleFile("common/event_modifiers.txt"),
    provides="modifier",
    fields=(
        Section("general", (Field("icon", Int(0)),)),
        Section("effects", (DynamicKeys("effects", OPEN_CATALOG, Float(), widget="table"),)),
    ),
    loc=(LocSpec("{id}", "modifiers"), LocSpec("{id}_desc", "modifiers", required=False)),
    template=lambda ident, idx: {"icon": 1, "effects": {"prestige": 1.0}},
    hall="events", section="modifiers", order=3, icon="gear",
)

SCHEMAS = (EVENT_MODIFIER,)
