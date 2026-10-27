"""Sala Proyecto (Ctrl+1): Inicio, Descriptor .mod, Archivos, Validación y Cambios pendientes
(wizard §11, §13.1, §13.3, §14.1)."""

from ....i18n import N_
from ..registry import HallSpec, SectionSpec


def _home(session):
    from .home import HomePage

    return HomePage(session)


def _descriptor(session):
    from .descriptor import DescriptorPage

    return DescriptorPage(session)


def _files(session):
    from .files import files_section

    return files_section(session)


def _validation(session):
    from .validation import ValidationPage

    return ValidationPage(session)


def _pending(session):
    from .pending import PendingChangesPage

    return PendingChangesPage(session)


def _problems_badge(session) -> int | None:
    """Errores del último informe (sin los heredados del juego base)."""
    report = session.report
    if report is None:
        return None
    from ....core.clausewitz import Severity

    return report.count(Severity.ERROR) or None


def _dirty_badge(session) -> int | None:
    count = session.dirty_count()
    return count or None


HALL = HallSpec("project", 1, N_("hall.project.plate"), N_("nav.project"), N_("hall.project.subtitle"), "project")

SECTIONS = [
    SectionSpec("home", "project", 1, N_("section.project.home"), "home", factory=_home),
    SectionSpec("descriptor", "project", 2, N_("section.project.descriptor"), "file_mod", factory=_descriptor),
    SectionSpec("files", "project", 3, N_("section.project.files"), "folder_open", factory=_files),
    SectionSpec("validation", "project", 4, N_("section.project.validation"), "validate", factory=_validation,
                badge=_problems_badge),
    SectionSpec("pending", "project", 5, N_("section.project.pending"), "scroll_seal", factory=_pending,
                badge=_dirty_badge),
]
