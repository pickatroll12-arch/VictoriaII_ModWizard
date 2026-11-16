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
  Si falla, el motivo queda en ``baseline_error`` y no se reintenta en cada F7 hasta
  ``retry_baseline``. ``problems``, ``fixes_for``, ``plan_fix`` y ``apply_fix`` trabajan
  sobre el último informe; ``request_explanation`` explica en ``POOL_VALIDATION`` (el
  contexto es inmutable, I12) y avisa con ``explanationReady``. Tras un arreglo, o tras
  deshacer o rehacer uno (pasos ``undo.fix_*``), se vuelve a validar sola cuando el
  índice se pone al día; mientras tanto ``fixes_blocked``. ``report_stale`` dice si los
  documentos cambiaron desde la instantánea del último informe (``reportStaleChanged``).
- **Buscador** (``search``, ``display``): ``SymbolIndex.search`` con la localización
  efectiva, en el idioma de la interfaz; la base efectiva se pide una vez y se guarda
  hasta que cambian los textos (pedirla cuesta lo que comprobar las firmas de todos los
  CSV).

Lo que entrega cada tarea (``_Outcome``) se conserva mientras se use su valor (``_held``):
``ui/tasks.py`` vigila ese objeto para descongelar el recolector, y soltarlo en el acto
devolvía el índice y los textos de VSM a la generación más vieja (pasadas de 0,5 s en el
hilo de la interfaz).

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
# Etiqueta de los pasos de deshacer de los arreglos (core/validate: «undo.fix_<clave>»).
FIX_STEP_PREFIX = "undo.fix_"
# Lo que se conserva de cada tarea mientras se usa (``_held``).
HELD_OPEN, HELD_INDEX, HELD_TEXTS, HELD_VALIDATION, HELD_EXPLAIN = "open", "index", "texts", "validation", "explain"
# Por qué un documento no tiene archivo que abrir en su línea (``in_memory``).
IN_MEMORY_NEW, IN_MEMORY_MODIFIED = "new", "modified"


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
    """Resultado de una validación: el informe, su contexto (para el explicador), la línea base usada y la versión de
    los documentos que validó (``Session._content_version`` al empezar: si cambia, el informe está desfasado)."""

    __slots__ = ("report", "context", "baseline", "baseline_error", "version", "date", "__weakref__")

    def __init__(self, report, context, baseline, baseline_error: str | None, version: int = 0, date=None):
        self.report = report
        self.context = context
        self.baseline = baseline
        self.baseline_error = baseline_error
        self.version = version
        self.date = date                    # la fecha de trabajo de la validación (y de su línea base)


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

    def context(self, snapshot, index, overrides, *, date=None, languages=None, cancelled=None):
        from ..core.validate import build_context

        extra = {} if languages is None else {"languages": tuple(languages)}
        return build_context(snapshot, index, overrides, date=date, cancelled=cancelled, **extra)

    def validate(self, context, baseline, *, progress=None, cancelled=None):
        from ..core.validate import Validator

        report = Validator(context, baseline=baseline).validate(progress=progress, cancelled=cancelled)
        return with_schema_problems(report, context, cancelled=cancelled)

    def explain(self, problem, context):
        from ..core.validate import explain

        return explain(problem, context)

    def fixes_for(self, problem) -> list:
        from ..core.validate import fixes_for

        return fixes_for(problem)

    def plan_fix(self, key: str, problem, project):
        from ..core.validate import plan_fix

        return plan_fix(key, problem, project)

    def apply_fix(self, key: str, problem, project, expected=None) -> None:
        from ..core.validate import apply_fix

        apply_fix(key, problem, project, expected=expected)


class BaselineEngine:
    """La línea base (I11): ``core.validate.baseline_for``, de la caché (``BaselineCache``) o calculada sobre lo que
    no es el mod (el juego y las dependencias, ``base_snapshot``) a la fecha de trabajo, y guardada."""

    def compute(self, snapshot, *, date=None, cancelled=None) -> frozenset:
        from ..core.validate import baseline_for

        return baseline_for(snapshot, date=date, cancelled=cancelled)


