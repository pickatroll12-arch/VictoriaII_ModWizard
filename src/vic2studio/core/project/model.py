"""Tipos del proyecto: documentos, escrituras planificadas, deshacer, eventos y ajustes (wizard §6).

Dataclasses sin E/S: el agente de interfaz las importa desde el commit de
contrato. ``DocKind`` vive en ``core.vfs.model`` (lo declaran las reglas de carga)
y se reexporta aquí.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from ..clausewitz.nodes import ClausewitzDate
from ..vfs.model import DocKind, FileEntry, Fingerprint
from ..vfs.paths import VPath

__all__ = [
    "DocHandle", "DocKind", "ChangeSet", "DirtyChanged", "DocChanged", "DocCreated", "DocDeleted", "DocReplaced",
    "ExternalChange", "JournalState", "PlannedWrite", "ProjectSettings", "RasterPatch", "RecoveryResult",
    "SaveProblem", "SaveReport", "SaveResult", "Saved", "Snapshot", "UndoApplied", "UndoStep", "WorkspaceEvent",
    "WriteAction",
]

# --- documentos (§6.1) -----------------------------------------------------------------------

READ_ONLY_PARSE_ERRORS = "parse_errors"   # D17: solo texto hasta corregir la sintaxis
READ_ONLY_BINARY = "binary"               # sin códec de escritura en esta iteración
READ_ONLY_LOCKED = "locked"               # otra instancia tiene el proyecto abierto (§6.5, bloqueo)
READ_ONLY_UNREADABLE = "unreadable_encoding"  # UTF-16: el juego no lo lee


@dataclass(eq=False)
class DocHandle:
    """Un documento abierto: instancia única por ``rel.key`` dentro de un ``Workspace``.

    ``model`` es el objeto vivo del códec (``ParseResult`` para Clausewitz,
    ``LocalisationFile`` para CSV, ``bytes`` para binarios). Solo se toca en el
    hilo del ``Workspace`` (I12). ``version`` sube en cada ``touch``/``replace_model``;
    ``saved_version`` es la de lo último guardado o leído, así que deshacer hasta el
    punto guardado deja el documento limpio.
    """

    rel: VPath
    kind: DocKind
    model: object
    origin: FileEntry | None = None        # capa de la que se leyó; None = documento nuevo
    base: Fingerprint | None = None        # huella al leer o guardar (cambios externos)
    version: int = 0
    saved_version: int = 0
    diagnostics: list = field(default_factory=list)
    read_only_reason: str | None = None
    deleted: bool = False                  # lápida: va a la papelera al guardar

    @property
    def dirty(self) -> bool:
        return self.version != self.saved_version

    @property
    def is_new(self) -> bool:
        return self.origin is None

    @property
    def copies_from_game(self) -> bool:
        """Sucio y leído de la capa del juego (o de una dependencia): al guardar se copia al mod (D5)."""
        from ..vfs.model import LayerKind

        return self.dirty and self.origin is not None and self.origin.layer.kind is not LayerKind.MOD


# --- escrituras (§6.5) -----------------------------------------------------------------------


class WriteAction(Enum):
    CREATE = "create"
    MODIFY = "modify"
    COPY_FROM_GAME = "copy_from_game"
    TRASH = "trash"


@dataclass(frozen=True)
class PlannedWrite:
    rel: VPath
    target: Path                          # ruta real de destino (ya pasó por WriteGuard.check)
    action: WriteAction
    data: bytes | None                    # None con TRASH
    expected: Fingerprint | None          # huella que debe tener el destino al confirmar (None = no debe existir)
    diff: str = ""                        # difflib.unified_diff para «Cambios pendientes»


@dataclass(frozen=True)
class ChangeSet:
    """Lo que escribiría un guardado ahora mismo (panel «Cambios pendientes» y diálogo de revisión, D13)."""

    writes: tuple[PlannedWrite, ...] = ()

    @property
    def copies_from_game(self) -> int:
        return sum(w.action is WriteAction.COPY_FROM_GAME for w in self.writes)

    @property
    def trashed(self) -> int:
        return sum(w.action is WriteAction.TRASH for w in self.writes)

    @property
    def needs_review(self) -> bool:
        """D13: el diálogo de revisión solo sale si hay copias del juego base o papelera (los conflictos y errores
        los añade ``SaveReport``)."""
        return bool(self.copies_from_game or self.trashed)


# Códigos de SaveProblem (textos en core/project/texts/project.{es,en}.json, clave "project.<código>").
SAVE_OUTSIDE_MOD = "save_outside_mod"
SAVE_WINDOWS_NAME = "save_windows_name"
SAVE_PATH_TOO_LONG = "save_path_too_long"
SAVE_CONFLICT = "save_conflict"              # el destino cambió fuera de la aplicación desde que se leyó
SAVE_UNENCODABLE = "save_unencodable"        # un carácter no cabe en cp1252 (con línea y columna)
SAVE_SOURCE_MISMATCH = "save_source_mismatch"
SAVE_NO_SPACE = "save_no_space"
SAVE_READ_ONLY = "save_read_only"            # proyecto bloqueado por otra instancia
SAVE_CASE_COLLISION = "save_case_collision"
SAVE_NOT_WRITABLE = "save_not_writable"      # documento sin códec de escritura (binario) o ilegible (UTF-16)
SAVE_FAILED = "save_failed"                  # el disco falló al confirmar; se revirtió (args: error)
SAVE_JOURNAL_PENDING = "save_journal_pending"  # un guardado anterior quedó a medias sin resolver (args: journal)
# Motivos de SAVE_NOT_WRITABLE (args["reason"]): se traducen con la clave "project.not_writable_<motivo>".
NOT_WRITABLE_INVALID_JSON = "invalid_json"   # args: line, column
NOT_WRITABLE_INVALID = "invalid"
NOT_WRITABLE_REASONS = (READ_ONLY_BINARY, NOT_WRITABLE_INVALID_JSON, NOT_WRITABLE_INVALID)
SAVE_CODES = (SAVE_OUTSIDE_MOD, SAVE_WINDOWS_NAME, SAVE_PATH_TOO_LONG, SAVE_CONFLICT, SAVE_UNENCODABLE,
              SAVE_SOURCE_MISMATCH, SAVE_NO_SPACE, SAVE_READ_ONLY, SAVE_CASE_COLLISION, SAVE_NOT_WRITABLE,
              SAVE_FAILED, SAVE_JOURNAL_PENDING)


@dataclass(frozen=True)
class SaveProblem:
    """Algo que impide (``blocking``) o desaconseja guardar, detectado antes de tocar el disco (I9)."""

    code: str
    rel: VPath | None
    args: Mapping = MappingProxyType({})
    blocking: bool = True

    def __getstate__(self) -> tuple[str, VPath | None, Mapping, bool, bool]:
        is_proxy = isinstance(self.args, MappingProxyType)
        return (self.code, self.rel, dict(self.args) if is_proxy else self.args, self.blocking, is_proxy)

    def __setstate__(self, state: tuple[str, VPath | None, Mapping, bool, bool]) -> None:
        code, rel, args, blocking, is_proxy = state
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "rel", rel)
        object.__setattr__(self, "args", MappingProxyType(args) if is_proxy else args)
        object.__setattr__(self, "blocking", blocking)

    def message(self, lang: str = "en") -> str:
        from ..texts import text

        args = dict(self.args)
        if self.code == SAVE_NOT_WRITABLE and args.get("reason") in NOT_WRITABLE_REASONS:
            args["reason"] = text(f"project.not_writable_{args['reason']}", lang, **args)
        return text(f"project.{self.code}", lang, rel=self.rel or "", **args)


@dataclass(frozen=True)
class SaveResult:
    txid: str
    written: tuple[VPath, ...] = ()        # creados, modificados o copiados del juego
    trashed: tuple[VPath, ...] = ()
    backups: tuple[Path, ...] = ()         # .bak hechos


@dataclass(frozen=True)
class SaveReport:
    """Resultado de ``Workspace.save``: o bien ``result`` (se guardó), o bien ``problems`` (no se tocó el disco)."""

    result: SaveResult | None = None
    problems: tuple[SaveProblem, ...] = ()
    nothing_to_save: bool = False

    @property
    def ok(self) -> bool:
        return self.result is not None or self.nothing_to_save


# --- deshacer (§6.3) -------------------------------------------------------------------------


@dataclass
class Snapshot:
    rel: VPath
    before: bytes | None                   # snapshot() del códec comprimido con zlib; None = no existía
    after: bytes | None = None             # se rellena al cerrar la transacción; None = deja de existir
    before_path: Path | None = None        # instantáneas de más de 8 MB: en disco (recovery/), no en memoria
    before_deleted: bool = False           # estado de la lápida antes y después
    after_deleted: bool = False
    before_version: int = 0                # DocHandle.version antes y después: deshacer hasta el punto guardado
    after_version: int = 0                 # deja version == saved_version (limpio)
    kind: DocKind | None = None            # para volver a crear un documento que deshacer había quitado


@dataclass
class RasterPatch:
    """Parche por caja envolvente de un BMP (iteración 5); ``before``/``after`` son ``numpy.ndarray``."""

    rel: VPath
    y0: int
    x0: int
    before: object
    after: object


@dataclass
class UndoStep:
    label: str                             # clave i18n (``undo.edit_descriptor``)
    fmt: Mapping = field(default_factory=dict)   # formato de la etiqueta (``tag="XYZ"``)
    snapshots: list[Snapshot] = field(default_factory=list)
    patches: list[RasterPatch] = field(default_factory=list)
    merge_key: str | None = None           # misma clave en menos de MERGE_SECONDS: se funden en un paso


# --- cambios externos y eventos (§6.2) --------------------------------------------------------


@dataclass(frozen=True)
class ExternalChange:
    rel: VPath
    kind: str                              # "modified" | "deleted" | "created"
    dirty: bool                            # el documento abierto tiene cambios sin guardar (conflicto)


@dataclass(frozen=True)
class WorkspaceEvent:
    """Base de los eventos de ``Workspace.subscribe``."""


@dataclass(frozen=True)
class DocChanged(WorkspaceEvent):
    rel: VPath
    version: int


@dataclass(frozen=True)
class DocReplaced(WorkspaceEvent):
    """El modelo se sustituyó entero (deshacer, rehacer, recarga, edición de texto libre): re-resolver referencias."""

    rel: VPath


@dataclass(frozen=True)
class DocCreated(WorkspaceEvent):
    rel: VPath


@dataclass(frozen=True)
class DocDeleted(WorkspaceEvent):
    rel: VPath


@dataclass(frozen=True)
class DirtyChanged(WorkspaceEvent):
    count: int                             # documentos sucios


@dataclass(frozen=True)
class Saved(WorkspaceEvent):
    rels: tuple[VPath, ...]


@dataclass(frozen=True)
class UndoApplied(WorkspaceEvent):
    label: str
    fmt: Mapping
    redo: bool
    rels: tuple[VPath, ...]


# --- diario y recuperación (§6.5) -------------------------------------------------------------

JOURNAL_STAGING = "staging"            # escrito antes de los temporales: un corte ahí no deja basura sin nombre
JOURNAL_PREPARED = "prepared"
JOURNAL_BACKED_UP = "backed_up"
JOURNAL_COMMITTING = "committing"
JOURNAL_COMMITTED = "committed"
JOURNAL_UNREADABLE = "unreadable"      # diario que no se puede leer: no se toca, se informa


@dataclass(frozen=True)
class JournalState:
    txid: str
    label: str
    state: str                             # JOURNAL_*
    files: tuple[Mapping, ...]             # por archivo: rel, target, temp, action, before_sha256, after_sha256, bak
    path: Path


@dataclass(frozen=True)
class RecoveryResult:
    txid: str
    outcome: str                           # "rolled_back" | "rolled_forward" | "cleaned" | "nothing"
    restored: tuple[VPath, ...] = ()
    trashed: tuple[VPath, ...] = ()
    notes: tuple[str, ...] = ()            # claves de texto para el diálogo de recuperación


# --- ajustes del proyecto (§6.4, decisiones 1, 3 y 7 de §24) ------------------------------------

PROJECT_FORMAT = 1
EVENT_ID_START = 200_000_000
EVENT_ID_BLOCK = 10_000


@dataclass(frozen=True)
class ProjectSettings:
    """``<mod>/.vic2studio/project.json``. Leerlo no lo crea; se escribe en el primer guardado que lo cambie."""

    prefix: str                                        # por defecto la carpeta del mod en mayúsculas: "VSM", "DAM"
    languages: tuple[str, ...] = ("en", "es")
    copy_en_to: tuple[str, ...] = ()
    id_ranges: Mapping[str, tuple[int, int]] = MappingProxyType(
        {"event": (EVENT_ID_START, EVENT_ID_START + EVENT_ID_BLOCK - 1)})
    working_date: ClausewitzDate = ClausewitzDate(1836, 1, 1)
    mode: str = "simple"                               # "simple" | "advanced"
    backup_bak: bool = True
