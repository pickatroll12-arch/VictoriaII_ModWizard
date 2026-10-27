"""``Project`` falso para las pruebas de interfaz mientras ``core/project`` es del contrato (wizard §20).

Imita la API pública que usa la interfaz (``Project``, ``Workspace`` y lo que la
interfaz mira de ``VirtualFS``) sobre carpetas reales, normalmente de
``tests/_layers.py``: lee del disco, deshace por instantáneas de bytes, emite los
mismos eventos (``core.project.model``) y guarda escribiendo directamente (las
pruebas pueden; el núcleo real escribe con el diario). Solo documentos Clausewitz;
lo demás se abre como binario de solo lectura. Comprueba el hilo dueño como el
real: hasta ``bind_to_current_thread`` solo lo usa el hilo que lo construyó.

``implemented(...)`` dice si las funciones del contrato ya están implementadas,
para marcar con ``skipUnless`` las pruebas que necesitan el núcleo real.
"""

from __future__ import annotations

import ast
import difflib
import inspect
import shutil
import textwrap
import threading
from contextlib import contextmanager
from pathlib import Path

from vic2studio.core.clausewitz import parse, to_source
from vic2studio.core.encoding import decode_bytes, encode_text, match_bom, split_bom, split_extra_boms
from vic2studio.core.modfile import DESCRIPTOR_SUFFIX, find_descriptor
from vic2studio.core.project.model import (
    READ_ONLY_BINARY,
    READ_ONLY_PARSE_ERRORS,
    SAVE_CONFLICT,
    SAVE_READ_ONLY,
    ChangeSet,
    DirtyChanged,
    DocChanged,
    DocCreated,
    DocDeleted,
    DocHandle,
    DocKind,
    DocReplaced,
    ExternalChange,
    PlannedWrite,
    ProjectSettings,
    RecoveryResult,
    Saved,
    SaveProblem,
    SaveReport,
    SaveResult,
    Snapshot,
    UndoApplied,
    UndoStep,
    WriteAction,
)
from vic2studio.core.project.workspace import ReadOnlyDocumentError, WrongThreadError
from vic2studio.core.vfs.model import FileEntry, Fingerprint, Layer, LayerKind
from vic2studio.core.vfs.paths import DESCRIPTOR_REL, VPath

CLAUSEWITZ_SUFFIXES = {".txt", ".mod", ".gui", ".gfx", ".sfx", ".asset", ".map"}


def isolate_app_dirs() -> Path:
    """Desvía la carpeta de datos y la de cachés de la aplicación (bloqueos, diarios sueltos) a una temporal del
    proceso, si nadie lo ha hecho ya: con el núcleo real, abrir un proyecto escribe ahí su bloqueo."""
    import atexit
    import os
    import tempfile

    if not os.environ.get("VIC2STUDIO_DATA_DIR"):
        base = Path(tempfile.mkdtemp(prefix="vic2studio-appdirs-"))
        atexit.register(shutil.rmtree, base, True)
        os.environ["VIC2STUDIO_DATA_DIR"] = str(base / "data")
        os.environ["VIC2STUDIO_CACHE_DIR"] = str(base / "cache")
    return Path(os.environ["VIC2STUDIO_DATA_DIR"])


