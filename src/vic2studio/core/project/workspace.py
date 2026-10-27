"""``Workspace``: documentos, transacciones con nombre, deshacer y guardado (wizard §6.2).

Python puro y de un solo hilo: llamar desde otro hilo lanza ``WrongThreadError``
(I12). Toda mutación va dentro de ``transaction``: antes de tocar un modelo se
llama a ``touch(handle)``, que toma la instantánea (una vez por transacción) y sube
``version``. Las transacciones anidadas se funden en la exterior; si una lanza, sus
documentos vuelven a la instantánea y no se apila nada.

Guardar (``save``): renderiza todos los sucios con su códec (aquí saltan los
errores de codificación y de verificación sin tocar el disco), planifica cada
escritura (CREATE, MODIFY, COPY_FROM_GAME a la misma ruta del mod, TRASH), la
comprueba y la confirma con ``journal.SaveTransaction``. Guardar sin cambios no
escribe nada ni crea ``.vic2studio/`` (I4).

Versiones: cada estado nuevo de un documento recibe un número único del
``Workspace``; deshacer y rehacer restauran el número del estado al que vuelven,
así que «sucio» (``version != saved_version``) es exacto: deshacer hasta el punto
guardado deja el documento limpio. Una transacción que no cambia los bytes de un
documento le devuelve su versión (tocar sin cambiar no ensucia).

Si al cerrar una transacción un documento no se puede codificar (un carácter que
no cabe en cp1252), la transacción se revierte y lanza ``UnencodableTextError``:
el error llega al editar, no al guardar (I9).

Las rutas bajo ``.vic2studio/`` (``project.json``) son documentos de la carpeta de
proyecto: no están en la VFS (``scan`` no las recorre) y se leen y guardan en
``project_dir``.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..clausewitz.diagnostics import ENCODING_CODES, Severity
from ..clausewitz.parser import ParseResult
from ..clausewitz.serializer import SourceMismatchError
from ..encoding import GAME_UNREADABLE, UnencodableTextError
from ..fileio import FileChangedError
from ..vfs.guard import WriteOutsideModError
from ..vfs.model import DocKind, FileEntry, Fingerprint, LayerKind
from ..vfs.paths import VPath
from ..vfs.vfs import VirtualFS
from . import journal
from .codecs import codec_for, kind_for
from .diffing import unified_diff
from .documents import DocumentStore
from .model import (
    NOT_WRITABLE_INVALID,
    NOT_WRITABLE_INVALID_JSON,
    READ_ONLY_BINARY,
    READ_ONLY_LOCKED,
    READ_ONLY_PARSE_ERRORS,
    READ_ONLY_UNREADABLE,
    SAVE_CONFLICT,
    SAVE_FAILED,
    SAVE_JOURNAL_PENDING,
    SAVE_NOT_WRITABLE,
    SAVE_OUTSIDE_MOD,
    SAVE_READ_ONLY,
    SAVE_SOURCE_MISMATCH,
    SAVE_UNENCODABLE,
    ChangeSet,
    DirtyChanged,
    DocChanged,
    DocCreated,
    DocDeleted,
    DocHandle,
    DocReplaced,
    ExternalChange,
    PlannedWrite,
    ProjectSettings,
    Saved,
    SaveProblem,
    SaveReport,
    SaveResult,
    Snapshot,
    UndoApplied,
    UndoStep,
    WorkspaceEvent,
    WriteAction,
)
from .undo import UndoStack, compress, decompress

_log = logging.getLogger(__name__)

PROJECT_PREFIX = journal.PROJECT_DIR
# Claves de etiqueta de los pasos que crea el propio Workspace (catálogo de la interfaz).
LABEL_REVERT = "undo.revert_file"
LABEL_SAVE = "save.label"
# Motivos de solo lectura que todavía admiten sustituir el texto entero (D17).
_TEXT_EDITABLE = frozenset({None, READ_ONLY_PARSE_ERRORS, READ_ONLY_UNREADABLE})


class WrongThreadError(RuntimeError):
    """El ``Workspace`` se usó desde un hilo que no es el suyo (I12)."""


class ReadOnlyDocumentError(PermissionError):
    """Se intentó mutar un documento con ``read_only_reason`` (sintaxis rota, binario, bloqueo)."""

    def __init__(self, rel: VPath, reason: str):
        self.rel = rel
        self.reason = reason
        super().__init__(f"{rel}: {reason}")

    def __reduce__(self):
        return (type(self), (self.rel, self.reason))


@dataclass
class _State:
    """Estado de un documento al empezar a cambiarlo en una transacción (``data=None``: no existía)."""

    handle: DocHandle | None
    data: bytes | None
    deleted: bool
    version: int
    kind: DocKind | None
    rel: VPath


class Txn:
    """Transacción abierta: ``label`` y ``fmt`` dan el nombre del paso de deshacer."""

    label: str
    fmt: dict
    merge_key: str | None

    def __init__(self, label: str, fmt: dict, merge_key: str | None, parent: Txn | None) -> None:
        self.label = label
        self.fmt = fmt
        self.merge_key = merge_key
        self.parent = parent
        self._states: dict[str, _State] = {}
        self._replaced: set[str] = set()
        self._reverted: dict[str, bytes] = {}
        self._revert_saved: dict[str, int | None] = {}

    def touched(self) -> list[VPath]:
        return [state.rel for state in self._states.values()]


class Workspace:
    AUTOSAVE_SECONDS = 60
    AUTOSAVE_TRANSACTIONS = 20

    def __init__(self, vfs: VirtualFS, *, settings: ProjectSettings, lru_bytes: int = 300 * 2**20,
                 read_only: bool = False, session_id: str | None = None, project_dir: Path | None = None) -> None:
        self._vfs = vfs
        self._settings = settings
        self._read_only = read_only
        self._session_id = session_id
        self._project_dir = Path(project_dir) if project_dir is not None else journal.project_dir(vfs.mod_root)
        self._thread = threading.get_ident()
        self._store = DocumentStore(lru_bytes=lru_bytes)
        self._undo = UndoStack()
        self._frames: list[Txn] = []
        self._versioned: set[str] = set()   # claves con versión nueva en la transacción exterior abierta
        self._versions = itertools.count(1)
        self._ghosts: dict[str, DocHandle] = {}
        self._snap: dict[str, tuple[int, bytes]] = {}
        self._subscribers: list[Callable[[WorkspaceEvent], None]] = []
        self._last_dirty = 0
        self._autosave_txns = 0
        self._autosave_time = time.monotonic()
        self._recovery_signature: dict[str, int] | None = None
        self._closed = False

    # --- hilo y estado general -------------------------------------------------------

    def _check(self) -> None:
        if threading.get_ident() != self._thread:
            raise WrongThreadError("el Workspace solo se usa desde el hilo que lo posee (I12)")
        if self._closed:
            raise RuntimeError("el Workspace está cerrado")

    def check_thread(self) -> None:
        """``WrongThreadError`` si se llama desde otro hilo (o ``RuntimeError`` si está cerrado), sin tocar nada."""
        self._check()

    def bind_to_current_thread(self) -> None:
        """Hace dueño al hilo actual (``Project.open`` se construye en segundo plano y se entrega a la interfaz).
        Lanza ``RuntimeError`` si hay una transacción abierta."""
        if self._frames:
            raise RuntimeError("no se puede cambiar de hilo con una transacción abierta")
        self._thread = threading.get_ident()

    @property
    def vfs(self) -> VirtualFS:
        return self._vfs

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def settings(self) -> ProjectSettings:
        return self._settings

    @settings.setter
    def settings(self, value: ProjectSettings) -> None:
        self._settings = value

    @property
    def project_dir(self) -> Path:
        return self._project_dir

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def in_transaction(self) -> bool:
        return bool(self._frames)

    # --- abrir --------------------------------------------------------------------------

    def _project_path(self, rel: VPath) -> Path | None:
        parts = rel.parts
        if parts and parts[0] == PROJECT_PREFIX and len(parts) > 1:
            return self._project_dir.joinpath(*parts[1:])
        return None

    def _disk_entry(self, rel: VPath) -> FileEntry | None:
        """Archivo efectivo de ``rel`` en disco: el ganador de la VFS o un archivo de la carpeta de proyecto."""
        project = self._project_path(rel)
        if project is None:
            return self._vfs.resolve(rel)
        try:
            fingerprint = Fingerprint.of_path(project)
        except OSError:
            return None
        return FileEntry(rel, self._vfs.mod_layer, project, fingerprint) if project.is_file() else None

    def _read_entry(self, entry: FileEntry) -> tuple[bytes, Fingerprint]:
        data = entry.path.read_bytes()
        try:
            stat = os.stat(entry.path)
        except OSError:
            return data, Fingerprint(len(data), entry.fingerprint.mtime_ns, None)
        return data, Fingerprint.of_bytes(data, stat)

    def _reason(self, kind: DocKind, model: object, diagnostics: list) -> str | None:
        if self._read_only:
            return READ_ONLY_LOCKED
        if not codec_for(kind).writable:
            return READ_ONLY_BINARY
        if kind is DocKind.CLAUSEWITZ and isinstance(model, ParseResult):
            if model.encoding in GAME_UNREADABLE:
                return READ_ONLY_UNREADABLE
            if any(d.severity is Severity.ERROR and d.code not in ENCODING_CODES for d in diagnostics):
                return READ_ONLY_PARSE_ERRORS
        return None

    def open(self, rel: str | VPath, *, kind: DocKind | None = None, create: bool = False) -> DocHandle:
        """Documento efectivo de ``rel`` (ganador de la VFS, o el nuevo/sucio en memoria). Leer no escribe (I4).

        Sin archivo y sin ``create``: ``FileNotFoundError``. Con ``create`` y sin
        archivo devuelve un documento nuevo vacío y limpio (no se guarda hasta que
        se toque). Un documento borrado (lápida) también da ``FileNotFoundError``; con
        ``create`` revive vacío, lo que es una mutación: va dentro de una transacción.
        Con errores de sintaxis se abre con ``read_only_reason="parse_errors"`` (D17).
        """
        self._check()
        rel = VPath.of(rel)
        handle = self._store.get(rel)
        if handle is not None:
            if handle.deleted:
                if create:
                    kind = kind or handle.kind
                    return self.create(rel, kind, self._underlying_model(rel, kind))
                raise FileNotFoundError(str(rel))
            return handle
        entry = self._disk_entry(rel)
        if entry is None:
            if not create:
                raise FileNotFoundError(str(rel))
            kind = kind or kind_for(rel)
            model = codec_for(kind).empty(rel)
            version = next(self._versions)
            handle = DocHandle(rel, kind, model, version=version, saved_version=version)
            handle.read_only_reason = self._reason(kind, model, [])
            self._store.add(handle, 0)
            return handle
        data, fingerprint = self._read_entry(entry)
        kind = kind or kind_for(entry.rel)
        model, diagnostics = codec_for(kind).load(data, entry.rel)
        version = next(self._versions)
        handle = DocHandle(entry.rel, kind, model, origin=entry, base=fingerprint, version=version,
                           saved_version=version, diagnostics=diagnostics)
        handle.read_only_reason = self._reason(kind, model, diagnostics)
        self._store.add(handle, len(data))
        self._evict(keep=handle.rel.key)
        return handle

    def _underlying_model(self, rel: VPath, kind: DocKind) -> object | None:
        """Modelo del archivo que el juego cargaría sin la copia del mod (juego o dependencia), o None: revivir
        una lápida con ``create=True`` no debe tapar ese archivo con uno vacío."""
        for entry in self._vfs.stack(rel):
            if entry.layer.kind is not LayerKind.MOD and not self._vfs.hidden_by_replace_path(entry):
                data, _ = self._read_entry(entry)
                return codec_for(kind).load(data, entry.rel)[0]
        return None

    def peek(self, rel: str | VPath) -> DocHandle | None:
        self._check()
        return self._store.get(rel)

    def documents(self) -> list[DocHandle]:
        """Documentos abiertos (también lápidas), ordenados por ``rel.key``."""
        self._check()
        return sorted(self._store, key=lambda h: h.rel.key)

    def _evict(self, keep: str | None = None) -> None:
        """Expulsa documentos limpios de la LRU; nunca los de la pila de deshacer, la transacción ni ``keep``
        (el que se acaba de abrir: quien llamó a ``open`` lo va a usar)."""
        pinned = self._undo.referenced() | {k for f in self._frames for k in f._states}
        if keep is not None:
            pinned.add(keep)
        for rel in self._store.evict(pinned):
            self._snap.pop(rel.key, None)

    # --- transacciones ------------------------------------------------------------------

    @contextmanager
    def transaction(self, label: str, *, merge_key: str | None = None, **fmt) -> Iterator[Txn]:
        self._check()
        parent = self._frames[-1] if self._frames else None
        txn = Txn(label, dict(fmt), merge_key, parent)
        self._frames.append(txn)
        try:
            yield txn
        except BaseException:
            self._frames.pop()
            self._revert(txn)
            raise
        self._frames.pop()
        if parent is None:
            self._finish(txn)

    def _require_txn(self) -> Txn:
        if not self._frames:
            raise RuntimeError("las mutaciones van dentro de Workspace.transaction()")
        return self._frames[-1]

    def _require_writable_workspace(self, rel: VPath) -> None:
        if self._read_only:
            raise ReadOnlyDocumentError(rel, READ_ONLY_LOCKED)

    def _require_live(self, handle: DocHandle) -> None:
        if self._store.get(handle.rel) is not handle:
            raise ValueError(f"{handle.rel}: el documento ya no está abierto (vuelve a pedirlo con open)")

    def _capture(self, handle: DocHandle | None, rel: VPath) -> _State:
        if handle is None:
            return _State(None, None, False, 0, None, rel)
        if handle.is_new and not handle.dirty and not handle.deleted:
            # Vacío de open(create=True) sin tocar: no existía (deshacer lo quita, o lo borra si ya se guardó).
            return _State(handle, None, False, handle.version, handle.kind, handle.rel)
        cached = self._snap.get(handle.rel.key)
        if cached is not None and cached[0] == handle.version:
            data = cached[1]
        else:
            data = compress(codec_for(handle.kind).snapshot(handle.model))
            self._snap[handle.rel.key] = (handle.version, data)
        return _State(handle, data, handle.deleted, handle.version, handle.kind, handle.rel)

    def _begin_change(self, handle: DocHandle | None, rel: VPath) -> None:
        """Registra el estado previo de ``rel`` en las transacciones que aún no lo tienen y le da versión nueva."""
        key = rel.key
        if key not in self._frames[-1]._states:
            state = self._capture(handle, rel)
            for frame in self._frames:
                frame._states.setdefault(key, state)
        if key not in self._versioned:
            self._versioned.add(key)
            if handle is not None:
                handle.version = next(self._versions)

    def touch(self, handle: DocHandle) -> None:
        """Llamar antes de mutar ``handle.model`` (dentro de una transacción; si no, ``RuntimeError``)."""
        self._check()
        self._require_txn()
        self._require_live(handle)
        if handle.read_only_reason is not None:
            raise ReadOnlyDocumentError(handle.rel, handle.read_only_reason)
        if handle.deleted:
            raise FileNotFoundError(f"{handle.rel}: está borrado")
        self._begin_change(handle, handle.rel)

    def replace_model(self, handle: DocHandle, model: object, *, diagnostics: list | None = None) -> None:
        """Sustituye el modelo entero (edición de texto libre, arreglo de sintaxis); también se deshace."""
        self._check()
        txn = self._require_txn()
        self._require_live(handle)
        if handle.read_only_reason not in _TEXT_EDITABLE:
            raise ReadOnlyDocumentError(handle.rel, handle.read_only_reason)
        if handle.deleted:
            raise FileNotFoundError(f"{handle.rel}: está borrado")
        self._begin_change(handle, handle.rel)
        if diagnostics is None:
            diagnostics = list(getattr(model, "diagnostics", []) or [])
        handle.model = model
        handle.diagnostics = diagnostics
        handle.read_only_reason = self._reason(handle.kind, model, diagnostics)
        txn._replaced.add(handle.rel.key)
        for frame in self._frames:
            frame._replaced.add(handle.rel.key)

    def replace_text(self, handle: DocHandle, data: bytes) -> None:
        """``replace_model(handle, codec.load(data))`` y recalcula ``read_only_reason`` (D17: tras arreglar la
        sintaxis se habilita la edición estructural)."""
        self._check()
        model, diagnostics = codec_for(handle.kind).load(bytes(data), handle.rel)
        self.replace_model(handle, model, diagnostics=diagnostics)

    def create(self, rel: str | VPath, kind: DocKind, model: object | None = None) -> DocHandle:
        """Documento nuevo (dentro de una transacción); ``model=None`` usa ``codec.empty``.

        ``FileExistsError`` si ya hay un archivo o un documento con esa ruta (salvo
        una lápida, que revive, o un documento nuevo aún sin tocar, que se reutiliza).
        """
        self._check()
        self._require_txn()
        rel = VPath.of(rel)
        self._require_writable_workspace(rel)
        codec = codec_for(kind)
        if not codec.writable:
            raise ReadOnlyDocumentError(rel, READ_ONLY_BINARY)
        handle = self._store.get(rel)
        if handle is not None and not handle.deleted and not (handle.is_new and not handle.dirty):
            raise FileExistsError(str(rel))
        if handle is None and self._disk_entry(rel) is not None:
            raise FileExistsError(str(rel))
        model = codec.empty(rel) if model is None else model
        diagnostics = list(getattr(model, "diagnostics", []) or [])
        if handle is None:
            self._begin_change(None, rel)
            self._ghosts.pop(rel.key, None)
            handle = DocHandle(rel, kind, model, version=next(self._versions), saved_version=0,
                               diagnostics=diagnostics)
            self._store.add(handle, 0)
        else:
            self._begin_change(handle, handle.rel)
            handle.kind = kind
            handle.model = model
            handle.deleted = False
            handle.diagnostics = diagnostics
        handle.read_only_reason = self._reason(kind, model, diagnostics)
        for frame in self._frames:
            frame._replaced.add(rel.key)
        return handle

    def delete(self, rel: str | VPath) -> None:
        """Lápida (dentro de una transacción): al guardar, el archivo del mod va a la papelera. Uno del juego no se
        puede borrar (``PermissionError``)."""
        self._check()
        self._require_txn()
        rel = VPath.of(rel)
        self._require_writable_workspace(rel)
        handle = self.open(rel)
        if handle.origin is not None and handle.origin.layer.kind is not LayerKind.MOD:
            raise PermissionError(f"{rel}: es del juego base (o de una dependencia) y no se puede borrar")
        self._begin_change(handle, handle.rel)
        if handle.is_new:
            self._remove(handle)
        else:
            handle.deleted = True

    def _remove(self, handle: DocHandle) -> None:
        self._store.discard(handle.rel)
        self._ghosts[handle.rel.key] = handle
        self._versioned.discard(handle.rel.key)   # otro DocHandle de la misma ruta recibirá versión nueva

    def _apply(self, rel: VPath, data: bytes | None, deleted: bool, version: int, kind: DocKind | None,
               handle: DocHandle | None = None) -> DocHandle | None:
        """Pone ``rel`` en un estado guardado (``data=None``: sin documento).

        «Sin documento» con el archivo ya en el mod (se creó y se guardó) es una
        lápida: la vista efectiva lo da por borrado y el próximo guardado lo manda a
        la papelera (I7). Sin archivo en el mod, el documento simplemente se quita.
        """
        key = rel.key
        live = self._store.get(rel)
        if data is not None and deleted:
            entry = self._disk_entry(rel)
            if entry is None or entry.layer.kind is not LayerKind.MOD:
                data = None    # lápida sin archivo del mod debajo: no queda nada que borrar
        if data is None:
            entry = self._disk_entry(rel)
            if entry is not None and entry.layer.kind is LayerKind.MOD:
                return self._tombstone(rel, entry, version, live or handle or self._ghosts.get(key))
            if live is not None:
                self._remove(live)
            self._snap.pop(key, None)
            return None
        target = live or handle or self._ghosts.get(key)
        if target is None:
            entry = self._disk_entry(rel)
            target = DocHandle(rel, kind or kind_for(rel), None, origin=entry,
                               base=None if entry is None else entry.fingerprint,
                               saved_version=next(self._versions))
        if live is None:
            self._ghosts.pop(key, None)
            self._store.add(target, len(data))
        model, diagnostics = codec_for(target.kind).load(decompress(data), target.rel)
        target.model = model
        target.diagnostics = diagnostics
        target.deleted = deleted
        target.version = version
        target.read_only_reason = self._reason(target.kind, model, diagnostics)
        self._snap[key] = (version, data)
        return target

    def _tombstone(self, rel: VPath, entry: FileEntry, version: int, target: DocHandle | None) -> DocHandle:
        if target is None:
            data, fingerprint = self._read_entry(entry)
            kind = kind_for(entry.rel)
            model, diagnostics = codec_for(kind).load(data, entry.rel)
            target = DocHandle(entry.rel, kind, model, origin=entry, base=fingerprint,
                               saved_version=next(self._versions), diagnostics=diagnostics)
        if target.origin is None or target.origin.layer.kind is not LayerKind.MOD:
            target.origin = entry
            target.base = entry.fingerprint
        if self._store.get(rel) is not target:
            self._ghosts.pop(rel.key, None)
            self._store.add(target, entry.fingerprint.size)
        target.deleted = True
        target.version = version
        self._snap.pop(rel.key, None)
        return target

    def _revert(self, txn: Txn) -> None:
        """Deshace en memoria lo que hizo ``txn`` (que lanzó) y lo olvida en las transacciones de fuera."""
        events: list[WorkspaceEvent] = []
        for key, state in reversed(list(txn._states.items())):
            self._apply(state.rel, state.data, state.deleted, state.version, state.kind, state.handle)
            for frame in self._frames:
                if frame._states.get(key) is state:
                    del frame._states[key]
                    frame._replaced.discard(key)
            if not any(key in frame._states for frame in self._frames):
                self._versioned.discard(key)
            events.append(DocReplaced(state.rel) if state.data is not None else DocDeleted(state.rel))
        if not self._frames:
            self._versioned.clear()
        for event in events:
            self._emit(event)

    def _finish(self, txn: Txn) -> None:
        """Cierra la transacción exterior: calcula los ``after``, apila el paso y avisa."""
        snapshots: list[Snapshot] = []
        saved: list[tuple[DocHandle, int]] = []
        swapped: list[VPath] = []
        try:
            for key, state in txn._states.items():
                handle = self._store.get(state.rel)
                if handle is None:
                    after, deleted, version, kind = None, False, 0, state.kind
                else:
                    after = compress(codec_for(handle.kind).snapshot(handle.model))
                    deleted, version, kind = handle.deleted, handle.version, handle.kind
                if after == state.data and deleted == state.deleted:
                    if handle is not None:
                        handle.version = state.version    # sin cambios: ni versión nueva ni paso
                        if key in txn._replaced:
                            swapped.append(handle.rel)    # mismo texto, otro objeto: hay que re-resolver
                    continue
                if handle is not None:
                    reverted = txn._reverted.get(key)
                    if reverted is not None and reverted == after and not deleted:
                        # «Revertir» deja el documento como en disco: si el disco no cambió desde lo leído o
                        # guardado, es el mismo estado que el punto guardado (deshacer hasta él queda limpio).
                        same = txn._revert_saved.get(key)
                        if same is not None:
                            handle.version = version = same
                        else:
                            saved.append((handle, version))
                    self._snap[key] = (version, after)
                snapshots.append(Snapshot(
                    handle.rel if handle is not None else state.rel, state.data, after,
                    before_deleted=state.deleted, after_deleted=deleted,
                    before_version=state.version, after_version=version, kind=kind or state.kind))
        except BaseException:
            self._revert(txn)
            raise
        finally:
            self._versioned.clear()
        for handle, version in saved:
            handle.saved_version = version
        for rel in swapped:
            self._emit(DocReplaced(rel))
        if not snapshots:
            return
        self._undo.push(UndoStep(txn.label, dict(txn.fmt), snapshots, merge_key=txn.merge_key))
        self._forget_ghosts()
        self._autosave_txns += 1
        self._emit_changes(snapshots, txn._replaced)
        self._evict()

    def _emit_changes(self, snapshots: Iterable[Snapshot], replaced: set[str] = frozenset(), *,
                      backwards: bool = False) -> None:
        for snapshot in snapshots:
            before_exists = snapshot.before is not None and not snapshot.before_deleted
            after_exists = snapshot.after is not None and not snapshot.after_deleted
            if backwards:
                before_exists, after_exists = after_exists, before_exists
            if after_exists and not before_exists:
                self._emit(DocCreated(snapshot.rel))
            elif before_exists and not after_exists:
                self._emit(DocDeleted(snapshot.rel))
            elif backwards or snapshot.rel.key in replaced:
                self._emit(DocReplaced(snapshot.rel))
            else:
                self._emit(DocChanged(snapshot.rel, snapshot.after_version))
        self._emit_dirty()

    def _emit_dirty(self) -> None:
        count = len(self._dirty_handles())
        if count != self._last_dirty:
            self._last_dirty = count
            self._emit(DirtyChanged(count))

    def _forget_ghosts(self) -> None:
        if self._ghosts:
            referenced = self._undo.referenced()
            for key in [k for k in self._ghosts if k not in referenced]:
                del self._ghosts[key]

    # --- deshacer -----------------------------------------------------------------------

    def _step(self, step: UndoStep | None, *, redo: bool) -> UndoStep | None:
        if step is None:
            return None
        order = step.snapshots if redo else list(reversed(step.snapshots))
        for snapshot in order:
            if redo:
                self._apply(snapshot.rel, snapshot.after, snapshot.after_deleted, snapshot.after_version,
                            snapshot.kind)
            else:
                self._apply(snapshot.rel, snapshot.before, snapshot.before_deleted, snapshot.before_version,
                            snapshot.kind)
        self._emit(UndoApplied(step.label, dict(step.fmt), redo, tuple(s.rel for s in step.snapshots)))
        if redo:
            self._emit_changes(step.snapshots, {s.rel.key for s in step.snapshots})
        else:
            self._emit_changes(step.snapshots, backwards=True)
        return step

    def undo(self) -> UndoStep | None:
        self._check()
        if self._frames:
            raise RuntimeError("no se puede deshacer con una transacción abierta")
        return self._step(self._undo.undo(), redo=False)

    def redo(self) -> UndoStep | None:
        self._check()
        if self._frames:
            raise RuntimeError("no se puede rehacer con una transacción abierta")
        return self._step(self._undo.redo(), redo=True)

    def can_undo(self) -> bool:
        self._check()
        return self._undo.can_undo()

    def can_redo(self) -> bool:
        self._check()
        return self._undo.can_redo()

    def history(self) -> list[tuple[str, dict]]:
        self._check()
        return self._undo.labels()

    def redo_history(self) -> list[tuple[str, dict]]:
        self._check()
        return self._undo.redo_labels()

    # --- cambios pendientes y guardado ----------------------------------------------------

    def _dirty_handles(self) -> list[DocHandle]:
        return sorted((h for h in self._store if h.dirty), key=lambda h: h.rel.key)

    def dirty(self) -> list[DocHandle]:
        self._check()
        return self._dirty_handles()

    def _selected(self, rels: Iterable[VPath] | None) -> list[DocHandle]:
        handles = self._dirty_handles()
        if rels is None:
            return handles
        keys = {VPath.of(r).key for r in rels}
        return [h for h in handles if h.rel.key in keys]

    def _target(self, handle: DocHandle) -> Path:
        project = self._project_path(handle.rel)
        if project is not None:
            return project
        if handle.origin is not None and handle.origin.layer.kind is LayerKind.MOD:
            return handle.origin.path
        return self._vfs.mod_target(handle.rel)

    def _encoding(self, handle: DocHandle) -> str | None:
        return getattr(handle.model, "encoding", None)

    def _plan(self, handles: list[DocHandle], *, with_diff: bool
              ) -> tuple[list[tuple[DocHandle, PlannedWrite]], list[SaveProblem], list[DocHandle]]:
        """(escrituras, problemas antes del disco, documentos sucios cuyo contenido ya es el del disco)."""
        plans: list[tuple[DocHandle, PlannedWrite]] = []
        problems: list[SaveProblem] = []
        unchanged: list[DocHandle] = []
        for handle in handles:
            codec = codec_for(handle.kind)
            target = self._target(handle)
            mod_file = handle.origin is not None and handle.origin.layer.kind is LayerKind.MOD
            if handle.deleted:
                if not mod_file:
                    unchanged.append(handle)
                    continue
                diff = ""
                if with_diff:
                    diff = unified_diff(handle.rel, codec.snapshot(handle.model), None,
                                        encoding=self._encoding(handle))
                plans.append((handle, PlannedWrite(handle.rel, target, WriteAction.TRASH, None, handle.base, diff)))
                continue
            if not codec.writable:
                problems.append(SaveProblem(SAVE_NOT_WRITABLE, handle.rel, {"reason": READ_ONLY_BINARY}))
                continue
            try:
                data = codec.render(handle.model, rel=handle.rel)
            except UnencodableTextError as exc:
                index, line, column, char = exc.problems[0]
                problems.append(SaveProblem(SAVE_UNENCODABLE, handle.rel, {
                    "line": line, "column": column, "char": char, "encoding": exc.encoding,
                    "count": len(exc.problems)}))
                continue
            except SourceMismatchError as exc:
                problems.append(SaveProblem(SAVE_SOURCE_MISMATCH, handle.rel, {
                    "entry": exc.params.get("entry", ""), "line": exc.params.get("line", 0),
                    "near_errors": bool(exc.params.get("near_errors"))}))
                continue
            except json.JSONDecodeError as exc:
                problems.append(SaveProblem(SAVE_NOT_WRITABLE, handle.rel, {
                    "reason": NOT_WRITABLE_INVALID_JSON, "line": exc.lineno, "column": exc.colno}))
                continue
            except (ValueError, LookupError):
                problems.append(SaveProblem(SAVE_NOT_WRITABLE, handle.rel, {"reason": NOT_WRITABLE_INVALID}))
                continue
            if mod_file:
                action, expected = WriteAction.MODIFY, handle.base
                before = _read_or_none(handle.origin.path)
            elif handle.origin is not None:
                action, expected = WriteAction.COPY_FROM_GAME, None
                before = _read_or_none(handle.origin.path)
            else:
                action, expected = WriteAction.CREATE, None
                before = None
            if before is not None and before == data:
                unchanged.append(handle)    # I4: un archivo del juego solo se copia al mod si cambió
                continue
            diff = unified_diff(handle.rel, before, data, encoding=self._encoding(handle)) if with_diff else ""
            plans.append((handle, PlannedWrite(handle.rel, target, action, data, expected, diff)))
        return plans, problems, unchanged

    def changeset(self, rels: Iterable[VPath] | None = None) -> ChangeSet:
        """Lo que escribiría ``save(rels)``, con su diff; no toca el disco. Puede lanzar los errores de render."""
        self._check()
        plans, problems, _ = self._plan(self._selected(rels), with_diff=True)
        for problem in problems:
            if problem.code in (SAVE_UNENCODABLE, SAVE_SOURCE_MISMATCH):
                handle = next(h for h in self._store if h.rel.key == problem.rel.key)
                codec_for(handle.kind).render(handle.model, rel=handle.rel)   # relanza el error original
        return ChangeSet(tuple(write for _, write in plans))

    def save(self, rels: Iterable[VPath] | None = None) -> SaveReport:
        self._check()
        if self._frames:
            raise RuntimeError("no se puede guardar con una transacción abierta")
        if self._read_only:
            return SaveReport(problems=(SaveProblem(SAVE_READ_ONLY, None),))
        handles = self._selected(rels)
        if not handles:
            return SaveReport(nothing_to_save=True)
        journal_dir = self._project_dir / journal.JOURNAL_DIR
        pending = self._unresolved_journal(journal_dir)
        if pending is not None:
            # Un guardado anterior quedó a medias: otro encima cambiaría las .bak y los archivos que su diario usa.
            return SaveReport(problems=(SaveProblem(SAVE_JOURNAL_PENDING, None, {"journal": str(pending)}),))
        plans, problems, unchanged = self._plan(handles, with_diff=False)
        if problems:
            return SaveReport(problems=tuple(problems))
        if not plans:
            self._mark_unchanged(unchanged)
            return SaveReport(nothing_to_save=True)
        transaction = journal.SaveTransaction(self._vfs.guard, journal_dir, label=LABEL_SAVE,
                                              backup_bak=self._settings.backup_bak)
        for _, write in plans:
            transaction.add(write)
        checks = transaction.prepare()
        if any(problem.blocking for problem in checks):
            return SaveReport(problems=tuple(checks))
        try:
            result = transaction.commit()
        except FileChangedError as exc:
            rel = next((w.rel for _, w in plans if Path(w.target) == Path(exc.path)), None)
            return SaveReport(problems=(SaveProblem(SAVE_CONFLICT, rel, {"path": str(exc.path)}),))
        except WriteOutsideModError as exc:
            return SaveReport(problems=(SaveProblem(SAVE_OUTSIDE_MOD, None, {"path": str(exc.path)}),))
        except BaseException as exc:
            result = self._after_failed_commit(transaction, plans, exc)
            if result is None:
                if not isinstance(exc, Exception):
                    raise
                return SaveReport(problems=(SaveProblem(SAVE_FAILED, None, {"error": str(exc)}),))
        self._mark_saved(plans)
        self._mark_unchanged(unchanged, emit=False)
        self._undo.seal()
        if not self._dirty_handles():
            self.clear_recovery()      # todo guardado: el autoguardado de esta sesión ya no sirve
        self._emit(Saved(tuple(h.rel for h, _ in plans)))
        self._emit_dirty()
        return SaveReport(result=result, problems=tuple(checks))

    def _unresolved_journal(self, journal_dir: Path) -> Path | None:
        """Intenta cerrar los diarios pendientes (``recover_all``); devuelve el primero que siga sin resolver.

        Uno que nombra rutas de otra carpeta (el mod se copió o se renombró tras el corte, ``NOTE_FOREIGN``) no
        cuenta: ningún guardado de este mod toca esas rutas, y la recuperación nunca lo resolvería.
        """
        from .recovery import NOTE_FOREIGN, pending_journals, recover_all

        if not journal_dir.is_dir() or not pending_journals(journal_dir):
            return None
        foreign: set[str] = set()
        try:
            foreign = {result.txid for result in recover_all(journal_dir, self._vfs.guard)
                       if NOTE_FOREIGN in result.notes}
        except Exception:
            _log.exception("no se pudo recuperar un guardado pendiente")
        remaining = [state for state in pending_journals(journal_dir) if state.txid not in foreign]
        return remaining[0].path if remaining else None

    def _after_failed_commit(self, transaction, plans, exc) -> SaveResult | None:
        """Tras una excepción en ``commit``: deja el disco coherente con ``recover`` y dice si quedó guardado."""
        from .recovery import OUTCOME_ROLLED_FORWARD, recover

        try:
            outcome = recover(self._project_dir / journal.JOURNAL_DIR, self._vfs.guard, transaction.txid)
        except Exception:
            _log.exception("no se pudo recuperar el guardado %s", transaction.txid)
            return None
        if outcome.outcome != OUTCOME_ROLLED_FORWARD:
            return None
        writes = [w for _, w in plans]
        return SaveResult(transaction.txid,
                          written=tuple(w.rel for w in writes if w.action is not WriteAction.TRASH),
                          trashed=tuple(w.rel for w in writes if w.action is WriteAction.TRASH))

    def _mark_saved(self, plans: list[tuple[DocHandle, PlannedWrite]]) -> None:
        self._vfs.refresh([w.rel for _, w in plans if self._project_path(w.rel) is None])
        for handle, write in plans:
            if write.action is WriteAction.TRASH:
                handle.origin = None
                handle.base = None
                handle.saved_version = handle.version
                self._remove(handle)
                continue
            handle.saved_version = handle.version
            entry = self._disk_entry(handle.rel)
            if entry is not None:
                handle.origin = entry
                try:
                    handle.base = Fingerprint.of_bytes(write.data, os.stat(entry.path))
                except OSError:
                    handle.base = entry.fingerprint
        self._forget_ghosts()

    def _mark_unchanged(self, handles: list[DocHandle], *, emit: bool = True) -> None:
        for handle in handles:
            handle.saved_version = handle.version
            if handle.deleted:
                self._remove(handle)
        if emit and handles:
            self._emit_dirty()

    def revert(self, rel: str | VPath) -> None:
        """Vuelve a lo que hay en disco (dentro de una transacción, así que también se deshace)."""
        self._check()
        rel = VPath.of(rel)
        if not self._frames:
            with self.transaction(LABEL_REVERT, rel=str(rel)):
                self.revert(rel)
            return
        handle = self._store.get(rel)
        if handle is None:
            return
        self._require_writable_workspace(rel)
        txn = self._frames[-1]
        if self._project_path(rel) is None:
            self._vfs.refresh([rel])
        entry = self._disk_entry(rel)
        self._begin_change(handle, handle.rel)
        if entry is None:
            self._remove(handle)
            return
        data, fingerprint = self._read_entry(entry)
        unchanged_disk = (handle.origin is not None and handle.base is not None
                          and os.path.normcase(str(handle.origin.path)) == os.path.normcase(str(entry.path))
                          and handle.base.matches(fingerprint, entry.path))
        codec = codec_for(handle.kind)
        model, diagnostics = codec.load(data, entry.rel)
        saved_point = handle.saved_version if unchanged_disk else None
        handle.model = model
        handle.diagnostics = diagnostics
        handle.deleted = False
        handle.origin = entry
        handle.base = fingerprint
        handle.read_only_reason = self._reason(handle.kind, model, diagnostics)
        reverted = compress(codec.snapshot(model))
        for frame in self._frames:
            frame._replaced.add(rel.key)
        txn._reverted[rel.key] = reverted
        outer = self._frames[0]
        outer._reverted[rel.key] = reverted
        outer._revert_saved[rel.key] = saved_point

    # --- cambios externos -----------------------------------------------------------------

    def check_external_changes(self) -> list[ExternalChange]:
        """Al recuperar el foco y antes de guardar: documentos abiertos cuyo archivo cambió fuera.

        Los documentos limpios que cambiaron se recargan solos (``DocReplaced``); los
        sucios se dejan como están (conflicto: «Conservar», «Recargar» o «Comparar»).
        Se devuelven todos, con ``dirty`` para distinguirlos.
        """
        self._check()
        changes: list[ExternalChange] = []
        for handle in list(self._store):
            kind = self._external_kind(handle)
            if kind is None:
                continue
            changes.append(ExternalChange(handle.rel, kind, handle.dirty))
            if not handle.dirty and not self._frames:
                self.reload(handle.rel)
        return changes

    def _external_kind(self, handle: DocHandle) -> str | None:
        target = self._target(handle)
        mod_file = handle.origin is not None and handle.origin.layer.kind is LayerKind.MOD
        try:
            current = Fingerprint.of_path(target)
        except OSError:
            current = None
        if mod_file:
            if current is None:
                return "deleted"
            if handle.base is not None and not handle.base.matches(current, target):
                return "modified"
            return None
        if current is not None:
            return "created"     # nuevo en memoria, o copia del juego que otro programa creó en el mod
        if handle.origin is not None and handle.base is not None:
            try:
                game = Fingerprint.of_path(handle.origin.path)
            except OSError:
                return "deleted"
            if not handle.base.matches(game, handle.origin.path):
                return "modified"
        return None

    def reload(self, rel: str | VPath) -> None:
        """Descarta lo de memoria y vuelve a leer (respuesta «Recargar del disco» al conflicto). No se deshace."""
        self._check()
        if self._frames:
            raise RuntimeError("no se puede recargar con una transacción abierta")
        rel = VPath.of(rel)
        handle = self._store.get(rel)
        if handle is None:
            return
        if self._project_path(rel) is None:
            self._vfs.refresh([rel])
        entry = self._disk_entry(rel)
        if entry is None:
            self._remove(handle)
            self._snap.pop(rel.key, None)
            self._emit(DocDeleted(handle.rel))
            self._emit_dirty()
            return
        data, fingerprint = self._read_entry(entry)
        model, diagnostics = codec_for(handle.kind).load(data, entry.rel)
        version = next(self._versions)
        handle.model = model
        handle.diagnostics = diagnostics
        handle.origin = entry
        handle.base = fingerprint
        handle.deleted = False
        handle.version = handle.saved_version = version
        handle.read_only_reason = self._reason(handle.kind, model, diagnostics)
        self._snap.pop(rel.key, None)
        self._store.resize(rel, len(data))
        self._undo.seal()
        self._emit(DocReplaced(handle.rel))
        self._emit_dirty()

    def accept_external(self, rel: str | VPath) -> None:
        """«Conservar mis cambios»: adopta la huella actual del disco como base, así que el próximo guardado
        sobrescribe el cambio externo (el diario hace su .bak). No toca el modelo."""
        self._check()
        rel = VPath.of(rel)
        handle = self._store.get(rel)
        if handle is None:
            return
        target = self._target(handle)
        if self._project_path(rel) is None:
            self._vfs.refresh([rel])
        try:
            fingerprint = Fingerprint.of_path(target, with_hash=True)
        except OSError:
            fingerprint = None
        if fingerprint is None:
            # Borrado fuera: el próximo guardado lo crea de nuevo en el mod.
            if handle.origin is not None and handle.origin.layer.kind is LayerKind.MOD:
                handle.origin = None
                handle.base = None
                if handle.deleted:
                    handle.saved_version = handle.version
                    self._remove(handle)
                    self._emit_dirty()
                else:
                    handle.saved_version = next(self._versions)   # el disco ya no tiene ningún estado del historial
            return
        handle.origin = self._disk_entry(rel) if self._project_path(rel) is not None else (
            self._vfs.entry(rel, LayerKind.MOD) or handle.origin)
        handle.base = fingerprint
        handle.saved_version = next(self._versions)   # ningún estado del historial es ya el del disco
        self._undo.seal()

    def external_diff(self, rel: str | VPath) -> str:
        """«Comparar»: diff entre lo que hay ahora en disco y el documento en memoria."""
        self._check()
        rel = VPath.of(rel)
        handle = self._store.get(rel)
        if handle is None:
            raise FileNotFoundError(str(rel))
        disk = _read_or_none(self._target(handle))
        if disk is None and handle.origin is not None:
            disk = _read_or_none(handle.origin.path)
        memory = None if handle.deleted else codec_for(handle.kind).snapshot(handle.model)
        return unified_diff(handle.rel, disk, memory, encoding=self._encoding(handle))

    # --- autoguardado ---------------------------------------------------------------------

    def autosave_due(self, now: float | None = None) -> bool:
        """True si toca autoguardar: cada ``AUTOSAVE_SECONDS`` o cada ``AUTOSAVE_TRANSACTIONS`` transacciones."""
        now = time.monotonic() if now is None else now
        return (self._autosave_txns >= self.AUTOSAVE_TRANSACTIONS
                or now - self._autosave_time >= self.AUTOSAVE_SECONDS)

    def write_recovery(self, *, final: bool = False) -> None:
        """Autoguardado de los sucios en ``recovery/<sesión>/`` (no crea nada si no hay sucios).

        ``final``: la sesión termina (``Project.close``); su autoguardado se ofrecerá al reabrir.
        """
        self._check()
        self._autosave_txns = 0
        self._autosave_time = time.monotonic()
        if self._read_only or self._session_id is None:
            return
        documents: dict[VPath, bytes] = {}
        signature: dict[str, int] = {}
        for handle in self._dirty_handles():
            if handle.deleted:
                continue
            try:
                documents[handle.rel] = codec_for(handle.kind).snapshot(handle.model)
            except (ValueError, LookupError):
                continue
            signature[handle.rel.key] = handle.version
        if signature == self._recovery_signature and not (final and documents):
            return
        root = self._project_dir / journal.RECOVERY_DIR
        if not documents and not (root / self._session_id).exists():
            self._recovery_signature = signature
            return
        journal.write_recovery(self._vfs.guard, root, self._session_id, documents, closed=final)
        self._recovery_signature = signature

    def clear_recovery(self) -> None:
        """Borra el autoguardado de esta sesión (al cerrar descartando los cambios)."""
        self._check()
        if self._read_only or self._session_id is None:
            return
        root = self._project_dir / journal.RECOVERY_DIR
        if (root / self._session_id).exists():
            journal.clear_recovery(self._vfs.guard, root, self._session_id)
        self._recovery_signature = None

    # --- eventos ----------------------------------------------------------------------------

    def subscribe(self, fn: Callable[[WorkspaceEvent], None]) -> Callable[[], None]:
        """Devuelve la función que cancela la suscripción."""
        self._check()
        self._subscribers.append(fn)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(fn)
            except ValueError:
                pass

        return unsubscribe

    def _emit(self, event: WorkspaceEvent) -> None:
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception:
                _log.exception("un suscriptor del Workspace falló con %r", event)

    def close(self) -> None:
        self._check()
        self._store.clear()
        self._undo.clear()
        self._ghosts.clear()
        self._snap.clear()
        self._subscribers.clear()
        self._closed = True


def _read_or_none(path: Path) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return None
