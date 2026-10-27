"""Sala Interfaz (Ctrl+6): ventanas .gui, sprites .gfx, imágenes y banderas en la iteración 8 (wizard §14.6, §17)."""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec

HALL = HallSpec("interface", 6, N_("hall.interface.plate"), N_("nav.interface"), N_("hall.interface.subtitle"),
                "window")

SECTIONS = [
    SectionSpec("windows", "interface", 1, N_("section.interface.windows"), "window", iteration=8, planned_keys=(
        N_("section.interface.windows.intro"), N_("section.interface.windows.f1"),
        N_("section.interface.windows.f2"), N_("section.interface.windows.f3"),
    )),
    SectionSpec("sprites", "interface", 2, N_("section.interface.sprites"), "file_image", iteration=8, planned_keys=(
        N_("section.interface.sprites.intro"), N_("section.interface.sprites.f1"),
        N_("section.interface.sprites.f2"),
    )),
    SectionSpec("images", "interface", 3, N_("section.interface.images"), "flag", iteration=8, planned_keys=(
        N_("section.interface.images.intro"), N_("section.interface.images.f1"),
        N_("section.interface.images.f2"),
    )),
]