def implemented(*functions) -> bool:
    """False si alguna de ``functions`` (funciones, métodos o propiedades) solo lanza ``NotImplementedError``."""
    for function in functions:
        target = function.fget if isinstance(function, property) else getattr(function, "__func__", function)
        target = inspect.unwrap(target)
        try:
            source = textwrap.dedent(inspect.getsource(target))
        except (OSError, TypeError):
            continue
        body = ast.parse(source).body[0].body
        body = [node for node in body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        if body and isinstance(body[0], ast.Raise):
            exc = body[0].exc
            name = exc.func if isinstance(exc, ast.Call) else exc
            if isinstance(name, ast.Name) and name.id == "NotImplementedError":
                return False
    return True


class Rel(VPath):
    """``VPath`` con los métodos que el contrato aún no implementa (solo para el falso)."""

    __slots__ = ()

    @classmethod
    def of(cls, raw) -> Rel:
        if isinstance(raw, VPath) and str(raw) == str(DESCRIPTOR_REL):
            return raw
        parts = [p for p in str(raw).replace("\\", "/").split("/") if p and p != "."]
        return str.__new__(cls, "/".join(parts))

    @property
    def key(self) -> str:
        return str.upper(self)

    @property
    def name(self) -> str:
        return str(self).rsplit("/", 1)[-1]

    @property
    def suffix(self) -> str:
        name = self.name
        return name[name.rfind("."):].lower() if "." in name else ""


def _key(rel) -> str:
    return str(rel).upper()


def fingerprint(path: Path) -> Fingerprint | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return Fingerprint(stat.st_size, stat.st_mtime_ns)


class FakeSaveProblem(SaveProblem):
    """Con texto propio: ``core/texts.py`` aún es del contrato."""

    def message(self, lang: str = "en") -> str:
        return f"{self.code}: {self.rel or ''}"


def load(data: bytes, kind: DocKind):
    """(modelo, diagnósticos, motivo de solo lectura) como el códec real."""
    if kind is not DocKind.CLAUSEWITZ:
        return data, [], READ_ONLY_BINARY
    decoded = decode_bytes(data)
    text, name = split_bom(decoded.text, match_bom(data, decoded.encoding))
    text, extra = split_extra_boms(text, name)
    result = parse(text)
    result.encoding = name
    result.document.extra_boms = extra
    errors = [d for d in result.diagnostics if d.severity.value == "error"]
    return result, list(result.diagnostics), READ_ONLY_PARSE_ERRORS if errors else None


def render(handle: DocHandle) -> bytes:
    if handle.kind is not DocKind.CLAUSEWITZ:
        return handle.model
    return encode_text(to_source(handle.model.document), handle.model.encoding)


class FakeVfs:
    def __init__(self, game_root: Path | None, mod_root: Path, descriptor: Path | None):
        self.game_root = game_root
        self.mod_root = mod_root
        self.descriptor_path = descriptor
        self.mod_layer = Layer(LayerKind.MOD, mod_root, mod_root.name)
        self.game_layer = Layer(LayerKind.GAME, game_root, "game") if game_root else None
        self.guard = object()

    def mod_target(self, rel) -> Path:
        if str(rel) == str(DESCRIPTOR_REL):
            return self.descriptor_path
        return self.mod_root / str(rel)

    def stack(self, rel) -> list[FileEntry]:
        entries = []
        candidates = [(self.mod_layer, self.mod_target(rel))]
        if self.game_layer is not None and str(rel) != str(DESCRIPTOR_REL):
            candidates.append((self.game_layer, self.game_root / str(rel)))
        for layer, path in candidates:
            if path is not None and path.is_file():
                entries.append(FileEntry(Rel.of(rel), layer, path, fingerprint(path)))
        return entries

    def resolve(self, rel) -> FileEntry | None:
        stack = self.stack(rel)
        return stack[0] if stack else None


class FakeTxn:
    def __init__(self, label: str, fmt: dict, merge_key: str | None):
        self.label = label
        self.fmt = fmt
        self.merge_key = merge_key
        self.before: dict[str, tuple[DocHandle, bytes | None, bool, int]] = {}

    def touched(self) -> list[VPath]:
        return [entry[0].rel for entry in self.before.values()]


class FakeWorkspace:
    AUTOSAVE_SECONDS = 60
    AUTOSAVE_TRANSACTIONS = 20

    def __init__(self, project: FakeProject):
        self._project = project
        self._thread = threading.get_ident()
        self._docs: dict[str, DocHandle] = {}
        self._undo: list[tuple[UndoStep, dict]] = []
        self._redo: list[tuple[UndoStep, dict]] = []
        self._txn: FakeTxn | None = None
        self._listeners: list = []
        self.read_only = project.read_only_flag
        self.recovery_writes = 0
        self.closed = False
        self.saves = 0

    # --- hilos y eventos -----------------------------------------------------------------------

    def bind_to_current_thread(self) -> None:
        if self._txn is not None:
            raise RuntimeError("transacción abierta")
        self._thread = threading.get_ident()

    def _check(self) -> None:
        if threading.get_ident() != self._thread:
            raise WrongThreadError("Workspace usado desde otro hilo")

    def subscribe(self, fn):
        self._check()
        self._listeners.append(fn)
        return lambda: fn in self._listeners and self._listeners.remove(fn)

    def _emit(self, event) -> None:
        for fn in list(self._listeners):
            fn(event)

    @property
    def vfs(self) -> FakeVfs:
        return self._project.vfs

    # --- documentos ----------------------------------------------------------------------------

    def _kind(self, rel) -> DocKind:
        if str(rel) == str(DESCRIPTOR_REL) or Rel.of(rel).suffix in CLAUSEWITZ_SUFFIXES:
            return DocKind.CLAUSEWITZ
        return DocKind.BINARY

    def open(self, rel, *, kind: DocKind | None = None, create: bool = False) -> DocHandle:
        self._check()
        handle = self._docs.get(_key(rel))
        if handle is not None:
            return handle
        entry = self.vfs.resolve(rel)
        if entry is None:
            if create:
                return self.create(rel, kind or self._kind(rel))
            raise FileNotFoundError(str(rel))
        kind = kind or self._kind(rel)
        model, diagnostics, reason = load(entry.path.read_bytes(), kind)
        handle = DocHandle(Rel.of(rel), kind, model, entry, entry.fingerprint, diagnostics=diagnostics,
                           read_only_reason="locked" if self.read_only else reason)
        self._docs[_key(rel)] = handle
        return handle

    def peek(self, rel) -> DocHandle | None:
        self._check()
        return self._docs.get(_key(rel))

    @contextmanager
    def transaction(self, label: str, *, merge_key: str | None = None, **fmt):
        self._check()
        if self._txn is not None:
            yield self._txn
            return
        txn = FakeTxn(label, fmt, merge_key)
        self._txn = txn
        try:
            yield txn
        except BaseException:
            for handle, before, deleted, version in txn.before.values():
                self._restore(handle, before, deleted, version)
            self._txn = None
            raise
        self._txn = None
        if not txn.before:
            return
        snapshots, versions = [], {}
        for key, (handle, before, deleted, version) in txn.before.items():
            after = None if self._docs.get(key) is None else render(handle)
            snapshots.append(Snapshot(handle.rel, before, after, before_deleted=deleted, after_deleted=handle.deleted))
            versions[key] = (handle, version, handle.version)
        self._undo.append((UndoStep(label, dict(fmt), snapshots, merge_key=merge_key), versions))
        self._redo.clear()
        for snapshot in snapshots:
            self._emit(DocChanged(snapshot.rel, self._docs[_key(snapshot.rel)].version)
                       if _key(snapshot.rel) in self._docs else DocDeleted(snapshot.rel))
        self._emit(DirtyChanged(len(self.dirty())))

    def _require_txn(self) -> FakeTxn:
        if self._txn is None:
            raise RuntimeError("fuera de una transacción")
        return self._txn

    def touch(self, handle: DocHandle) -> None:
        self._check()
        txn = self._require_txn()
        if handle.read_only_reason:
            raise ReadOnlyDocumentError(handle.rel, handle.read_only_reason)
        key = _key(handle.rel)
        if key not in txn.before:
            existed = key in self._docs and not handle.is_new or handle.version > 0
            txn.before[key] = (handle, render(handle) if existed else None, handle.deleted, handle.version)
        handle.version += 1

    def replace_model(self, handle: DocHandle, model) -> None:
        self.touch(handle)
        handle.model = model
        self._emit(DocReplaced(handle.rel))

    def replace_text(self, handle: DocHandle, data: bytes) -> None:
        model, diagnostics, reason = load(data, handle.kind)
        self.replace_model(handle, model)
        handle.diagnostics = diagnostics
        handle.read_only_reason = reason

    def create(self, rel, kind: DocKind, model=None) -> DocHandle:
        self._check()
        txn = self._require_txn()
        if model is None:
            model = load(b"", kind)[0]
        handle = DocHandle(Rel.of(rel), kind, model)
        self._docs[_key(rel)] = handle
        txn.before.setdefault(_key(rel), (handle, None, False, 0))
        handle.version += 1
        self._emit(DocCreated(handle.rel))
        return handle

    def delete(self, rel) -> None:
        handle = self.open(rel)
        if handle.origin is not None and handle.origin.layer.kind is not LayerKind.MOD:
            raise PermissionError(str(rel))
        self.touch(handle)
        handle.deleted = True

    def _restore(self, handle: DocHandle, data: bytes | None, deleted: bool, version: int) -> None:
        key = _key(handle.rel)
        if data is None and handle.origin is None:
            self._docs.pop(key, None)
        elif data is not None:
            handle.model = load(data, handle.kind)[0]
            self._docs[key] = handle
        handle.deleted = deleted
        handle.version = version

    def _apply(self, step: UndoStep, versions: dict, *, redo: bool) -> UndoStep:
        for snapshot in step.snapshots:
            handle, before, after = versions[_key(snapshot.rel)]
            data = snapshot.after if redo else snapshot.before
            deleted = snapshot.after_deleted if redo else snapshot.before_deleted
            self._restore(handle, data, deleted, after if redo else before)
            self._emit(DocReplaced(snapshot.rel))
        self._emit(UndoApplied(step.label, step.fmt, redo, tuple(s.rel for s in step.snapshots)))
        self._emit(DirtyChanged(len(self.dirty())))
        return step

    def undo(self) -> UndoStep | None:
        self._check()
        if not self._undo:
            return None
        step, versions = self._undo.pop()
        self._redo.append((step, versions))
        return self._apply(step, versions, redo=False)

    def redo(self) -> UndoStep | None:
        self._check()
        if not self._redo:
            return None
        step, versions = self._redo.pop()
        self._undo.append((step, versions))
        return self._apply(step, versions, redo=True)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def history(self) -> list[tuple[str, dict]]:
        return [(step.label, dict(step.fmt)) for step, _ in reversed(self._undo)]

    def dirty(self) -> list[DocHandle]:
        self._check()
        return [h for h in self._docs.values() if h.dirty]

    # --- guardar -------------------------------------------------------------------------------

    def _action(self, handle: DocHandle) -> WriteAction:
        if handle.deleted:
            return WriteAction.TRASH
        if handle.origin is None:
            return WriteAction.CREATE
        if handle.origin.layer.kind is LayerKind.MOD:
            return WriteAction.MODIFY
        return WriteAction.COPY_FROM_GAME

    def changeset(self, rels=None) -> ChangeSet:
        self._check()
        wanted = None if rels is None else {_key(r) for r in rels}
        writes = []
        for handle in self.dirty():
            if wanted is not None and _key(handle.rel) not in wanted:
                continue
            action = self._action(handle)
            data = None if action is WriteAction.TRASH else render(handle)
            before = handle.origin.path.read_bytes() if handle.origin is not None else None
            writes.append(PlannedWrite(handle.rel, self.vfs.mod_target(handle.rel), action, data,
                                       handle.base if action is WriteAction.MODIFY else None,
                                       diff_text(handle.rel, before, data)))
        return ChangeSet(tuple(writes))

    def save(self, rels=None) -> SaveReport:
        changes = self.changeset(rels)
        if not changes.writes:
            return SaveReport(nothing_to_save=True)
        if self.read_only:
            return SaveReport(problems=(FakeSaveProblem(SAVE_READ_ONLY, None),))
        problems = []
        for write in changes.writes:
            handle = self._docs[_key(write.rel)]
            if write.action is WriteAction.MODIFY and fingerprint(write.target) != handle.base:
                problems.append(FakeSaveProblem(SAVE_CONFLICT, write.rel))
        if problems:
            return SaveReport(problems=tuple(problems))
        written, trashed = [], []
        for write in changes.writes:
            handle = self._docs[_key(write.rel)]
            if write.action is WriteAction.TRASH:
                trash = self._project.project_dir / "trash" / "fake" / str(write.rel)
                trash.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(write.target), trash)
                del self._docs[_key(write.rel)]
                trashed.append(write.rel)
                continue
            write.target.parent.mkdir(parents=True, exist_ok=True)
            write.target.write_bytes(write.data)
            handle.saved_version = handle.version
            handle.origin = FileEntry(handle.rel, self.vfs.mod_layer, write.target, fingerprint(write.target))
            handle.base = fingerprint(write.target)
            written.append(write.rel)
        self.saves += 1
        self._emit(Saved(tuple(written + trashed)))
        self._emit(DirtyChanged(len(self.dirty())))
        return SaveReport(SaveResult(f"fake-{self.saves}", tuple(written), tuple(trashed)))

    # --- disco ---------------------------------------------------------------------------------

    def revert(self, rel) -> None:
        handle = self.open(rel)
        if handle.origin is None:
            raise FileNotFoundError(str(rel))
        self.touch(handle)
        handle.model = load(handle.origin.path.read_bytes(), handle.kind)[0]
        handle.deleted = False
        handle.saved_version = handle.version  # igual que el disco: limpio (deshacerlo lo vuelve a ensuciar)

    def check_external_changes(self) -> list[ExternalChange]:
        self._check()
        changes = []
        for handle in self._docs.values():
            if handle.origin is None or handle.base is None:
                continue
            now = fingerprint(handle.origin.path)
            if now != handle.base:
                changes.append(ExternalChange(handle.rel, "deleted" if now is None else "modified", handle.dirty))
        return changes

    def reload(self, rel) -> None:
        self._check()
        handle = self._docs[_key(rel)]
        model, diagnostics, reason = load(handle.origin.path.read_bytes(), handle.kind)
        handle.model, handle.diagnostics, handle.read_only_reason = model, diagnostics, reason
        handle.version += 1
        handle.saved_version = handle.version
        handle.base = fingerprint(handle.origin.path)
        self._emit(DocReplaced(handle.rel))
        self._emit(DirtyChanged(len(self.dirty())))

    def accept_external(self, rel) -> None:
        self._check()
        handle = self._docs[_key(rel)]
        handle.base = fingerprint(handle.origin.path)

    def external_diff(self, rel) -> str:
        handle = self._docs[_key(rel)]
        return diff_text(handle.rel, handle.origin.path.read_bytes(), render(handle))

    def write_recovery(self) -> None:
        self._check()
        if self.dirty():
            self.recovery_writes += 1

    def close(self) -> None:
        self._check()
        self.closed = True


