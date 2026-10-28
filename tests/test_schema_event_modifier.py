"""Esquema ``event_modifier`` con el arnés (wizard §19.3)."""

import schema_harness
from vic2studio.core.schemas.event_modifier import EVENT_MODIFIER


class EventModifierContract(schema_harness.SchemaContract):
    schema = EVENT_MODIFIER
    corpus = "common/event_modifiers.txt"
    allowed = {}
