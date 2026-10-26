"""Bloqueo entre instancias: una segunda instancia abre el mismo mod en solo lectura (wizard §5.4, §6.5, I8).

El archivo vive fuera del mod: ``core.appdirs.locks_dir() / <sha1(realpath(mod))>.lock``
con JSON ``{pid, host, started, app_version}``. Un bloqueo cuyo pid ya no existe
en este mismo equipo se considera caducado y se sustituye. Escribe a través de
``core.fileio`` (está en la lista de módulos permitidos de ``test_arch_writes``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LockInfo:
    pid: int
    host: str
    started: str


class ProjectLock:
    def __init__(self, mod_root: Path) -> None:
        raise NotImplementedError

    @property
    def path(self) -> Path:
        raise NotImplementedError

    def acquire(self) -> bool:
        """True si se obtuvo (o era caducado); False si otra instancia viva lo tiene (→ solo lectura)."""
        raise NotImplementedError

    def holder(self) -> LockInfo | None:
        raise NotImplementedError

    def release(self) -> None:
        """Solo borra el bloqueo si es de este proceso."""
        raise NotImplementedError

    def __enter__(self) -> ProjectLock:
        raise NotImplementedError

    def __exit__(self, *exc) -> None:
        raise NotImplementedError


def pid_alive(pid: int) -> bool:
    raise NotImplementedError
