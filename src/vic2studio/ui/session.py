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

**Iteración 3** (wizard §7, §8, §11):

- **Índice de símbolos** (``index``). Al abrir se construye en segundo plano
  (``POOL_INDEX``) con la instantánea de la VFS y los bytes de los documentos sin
  guardar; el índice real usa ``FactsCache``. Con cada cambio de un documento, a los
  ``REINDEX_DELAY_MS`` (300 ms), se reextraen sus hechos de su ``snapshot`` en segundo
  plano y se aplican en el hilo de la interfaz (``SymbolIndex.apply``); emite
  ``symbolsChanged`` con los tipos afectados. ``rebuild_index`` lo rehace entero.
- **Localización** (``locsync``): ``core.locsync.LocSync`` sobre el ``Workspace``; sus
  CSV del disco se leen al abrir en segundo plano (``textsReady``); ``textsChanged``
  avisa cuando cambian los textos efectivos (ediciones, deshacer, recargas).
- **Validación** (``validate``): en ``POOL_VALIDATION``, con ``build_context`` sobre la
  instantánea, los bytes de los documentos sucios y una copia del índice hecha en el
  propio hilo (el vivo sigue cambiando en el de la interfaz); la línea base se calcula
  allí mismo la primera vez (``BaselineCache``) y se guarda para el resto de la sesión.
  ``problems``, ``explain``, ``fixes_for``, ``plan_fix`` y ``apply_fix`` trabajan sobre
  el último informe; tras un arreglo se vuelve a validar sola cuando el índice se pone
  al día.
- **Buscador** (``search``, ``display``): ``SymbolIndex.search`` con la localización
  efectiva, en el idioma de la interfaz.

