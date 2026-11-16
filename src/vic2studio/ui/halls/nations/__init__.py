"""Sala Naciones (Ctrl+3): países en la iteración 6; culturas y gobiernos en la 4 (wizard §14.2, §14.11, §14.13)."""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec


def _countries(session):
    from .countries import CountriesPage

    return CountriesPage(session)


HALL = HallSpec("nations", 3, N_("hall.nations.plate"), N_("nav.nations"), N_("hall.nations.subtitle"), "countries")

SECTIONS = [
    SectionSpec("countries", "nations", 1, N_("section.nations.countries"), "countries", factory=_countries,
                iteration=6, planned_keys=(
        N_("countries.intro"), N_("countries.f.tag"), N_("countries.f.tag_register"), N_("countries.f.color"),
        N_("countries.f.flags"), N_("countries.f.parties"), N_("countries.f.units"), N_("countries.f.history"),
        N_("countries.f.history_fields"),
    ), hosts=("country", "country_history", "country_colors", "oob")),
    SectionSpec("cultures", "nations", 2, N_("section.nations.cultures"), "culture", iteration=4, planned_keys=(
        N_("section.nations.cultures.intro"), N_("section.nations.cultures.f1"),
        N_("section.nations.cultures.f2"), N_("section.nations.cultures.f3"),
    )),
    SectionSpec("governments", "nations", 3, N_("section.nations.governments"), "crown", iteration=4,
                planned_keys=(
                    N_("section.nations.governments.intro"), N_("section.nations.governments.f1"),
                    N_("section.nations.governments.f2"), N_("section.nations.governments.f3"),
                )),
]
