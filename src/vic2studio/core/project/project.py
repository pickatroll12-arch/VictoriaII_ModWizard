"""``Project``: la fachada que abre un mod sobre el juego base (wizard §6.4).

En la iteración 2 reúne la VFS, el ``Workspace``, los ajustes, el bloqueo y la
recuperación. Los atributos de las iteraciones siguientes (``rules``, ``index``,
``loc``, ``entities``, ``validator``) existen y valen None hasta entonces.

Abrir: lee el descriptor, construye la VFS y la escanea (sin leer contenidos),
toma el bloqueo (si otra instancia lo tiene, el proyecto se abre en solo
lectura), recupera los diarios pendientes y detecta sesiones de autoguardado
huérfanas. Nada de eso escribe en el mod salvo la recuperación de un diario
pendiente, que solo restaura un estado anterior o posterior (I2, I4).
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractContextManager
from pathlib import Path

from ..cancel import CancelCheck
from ..modfile import ModDescriptor
from ..vfs.paths import VPath
from ..vfs.vfs import VirtualFS
from .lock import ProjectLock
from .model import ProjectSettings, RecoveryResult, SaveReport
from .workspace import Txn, Workspace


class Project:
    vfs: VirtualFS
    ws: Workspace
    settings: ProjectSettings
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
        raise NotImplementedError

    @property
    def game_root(self) -> Path | None:
        raise NotImplementedError

    @property
    def mod_root(self) -> Path:
        raise NotImplementedError

    @property
    def project_dir(self) -> Path:
        """``<mod>/.vic2studio`` (puede no existir todavía)."""
        raise NotImplementedError

    def edit(self, label: str, *, merge_key: str | None = None, **fmt) -> AbstractContextManager[Txn]:
        raise NotImplementedError

    def save(self, rels: Iterable[VPath] | None = None) -> SaveReport:
        raise NotImplementedError

    def set_settings(self, settings: ProjectSettings) -> None:
        """Cambia los ajustes dentro de una transacción: ``project.json`` se escribe con el próximo guardado."""
        raise NotImplementedError

    def restore_session(self, session: str) -> list[VPath]:
        """Carga como documentos sucios un autoguardado huérfano (una transacción deshacible)."""
        raise NotImplementedError

    def close(self) -> None:
        """Escribe la recuperación si hay sucios, suelta el bloqueo y cierra el Workspace."""
        raise NotImplementedError
