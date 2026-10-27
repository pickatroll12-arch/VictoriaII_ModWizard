"""Sala Proyecto (Ctrl+1): Inicio, Descriptor .mod, Archivos, Validación (iteración 3) y Cambios pendientes
(wizard §13.1, §13.3, §14.1)."""

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


def _pending(session):
    from .pending import PendingChangesPage

    return PendingChangesPage(session)


def _dirty_badge(session) -> int | None:
    count = session.dirty_count()
    return count or None


HALL = HallSpec("project", 1, N_("hall.project.plate"), N_("nav.project"), N_("hall.project.subtitle"), "project")

SECTIONS = [
    SectionSpec("home", "project", 1, N_("section.project.home"), "home", factory=_home),
    SectionSpec("descriptor", "project", 2, N_("section.project.descriptor"), "file_mod", factory=_descriptor),
    SectionSpec("files", "project", 3, N_("section.project.files"), "folder_open", factory=_files),
    SectionSpec("validation", "project", 4, N_("section.project.validation"), "validate", iteration=3, planned_keys=(
        N_("section.project.validation.intro"), N_("section.project.validation.f1"),
        N_("section.project.validation.f2"), N_("section.project.validation.f3"),
    )),
    SectionSpec("pending", "project", 5, N_("section.project.pending"), "scroll_seal", factory=_pending,
                badge=_dirty_badge),
]
