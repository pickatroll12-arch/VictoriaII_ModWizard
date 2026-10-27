"""Bloqueo entre instancias: una segunda instancia abre el mismo mod en solo lectura (wizard §5.4, §6.5, I8).

El archivo vive fuera del mod: ``core.appdirs.locks_dir() / <sha1(realpath(mod))>.lock``
con JSON ``{pid, host, started, app_version}``. Un bloqueo cuyo pid ya no existe
en este mismo equipo se considera caducado y se sustituye. Escribe a través de
``core.fileio`` (está en la lista de módulos permitidos de ``test_arch_writes``).
La creación es exclusiva (``fileio.create_exclusive``): dos instancias que abren
a la vez no pueden quedarse las dos con el bloqueo.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import appdirs, fileio


@dataclass(frozen=True)
class LockInfo:
    pid: int
    host: str
    started: str


def _app_version() -> str:
    from ... import __version__

    return __version__


class ProjectLock:
    def __init__(self, mod_root: Path) -> None:
        self._mod_root = Path(mod_root)
        self._path = appdirs.locks_dir() / f"{appdirs.mod_key(self._mod_root)}.lock"
        self._held = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def held(self) -> bool:
        """True si este objeto tiene el bloqueo."""
        return self._held

    def acquire(self) -> bool:
        """True si se obtuvo (o era caducado); False si otra instancia viva lo tiene (→ solo lectura)."""
        for _ in range(3):
            data = json.dumps({
                "pid": os.getpid(), "host": socket.gethostname(),
                "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "app_version": _app_version(), "mod": str(self._mod_root),
            }, ensure_ascii=False).encode("utf-8")
            if fileio.create_exclusive(self._path, data):
                self._held = True
                return True
            holder = self.holder()
            if holder is not None and holder.host == socket.gethostname():
                # Vivo (también si es este mismo proceso: otro Project abierto sobre el mismo mod).
                if holder.pid == os.getpid() or pid_alive(holder.pid):
                    return False
            elif holder is not None:
                return False             # de otro equipo: no se puede saber si vive
            # Caducado o ilegible: se sustituye (y se vuelve a intentar la creación exclusiva).
            fileio.remove_file(self._path)
        return False

    def holder(self) -> LockInfo | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return LockInfo(int(data["pid"]), str(data["host"]), str(data.get("started", "")))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def release(self) -> None:
        """Solo borra el bloqueo si es de este proceso."""
        if not self._held:
            return
        self._held = False
        holder = self.holder()
        if holder is not None and holder.pid == os.getpid() and holder.host == socket.gethostname():
            fileio.remove_file(self._path)

    def __enter__(self) -> ProjectLock:
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True      # existe, pero es de otro usuario
    except OSError:
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    # os.kill(pid, 0) en Windows llama a TerminateProcess: nunca se usa aquí.
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5   # ERROR_ACCESS_DENIED: existe
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)