El índice, la validación y la línea base se pueden **inyectar** en el constructor
(``index=``, ``validation=``, ``baseline=``), como ``opener`` y ``creator``: las
pruebas usan falsos; por defecto (``IndexEngine``, ``ValidationEngine`` y
``BaselineEngine``) se llama a las funciones reales del contrato. Nada de lo que
viaja a un hilo de tarea es un objeto de Qt ni la propia sesión (``ui/tasks.py``).
"""

from __future__ import annotations

import itertools
import logging
import os
import threading
from collections.abc import Callable, Collection, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.cancel import Cancelled, raise_if_cancelled
from ..core.clausewitz import ClausewitzDate
from ..core.locsync import LocSync, is_localisation_rel, read_localisation
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
from ..core.project.codecs import codec_for
from ..core.vfs import LayerKind, VPath
from ..i18n import N_, language
from .tasks import POOL_INDEX, POOL_PREVIEW, POOL_VALIDATION, TaskRunner

log = logging.getLogger(__name__)

DEFAULT_WORKING_DATE = ClausewitzDate(1836, 1, 1)
# Claves de projectOpenFailed / modCreateFailed (con ``error``: el motivo del sistema o de la excepción).
OPEN_FAILED = N_("session.open_failed")
CREATE_FAILED = N_("session.create_failed")
# Espera entre el último cambio de un documento y la reextracción de sus hechos (wizard §7).
REINDEX_DELAY_MS = 300
PROJECT_DIR_PREFIX = ".vic2studio"
SETTINGS_KEY = ".VIC2STUDIO/PROJECT.JSON"

# Estados del índice y de la validación.
IDLE, BUSY, READY, FAILED = "idle", "busy", "ready", "failed"
WAITING = "waiting"      # validación pedida a la espera de que termine el índice


def _error_text(exc: BaseException, lang: str = "en") -> str:
    """Motivo de un fallo sin retener la excepción (su traza formaría un ciclo con el marco del hilo); en ``lang``
    si la excepción sabe dar su texto (``message(lang)``, los errores del núcleo)."""
    message = getattr(exc, "message", None)
    if callable(message):
        try:
            return str(message(lang))
        except TypeError:
            pass
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
        self.started = False
        self.key = os.path.normcase(os.path.realpath(mod))


class _Validation:
    """Resultado de una validación: el informe, su contexto (para el explicador) y la línea base usada."""

    __slots__ = ("report", "context", "baseline", "baseline_error", "__weakref__")

    def __init__(self, report, context, baseline, baseline_error: str | None):
        self.report = report
        self.context = context
        self.baseline = baseline
        self.baseline_error = baseline_error


# --- motores por defecto: las funciones reales del contrato (wizard §7, §11) ---------------------------------


class IndexEngine:
    """Lo que ``Session`` usa del índice; por defecto ``core.index`` (``build_index`` con ``FactsCache``)."""

    def build(self, snapshot, overrides, *, progress=None, cancelled=None):
        from ..core.index import FactsCache, build_index

        return build_index(snapshot, FactsCache(), overrides, progress=progress, cancelled=cancelled)

    def extract(self, rel, data: bytes, layer):
        from ..core.index import extract_bytes

        return extract_bytes(rel, data, layer)


class ValidationEngine:
    """Lo que ``Session`` usa de la validación; por defecto ``core.validate``."""

    def context(self, snapshot, index, overrides, *, date=None, cancelled=None):
        from ..core.validate import build_context

        return build_context(snapshot, index, overrides, date=date, cancelled=cancelled)

    def validate(self, context, baseline, *, progress=None, cancelled=None):
        from ..core.validate import Validator

        return Validator(context, baseline=baseline).validate(progress=progress, cancelled=cancelled)

    def explain(self, problem, context):
        from ..core.validate import explain

        return explain(problem, context)

    def fixes_for(self, problem) -> list:
        from ..core.validate import fixes_for

        return fixes_for(problem)

    def plan_fix(self, key: str, problem, project):
        from ..core.validate import plan_fix

        return plan_fix(key, problem, project)

    def apply_fix(self, key: str, problem, project) -> None:
        from ..core.validate import apply_fix

        apply_fix(key, problem, project)


class BaselineEngine:
    """La línea base (I11): de la caché por instalación (``BaselineCache``) o, si no vale, calculada sobre la capa
    del juego sola (``game_only_snapshot`` + ``build_index`` + ``compute_baseline``) y guardada."""

    def compute(self, snapshot, *, cancelled=None) -> frozenset:
        from ..core.index import FactsCache, build_index
        from ..core.validate import BaselineCache, build_context, compute_baseline, game_only_snapshot

        cache = BaselineCache()
        cached = cache.load(snapshot)
        if cached is not None:
            return cached
        game = game_only_snapshot(snapshot)
        index = build_index(game, FactsCache(), {}, cancelled=cancelled)
        context = build_context(game, index, {}, game_only=True, cancelled=cancelled)
        baseline = compute_baseline(context, cancelled=cancelled)
        cache.store(snapshot, baseline)
        return baseline


def document_overrides(project) -> dict[VPath, bytes | None]:
    """Bytes (``snapshot`` del códec) de los documentos sin guardar: lo que ven el índice y la validación (I7).

    Un documento borrado sin guardar va como ``None`` (contrato de ``build_index`` y ``build_context``): sin él, el
    índice y la validación seguían viendo el archivo del disco (un arreglo que lo manda a la papelera no se notaba).
    """
    overrides: dict[VPath, bytes | None] = {}
    for handle in project.ws.dirty():
        if VPath.of(handle.rel).key.startswith(PROJECT_DIR_PREFIX.upper() + "/"):
            continue
        if handle.deleted:
            overrides[handle.rel] = None
            continue
        codec = codec_for(handle.kind)
        if not codec.writable:
            continue
        try:
            overrides[handle.rel] = codec.snapshot(handle.model)
        except (ValueError, LookupError):
            continue
    return overrides


def _document_layer(handle) -> LayerKind:
    """Capa que representa un documento abierto: MOD si se escribirá en el mod; si no, la de su origen."""
    origin = handle.origin
    if handle.dirty or origin is None or origin.layer.kind is LayerKind.MOD:
        return LayerKind.MOD
    return origin.layer.kind


class Session(QObject):
    projectOpening = Signal(object, object)       # (juego, mod) al empezar a abrir
    projectOpened = Signal(object)                # Project
    projectOpenFailed = Signal(str, object)       # (clave i18n, formato)
    projectClosed = Signal()
    documentsChanged = Signal(object)             # set[VPath]
    symbolsChanged = Signal(object)               # set[str] de tipos afectados (todos tras una construcción)
    dirtyChanged = Signal(int)                    # documentos sin guardar
    undoChanged = Signal()                        # cambió lo que se puede deshacer o rehacer
    saved = Signal(object)                        # SaveReport con result
    saveBlocked = Signal(object)                  # SaveReport con problems (la interfaz abre el diálogo)
    problemsChanged = Signal()                    # hay otro informe de validación (o ninguno)
    workingDateChanged = Signal(object)           # ClausewitzDate
    recoveryAvailable = Signal(object)            # list[str]: sesiones de autoguardado huérfanas
    externalChanges = Signal(object)              # list[ExternalChange]
    modCreated = Signal(object)                   # ModDescriptor del mod nuevo («Nuevo mod»)
    modCreateFailed = Signal(str, object)         # (clave i18n, formato)
    # Iteración 3
    indexStateChanged = Signal()                  # empieza, termina o falla la construcción del índice
    indexProgress = Signal(int, int)              # (hechos, total) de la construcción
    validationStateChanged = Signal()             # empieza, espera, termina, falla o se cancela una validación
    validationProgress = Signal(int, int)         # (reglas hechas, total)
    textsReady = Signal()                         # los CSV del disco ya están leídos (la tabla puede mostrarse)
    textsChanged = Signal()                       # cambiaron los textos efectivos (edición, deshacer, recarga)

    def __init__(self, parent: QObject | None = None, *,
                 opener: Callable[..., Project] | None = None,
                 creator: Callable[..., ModDescriptor] | None = None,
                 index: IndexEngine | None = None,
                 validation: ValidationEngine | None = None,
                 baseline: BaselineEngine | None = None) -> None:
        """``opener`` (``Project.open``) y ``creator`` (``create_mod_skeleton``) se pueden sustituir en pruebas, y
        también los motores del índice, la validación y la línea base (``IndexEngine``, ``ValidationEngine`` y
        ``BaselineEngine`` usan las funciones reales del contrato)."""
        super().__init__(parent)
        self._opener = opener or Project.open
        self._creator = creator or create_mod_skeleton
        self._index_engine = index or IndexEngine()
        self._validation_engine = validation or ValidationEngine()
        self._baseline_engine = baseline or BaselineEngine()
        self._project: Project | None = None
        self._target: tuple[Path | None, Path] | None = None
        self._request: _Request | None = None
        self._stale: list[_Request] = []   # aperturas canceladas que aún no han vuelto (pueden tener el bloqueo)
        self._numbers = itertools.count(1)
        self._unsubscribe: Callable[[], None] | None = None
        self._pending: set[VPath] = set()
        self._content: set[VPath] = set()   # rutas cuyo contenido cambió (reindexar, textos)
        self._structural = False            # se creó o se borró algún documento (cambia el orden de capas)
        self._depth = 0
        self._last_dirty = 0
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
        # Índice
        self._index = None
        self._index_state = IDLE
        self._index_error: str | None = None
        self._index_runner = TaskRunner(self, pool=POOL_INDEX)
        self._index_runner.finished.connect(self._on_index_built)
        self._index_runner.progress.connect(self._on_index_progress)
        self._reindex_runner = TaskRunner(self, pool=POOL_INDEX)
        self._reindex_runner.finished.connect(self._on_reindexed)
        self._reindex_runner.failed.connect(self._on_reindex_failed)
        self._reindex_pending: dict[str, VPath] = {}
        self._reindex_inflight: dict[str, VPath] = {}
        self._reindex_structural = False
        self._reindex_timer = QTimer(self)
        self._reindex_timer.setSingleShot(True)
        self._reindex_timer.setInterval(REINDEX_DELAY_MS)
        self._reindex_timer.timeout.connect(self._start_reindex)
        # Localización
        self._locsync: LocSync | None = None
        self._texts_ready = False
        self._texts_runner = TaskRunner(self, pool=POOL_PREVIEW)
        self._texts_runner.finished.connect(self._on_texts_read)
        # Validación
        self._validation_runner = TaskRunner(self, pool=POOL_VALIDATION)
        self._validation_runner.finished.connect(self._on_validated)
        self._validation_runner.progress.connect(self._on_validation_progress)
        self._validation: _Validation | None = None
        self._validation_state = IDLE
        self._validation_error: str | None = None
        self._baseline = None
        self._baseline_error: str | None = None
        self._revalidate = False            # validar en cuanto el índice se ponga al día (tras un arreglo)

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

    def is_working(self) -> bool:
        """True mientras el índice, la lectura de textos o la validación trabajan en segundo plano."""
        return (self._index_runner.is_busy() or self._reindex_runner.is_busy() or self._texts_runner.is_busy()
                or self._validation_runner.is_busy() or self._reindex_timer.isActive())

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
        runner.finished.connect(lambda outcome, r=request: self._on_open_outcome(r, outcome))
        runner.discarded.connect(lambda outcome, r=request: self._on_open_outcome(r, outcome))
        self.projectOpening.emit(game, mod)
        # Una apertura cancelada del mismo mod puede tener aún el bloqueo: esta espera a que vuelva.
        if not any(stale.key == request.key for stale in self._stale):
            self._start(request)

    def _start(self, request: _Request) -> None:
        request.started = True
        opener, game, mod, cancelled, lang = self._opener, request.game, request.mod, request.cancel.is_set, language()

        def task(context) -> _Outcome:
            try:
                project = opener(game, mod, progress=None, cancelled=cancelled)
            except Cancelled:
                return _Outcome()
            except Exception as exc:  # noqa: BLE001 - el motivo se muestra en la interfaz
                return _Outcome(error=_error_text(exc, lang))
            if cancelled() or context.cancelled():
                try:
                    project.close()   # aún es de este hilo: suelta el bloqueo aquí mismo
                except Exception:  # noqa: BLE001
                    log.exception("no se pudo cerrar un proyecto cancelado")
                return _Outcome()
            return _Outcome(project)

        request.runner.start(task)

    def close_project(self, *, discard: bool = False) -> None:
        """Cancela la apertura en curso y cierra el proyecto. ``Project.close`` suelta el bloqueo y escribe la
        recuperación de lo que quede sin guardar; con ``discard`` (el usuario eligió «Descartar») borra en cambio
        el autoguardado de esta sesión, para que al reabrir no se ofrezca lo que acaba de tirar. Emite
        projectClosed si había alguno."""
        had = self._request is not None or self._project is not None
        if self._request is not None:
            self._request.cancel.set()
            if self._request.started:
                self._stale.append(self._request)
            else:
                self._request.runner.deleteLater()
            self._request = None
        project, self._project = self._project, None
        self._target = None
        self._autosave.stop()
        self._flush_timer.stop()
        self._pending.clear()
        self._content.clear()
        self._structural = False
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        had_services = self._stop_services()
        if project is not None:
            try:
                project.close(discard=discard)
            except Exception:  # noqa: BLE001 - cerrar nunca debe impedir salir
                log.exception("no se pudo cerrar el proyecto")
        if had:
            self._last_dirty = 0
            self.projectClosed.emit()
            self.dirtyChanged.emit(0)
            self.undoChanged.emit()
        if had_services:
            self.indexStateChanged.emit()
            self.symbolsChanged.emit(set())
            self.validationStateChanged.emit()
            self.problemsChanged.emit()
            self.textsChanged.emit()

    def _on_open_outcome(self, request: _Request, outcome: _Outcome) -> None:
        request.runner.deleteLater()
        project = outcome.value
        if request is not self._request:
            if project is not None:
                self._dispose(project)  # se abrió cuando ya nadie lo quería
            if request in self._stale:
                self._stale.remove(request)
            waiting = self._request
            if waiting is not None and not waiting.started and not any(s.key == waiting.key for s in self._stale):
                self._start(waiting)
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
        self._autosave.start()
        self._start_services(project)
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

    # --- servicios del proyecto: índice, textos y validación ------------------------------------

    def _start_services(self, project: Project) -> None:
        settings = project.settings
        self._locsync = LocSync(project.ws, project.vfs, prefix=settings.prefix, languages=settings.languages,
                                copy_en_to=settings.copy_en_to)
        self._texts_ready = False
        self._start_texts()
        self.rebuild_index()

    def _stop_services(self) -> bool:
        """Cancela las tareas del proyecto y olvida su índice, sus textos y su informe; True si había algo."""
        had = self._index is not None or self._locsync is not None or self._validation is not None \
            or self._index_state != IDLE or self._validation_state != IDLE
        for runner in (self._index_runner, self._reindex_runner, self._texts_runner, self._validation_runner):
            runner.cancel()
        self._reindex_timer.stop()
        self._reindex_pending.clear()
        self._reindex_inflight.clear()
        self._reindex_structural = False
        self._index = None
        self._index_state = IDLE
        self._index_error = None
        self._locsync = None
        self._texts_ready = False
        self._validation = None
        self._validation_state = IDLE
        self._validation_error = None
        self._baseline = None
        self._baseline_error = None
        self._revalidate = False
        return had

    # --- índice -----------------------------------------------------------------------------------

    @property
    def index(self):
        """``SymbolIndex`` de la vista efectiva (con lo sin guardar), o None mientras no hay."""
        return self._index

    def index_state(self) -> str:
        """``idle``, ``busy`` (construyéndose), ``ready`` o ``failed``."""
        return self._index_state

    def index_error(self) -> str | None:
        return self._index_error

    def rebuild_index(self) -> None:
        """Construye el índice entero en segundo plano (al abrir, o a petición); el anterior sigue hasta entonces."""
        project = self._project
        if project is None:
            return
        snapshot_of = getattr(project.vfs, "snapshot", None)
        if snapshot_of is None:
            self._index_state = FAILED
            self._index_error = "snapshot"
            self.indexStateChanged.emit()
            return
        self._reindex_runner.cancel()
        self._reindex_timer.stop()
        self._reindex_pending.clear()
        self._reindex_inflight.clear()
        snapshot, overrides = snapshot_of(), document_overrides(project)
        engine, lang = self._index_engine, language()

        def task(context) -> _Outcome:
            try:
                index = engine.build(snapshot, overrides, progress=lambda done, total: context.report((done, total)),
                                     cancelled=context.cancelled)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - el índice es opcional: el motivo se muestra
                return _Outcome(error=_error_text(exc, lang))
            return _Outcome(index)

        self._index_state = BUSY
        self._index_error = None
        self._index_runner.start(task)
        self.indexStateChanged.emit()

    def _on_index_progress(self, value) -> None:
        self.indexProgress.emit(*value)

    def _on_index_built(self, outcome: _Outcome) -> None:
        if outcome.error is not None:
            self._index_state = FAILED
            self._index_error = outcome.error
            log.info("no hay índice de símbolos: %s", outcome.error)
            self.indexStateChanged.emit()
            if self._validation_state == WAITING:
                self._fail_validation(outcome.error)
            return
        self._index = outcome.value
        self._index_state = READY
        self.indexStateChanged.emit()
        self.symbolsChanged.emit(set(self._safe_kinds()))
        if self._reindex_pending:
            self._reindex_timer.start()   # lo que cambió mientras se construía
        if self._validation_state == WAITING:
            self.validate()

    def _safe_kinds(self) -> list[str]:
        try:
            return list(self._index.kinds())
        except Exception:  # noqa: BLE001 - un índice falso puede no saberlo
            return []

    def _schedule_reindex(self, rels: Iterable[VPath], structural: bool) -> None:
        for rel in rels:
            rel = VPath.of(rel)
            if rel.key.startswith(PROJECT_DIR_PREFIX.upper() + "/"):
                continue
            self._reindex_pending[rel.key] = rel
        self._reindex_structural |= structural
        if self._reindex_pending and self._index_state != BUSY:
            self._reindex_timer.start()

    def _start_reindex(self) -> None:
        project, index = self._project, self._index
        if project is None or index is None:
            return
        if self._reindex_runner.is_busy():
            # La tanda anterior se cancela: sus rutas van también en esta.
            self._reindex_pending.update(self._reindex_inflight)
        batch, self._reindex_pending = self._reindex_pending, {}
        self._reindex_inflight = dict(batch)
        structural, self._reindex_structural = self._reindex_structural, False
        items, removed = [], []
        for rel in batch.values():
            handle = project.ws.peek(rel)
            if handle is not None and not handle.deleted:
                codec = codec_for(handle.kind)
                layer = _document_layer(handle)
                if layer is not LayerKind.MOD:
                    removed.append((handle.rel, LayerKind.MOD))   # vuelve a ser el del juego: fuera lo del mod
                    continue
                if not codec.writable:
                    continue
                try:
                    items.append((handle.rel, layer, codec.snapshot(handle.model), None))
                except (ValueError, LookupError):
                    continue
                continue
            entry = project.vfs.resolve(rel)
            if handle is None and entry is not None and entry.layer.kind is LayerKind.MOD:
                items.append((entry.rel, LayerKind.MOD, None, entry.path))   # se deshizo hasta el disco
            else:
                removed.append((rel, LayerKind.MOD))
        snapshot = project.vfs.snapshot() if structural or removed else None
        engine = self._index_engine

        def task(context) -> _Outcome:
            facts = []
            gone = list(removed)
            for rel, layer, data, path in items:
                raise_if_cancelled(context.cancelled)
                if data is None:
                    try:
                        data = path.read_bytes()
                    except OSError:
                        gone.append((rel, layer))
                        continue
                try:
                    facts.extend(engine.extract(rel, data, layer))
                except Exception:  # noqa: BLE001 - un extractor no debe tumbar el índice
                    log.exception("no se pudieron extraer los hechos de %s", rel)
            return _Outcome((facts, gone, snapshot))

        self._reindex_runner.start(task)

    def _on_reindex_failed(self, failure) -> None:
        """Un reindexado que lanza (ya registrado por ``TaskRunner``): la validación en espera sigue, con el índice
        que haya, antes que quedarse esperando para siempre."""
        self._reindex_inflight = {}
        if self._revalidate and not self._index_behind():
            self._revalidate = False
            self.validate()

    def _on_reindexed(self, outcome: _Outcome) -> None:
        self._reindex_inflight = {}
        index = self._index
        if index is None or outcome.value is None:
            return
        facts, removed, snapshot = outcome.value
        kinds: set[str] = set()
        for rel in {f.rel for f in facts} | {rel for rel, _ in removed}:
            try:
                kinds.update(symbol.kind for symbol in index.defs_in(rel))
            except Exception:  # noqa: BLE001
                pass
        try:
            index.apply(facts, removed, snapshot=snapshot)
        except Exception:  # noqa: BLE001 - mejor un índice algo atrasado que una interfaz rota
            log.exception("no se pudo aplicar la reextracción al índice")
            return
        kinds.update(symbol.kind for fact in facts for symbol in fact.defs)
        self.symbolsChanged.emit(kinds)
        if self._revalidate and not self._reindex_pending and not self._reindex_timer.isActive():
            self._revalidate = False
            self.validate()

    # --- localización -------------------------------------------------------------------------------

    @property
    def locsync(self) -> LocSync | None:
        """``LocSync`` del proyecto abierto (textos efectivos y la política de dónde se escribe), o None."""
        return self._locsync

    def texts_ready(self) -> bool:
        """True cuando los CSV del disco ya están leídos: consultar ``locsync`` no leerá en este hilo."""
        return self._texts_ready

    def _start_texts(self) -> None:
        locsync = self._locsync
        try:
            entries = locsync.disk_entries()
        except Exception:  # noqa: BLE001 - un proyecto falso puede no tener localización
            log.debug("sin localización que leer", exc_info=True)
            entries = []
        if not entries:
            self._texts_ready = True
            QTimer.singleShot(0, self._announce_texts)
            return

        def task(context) -> _Outcome:
            return _Outcome(read_localisation(entries, cancelled=context.cancelled))

        self._texts_runner.start(task)

    def _announce_texts(self) -> None:
        if self._locsync is not None and self._texts_ready:
            self.textsReady.emit()
            self.textsChanged.emit()

    def _on_texts_read(self, outcome: _Outcome) -> None:
        if self._locsync is None:
            return
        self._locsync.adopt(outcome.value)
        self._texts_ready = True
        self._announce_texts()

    # --- validación ---------------------------------------------------------------------------------

    def validation_state(self) -> str:
        """``idle`` (sin validar), ``waiting`` (al índice), ``busy``, ``ready`` o ``failed``."""
        return self._validation_state

    def validation_error(self) -> str | None:
        return self._validation_error

    def baseline_error(self) -> str | None:
        """Por qué no hay línea base (los heredados no se marcan), o None."""
        return self._baseline_error

    @property
    def report(self):
        """El último ``ValidationReport``, o None si aún no se ha validado."""
        return None if self._validation is None else self._validation.report

    @property
    def validation_context(self):
        """El ``ValidationContext`` del último informe (lo usa el explicador), o None."""
        return None if self._validation is None else self._validation.context

    def problems(self, *, inherited: bool = False) -> list:
        """Problemas del último informe; los heredados del juego base solo si se piden (I11)."""
        report = self.report
        return [] if report is None else list(report.visible(inherited=inherited))

    def is_validating(self) -> bool:
        return self._validation_state in (BUSY, WAITING)

    def validate(self) -> bool:
        """Valida el mod en segundo plano (``POOL_VALIDATION``); False si no hay proyecto. Si el índice aún se
        construye, espera a que termine. Emite ``validationStateChanged`` y, al terminar, ``problemsChanged``."""
        project = self._project
        if project is None:
            return False
        if self._index is None:
            if self._index_state == FAILED:
                self._fail_validation(self._index_error or "")
                return True
            self._validation_runner.cancel()
            self._validation_state = WAITING
            self._validation_error = None
            self.validationStateChanged.emit()
            if self._index_state == IDLE:
                self.rebuild_index()
            return True
        if self._flush_timer.isActive():
            self._flush()                       # los cambios aún sin avisar: que los recoja el reindexado
        if self._index_behind():
            # El índice aún no tiene algún cambio de los documentos (un Ctrl+Z, una edición de hace menos de
            # REINDEX_DELAY_MS): validar ya daría los problemas de antes. Se valida en cuanto se ponga al día.
            self._validation_runner.cancel()
            self._validation_state = WAITING
            self._validation_error = None
            self._revalidate = True
            self.validationStateChanged.emit()
            if self._reindex_timer.isActive():
                self._reindex_timer.stop()
                self._start_reindex()
            return True
        snapshot, overrides = project.vfs.snapshot(), document_overrides(project)
        index = self._index
        index_type, facts = type(index), list(index.facts())
        engine, baseline_engine, baseline = self._validation_engine, self._baseline_engine, self._baseline
        date, lang = self._working_date, language()

        def task(context) -> _Outcome:
            cancelled = context.cancelled
            baseline_error = None
            known = baseline
            if known is None:
                try:
                    known = baseline_engine.compute(snapshot, cancelled=cancelled)
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - sin línea base se valida igual (sin heredados)
                    baseline_error = _error_text(exc, lang)
            try:
                # Copia del índice hecha aquí: el vivo lo cambia el hilo de la interfaz mientras tanto.
                frozen = index_type(facts, snapshot=snapshot)
                validation_context = engine.context(snapshot, frozen, overrides, date=date, cancelled=cancelled)
                report = engine.validate(validation_context, known,
                                         progress=lambda done, total: context.report((done, total)),
                                         cancelled=cancelled)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - el motivo se muestra en Proyecto › Validación
                return _Outcome(error=_error_text(exc, lang))
            return _Outcome(_Validation(report, validation_context, known, baseline_error))

        self._validation_state = BUSY
        self._validation_error = None
        self._validation_runner.start(task)
        self.validationStateChanged.emit()
        return True

    def _index_behind(self) -> bool:
        """True si el índice aún no refleja todos los documentos: se rehace entero o hay un reindexado pendiente (con
        su temporizador en marcha) o en curso."""
        return (self._index_state == BUSY or bool(self._reindex_pending) or bool(self._reindex_inflight)
                or self._reindex_runner.is_busy())

    def cancel_validation(self) -> None:
        if self.is_validating():
            self._validation_runner.cancel()
            self._validation_state = READY if self._validation is not None else IDLE
            self.validationStateChanged.emit()

    def _fail_validation(self, error: str) -> None:
        self._validation_state = FAILED
        self._validation_error = error
        self.validationStateChanged.emit()

    def _on_validation_progress(self, value) -> None:
        self.validationProgress.emit(*value)

    def _on_validated(self, outcome: _Outcome) -> None:
        if outcome.error is not None:
            self._fail_validation(outcome.error)
            return
        result: _Validation = outcome.value
        self._validation = result
        if result.baseline is not None:
            self._baseline = result.baseline
        self._baseline_error = result.baseline_error
        self._validation_state = READY
        self.validationStateChanged.emit()
        self.problemsChanged.emit()

    def explain(self, problem):
        """Explicación (``Explanation``) de un problema del último informe; None si no hay informe."""
        context = self.validation_context
        if context is None:
            return None
        return self._validation_engine.explain(problem, context)

    def fixes_for(self, problem) -> list:
        """Los arreglos (``FixSpec``) de un problema, el SimpleFix primero."""
        return list(self._validation_engine.fixes_for(problem))

    def plan_fix(self, key: str, problem):
        """Vista previa (``ChangePlan``) de un arreglo, sin cambiar nada (tampoco la pila de deshacer)."""
        project = self._require()
        with self._operation():
            return self._validation_engine.plan_fix(key, problem, project)

    def apply_fix(self, key: str, problem) -> None:
        """Aplica un arreglo (una transacción deshacible) y vuelve a validar cuando el índice se ponga al día."""
        project = self._require()
        with self._operation():
            self._validation_engine.apply_fix(key, problem, project)
        # Los resultados de antes siguen a la vista hasta que el índice tenga el arreglo; entonces se revalida.
        self._revalidate = True
        if not self._index_behind():
            self._revalidate = False
            self.validate()

    # --- buscador ---------------------------------------------------------------------------------

    def _loc_for_search(self):
        if self._locsync is None or not self._texts_ready:
            return None
        try:
            return self._locsync.localisation_db()
        except Exception:  # noqa: BLE001
            log.debug("sin localización para el buscador", exc_info=True)
            return None

    def search(self, text: str, *, kinds: Collection[str] = (), limit: int = 50) -> list:
        """Símbolos que encajan con ``text`` (id, nombre o nombre localizado, sin acentos), los exactos primero."""
        if self._index is None or not text.strip():
            return []
        return list(self._index.search(text.strip(), kinds=kinds, loc=self._loc_for_search(),
                                       lang=self._text_language(), limit=limit))

    def display(self, symbol) -> str:
        """Nombre para mostrar de un símbolo: «Prusia (PRU)», «549 Berlín»."""
        if self._index is None:
            return symbol.name
        return self._index.display(symbol.kind, symbol.name, self._loc_for_search(), self._text_language())

    @staticmethod
    def _text_language() -> str:
        """Columna de la localización del juego que se muestra: la del idioma de la interfaz."""
        return language() if language() in ("es", "en") else "en"

    def location_path(self, rel, layer: LayerKind | None = None) -> Path | None:
        """Ruta en disco de ``rel`` (la de ``layer`` si se da, si no la ganadora); None si solo está en memoria."""
        project = self._project
        if project is None or rel is None:
            return None
        vfs = project.vfs
        entry = None
        if layer is not None and hasattr(vfs, "entry"):
            entry = vfs.entry(rel, layer)
        if entry is None:
            entry = vfs.resolve(rel)
        return None if entry is None else Path(entry.path)

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
        if not nested and project.ws.autosave_due():
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
            self._content.add(rel)

    def external_diff(self, rel: VPath) -> str:
        """«Comparar»: diff entre el disco y lo que hay en memoria."""
        return self._require().ws.external_diff(rel)

    def write_recovery(self) -> None:
        """Autoguardado de recuperación (``Workspace.write_recovery``): los documentos sin guardar o, si ya no
        queda ninguno (todo deshecho o descartado), borra el de esta sesión, que si no ofrecería tras un cierre
        inesperado cambios que el usuario ya había deshecho."""
        project = self._project
        if project is None or project.read_only:
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
        self._require().discard_session(session)

    # --- «Nuevo mod» ---------------------------------------------------------------------------

    def create_mod(self, game_root: Path, spec: DescriptorSpec, template: Path | None = None) -> None:
        """Crea el mod en segundo plano (``create_mod_skeleton``); emite modCreated o modCreateFailed."""
        creator, lang = self._creator, language()

        def task(context) -> _Outcome:
            try:
                return _Outcome(creator(Path(game_root), spec, template=template))
            except Exception as exc:  # noqa: BLE001 - el motivo se muestra en el diálogo
                return _Outcome(error=_error_text(exc, lang))

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
            self._content.add(event.rel)
            if isinstance(event, (DocCreated, DocDeleted)):
                self._structural = True
        elif isinstance(event, UndoApplied):
            self._pending.update(event.rels)
            self._content.update(event.rels)
        elif isinstance(event, Saved):
            self._pending.update(event.rels)
            self._structural = True   # lo guardado ya es un archivo del mod: cambia el orden de capas
        if self._depth == 0:
            self._flush_timer.start()

    def _flush(self) -> None:
        self._flush_timer.stop()
        rels, self._pending = self._pending, set()
        content, self._content = self._content, set()
        structural, self._structural = self._structural, False
        if rels:
            self.documentsChanged.emit(rels)
        if self._project is not None and (content or structural):
            self._after_content_change(content, structural)
        count = self.dirty_count()
        if count != self._last_dirty:
            self._last_dirty = count
            self.dirtyChanged.emit(count)
            if count == 0:
                self.write_recovery()   # todo deshecho: sin esperar al latido, el autoguardado ya no sirve
        self.undoChanged.emit()

    def _after_content_change(self, content: set[VPath], structural: bool) -> None:
        if any(VPath.of(rel).key == SETTINGS_KEY for rel in content) and self._locsync is not None:
            settings = self._project.settings
            self._locsync.configure(prefix=settings.prefix, languages=settings.languages,
                                    copy_en_to=settings.copy_en_to)
        if content or structural:
            self._schedule_reindex(content, structural)
        if self._locsync is not None and any(_is_loc(rel) for rel in content):
            self._locsync.invalidate()
            if self._texts_ready:
                self.textsChanged.emit()


def _is_loc(rel) -> bool:
    try:
        return is_localisation_rel(rel)
    except ValueError:
        return False


__all__ = [
    "BUSY", "BaselineEngine", "DEFAULT_WORKING_DATE", "FAILED", "IDLE", "IndexEngine", "READY", "REINDEX_DELAY_MS",
    "Session", "ValidationEngine", "WAITING", "document_overrides",
]
