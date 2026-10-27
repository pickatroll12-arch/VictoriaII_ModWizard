"""``Project``: la fachada que abre un mod sobre el juego base (wizard §6.4).

En la iteración 2 reúne la VFS, el ``Workspace``, los ajustes, el bloqueo y la
recuperación. Los atributos de las iteraciones siguientes (``rules``, ``index``,
``loc``, ``entities``, ``validator``) existen y valen None hasta entonces.

Abrir: lee el descriptor, construye la VFS y la escanea (sin leer contenidos),
toma el bloqueo (si otra instancia lo tiene, el proyecto se abre en solo
lectura), recupera los diarios pendientes y detecta sesiones de autoguardado
huérfanas. Nada de eso escribe en el mod salvo la recuperación de un diario
pendiente, que solo restaura un estado anterior o posterior (I2, I4). El bloqueo
se escribe fuera del mod (``core.appdirs``).

Los ajustes (``project.json``) son un documento más (``SETTINGS_REL``):
``set_settings`` los cambia en una transacción que se deshace y se guarda con el
resto; ``settings`` siempre refleja el documento en memoria.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Iterable
from contextlib import AbstractContextManager
from pathlib import Path

from ..cancel import CancelCheck, raise_if_cancelled
from ..modfile import DESCRIPTOR_SUFFIX, ModDescriptor, find_descriptor, read_descriptor
from ..vfs.model import DocKind
from ..vfs.paths import VPath
from ..vfs.vfs import VirtualFS, resolve_dependencies
from . import journal
from .codecs import codec_for
from .lock import ProjectLock
from .model import DocChanged, DocCreated, DocDeleted, DocReplaced, ProjectSettings, RecoveryResult, SaveReport
from .recovery import load_session, orphan_sessions, recover_all
from .settings import load_settings, render_settings, settings_from_json
from .workspace import ReadOnlyDocumentError, Txn, Workspace

SETTINGS_REL = VPath.of(f"{journal.PROJECT_DIR}/{journal.SETTINGS_FILE}")
# Claves de etiqueta de los pasos que crea el proyecto (catálogo de la interfaz).
LABEL_SETTINGS = "undo.project_settings"
LABEL_RESTORE = "undo.restore_session"


def new_session_id() -> str:
    """``YYYYmmddTHHMMSS-<pid>-<4 hex>``: único y ordenable; el índice del autoguardado guarda además pid y equipo."""
    return f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{os.getpid()}-{secrets.token_hex(2)}"


class Project:
    vfs: VirtualFS
    ws: Workspace
    descriptor: ModDescriptor | None
    lock: ProjectLock
    read_only: bool
    recovered: list[RecoveryResult]          # diarios que se recuperaron al abrir
    orphan_sessions: list[str]               # autoguardados de sesiones que murieron
    rules = None                             # iteración 3
    index = None                             # iteración 3
    loc = None                               # iteración 3
    entities = None                          # iteración 4
    validator = None                         # iteración 3

    @classmethod
    def open(cls, game_root: Path | None, mod_root: Path, *, descriptor: Path | None = None,
             replace_recursive: bool = True, progress=None, cancelled: CancelCheck = None) -> Project:
        """Abre ``mod_root`` (``FileNotFoundError`` si no es una carpeta). Ver el docstring del módulo."""
        raise_if_cancelled(cancelled)
        mod_root = Path(mod_root)
        if not mod_root.is_dir():
            raise FileNotFoundError(str(mod_root))
        game_root = None if game_root is None else Path(game_root)
        if descriptor is not None:
            descriptor_path = Path(descriptor)
            parsed = read_descriptor(descriptor_path)
        else:
            parsed = find_descriptor(mod_root)
            # Sin .mod, el sitio donde se creará: <juego>/mod/<Carpeta>.mod, junto a la carpeta (wizard §14.1).
            descriptor_path = (parsed.file if parsed is not None
                               else mod_root.with_name(mod_root.name + DESCRIPTOR_SUFFIX))
        dependencies, missing = resolve_dependencies(game_root, parsed.dependencies if parsed else ())
        detached = not os.access(mod_root, os.W_OK)
        project_dir = journal.project_dir(mod_root, read_only=detached)
        vfs = VirtualFS(game_root, mod_root, descriptor=descriptor_path,
                        replace_paths=parsed.replace_paths if parsed else (), replace_recursive=replace_recursive,
                        dependencies=dependencies, extra_roots=[project_dir] if detached else [])
        vfs.missing_dependencies = tuple(missing)
        lock = ProjectLock(mod_root)
        held = lock.acquire()
        try:
            recovered: list[RecoveryResult] = []
            journal_dir = project_dir / journal.JOURNAL_DIR
            if held and journal_dir.is_dir():
                recovered = recover_all(journal_dir, vfs.guard)
                if not mod_root.is_dir():   # la recuperación deshizo un «Nuevo mod» cortado: no hay mod
                    raise FileNotFoundError(str(mod_root))
            vfs.scan(progress=progress, cancelled=cancelled)
            settings = load_settings(project_dir / journal.SETTINGS_FILE, mod_root=mod_root, descriptor=parsed)
            session = new_session_id()
            orphans = orphan_sessions(project_dir / journal.RECOVERY_DIR, alive={session}, lock_held=True) if held else []
            ws = Workspace(vfs, settings=settings, read_only=not held, session_id=session, project_dir=project_dir)
        except BaseException:
            lock.release()
            raise
        project = cls.__new__(cls)
        project.vfs = vfs
        project.ws = ws
        project.descriptor = parsed
        project.lock = lock
        project.read_only = not held
        project.recovered = recovered
        project.orphan_sessions = orphans
        project._closed = False
        ws.subscribe(project._on_event)
        return project

    @property
    def closed(self) -> bool:
        """True tras ``close`` (el bloqueo ya está suelto)."""
        return self._closed

    @property
    def settings(self) -> ProjectSettings:
        return self.ws.settings

    @property
    def game_root(self) -> Path | None:
        return self.vfs.game_root

    @property
    def mod_root(self) -> Path:
        return self.vfs.mod_root

    @property
    def project_dir(self) -> Path:
        """``<mod>/.vic2studio`` (puede no existir todavía)."""
        return self.ws.project_dir

    def edit(self, label: str, *, merge_key: str | None = None, **fmt) -> AbstractContextManager[Txn]:
        return self.ws.transaction(label, merge_key=merge_key, **fmt)

    def save(self, rels: Iterable[VPath] | None = None) -> SaveReport:
        return self.ws.save(rels)

    def set_settings(self, settings: ProjectSettings) -> None:
        """Cambia los ajustes dentro de una transacción: ``project.json`` se escribe con el próximo guardado."""
        if settings == self.settings:
            return     # nada cambia: ni paso de deshacer ni project.json
        with self.ws.transaction(LABEL_SETTINGS):
            handle = self.ws.open(SETTINGS_REL, kind=DocKind.JSON, create=True)
            existing = bytes(handle.model) if handle.origin is not None or handle.dirty else None
            self.ws.replace_model(handle, render_settings(settings, existing))
            self._on_event(DocReplaced(SETTINGS_REL))   # visible ya dentro de una transacción exterior

    def _on_event(self, event) -> None:
        if isinstance(event, (DocChanged, DocReplaced, DocCreated, DocDeleted)) and event.rel.key == SETTINGS_REL.key:
            handle = self.ws.peek(SETTINGS_REL)
            if handle is not None:
                data = None if handle.deleted else bytes(handle.model)   # una lápida es «sin archivo»
            else:
                try:
                    data = (self.project_dir / journal.SETTINGS_FILE).read_bytes()
                except OSError:
                    data = None
            self.ws.settings = settings_from_json(data, mod_root=self.mod_root, descriptor=self.descriptor)

    def restore_session(self, session: str) -> list[VPath]:
        """Carga como documentos sucios un autoguardado huérfano (una transacción deshacible).

        Después borra ese autoguardado (sus documentos ya están en esta sesión, que
        tiene el suyo).
        """
        if self.read_only:
            raise ReadOnlyDocumentError(VPath.of(journal.RECOVERY_DIR), "locked")
        root = self.project_dir / journal.RECOVERY_DIR
        documents = load_session(root, session)
        restored: list[VPath] = []
        with self.ws.transaction(LABEL_RESTORE, session=session):
            for rel in sorted(documents, key=lambda r: r.key):
                handle = self.ws.open(rel, create=True)
                if not codec_for(handle.kind).writable:
                    continue
                self.ws.replace_text(handle, documents[rel])
                restored.append(handle.rel)
        # Antes de borrar el huérfano, el autoguardado de esta sesión: un corte ahora no debe perder nada (I8).
        self.ws.write_recovery()
        journal.clear_recovery(self.vfs.guard, root, session)
        if session in self.orphan_sessions:
            self.orphan_sessions.remove(session)
        return restored

    def discard_session(self, session: str) -> None:
        """Borra un autoguardado huérfano sin restaurarlo (respuesta «Descartar» del diálogo)."""
        if self.read_only:
            raise ReadOnlyDocumentError(VPath.of(journal.RECOVERY_DIR), "locked")
        journal.clear_recovery(self.vfs.guard, self.project_dir / journal.RECOVERY_DIR, session)
        if session in self.orphan_sessions:
            self.orphan_sessions.remove(session)

    def close(self, *, discard: bool = False) -> None:
        """Escribe la recuperación si hay sucios, suelta el bloqueo y cierra el Workspace.

        ``discard=True`` (cerrar sin guardar a sabiendas) borra en cambio el
        autoguardado de esta sesión.
        """
        if self._closed:
            return
        self.ws.check_thread()     # I12: desde otro hilo lanza sin soltar el bloqueo ni cerrar a medias
        self._closed = True
        try:
            if not self.read_only:
                if discard or not self.ws.dirty():
                    self.ws.clear_recovery()
                else:
                    self.ws.write_recovery(final=True)
        finally:
            self.lock.release()
            self.ws.close()

    def __enter__(self) -> Project:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
