"""Sala Textos (Ctrl+7): todos los textos editables y sincronizados, los pendientes de traducir y los CSV del mod
(wizard §8, §13.1)."""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec


def _all_texts(session):
    from .texts import TextsPage

    return TextsPage(session)


def _pending(session):
    from .texts import FILTER_UNTRANSLATED, TextsPage

    return TextsPage(session, preset=FILTER_UNTRANSLATED)


def _pending_badge(session) -> int | None:
    """Claves del mod sin traducir a algún idioma del proyecto (cuando los textos ya están leídos); el recuento se
    guarda mientras ``LocSync.entries()`` no cambie (``texts.pending_count``)."""
    locsync = session.locsync
    if locsync is None or not session.texts_ready():
        return None
    from .texts import pending_count

    try:
        count = pending_count(locsync)
    except Exception:  # noqa: BLE001 - el contador nunca rompe el índice lateral
        return None
    return count or None


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
    SectionSpec("all", "localisation", 1, N_("section.localisation.all"), "localisation", factory=_all_texts),
    SectionSpec("pending", "localisation", 2, N_("section.localisation.pending"), "quill", factory=_pending,
                badge=_pending_badge),
    SectionSpec("csv", "localisation", 3, N_("section.localisation.csv"), "file_table", factory=_csv_files),
]
