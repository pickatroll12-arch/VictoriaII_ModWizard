"""``Session``: el único puente entre el proyecto (Python puro) y Qt (wizard §6.4, D2).

Ningún widget abre ni escribe archivos: todo pasa por ``Session`` → ``Project``.
Abrir un proyecto escanea la VFS en segundo plano (``ui.tasks.TaskRunner``); el
resto de llamadas son síncronas y en el hilo de la interfaz, que es el dueño del
``Workspace`` (I12). Las señales llevan ``object`` para no copiar estructuras.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..core.clausewitz import ClausewitzDate
from ..core.project import ChangeSet, Project, SaveReport, Txn
from ..core.vfs import VPath


class Session(QObject):
    projectOpening = Signal(object, object)       # (juego, mod) al empezar a abrir
    projectOpened = Signal(object)                # Project
    projectOpenFailed = Signal(str, object)       # (clave i18n, formato)
    projectClosed = Signal()
    documentsChanged = Signal(object)             # set[VPath]
    symbolsChanged = Signal(object)               # set[str] de tipos (iteración 3)
    dirtyChanged = Signal(int)                    # documentos sin guardar
    undoChanged = Signal()                        # cambió lo que se puede deshacer o rehacer
    saved = Signal(object)                        # SaveReport con result
    saveBlocked = Signal(object)                  # SaveReport con problems (la interfaz abre el diálogo)
    problemsChanged = Signal()                    # iteración 3
    workingDateChanged = Signal(object)           # ClausewitzDate
    recoveryAvailable = Signal(object)            # list[str]: sesiones de autoguardado huérfanas
    externalChanges = Signal(object)              # list[ExternalChange]

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        raise NotImplementedError

    @property
    def project(self) -> Project | None:
        raise NotImplementedError

    @property
    def working_date(self) -> ClausewitzDate:
        raise NotImplementedError

    def set_working_date(self, date: ClausewitzDate) -> None:
        raise NotImplementedError

    def open_project(self, game: Path | None, mod: Path) -> None:
        """En segundo plano: descriptor, VFS, escaneo, bloqueo y recuperación. Emite projectOpened o
        projectOpenFailed. Cierra antes el proyecto abierto (con closeProject)."""
        raise NotImplementedError

    def close_project(self) -> None:
        raise NotImplementedError

    def is_busy(self) -> bool:
        """True mientras se abre un proyecto (las capturas y las pruebas esperan)."""
        raise NotImplementedError

    def edit(self, label: str, *, merge_key: str | None = None, **fmt) -> AbstractContextManager[Txn]:
        """``Project.edit`` y, al cerrar, documentsChanged, dirtyChanged y undoChanged."""
        raise NotImplementedError

    def changeset(self, rels: Iterable[VPath] | None = None) -> ChangeSet:
        raise NotImplementedError

    def save(self, rels: Iterable[VPath] | None = None) -> SaveReport:
        """Guarda; emite saved o saveBlocked. La revisión previa (D13) la decide quien llama con ``changeset``."""
        raise NotImplementedError

    def undo(self) -> None:
        raise NotImplementedError

    def redo(self) -> None:
        raise NotImplementedError

    def dirty_count(self) -> int:
        raise NotImplementedError

    def check_external_changes(self) -> None:
        """Al recuperar el foco la ventana: emite externalChanges si hay alguno."""
        raise NotImplementedError

    def write_recovery(self) -> None:
        raise NotImplementedError
