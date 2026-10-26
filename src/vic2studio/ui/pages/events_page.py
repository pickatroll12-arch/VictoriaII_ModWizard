"""Estudio de Eventos (iteración 5): constructor visual planificado."""

from __future__ import annotations

from ...i18n import N_
from .planned import FeatureGroup, PlannedModulePage


class EventsPage(PlannedModulePage):
    key = "events"
    title_key = N_("nav.events")
    subtitle_key = N_("page.events.subtitle")
    icon_name = "events"
    iteration = 5
    intro_key = N_("events.intro")
    groups = (
        FeatureGroup(N_("events.group.types"), (N_("events.f.types"), N_("events.f.vanilla")), "events"),
        FeatureGroup(N_("events.group.header"), (N_("events.f.header"), N_("events.f.picture")), "quill"),
        FeatureGroup(N_("events.group.triggers"), (N_("events.f.logic"), N_("events.f.conditions")), "gear"),
        FeatureGroup(N_("events.group.mtth"), (N_("events.f.mtth"), N_("events.f.mtth_mods")), "refresh"),
        FeatureGroup(N_("events.group.options"), (N_("events.f.options"), N_("events.f.ai_chance")), "check"),
        FeatureGroup(N_("events.group.sync"), (N_("events.f.localisation"),), "localisation"),
    )
