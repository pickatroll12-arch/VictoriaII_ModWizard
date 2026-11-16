"""Sala Eventos (Ctrl+5): Event Studio, decisiones y modificadores en la iteración 7 (wizard §12, §14.5, §14.7).

Eventos y Decisiones son páginas propias (``studio.py``) que alojan sus esquemas; Modificadores es la sección que
genera el esquema ``event_modifier`` (sustituye a la tarjeta planificada).
"""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec


def _events(session):
    from .studio import EventStudioPage

    return EventStudioPage(session)


def _decisions(session):
    from .studio import DecisionStudioPage

    return DecisionStudioPage(session)


HALL = HallSpec("events", 5, N_("hall.events.plate"), N_("nav.events"), N_("hall.events.subtitle"), "events")

SECTIONS = [
    SectionSpec("events", "events", 1, N_("section.events.events"), "events", factory=_events, iteration=7,
                planned_keys=(
        N_("events.intro"), N_("events.f.types"), N_("events.f.vanilla"), N_("events.f.header"),
        N_("events.f.picture"), N_("events.f.logic"), N_("events.f.conditions"), N_("events.f.mtth"),
        N_("events.f.mtth_mods"), N_("events.f.options"), N_("events.f.ai_chance"), N_("events.f.localisation"),
    ), hosts=("event",)),
    SectionSpec("decisions", "events", 2, N_("section.events.decisions"), "quill", factory=_decisions,
                iteration=7, planned_keys=(
        N_("section.events.decisions.intro"), N_("section.events.decisions.f1"),
        N_("section.events.decisions.f2"), N_("section.events.decisions.f3"),
    ), hosts=("decision",)),
    SectionSpec("modifiers", "events", 3, N_("section.events.modifiers"), "gear", iteration=7, planned_keys=(
        N_("section.events.modifiers.intro"), N_("section.events.modifiers.f1"),
        N_("section.events.modifiers.f2"),
    )),
]
