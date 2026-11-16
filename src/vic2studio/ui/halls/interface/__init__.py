"""Sala Interfaz (Ctrl+6): ventanas .gui, sprites .gfx e imágenes y banderas (wizard §14.6, §17). Iteración 8."""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec

GUI_KINDS = ("gui_window", "gui_dialog", "gui_button", "gui_icon", "gui_instant_text", "gui_text", "gui_checkbox",
             "gui_listbox", "gui_scrollbar", "gui_position", "gui_overlapping", "gui_editbox", "gui_shield")


def _windows(session):
    from .windows import WindowsPage

    return WindowsPage(session)


def _sprites(session):
    from .sprites import SpritesPage

    return SpritesPage(session)


def _images(session):
    from .images import ImagesPage

    return ImagesPage(session)


HALL = HallSpec("interface", 6, N_("hall.interface.plate"), N_("nav.interface"), N_("hall.interface.subtitle"),
                "window")

SECTIONS = [
    SectionSpec("windows", "interface", 1, N_("section.interface.windows"), "window", factory=_windows, iteration=8,
                planned_keys=(
        N_("section.interface.windows.intro"), N_("section.interface.windows.f1"),
        N_("section.interface.windows.f2"), N_("section.interface.windows.f3"),
    ), hosts=GUI_KINDS),
    SectionSpec("sprites", "interface", 2, N_("section.interface.sprites"), "file_image", factory=_sprites,
                iteration=8, planned_keys=(
        N_("section.interface.sprites.intro"), N_("section.interface.sprites.f1"),
        N_("section.interface.sprites.f2"),
    ), hosts=("sprite",)),
    SectionSpec("images", "interface", 3, N_("section.interface.images"), "flag", factory=_images, iteration=8,
                planned_keys=(
        N_("section.interface.images.intro"), N_("section.interface.images.f1"),
        N_("section.interface.images.f2"),
    )),
]
