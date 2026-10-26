"""Guardado multiarchivo con diario: todo o nada, aunque el proceso muera (wizard §6.5, I1, I2, I9, D4).

Es el **único** módulo que escribe dentro del mod (y en su descriptor): el
guardado, la papelera, ``originals/`` y el autoguardado de ``recovery/``. Toda
ruta pasa antes por ``WriteGuard.check`` y toda escritura por ``core.fileio``
(``tests/test_arch_writes.py`` lo comprueba).

Secuencia de ``SaveTransaction.commit`` (los datos ya vienen renderizados):

1. **Preparar.** Cada temporal ``.<nombre>.<txid>.tmp`` junto a su destino, con
   fsync. Después ``journal/<txid>.json`` con ``state="prepared"`` y, por archivo,
   ``rel, target, temp, action, before_sha256 | null, after_sha256, bak``; fsync
   del diario y de su carpeta.
2. **Copias.** Cada destino que existe se copia a ``<destino>.bak`` y, la primera
   vez, a ``originals/<rel>`` (nunca se sobrescribe). ``state="backed_up"``.
3. **Confirmar.** ``state="committing"``; ``commit_staged`` en orden (reintenta
   ante PermissionError); TRASH mueve a ``trash/<txid>/<rel>``. Si un paso falla
   del todo, se revierte con las ``.bak`` y los CREATE van a la papelera. Al
   terminar, ``state="committed"`` y ``fsync_dir``.
4. **Cerrar.** Se borra el diario (y ``journal/`` si queda vacía).

``FAULT_HOOK`` permite a las pruebas inyectar un fallo en cada paso.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from ..vfs.guard import WriteGuard
from ..vfs.paths import VPath
from .model import PlannedWrite, SaveProblem, SaveResult

PROJECT_DIR = ".vic2studio"
JOURNAL_DIR = "journal"
ORIGINALS_DIR = "originals"
TRASH_DIR = "trash"
RECOVERY_DIR = "recovery"
SETTINGS_FILE = "project.json"

# Pasos en los que FAULT_HOOK(step, index) puede lanzar (pruebas de I2).
STEPS = ("stage", "journal_prepared", "backup", "journal_backed_up", "replace", "trash", "journal_committed", "close")
FAULT_HOOK: Callable[[str, int], None] | None = None


def project_dir(mod_root: Path) -> Path:
    """``<mod>/.vic2studio`` (o la carpeta de datos si el mod es de solo lectura, §5.4)."""
    raise NotImplementedError


def new_txid() -> str:
    """Id ordenable por tiempo y único: ``YYYYmmddTHHMMSS-<6 hex>``."""
    raise NotImplementedError


class SaveTransaction:
    def __init__(self, guard: WriteGuard, journal_dir: Path, *, label: str, backup_bak: bool = True,
                 originals_dir: Path | None = None, trash_dir: Path | None = None) -> None:
        raise NotImplementedError

    @property
    def txid(self) -> str:
        raise NotImplementedError

    def add(self, write: PlannedWrite) -> None:
        raise NotImplementedError

    def prepare(self) -> list[SaveProblem]:
        """Comprueba sin escribir: guard, nombres de Windows, longitud de ruta, colisiones de mayúsculas,
        huella esperada de cada destino (conflictos externos) y espacio libre. Bloqueantes primero."""
        raise NotImplementedError

    def commit(self) -> SaveResult:
        """Ejecuta los pasos 1 a 4. Lanza (tras revertir) si no se puede completar; deja el diario si muere."""
        raise NotImplementedError


def trash_file(guard: WriteGuard, trash_root: Path, txid: str, rel: VPath, source: Path) -> Path:
    """Mueve ``source`` a ``trash/<txid>/<rel>``; nada se borra de verdad (I6)."""
    raise NotImplementedError


def write_recovery(guard: WriteGuard, recovery_root: Path, session: str, documents: Mapping[VPath, bytes]) -> None:
    """Autoguardado: ``recovery/<sesión>/<rel>`` con el ``snapshot()`` de cada documento sucio y un índice JSON."""
    raise NotImplementedError


def clear_recovery(guard: WriteGuard, recovery_root: Path, session: str) -> None:
    raise NotImplementedError
