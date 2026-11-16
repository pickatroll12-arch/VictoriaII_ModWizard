"""Sala Guerra (Ctrl+4): fechas de inicio, casus belli y unidades en la iteración 4; guerras y diplomacia de inicio
en la 6 (wizard §14.4, §14.8–§14.10, §14.12)."""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec


def _wars(session):
    from .wars import WarsPage

    return WarsPage(session)


def _diplomacy(session):
    from .diplomacy import DiplomacyPage

    return DiplomacyPage(session)


HALL = HallSpec("war", 4, N_("hall.war.plate"), N_("nav.war"), N_("hall.war.subtitle"), "swords")

SECTIONS = [
    SectionSpec("bookmarks", "war", 1, N_("section.war.bookmarks"), "calendar", iteration=4, planned_keys=(
        N_("section.war.bookmarks.intro"), N_("section.war.bookmarks.f1"), N_("section.war.bookmarks.f2"),
    )),
    SectionSpec("wars", "war", 2, N_("section.war.wars"), "swords", factory=_wars, iteration=6, planned_keys=(
        N_("section.war.wars.intro"), N_("section.war.wars.f1"), N_("section.war.wars.f2"),
        N_("section.war.wars.f3"),
    ), hosts=("war",)),
    SectionSpec("diplomacy", "war", 3, N_("section.war.diplomacy"), "handshake", factory=_diplomacy, iteration=6,
                planned_keys=(
        N_("section.war.diplomacy.intro"), N_("section.war.diplomacy.f1"), N_("section.war.diplomacy.f2"),
    ), hosts=("diplomacy",)),
    SectionSpec("cb", "war", 4, N_("section.war.cb"), "scroll_seal", iteration=4, planned_keys=(
        N_("section.war.cb.intro"), N_("section.war.cb.f1"), N_("section.war.cb.f2"), N_("section.war.cb.f3"),
    )),
    SectionSpec("land", "war", 5, N_("section.war.land"), "helmet", iteration=4, planned_keys=(
        N_("section.war.land.intro"), N_("section.war.land.f1"), N_("section.war.land.f2"),
    )),
    SectionSpec("naval", "war", 6, N_("section.war.naval"), "ship", iteration=4, planned_keys=(
        N_("section.war.naval.intro"), N_("section.war.naval.f1"), N_("section.war.naval.f2"),
    )),
]