def diff_text(rel, before: bytes | None, after: bytes | None) -> str:
    old = [] if before is None else before.decode("cp1252", "replace").splitlines(keepends=True)
    new = [] if after is None else after.decode("cp1252", "replace").splitlines(keepends=True)
    return "".join(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}"))


class FakeProject:
    rules = index = loc = entities = validator = None

    def __init__(self, game_root: Path | None, mod_root: Path, *, read_only: bool = False,
                 orphan_sessions=(), recovered=(), sessions: dict | None = None):
        self._game_root = Path(game_root) if game_root else None
        self._mod_root = Path(mod_root)
        self.descriptor = find_descriptor(self._mod_root)
        file = self.descriptor.file if self.descriptor else self._mod_root.with_name(
            self._mod_root.name + DESCRIPTOR_SUFFIX)
        self.read_only_flag = read_only
        self.read_only = read_only
        self.vfs = FakeVfs(self._game_root, self._mod_root, file)
        self.ws = FakeWorkspace(self)
        self.settings = ProjectSettings(prefix=self._mod_root.name.upper())
        self.lock = None
        self.recovered = list(recovered)
        self.orphan_sessions = list(orphan_sessions)
        self.sessions = dict(sessions or {})
        self.closed = False
        self.opened_in = threading.get_ident()

    @property
    def game_root(self) -> Path | None:
        return self._game_root

    @property
    def mod_root(self) -> Path:
        return self._mod_root

    @property
    def project_dir(self) -> Path:
        return self._mod_root / ".vic2studio"

    def edit(self, label: str, *, merge_key: str | None = None, **fmt):
        return self.ws.transaction(label, merge_key=merge_key, **fmt)

    def save(self, rels=None) -> SaveReport:
        return self.ws.save(rels)

    def set_settings(self, settings: ProjectSettings) -> None:
        self.settings = settings

    def restore_session(self, session: str) -> list[VPath]:
        documents = self.sessions.pop(session, {})
        with self.ws.transaction("recovery.restore"):
            for rel, data in documents.items():
                handle = self.ws.open(rel, create=True)
                self.ws.replace_text(handle, data)
        if session in self.orphan_sessions:
            self.orphan_sessions.remove(session)
        return [Rel.of(rel) for rel in documents]

    def close(self) -> None:
        self.ws.close()
        self.closed = True


