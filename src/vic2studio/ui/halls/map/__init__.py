"""Sala Mapa (Ctrl+2): editor del mapa existente en la iteración 5 y taller de mapas nuevos en la 9 (wizard §16, §18).

Cada sección dice en ``hosts`` qué esquemas del mapa edita en su propia página (los 9 de ``core/schemas`` con
``hall="map"``), para que no generen un ``EntityEditorPage``. Su ``factory`` crea la página
(``ui/halls/map/<sección>.py``), que implementa ``focus_field(ref, field) -> bool`` (lo que llama
``MainWindow.open_entity`` al abrir un problema o un resultado de Ctrl+K).
"""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec


def _world(session):
    from .world import WorldPage

    return WorldPage(session)


def _regions(session):
    from .groups import RegionsPage

    return RegionsPage(session)


def _climates(session):
    from .groups import ClimatesPage

    return ClimatesPage(session)


def _forge(session):
    from .forge import ForgePage

    return ForgePage(session)


def _straits(session):
    from .straits import StraitsPage

    return StraitsPage(session)


HALL = HallSpec("map", 2, N_("hall.map.plate"), N_("nav.map"), N_("hall.map.subtitle"), "map")

SECTIONS = [
    SectionSpec("world", "map", 1, N_("section.map.world"), "map", factory=_world, iteration=5, planned_keys=(
        N_("map.intro"), N_("map.f.canvas"), N_("map.f.modes"), N_("map.f.live"), N_("map.f.ownership"),
        N_("map.f.resources"), N_("map.f.buildings"), N_("map.f.pops"), N_("map.f.storage"), N_("map.f.vanilla"),
    ), hosts=("province_history", "pops", "terrain", "default_map")),
    SectionSpec("regions", "map", 2, N_("section.map.regions"), "layers", factory=_regions, iteration=5, planned_keys=(
        N_("section.map.regions.intro"), N_("section.map.regions.f1"), N_("section.map.regions.f2"),
        N_("section.map.regions.f3"),
    ), hosts=("region", "region_sea")),
    SectionSpec("climates", "map", 3, N_("section.map.climates"), "climate", factory=_climates, iteration=5,
                planned_keys=(
        N_("section.map.climates.intro"), N_("section.map.climates.f1"), N_("section.map.climates.f2"),
    ), hosts=("continent", "climate")),
    SectionSpec("straits", "map", 4, N_("section.map.straits"), "anchor", factory=_straits, iteration=5, planned_keys=(
        N_("section.map.straits.intro"), N_("section.map.straits.f1"), N_("section.map.straits.f2"),
    ), hosts=("adjacency",)),
    SectionSpec("forge", "map", 5, N_("section.map.forge"), "anvil", factory=_forge, iteration=9, planned_keys=(
        N_("section.map.forge.intro"), N_("section.map.forge.f1"), N_("section.map.forge.f2"),
        N_("section.map.forge.f3"), N_("section.map.forge.f4"),
    )),
]
