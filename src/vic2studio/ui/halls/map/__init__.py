"""Sala Mapa (Ctrl+2): editor del mapa existente en la iteración 5 y taller de mapas nuevos en la 9 (wizard §16, §18)."""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec

HALL = HallSpec("map", 2, N_("hall.map.plate"), N_("nav.map"), N_("hall.map.subtitle"), "map")

SECTIONS = [
    SectionSpec("world", "map", 1, N_("section.map.world"), "map", iteration=5, planned_keys=(
        N_("map.intro"), N_("map.f.canvas"), N_("map.f.modes"), N_("map.f.live"), N_("map.f.ownership"),
        N_("map.f.resources"), N_("map.f.buildings"), N_("map.f.pops"), N_("map.f.storage"), N_("map.f.vanilla"),
    )),
    SectionSpec("regions", "map", 2, N_("section.map.regions"), "layers", iteration=5, planned_keys=(
        N_("section.map.regions.intro"), N_("section.map.regions.f1"), N_("section.map.regions.f2"),
        N_("section.map.regions.f3"),
    )),
    SectionSpec("climates", "map", 3, N_("section.map.climates"), "climate", iteration=5, planned_keys=(
        N_("section.map.climates.intro"), N_("section.map.climates.f1"), N_("section.map.climates.f2"),
    )),
    SectionSpec("straits", "map", 4, N_("section.map.straits"), "anchor", iteration=5, planned_keys=(
        N_("section.map.straits.intro"), N_("section.map.straits.f1"), N_("section.map.straits.f2"),
    )),
    SectionSpec("forge", "map", 5, N_("section.map.forge"), "anvil", iteration=9, planned_keys=(
        N_("section.map.forge.intro"), N_("section.map.forge.f1"), N_("section.map.forge.f2"),
        N_("section.map.forge.f3"), N_("section.map.forge.f4"),
    )),
]