class FakeOpener:
    """Sustituye a ``Project.open`` en ``Session(opener=...)``: anota las llamadas y construye ``FakeProject``.

    ``gate``: un ``threading.Event`` que la apertura espera (para probar la cancelación y las aperturas que
    llegan tarde). ``error``: excepción que lanza. El resto se pasa a ``FakeProject``.
    """

    def __init__(self, *, error: BaseException | None = None, gate: threading.Event | None = None, **options):
        self.error = error
        self.gate = gate
        self.options = options
        self.calls: list[tuple[Path | None, Path]] = []
        self.projects: list[FakeProject] = []
        self.threads: list[int] = []

    def __call__(self, game_root, mod_root, *, descriptor=None, replace_recursive=True, progress=None,
                 cancelled=None) -> FakeProject:
        self.calls.append((game_root, mod_root))
        self.threads.append(threading.get_ident())
        if self.gate is not None:
            while not self.gate.wait(0.01):
                if cancelled is not None and cancelled():
                    from vic2studio.core.cancel import Cancelled

                    raise Cancelled()
        if self.error is not None:
            raise self.error
        project = FakeProject(game_root, mod_root, **self.options)
        self.projects.append(project)
        return project


def recovered_result(txid: str = "20261026T120000-abcdef", outcome: str = "rolled_back") -> RecoveryResult:
    return RecoveryResult(txid, outcome, restored=(Rel.of("common/countries.txt"),))
