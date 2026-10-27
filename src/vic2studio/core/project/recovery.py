"""Recuperación tras un corte: diarios pendientes y sesiones huérfanas de autoguardado (wizard §6.5, I2, I8).

``recover`` es idempotente: recuperar dos veces da lo mismo.

- ``staging`` o ``prepared``: se borran los temporales; nada había cambiado
  (``outcome="cleaned"``).
- ``backed_up`` o ``committing``: se compara el sha256 de cada destino. Si todos
  coinciden con ``after``, se cierra. Si faltan algunos y sus temporales existen con
  ``after_sha256``, se avanza. Si no, se retrocede con las ``.bak`` y los CREATE van
  a la papelera (``"rolled_forward"`` o ``"rolled_back"``).
- ``committed``: solo queda cerrar (borrar el diario); el guardado estaba completo
  (``"rolled_forward"``, sin archivos tocados).

``prefer="auto"`` sigue esa regla; ``"forward"`` y ``"back"`` fuerzan el sentido
cuando ambos son posibles. Las escrituras las hace ``journal`` (a través del guard).
Lo que no encaja con ningún estado se copia antes a la papelera (I6).
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from types import MappingProxyType

from ..vfs.guard import WriteGuard
from ..vfs.model import sha256_bytes
from ..vfs.paths import DESCRIPTOR_REL, VPath
from . import journal
from .model import (
    JOURNAL_BACKED_UP,
    JOURNAL_COMMITTED,
    JOURNAL_COMMITTING,
    JOURNAL_PREPARED,
    JOURNAL_STAGING,
    JOURNAL_UNREADABLE,
    JournalState,
    RecoveryResult,
    WriteAction,
)

# Claves de texto (core/project/texts) para el diálogo de recuperación.
NOTE_UNREADABLE = "project.recovery_unreadable"
NOTE_COMPLETED = "project.recovery_completed"
NOTE_INCOMPLETE = "project.recovery_incomplete"
NOTE_FOREIGN = "project.recovery_foreign"

OUTCOME_ROLLED_BACK = "rolled_back"
OUTCOME_ROLLED_FORWARD = "rolled_forward"
OUTCOME_CLEANED = "cleaned"
OUTCOME_NOTHING = "nothing"


def rel_from_text(text: str) -> VPath:
    """``VPath`` de una ruta guardada en un diario o un índice (admite ``DESCRIPTOR_REL``)."""
    return DESCRIPTOR_REL if text == str(DESCRIPTOR_REL) else VPath.of(text)


def _read(path: Path) -> dict | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get("files", []), list):
        return None
    if record.get("format") != journal.JOURNAL_FORMAT:
        return None        # de otra versión del Studio: no se interpreta
    return record


def pending_journals(journal_dir: Path) -> list[JournalState]:
    """Diarios que quedaron sin cerrar, del más viejo al más nuevo. Uno ilegible no se borra: se informa."""
    journal_dir = Path(journal_dir)
    try:
        names = sorted(name for name in os.listdir(journal_dir) if name.endswith(".json"))
    except OSError:
        return []
    states = []
    for name in names:
        path = journal_dir / name
        record = _read(path)
        txid = name[:-len(".json")]
        if record is None:
            states.append(JournalState(txid, "", JOURNAL_UNREADABLE, (), path))
            continue
        files = tuple(MappingProxyType(dict(f)) for f in record.get("files", ()) if isinstance(f, dict))
        states.append(JournalState(str(record.get("txid", txid)), str(record.get("label", "")),
                                   str(record.get("state", JOURNAL_UNREADABLE)), files, path))
    return states


def _status(file: dict) -> tuple[bool, bool, bool]:
    """(ya está como después, se puede llevar a después, se puede llevar a antes)."""
    target = Path(file["target"])
    current = journal.sha_of(target)
    if file["action"] == WriteAction.TRASH.value:
        after_ok = current is None
        trash_ok = Path(file["trash"]).exists()
        return after_ok, after_ok or current is not None, current is not None or trash_ok
    after, before = file["after_sha256"], file["before_sha256"]
    after_ok = current == after
    temp = file.get("temp")
    can_forward = after_ok or (temp is not None and journal.sha_of(Path(temp)) == after)
    if current == before or before is None:
        can_back = True
    else:
        bak = file.get("bak")
        can_back = bak is not None and journal.sha_of(Path(bak)) == before
    return after_ok, can_forward, can_back


def _journal_paths(record: dict, files: list[dict]) -> list[str]:
    """Todas las rutas en las que la recuperación podría escribir o borrar."""
    paths = [str(record["trash_dir"])] if record.get("trash_dir") else []
    for file in files:
        paths += [str(file[k]) for k in ("target", "temp", "bak", "original", "trash") if file.get(k)]
        paths += [str(d) for d in file.get("created_dirs", ())]
    for folder in record.get("folders", ()):
        if isinstance(folder, dict):
            paths += [str(folder["path"])] if folder.get("path") else []
            paths += [str(d) for d in folder.get("created", ())]
    return paths


def recover(journal_dir: Path, guard: WriteGuard, txid: str, *, prefer: str = "auto") -> RecoveryResult:
    if prefer not in ("auto", "forward", "back"):
        raise ValueError(f"prefer debe ser 'auto', 'forward' o 'back', no {prefer!r}")
    path = Path(journal_dir) / f"{txid}.json"
    if not path.exists():
        return RecoveryResult(txid, OUTCOME_NOTHING)
    record = _read(path)
    if record is None:
        return RecoveryResult(txid, OUTCOME_NOTHING, notes=(NOTE_UNREADABLE,))
    state = record.get("state")
    files = [dict(f) for f in record.get("files", ())]
    if not all(guard.allows(p) for p in _journal_paths(record, files)):
        # El diario nombra rutas fuera de este mod (se copió o se renombró tras el corte): no se toca nada y
        # el diario se conserva; el mod se abre igual y el diálogo lo explica.
        return RecoveryResult(txid, OUTCOME_NOTHING, notes=(NOTE_FOREIGN,))
    if state in (JOURNAL_STAGING, JOURNAL_PREPARED):
        journal.discard_prepared(guard, path, record)
        return RecoveryResult(txid, OUTCOME_CLEANED)
    if state == JOURNAL_COMMITTED:
        journal.finish_journal(guard, path, record)
        return RecoveryResult(txid, OUTCOME_ROLLED_FORWARD, notes=(NOTE_COMPLETED,))
    if state not in (JOURNAL_BACKED_UP, JOURNAL_COMMITTING):
        return RecoveryResult(txid, OUTCOME_NOTHING, notes=(NOTE_UNREADABLE,))
    statuses = [_status(f) for f in files]
    can_forward = all(s[1] for s in statuses)
    can_back = all(s[2] for s in statuses)
    if prefer == "back":
        forward = not can_back and can_forward
    elif prefer == "forward":
        forward = can_forward or not can_back
    else:
        forward = can_forward
    possible = can_forward if forward else can_back
    if not possible:
        # Ni hacia delante ni hacia atrás: aplicar una parte mezclaría estados y podría pisar lo que escribió un
        # guardado posterior. No se toca nada y se conserva el diario; el diálogo lo explica.
        return RecoveryResult(txid, OUTCOME_NOTHING, notes=(NOTE_INCOMPLETE,))
    restored, trashed = [], []
    order = files if forward else list(reversed(files))
    for file in order:
        done = journal.restore_from_journal(guard, file, forward=forward,
                                            trash_creates=record.get("trash_creates", True))
        rel = rel_from_text(file["rel"])
        if done == "trashed":
            trashed.append(rel)
        elif done != "kept":
            restored.append(rel)
    if not forward:
        journal.discard_prepared(guard, path, record)
    else:
        journal.finish_journal(guard, path, record)
    return RecoveryResult(txid, OUTCOME_ROLLED_FORWARD if forward else OUTCOME_ROLLED_BACK,
                          tuple(restored), tuple(trashed))


def recover_all(journal_dir: Path, guard: WriteGuard) -> list[RecoveryResult]:
    results = []
    for state in pending_journals(journal_dir):
        if state.state == JOURNAL_UNREADABLE:
            results.append(RecoveryResult(state.txid, OUTCOME_NOTHING, notes=(NOTE_UNREADABLE,)))
            continue
        try:
            results.append(recover(journal_dir, guard, state.txid))
        except OSError:
            # Un destino bloqueado o el disco: se conserva el diario y se reintentará (también antes de guardar).
            results.append(RecoveryResult(state.txid, OUTCOME_NOTHING, notes=(NOTE_INCOMPLETE,)))
        except Exception:
            # JSON válido pero con otra forma (campos que faltan, tipos raros): como uno ilegible, no impide abrir.
            results.append(RecoveryResult(state.txid, OUTCOME_NOTHING, notes=(NOTE_UNREADABLE,)))
    return results


def _index(folder: Path) -> dict | None:
    try:
        index = json.loads((folder / journal.RECOVERY_INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return index if isinstance(index, dict) and isinstance(index.get("files"), list) else None


def orphan_sessions(recovery_root: Path, *, alive: set[str] = frozenset(), lock_held: bool = False) -> list[str]:
    """Sesiones de autoguardado cuyo proceso ya no existe (y que no están en ``alive``).

    También las que se cerraron con cambios sin guardar (``closed`` en su índice)
    aunque su proceso siga vivo. Una sesión de otro equipo cuenta como huérfana (no
    se puede saber si vive): restaurarla siempre lo confirma el usuario.
    """
    from .lock import pid_alive

    try:
        names = sorted(os.listdir(recovery_root))
    except OSError:
        return []
    host = socket.gethostname()
    orphans = []
    for name in names:
        if name in alive:
            continue
        index = _index(Path(recovery_root) / name)
        if index is None or not index["files"]:
            continue
        pid = index.get("pid")
        # Con el bloqueo del mod en la mano ninguna otra sesión de este equipo lo edita: un pid vivo es reutilizado.
        if (not lock_held and index.get("closed") is not True and index.get("host") == host
                and isinstance(pid, int) and pid_alive(pid)):
            continue
        orphans.append(name)
    return orphans


def load_session(recovery_root: Path, session: str) -> dict[VPath, bytes]:
    """Documentos guardados por ``journal.write_recovery`` en esa sesión (los que no cuadran con su sha, no)."""
    folder = Path(recovery_root) / session
    index = _index(folder)
    documents: dict[VPath, bytes] = {}
    if index is None:
        return documents
    for entry in index["files"]:
        try:
            data = (folder / entry["file"]).read_bytes()
            rel = rel_from_text(entry["rel"])
        except (OSError, KeyError, TypeError, ValueError):
            continue
        if sha256_bytes(data) == entry.get("sha256"):
            documents[rel] = data
    return documents
