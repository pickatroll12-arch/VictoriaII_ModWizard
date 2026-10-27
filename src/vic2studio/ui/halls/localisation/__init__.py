"""Sala Textos (Ctrl+7): los CSV de localización hoy; todos los textos y los pendientes de traducir, editables y
sincronizados, en la iteración 3 (wizard §8)."""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec


def _csv_files(session):
    """La página de Localización de la iteración 1, como sección «Archivos CSV» (``MainWindow.page("localisation")``)."""
    from ...pages.localisation_page import LocalisationPage

    page = LocalisationPage()
    page.title_key = N_("section.localisation.csv")
    page.subtitle_key = N_("section.localisation.csv.subtitle")
    page.retranslate()
    return page


HALL = HallSpec("localisation", 7, N_("hall.localisation.plate"), N_("nav.localisation"),
                N_("hall.localisation.subtitle"), "localisation")

SECTIONS = [
    SectionSpec("all", "localisation", 1, N_("section.localisation.all"), "localisation", iteration=3, planned_keys=(
        N_("section.localisation.all.intro"), N_("section.localisation.all.f1"),
        N_("section.localisation.all.f2"), N_("section.localisation.all.f3"),
    )),
    SectionSpec("pending", "localisation", 2, N_("section.localisation.pending"), "quill", iteration=3, planned_keys=(
        N_("section.localisation.pending.intro"), N_("section.localisation.pending.f1"),
        N_("section.localisation.pending.f2"),
    )),
    SectionSpec("csv", "localisation", 3, N_("section.localisation.csv"), "file_table", factory=_csv_files),
]