def with_schema_problems(report, context, *, cancelled=None):
    """El informe con los problemas de esquema de la iteración 4 añadidos (decisión 3 del informe IT4).

    Se calculan en la misma tarea que la validación, sobre el ``ValidationContext`` inmutable (I12):
    ``core.schema.validate.schema_problems``. Uno que ya da la validación global (mismo código y archivo, y misma
    línea o entidad) no se repite. Un contexto que no es el real (pruebas con motores falsos) deja el informe igual.
    """
    from dataclasses import replace

    from ..core.schema.validate import schema_problems
    from ..core.validate import ValidationContext
    from ..core.validate.validator import _sort_key

    if not isinstance(context, ValidationContext) or report is None:
        return report
    known = set()
    for problem in report.problems:
        rel = problem.rel.key if problem.rel is not None else ""
        known.add((problem.code, rel, problem.line))
        if problem.entity is not None:
            known.add((problem.code, rel, problem.entity[1]))
    extra = []
    for problem in schema_problems(context, cancelled=cancelled):
        rel = problem.rel.key if problem.rel is not None else ""
        if (problem.code, rel, problem.line) in known or \
                (problem.entity is not None and (problem.code, rel, problem.entity[1]) in known):
            continue
        extra.append(problem)
    if not extra:
        return report
    return replace(report, problems=tuple(sorted((*report.problems, *extra), key=_sort_key)))


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
    reportStaleChanged = Signal()                 # el último informe pasa a estar desfasado (o deja de estarlo)
    explanationReady = Signal(object, object)     # (problema, Explanation) de request_explanation
    explanationFailed = Signal(object, str)       # (problema, motivo)
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
        # Lo que entregaron las tareas y aún se usa: ui/tasks.py vigila estos objetos, no su valor.
        self._held: dict[str, _Outcome] = {}
        # Índice
        self._index = None
        self._index_state = IDLE
        self._index_error: str | None = None
        self._index_runner = TaskRunner(self, pool=POOL_INDEX)
        self._index_runner.finished.connect(self._on_index_built)
        self._index_runner.failed.connect(self._on_index_failed)
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
        self._texts_error: str | None = None
        self._search_loc = None             # (LocSync, LocalisationDB) del buscador, hasta que cambien los textos
        self._texts_runner = TaskRunner(self, pool=POOL_PREVIEW)
        self._texts_runner.finished.connect(self._on_texts_read)
        self._texts_runner.failed.connect(self._on_texts_failed)
        # Validación
        self._validation_runner = TaskRunner(self, pool=POOL_VALIDATION)
        self._validation_runner.finished.connect(self._on_validated)
        self._validation_runner.failed.connect(self._on_validation_failed)
        self._validation_runner.progress.connect(self._on_validation_progress)
        self._validation: _Validation | None = None
        self._validation_state = IDLE
        self._validation_error: str | None = None
        self._validation_cancelled = False  # la última validación pedida se canceló (la barra de estado lo dice)
        self._content_version = 0           # sube con cada cambio de contenido de un documento (informe desfasado)
        self._baseline = None
        self._baseline_date = None          # la fecha de trabajo a la que se calculó (otra fecha, otra línea base)
        self._baseline_error: str | None = None
        self._revalidate = False            # validar en cuanto el índice se ponga al día (tras un arreglo)
        # Explicador (el contexto del informe es inmutable: se puede usar en otro hilo, I12)
        self._explain_runner = TaskRunner(self, pool=POOL_VALIDATION)
        self._explain_runner.finished.connect(self._on_explained)
        self._explain_runner.failed.connect(self._on_explain_failed)
        self._explaining = None             # el problema que se está explicando
        # Entidades (iteración 4): el servicio del motor de esquemas sobre el proyecto abierto
        self._entities = None
        # Mapa (iteración 5): ``MapSession``, creada al pedirla (``map``)
        self._map = None

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
        """True mientras el índice, la lectura de textos, la validación o el explicador trabajan en segundo plano."""
        return (self._index_runner.is_busy() or self._reindex_runner.is_busy() or self._texts_runner.is_busy()
                or self._validation_runner.is_busy() or self._explain_runner.is_busy()
                or self._reindex_timer.isActive())

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
        self._held.pop(HELD_OPEN, None)
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
        self._held[HELD_OPEN] = outcome
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
        self._texts_error = None
        self._search_loc = None
        self._start_texts()
        self.rebuild_index()

    def _stop_services(self) -> bool:
        """Cancela las tareas del proyecto y olvida su índice, sus textos y su informe; True si había algo."""
        had = self._index is not None or self._locsync is not None or self._validation is not None \
            or self._index_state != IDLE or self._validation_state != IDLE
        for runner in (self._index_runner, self._reindex_runner, self._texts_runner, self._validation_runner,
                       self._explain_runner):
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
        self._texts_error = None
        self._search_loc = None
        self._validation = None
        self._validation_state = IDLE
        self._validation_error = None
        self._validation_cancelled = False
        self._baseline = None
        self._baseline_date = None
        self._baseline_error = None
        self._revalidate = False
        self._explaining = None
        self._entities = None
        for name in (HELD_INDEX, HELD_TEXTS, HELD_VALIDATION, HELD_EXPLAIN):
            self._held.pop(name, None)
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
            self._index_failed(outcome.error)
            return
        self._index = outcome.value
        self._held[HELD_INDEX] = outcome   # mientras viva el índice: ui/tasks.py lo vigila a través de este objeto
        self._index_state = READY
        self.indexStateChanged.emit()
        self.symbolsChanged.emit(set(self._safe_kinds()))
        if self._reindex_pending:
            self._reindex_timer.start()   # lo que cambió mientras se construía
        if self._validation_state == WAITING:
            self.validate()

    def _index_failed(self, error: str) -> None:
        self._index_state = FAILED
        self._index_error = error
        log.info("no hay índice de símbolos: %s", error)
        self.indexStateChanged.emit()
        if self._validation_state == WAITING:
            self._fail_validation(error)

    def _on_index_failed(self, failure) -> None:
        """La construcción lanzó algo que la tarea no atrapa (ya registrado por ``TaskRunner``): sin esto, la interfaz
        y la validación en espera se quedaban esperando al índice para siempre."""
        self._index_failed(str(failure))

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

    # --- entidades (iteración 4) --------------------------------------------------------------------

    @property
    def entities(self):
        """``core.schema.Entities`` del proyecto abierto (con el índice que haya, o sin él: entonces recorre los
        archivos), o None sin proyecto. Siempre sobre el ``Workspace`` vivo de este hilo (I12)."""
        project = self._project
        if project is None or self._locsync is None:
            return None
        if self._entities is None or self._entities.ws is not project.ws:
            from ..core.schema import Entities

            self._entities = Entities(project.ws, self._index, self._locsync)
        self._entities.index = self._index
        return self._entities

    # --- mapa (iteración 5) -------------------------------------------------------------------------

    @property
    def map(self):
        """``ui.session_map.MapSession`` de esta sesión: el ráster de provincias, los hechos en la fecha de
        trabajo y las ediciones del mapa. Se crea al pedirla por primera vez y vive lo que la sesión; sin proyecto
        existe igual, vacía (``raster`` y ``facts`` son None)."""
        if self._map is None:
            from .session_map import MapSession

            self._map = MapSession(self)
        return self._map

    # --- localización -------------------------------------------------------------------------------

    @property
    def locsync(self) -> LocSync | None:
        """``LocSync`` del proyecto abierto (textos efectivos y la política de dónde se escribe), o None."""
        return self._locsync

    def texts_ready(self) -> bool:
        """True cuando los CSV del disco ya están leídos: consultar ``locsync`` no leerá en este hilo."""
        return self._texts_ready

    def texts_error(self) -> str | None:
        """Por qué no se pudieron leer los CSV del disco (los textos no llegan a estar listos), o None."""
        return self._texts_error

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
        self._held[HELD_TEXTS] = outcome   # LocSync guarda los archivos leídos: viven lo que el proyecto
        self._search_loc = None
        self._texts_ready = True
        self._announce_texts()

    def _on_texts_failed(self, failure) -> None:
        """La lectura lanzó: los textos no se dan por listos (consultarlos los volvería a leer en este hilo), pero la
        sala Textos deja de decir «Cargando…» y dice por qué."""
        if self._locsync is None:
            return
        self._texts_error = str(failure)
        self.textsChanged.emit()

    # --- validación ---------------------------------------------------------------------------------

    def validation_state(self) -> str:
        """``idle`` (sin validar), ``waiting`` (al índice), ``busy``, ``ready`` o ``failed``."""
        return self._validation_state

    def validation_error(self) -> str | None:
        return self._validation_error

    def baseline_error(self) -> str | None:
        """Por qué no hay línea base (los heredados no se marcan), o None. Mientras lo haya, validar no la vuelve a
        calcular (fallaría igual en cada F7): ``retry_baseline`` lo intenta de nuevo."""
        return self._baseline_error

    def retry_baseline(self) -> bool:
        """Olvida el fallo de la línea base y valida otra vez (que la vuelve a calcular); False si no hay proyecto."""
        self._baseline_error = None
        return self.validate()

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

    def validation_cancelled(self) -> bool:
        """True si la última validación pedida se canceló (lo que se ve es el informe anterior, o ninguno)."""
        return self._validation_cancelled

    def report_stale(self) -> bool:
        """True si algún documento cambió desde la instantánea del último informe (un Ctrl+Z, una edición mientras
        validaba): la tabla y las insignias son de antes, hasta volver a validar."""
        return self._validation is not None and self._validation.version != self._content_version

    def fixes_blocked(self) -> bool:
        """True mientras se valida o hay una revalidación pendiente (tras un arreglo, o tras deshacerlo o
        rehacerlo): el informe a la vista aún no lo tiene y arreglar otra vez un problema ya arreglado fallaría."""
        return self._revalidate or self.is_validating()

    def validate(self) -> bool:
        """Valida el mod en segundo plano (``POOL_VALIDATION``); False si no hay proyecto. Si el índice aún se
        construye, espera a que termine. Emite ``validationStateChanged`` y, al terminar, ``problemsChanged``."""
        project = self._project
        if project is None:
            return False
        self._validation_cancelled = False
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
        date, lang, version = self._working_date, language(), self._content_version
        languages = tuple(getattr(project.settings, "languages", ()) or ()) or None
        if self._baseline_date != date:
            # La línea base mira las historias a la fecha de trabajo: con otra fecha, la de antes ya no vale.
            self._baseline, self._baseline_error = None, None
        engine, baseline_engine, baseline = self._validation_engine, self._baseline_engine, self._baseline
        # Una línea base que ya falló no se recalcula en cada F7 (retry_baseline la pide otra vez).
        failed_baseline = self._baseline_error if baseline is None else None

        def task(context) -> _Outcome:
            cancelled = context.cancelled
            baseline_error = failed_baseline
            known = baseline
            if known is None and failed_baseline is None:
                try:
                    known = baseline_engine.compute(snapshot, date=date, cancelled=cancelled)
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - sin línea base se valida igual (sin heredados)
                    baseline_error = _error_text(exc, lang)
            try:
                # Copia del índice hecha aquí: el vivo lo cambia el hilo de la interfaz mientras tanto.
                frozen = index_type(facts, snapshot=snapshot)
                validation_context = engine.context(snapshot, frozen, overrides, date=date, languages=languages,
                                                    cancelled=cancelled)
                report = engine.validate(validation_context, known,
                                         progress=lambda done, total: context.report((done, total)),
                                         cancelled=cancelled)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - el motivo se muestra en Proyecto › Validación
                return _Outcome(error=_error_text(exc, lang))
            return _Outcome(_Validation(report, validation_context, known, baseline_error, version, date))

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
        """Cancela la validación en curso o en espera, y también la revalidación pendiente (tras un arreglo): sin
        eso, la validación volvía a arrancar sola en cuanto el índice se ponía al día."""
        if self.is_validating() or self._revalidate:
            self._validation_runner.cancel()
            self._revalidate = False
            self._validation_cancelled = True
            self._validation_state = READY if self._validation is not None else IDLE
            self.validationStateChanged.emit()

    def _fail_validation(self, error: str) -> None:
        self._revalidate = False
        self._validation_state = FAILED
        self._validation_error = error
        self.validationStateChanged.emit()

    def _on_validation_failed(self, failure) -> None:
        """La validación lanzó algo que la tarea no atrapa: sin esto, «Validando…» se quedaba para siempre."""
        self._fail_validation(str(failure))

    def _on_validation_progress(self, value) -> None:
        self.validationProgress.emit(*value)

    def _on_validated(self, outcome: _Outcome) -> None:
        if outcome.error is not None:
            self._fail_validation(outcome.error)
            return
        result: _Validation = outcome.value
        self._validation = result
        self._held[HELD_VALIDATION] = outcome   # el informe y su contexto viven lo que este objeto
        self._held.pop(HELD_EXPLAIN, None)      # una explicación del informe anterior ya no sirve
        if result.baseline is not None:
            self._baseline = result.baseline
        self._baseline_date = result.date
        self._baseline_error = result.baseline_error
        self._validation_state = READY
        self.validationStateChanged.emit()
        self.problemsChanged.emit()
        self.reportStaleChanged.emit()

    def explain(self, problem):
        """Explicación (``Explanation``) de un problema del último informe, en este hilo; None si no hay informe.
        La interfaz usa ``request_explanation``: algunos explicadores tardan décimas con VSM."""
        context = self.validation_context
        if context is None:
            return None
        return self._validation_engine.explain(problem, context)

    def request_explanation(self, problem) -> bool:
        """Explica ``problem`` en segundo plano (``POOL_VALIDATION``) con el contexto del último informe, que no
        cambia (I12); emite ``explanationReady`` o ``explanationFailed``. False si no hay informe."""
        context = self.validation_context
        if context is None or problem is None:
            return False
        engine, lang = self._validation_engine, language()

        def task(_context) -> _Outcome:
            try:
                return _Outcome((problem, engine.explain(problem, context)))
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - el motivo se muestra en la barra de estado
                return _Outcome((problem, None), error=_error_text(exc, lang))

        self._explaining = problem
        self._explain_runner.start(task)
        return True

    def is_explaining(self) -> bool:
        return self._explain_runner.is_busy()

    def cancel_explanation(self) -> None:
        self._explain_runner.cancel()
        self._explaining = None

    def _on_explained(self, outcome: _Outcome) -> None:
        problem, explanation = outcome.value
        self._explaining = None
        if outcome.error is not None:
            self.explanationFailed.emit(problem, outcome.error)
            return
        self._held[HELD_EXPLAIN] = outcome
        self.explanationReady.emit(problem, explanation)

    def _on_explain_failed(self, failure) -> None:
        problem, self._explaining = self._explaining, None
        self.explanationFailed.emit(problem, str(failure))

    def fixes_for(self, problem) -> list:
        """Los arreglos (``FixSpec``) de un problema, el SimpleFix primero."""
        return list(self._validation_engine.fixes_for(problem))

    def plan_fix(self, key: str, problem):
        """Vista previa (``ChangePlan``) de un arreglo, sin cambiar nada (tampoco la pila de deshacer)."""
        project = self._require()
        with self._operation():
            return self._validation_engine.plan_fix(key, problem, project)

    def apply_fix(self, key: str, problem, plan=None) -> None:
        """Aplica un arreglo (una transacción deshacible) y vuelve a validar cuando el índice se ponga al día.
        ``plan``: el que vio el usuario; si el arreglo ya no haría eso, ``FixError(plan_changed)`` y nada cambia."""
        project = self._require()
        with self._operation():
            self._validation_engine.apply_fix(key, problem, project, plan)
        # Los resultados de antes siguen a la vista hasta que el índice tenga el arreglo; entonces se revalida.
        self._request_revalidation()

    def _request_revalidation(self) -> None:
        """Valida en cuanto el índice tenga los últimos cambios; hasta entonces ``fixes_blocked`` (y se avisa)."""
        if self._project is None:
            return
        self._revalidate = True
        if not self._index_behind():
            self._revalidate = False
            self.validate()
        else:
            self.validationStateChanged.emit()   # mismo estado, pero los arreglos se bloquean hasta el informe

    def _after_step(self, step) -> None:
        """Deshacer o rehacer un arreglo revalida como aplicarlo: si no, la tabla y las insignias seguían diciendo
        que el problema estaba arreglado (o al revés)."""
        if step is not None and self._validation is not None \
                and str(getattr(step, "label", "")).startswith(FIX_STEP_PREFIX):
            self._request_revalidation()

    # --- buscador ---------------------------------------------------------------------------------

    def _loc_for_search(self):
        """La base efectiva para el buscador y los nombres: se pide una vez y se guarda hasta que cambian los
        textos (``_forget_search_loc``). Pedirla a ``LocSync`` cuesta lo que comprobar las firmas de todos los CSV
        (unos 4 ms con VSM): con una por resultado, Ctrl+K «a» tardaba 270 ms."""
        locsync = self._locsync
        if locsync is None or not self._texts_ready:
            return None
        cached = self._search_loc
        if cached is not None and cached[0] is locsync:
            return cached[1]
        try:
            db = locsync.localisation_db()
        except Exception:  # noqa: BLE001
            log.debug("sin localización para el buscador", exc_info=True)
            return None
        self._search_loc = (locsync, db)
        return db

    def _forget_search_loc(self) -> None:
        self._search_loc = None

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

    def in_memory(self, rel, layer: LayerKind | None = None) -> str | None:
        """Si lo que se ve de ``rel`` (en ``layer``, o el efectivo) es un documento sin guardar: ``IN_MEMORY_NEW``
        (no hay archivo), ``IN_MEMORY_MODIFIED`` (el del disco aún no tiene los cambios) o None.

        Los símbolos y los problemas de un documento sin guardar llevan las líneas de lo que hay en memoria; abrir el
        archivo del disco en esa línea mostraría otra cosa (o el del juego, si el documento es una copia nueva).
        Un símbolo de otra capa (el del juego que pierde) sí está en su archivo.
        """
        project = self._project
        if project is None or rel is None or (layer is not None and layer is not LayerKind.MOD):
            return None
        try:
            handle = project.ws.peek(rel)
        except Exception:  # noqa: BLE001 - un proyecto falso puede no tenerlo
            return None
        # Uno borrado sin guardar (a la papelera) sigue en el disco tal cual: se abre ese.
        if handle is None or handle.deleted or not handle.dirty:
            return None
        origin = handle.origin
        if origin is None or origin.layer.kind is not LayerKind.MOD:
            return IN_MEMORY_NEW      # nuevo, o copia del juego que aún no está en el mod
        return IN_MEMORY_MODIFIED

    def location_path(self, rel, layer: LayerKind | None = None) -> Path | None:
        """Ruta en disco de ``rel`` (la de ``layer`` si se da, si no la ganadora); None si lo que se ve está solo en
        memoria (``in_memory``): un documento nuevo, o uno con cambios sin guardar, cuyas líneas no son las del
        disco."""
        project = self._project
        if project is None or rel is None or self.in_memory(rel, layer) is not None:
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
        """Deshace el último paso; si es un arreglo (``undo.fix_*``), vuelve a validar como al aplicarlo."""
        if self._project is None:
            return None
        with self._operation():
            step = self._project.ws.undo()
        self._after_step(step)
        return step

    def redo(self) -> UndoStep | None:
        if self._project is None:
            return None
        with self._operation():
            step = self._project.ws.redo()
        self._after_step(step)
        return step

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
        if content:
            stale = self.report_stale()
            self._content_version += 1
            if self.report_stale() != stale:
                self.reportStaleChanged.emit()
        if any(VPath.of(rel).key == SETTINGS_KEY for rel in content) and self._locsync is not None:
            settings = self._project.settings
            self._locsync.configure(prefix=settings.prefix, languages=settings.languages,
                                    copy_en_to=settings.copy_en_to)
            self._forget_search_loc()
        if content or structural:
            self._schedule_reindex(content, structural)
        if self._locsync is not None and any(_is_loc(rel) for rel in content):
            self._locsync.invalidate()
            self._forget_search_loc()
            if self._texts_ready:
                self.textsChanged.emit()


def _is_loc(rel) -> bool:
    try:
        return is_localisation_rel(rel)
    except ValueError:
        return False


__all__ = [
    "BUSY", "BaselineEngine", "DEFAULT_WORKING_DATE", "FAILED", "FIX_STEP_PREFIX", "IDLE", "IN_MEMORY_MODIFIED",
    "IN_MEMORY_NEW", "IndexEngine", "READY", "REINDEX_DELAY_MS", "Session", "ValidationEngine", "WAITING",
    "document_overrides", "with_schema_problems",
]
