"""Recuperación tras un corte: diarios pendientes y sesiones huérfanas de autoguardado (wizard §6.5, I2, I8).

``recover`` es idempotente: recuperar dos veces da lo mismo.

- ``prepared``: se borran los temporales; nada había cambiado.
- ``backed_up`` o ``committing``: se compara el sha256 de cada destino. Si todos
  coinciden con ``after``, se cierra. Si faltan algunos y sus temporales existen con
  ``after_sha256``, se avanza. Si no, se retrocede con las ``.bak`` y los CREATE van
  a la papelera.
- ``committed``: solo queda cerrar (borrar el diario).

``prefer="auto"`` sigue esa regla; ``"forward"`` y ``"back"`` fuerzan el sentido
cuando ambos son posibles. Las escrituras las hace ``journal`` (a través del guard).
"""

from __future__ import annotations

from pathlib import Path

from ..vfs.guard import WriteGuard
from ..vfs.paths import VPath
from .model import JournalState, RecoveryResult


def pending_journals(journal_dir: Path) -> list[JournalState]:
    """Diarios que quedaron sin cerrar, del más viejo al más nuevo. Uno ilegible no se borra: se informa."""
    raise NotImplementedError


def recover(journal_dir: Path, guard: WriteGuard, txid: str, *, prefer: str = "auto") -> RecoveryResult:
    raise NotImplementedError


def recover_all(journal_dir: Path, guard: WriteGuard) -> list[RecoveryResult]:
    raise NotImplementedError


def orphan_sessions(recovery_root: Path, *, alive: set[str] = frozenset()) -> list[str]:
    """Sesiones de autoguardado cuyo proceso ya no existe (y que no están en ``alive``)."""
    raise NotImplementedError


def load_session(recovery_root: Path, session: str) -> dict[VPath, bytes]:
    """Documentos guardados por ``journal.write_recovery`` en esa sesión."""
    raise NotImplementedError
