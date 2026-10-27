"""``Session``: el único puente entre el proyecto (Python puro) y Qt (wizard §6.4, D2).

Ningún widget abre ni escribe archivos: todo pasa por ``Session`` → ``Project``.
Abrir un proyecto escanea la VFS en segundo plano (``ui.tasks.TaskRunner``) y, al
recibirlo en el hilo de la interfaz, ``Workspace.bind_to_current_thread`` hace a
este hilo su dueño (I12); el resto de llamadas son síncronas y en el hilo de la
interfaz. Las señales llevan ``object`` para no copiar estructuras.

Los eventos del ``Workspace`` (``subscribe``) se acumulan mientras dura una
operación de la sesión (``edit``, ``save``, ``undo``...) y se emiten una vez al
terminar: ``documentsChanged`` con las rutas tocadas, ``dirtyChanged`` si cambió el
número de documentos sin guardar y ``undoChanged``. Los que llegan fuera de una
operación se emiten en la siguiente vuelta del bucle de eventos.

Cada apertura es una petición con su propio ``TaskRunner``: si se pide otra (o se
cierra) antes de que termine, la vieja se cancela y, si aun así llega a abrir el
proyecto, se cierra al recibirlo (suelta el bloqueo). La recuperación de sesiones
huérfanas y el autoguardado (``Workspace.AUTOSAVE_SECONDS`` y cada
``AUTOSAVE_TRANSACTIONS`` transacciones) también van por aquí.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.cancel import Cancelled
from ..core.clausewitz import ClausewitzDate
from ..core.modfile import DescriptorSpec, ModDescriptor, create_mod_skeleton
from ..core.project import (
    ChangeSet,
    DocChanged,
    DocCreated,
    DocDeleted,
    DocReplaced,
    Project,
    Saved,
    SaveReport,
    Txn,
    UndoApplied,
    UndoStep,
    Workspace,
)
from ..core.vfs import VPath
from ..i18n import N_
from .tasks import POOL_PREVIEW, TaskRunner

log = logging.getLogger(__name__)

DEFAULT_WORKING_DATE = ClausewitzDate(1836, 1, 1)
# Claves de projectOpenFailed / modCreateFailed (con ``error``: el motivo del sistema o de la excepción).
OPEN_FAILED = N_("session.open_failed")
CREATE_FAILED = N_("session.create_failed")


def _error_text(exc: BaseException) -> str:
    """Motivo de un fallo sin retener la excepción (su traza formaría un ciclo con el marco del hilo)."""
    if isinstance(exc, OSError) and exc.strerror:
        return f"{exc.strerror}: {exc.filename}" if exc.filename else exc.strerror
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class _Outcome:
    """Lo que entrega una tarea de la sesión: el resultado o el texto del fallo (nunca la excepción)."""

    __slots__ = ("value", "error", "__weakref__")

    def __init__(self, value=None, error: str | None = None):
        self.value = value
        self.error = error


class _Request:
    """Una apertura en curso: su runner, su cancelación y lo que pidió."""

    def __init__(self, number: int, game: Path | None, mod: Path, runner: TaskRunner):
        self.number = number
        self.game = game
        self.mod = mod
        self.runner = runner
        self.cancel = threading.Event()


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
    modCreated = Signal(object)                   # ModDescriptor del mod nuevo («Nuevo mod»)
    modCreateFailed = Signal(str, object)         # (clave i18n, formato)

    def __init__(self, parent: QObject | None = None, *,
                 opener: Callable[..., Project] | None = None,
                 creator: Callable[..., ModDescriptor] | None = None) -> None:
        """``opener`` (``Project.open``) y ``creator`` (``create_mod_skeleton``) se pueden sustituir en pruebas."""
        super().__init__(parent)
        self._opener = opener or Project.open
        self._creator = creator or create_mod_skeleton
        self._project: Project | None = None
        self._target: tuple[Path | None, Path] | None = None
        self._request: _Request | None = None
        self._numbers = itertools.count(1)
        self._unsubscribe: Callable[[], None] | None = None
        self._pending: set[VPath] = set()
        self._depth = 0
        self._last_dirty = 0
        self._edits = 0
        self._working_date = DEFAULT_WORKING_DATE
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(0)
        self._flush_timer.timeout.connect(self._flush)
        self._autosave = QTimer(self)
        self._autosave.setInterval(Workspace.AUTOSAVE_SECONDS * 1000)
        self._autosave.timeout.connect(self.write_recovery)
        self._create_runner = TaskRunner(self, pool=POOL_PREVIEW)
        self._create_runner.finished.connect(self._on_created)

    # --- estado ----------------------------------------------------------------------------

    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def target(self) -> tuple[Path | None, Path] | None:
        """(juego, mod) del proyecto abierto o que se está abriendo; None si no hay ninguno."""
        return self._target

    @property
    def working_date(self) -> ClausewitzDate:
        return self._working_date

    def set_working_date(self, date: ClausewitzDate) -> None:
        if date != self._working_date:
            self._working_date = date
            self.workingDateChanged.emit(date)

    def is_busy(self) -> bool:
        """True mientras se abre un proyecto o se crea un mod (las capturas y las pruebas esperan)."""
        return self._request is not None or self._create_runner.is_busy()

    def is_read_only(self) -> bool:
        return self._project is not None and bool(self._project.read_only)

    # --- abrir y cerrar ----------------------------------------------------------------------

    def open_project(self, game: Path | None, mod: Path) -> None:
        """En segundo plano: descriptor, VFS, escaneo, bloqueo y recuperación. Emite projectOpened o
        projectOpenFailed. Cierra antes el proyecto abierto (con closeProject)."""
        self.close_project()
        game = Path(game) if game else None
        mod = Path(mod)
        runner = TaskRunner(self, pool=POOL_PREVIEW)
        request = _Request(next(self._numbers), game, mod, runner)
        self._request = request
        self._target = (game, mod)
        opener, cancelled = self._opener, request.cancel.is_set

        def task(context) -> _Outcome:
            try:
                return _Outcome(opener(game, mod, progress=None, cancelled=cancelled))
            except Cancelled:
                return _Outcome()
            except Exception as exc:  # noqa: BLE001 - el motivo se muestra en la interfaz
                return _Outcome(error=_error_text(exc))

        runner.finished.connect(lambda outcome, r=request: self._on_open_outcome(r, outcome))
        self.projectOpening.emit(game, mod)
        runner.start(task)

    def close_project(self) -> None:
        """Cancela la apertura en curso y cierra el proyecto (``Project.close`` escribe la recuperación si hay
        cambios sin guardar y suelta el bloqueo). Emite projectClosed si había alguno."""
        had = self._request is not None or self._project is not None
        if self._request is not None:
            self._request.cancel.set()
            self._request = None
        project, self._project = self._project, None
        self._target = None
        self._autosave.stop()
        self._flush_timer.stop()
        self._pending.clear()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if project is not None:
            try:
                project.close()
            except Exception:  # noqa: BLE001 - cerrar nunca debe impedir salir
                log.exception("no se pudo cerrar el proyecto")
        if had:
            self._last_dirty = 0
            self.projectClosed.emit()
            self.dirtyChanged.emit(0)
            self.undoChanged.emit()

    def _on_open_outcome(self, request: _Request, outcome: _Outcome) -> None:
        request.runner.deleteLater()
        project = outcome.value
        if request is not self._request:
            if project is not None:
                self._dispose(project)  # se abrió cuando ya nadie lo quería
            return
        self._request = None
        if project is None:
            self._target = None
            if outcome.error is not None:
                self.projectOpenFailed.emit(OPEN_FAILED, {"error": outcome.error})
            return
        project.ws.bind_to_current_thread()
        self._project = project
        self._unsubscribe = project.ws.subscribe(self._on_event)
        self._last_dirty = len(project.ws.dirty())
        self._working_date = getattr(project.settings, "working_date", DEFAULT_WORKING_DATE)
        self._edits = 0
        self._autosave.start()
        self.projectOpened.emit(project)
        self.dirtyChanged.emit(self._last_dirty)
        self.undoChanged.emit()
        if project.orphan_sessions:
            self.recoveryAvailable.emit(list(project.orphan_sessions))

    @staticmethod
    def _dispose(project: Project) -> None:
        try:
            project.ws.bind_to_current_thread()
            project.close()
        except Exception:  # noqa: BLE001
            log.exception("no se pudo cerrar un proyecto abierto tarde")

    # --- edición -----------------------------------------------------------------------------

    def _require(self) -> Project:
        if self._project is None:
            raise RuntimeError("no hay ningún proyecto abierto")
        return self._project

    @contextmanager
    def _operation(self) -> Iterator[None]:
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0:
                self._flush()

    def edit(self, label: str, *, merge_key: str | None = None, **fmt) -> AbstractContextManager[Txn]:
        """``Project.edit`` y, al cerrar, documentsChanged, dirtyChanged y undoChanged."""
        return self._edit(label, merge_key, fmt)

    @contextmanager
    def _edit(self, label: str, merge_key: str | None, fmt: dict) -> Iterator[Txn]:
        project = self._require()
        with self._operation():
            with project.edit(label, merge_key=merge_key, **fmt) as txn:
                yield txn
            nested = self._depth > 1
        if not nested:
            self._edits += 1
            if self._edits >= Workspace.AUTOSAVE_TRANSACTIONS:
                self.write_recovery()

    def changeset(self, rels: Iterable[VPath] | None = None) -> ChangeSet:
        if self._project is None:
            return ChangeSet()
        return self._project.ws.changeset(rels)

    def save(self, rels: Iterable[VPath] | None = None) -> SaveReport:
        """Guarda; emite saved o saveBlocked. La revisión previa (D13) la decide quien llama con ``changeset``."""
        project = self._require()
        with self._operation():
            report = project.save(rels)
        if report.ok:
            self.saved.emit(report)
        else:
            self.saveBlocked.emit(report)
        return report

    def undo(self) -> UndoStep | None:
        if self._project is None:
            return None
        with self._operation():
            return self._project.ws.undo()

    def redo(self) -> UndoStep | None:
        if self._project is None:
            return None
        with self._operation():
            return self._project.ws.redo()

    def can_undo(self) -> bool:
        return self._project is not None and self._project.ws.can_undo()

    def can_redo(self) -> bool:
        return self._project is not None and self._project.ws.can_redo()

    def history(self) -> list[tuple[str, dict]]:
        """(clave, formato) de los pasos que se pueden deshacer, el más reciente primero."""
        return [] if self._project is None else list(self._project.ws.history())

    def dirty_count(self) -> int:
        return 0 if self._project is None else len(self._project.ws.dirty())

    # --- cambios externos y recuperación --------------------------------------------------------

    def check_external_changes(self) -> None:
        """Al recuperar el foco la ventana: emite externalChanges si hay alguno."""
        if self._project is None:
            return
        with self._operation():
            changes = self._project.ws.check_external_changes()
        if changes:
            self.externalChanges.emit(list(changes))

    def accept_external(self, rel: VPath) -> None:
        """«Conservar mis cambios»: el próximo guardado sobrescribe el cambio externo."""
        with self._operation():
            self._require().ws.accept_external(rel)

    def reload(self, rel: VPath) -> None:
        """«Recargar del disco»: descarta lo que hay en memoria de ``rel``."""
        with self._operation():
            self._require().ws.reload(rel)
            self._pending.add(rel)

    def external_diff(self, rel: VPath) -> str:
        """«Comparar»: diff entre el disco y lo que hay en memoria."""
        return self._require().ws.external_diff(rel)

    def write_recovery(self) -> None:
        """Autoguardado de recuperación de los documentos sin guardar (no escribe nada si no hay)."""
        project = self._project
        self._edits = 0
        if project is None or project.read_only or not project.ws.dirty():
            return
        try:
            project.ws.write_recovery()
        except OSError as exc:  # el autoguardado nunca interrumpe el trabajo
            log.warning("no se pudo escribir la recuperación: %s", exc)

    def restore_session(self, session: str) -> list[VPath]:
        """Carga como documentos sin guardar un autoguardado huérfano (se deshace en un paso)."""
        with self._operation():
            return list(self._require().restore_session(session))

    def discard_recovery(self, session: str) -> None:
        """Descarta un autoguardado huérfano (el usuario no lo quiere restaurar)."""
        from ..core.project import journal

        project = self._require()
        journal.clear_recovery(project.vfs.guard, project.project_dir / journal.RECOVERY_DIR, session)
        if session in project.orphan_sessions:
            project.orphan_sessions.remove(session)

    # --- «Nuevo mod» ---------------------------------------------------------------------------

    def create_mod(self, game_root: Path, spec: DescriptorSpec, template: Path | None = None) -> None:
        """Crea el mod en segundo plano (``create_mod_skeleton``); emite modCreated o modCreateFailed."""
        creator = self._creator

        def task(context) -> _Outcome:
            try:
                return _Outcome(creator(Path(game_root), spec, template=template))
            except Exception as exc:  # noqa: BLE001 - el motivo se muestra en el diálogo
                return _Outcome(error=_error_text(exc))

        self._create_runner.start(task)

    def is_creating(self) -> bool:
        return self._create_runner.is_busy()

    def _on_created(self, outcome: _Outcome) -> None:
        if outcome.error is not None:
            self.modCreateFailed.emit(CREATE_FAILED, {"error": outcome.error})
        else:
            self.modCreated.emit(outcome.value)

    # --- eventos del Workspace -----------------------------------------------------------------

    def _on_event(self, event) -> None:
        if isinstance(event, (DocChanged, DocReplaced, DocCreated, DocDeleted)):
            self._pending.add(event.rel)
        elif isinstance(event, (UndoApplied, Saved)):
            self._pending.update(event.rels)
        if self._depth == 0:
            self._flush_timer.start()

    def _flush(self) -> None:
        self._flush_timer.stop()
        rels, self._pending = self._pending, set()
        if rels:
            self.documentsChanged.emit(rels)
        count = self.dirty_count()
        if count != self._last_dirty:
            self._last_dirty = count
            self.dirtyChanged.emit(count)
        self.undoChanged.emit()
