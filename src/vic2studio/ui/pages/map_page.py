"""Editor de Mapa (iteración 5): de momento, tarjeta de funcionalidades planificadas."""

from __future__ import annotations

from ...i18n import N_
from .planned import FeatureGroup, PlannedModulePage


class MapPage(PlannedModulePage):
    key = "map"
    title_key = N_("nav.map")
    subtitle_key = N_("page.map.subtitle")
    icon_name = "map"
    iteration = 5
    intro_key = N_("map.intro")
    groups = (
        FeatureGroup(N_("map.group.canvas"), (N_("map.f.canvas"), N_("map.f.modes"), N_("map.f.live")), "map"),
        FeatureGroup(N_("map.group.province"), (
            N_("map.f.ownership"), N_("map.f.resources"), N_("map.f.buildings"), N_("map.f.pops"),
        ), "project"),
        FeatureGroup(N_("map.group.nation"), (
            N_("map.f.tech"), N_("map.f.politics"), N_("map.f.economy"),
        ), "countries"),
        FeatureGroup(N_("map.group.storage"), (N_("map.f.storage"), N_("map.f.vanilla")), "folder"),
    )
