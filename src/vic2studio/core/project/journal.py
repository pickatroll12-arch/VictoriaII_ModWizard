"""Guardado multiarchivo con diario: todo o nada, aunque el proceso muera (wizard §6.5, I1, I2, I9, D4).

Es el **único** módulo que escribe dentro del mod (y en su descriptor): el
guardado, la papelera, ``originals/`` y el autoguardado de ``recovery/``. Toda
ruta pasa antes por ``WriteGuard.check`` y toda escritura por ``core.fileio``
(``tests/test_arch_writes.py`` lo comprueba: las llamadas a ``fileio`` solo están
en las funciones ``_guarded_*``, que comprueban cada ruta con el guard).

Secuencia de ``SaveTransaction.commit`` (los datos ya vienen renderizados):

1. **Preparar.** ``journal/<txid>.json`` con ``state="staging"`` y la lista de
   temporales (un corte mientras se escriben no deja basura sin nombre). Cada
   temporal ``.<nombre>.<txid>.tmp`` junto a su destino, con fsync. Después el
   diario pasa a ``state="prepared"`` con, por archivo, ``rel, target, temp,
   action, before_sha256 | null, after_sha256, bak``; fsync del diario y de su carpeta.
2. **Copias.** Cada destino que existe se copia a ``<destino>.bak`` y, la primera
   vez, a ``originals/<rel>`` (nunca se sobrescribe). ``state="backed_up"``.
   Con ``backup_bak=False`` la copia de reversión va a ``journal/<txid>/`` y se
   borra al cerrar.
3. **Confirmar.** ``state="committing"``; ``commit_staged`` en orden (reintenta
   ante PermissionError); TRASH mueve a ``trash/<txid>/<rel>``. Si un paso falla
   del todo, se revierte con las ``.bak`` y los CREATE van a la papelera. Al
   terminar, ``state="committed"`` y ``fsync_dir``.
4. **Cerrar.** Se borra el diario (y ``journal/`` y ``.vic2studio/`` si quedan vacías).

``FAULT_HOOK`` permite a las pruebas inyectar un fallo en cada paso.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from .. import appdirs, fileio
from ..fileio import BACKUP_SUFFIX, FileChangedError
from ..vfs.guard import WriteGuard, WriteOutsideModError
from ..vfs.model import Fingerprint, sha256_bytes, sha256_file
from ..vfs.paths import VPath, long_path_problem, windows_name_problems
from .model import (
    JOURNAL_BACKED_UP,
    JOURNAL_COMMITTED,
    JOURNAL_COMMITTING,
    JOURNAL_PREPARED,
    JOURNAL_STAGING,
    SAVE_CASE_COLLISION,
    SAVE_CONFLICT,
    SAVE_NO_SPACE,
    SAVE_OUTSIDE_MOD,
    SAVE_PATH_TOO_LONG,
    SAVE_WINDOWS_NAME,
    PlannedWrite,
    SaveProblem,
    SaveResult,
    WriteAction,
)

PROJECT_DIR = ".vic2studio"
JOURNAL_DIR = "journal"
ORIGINALS_DIR = "originals"
TRASH_DIR = "trash"
RECOVERY_DIR = "recovery"
SETTINGS_FILE = "project.json"
JOURNAL_FORMAT = 1
RECOVERY_INDEX = "index.json"
# Margen de espacio libre que se exige además de los bytes a escribir (temporales y copias).
SPACE_MARGIN = 4 * 2**20

# Pasos en los que FAULT_HOOK(step, index) puede lanzar (pruebas de I2).
STEPS = ("stage", "journal_prepared", "backup", "journal_backed_up", "replace", "trash", "journal_committed", "close")
FAULT_HOOK: Callable[[str, int], None] | None = None


def _fault(step: str, index: int = 0) -> None:
    hook = FAULT_HOOK
    if hook is not None:
        hook(step, index)


def project_dir(mod_root: Path, *, read_only: bool | None = None) -> Path:
    """``<mod>/.vic2studio`` (o la carpeta de datos si el mod es de solo lectura, §5.4).

    ``read_only=None`` lo averigua con ``os.access`` (un mod que aún no existe no es de solo lectura).
    """
    mod_root = Path(mod_root)
    if read_only is None:
        read_only = mod_root.exists() and not os.access(mod_root, os.W_OK)
    return appdirs.detached_project_dir(mod_root) if read_only else mod_root / PROJECT_DIR


def new_txid() -> str:
    """Id ordenable por tiempo y único: ``YYYYmmddTHHMMSS-<6 hex>``."""
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- escrituras: todas pasan por el guard -------------------------------------------------

def _guarded_write(guard: WriteGuard, path: Path, data: bytes) -> None:
    fileio.atomic_write_bytes(guard.check(path), data)


def _guarded_stage(guard: WriteGuard, target: Path, data: bytes, token: str) -> Path:
    temp = _temp_path(target, token)
    guard.check(temp)
    fileio.remove_file(guard.check(temp))  # restos de un intento anterior con el mismo txid (recuperación)
    return fileio.stage_bytes(guard.check(target), data, token=token)


def _guarded_commit(guard: WriteGuard, temp: Path, target: Path) -> None:
    fileio.commit_staged(guard.check(temp), guard.check(target))


def _guarded_copy(guard: WriteGuard, source: Path, target: Path) -> None:
    fileio.copy_file(source, guard.check(target))


def _guarded_move(guard: WriteGuard, source: Path, target: Path) -> None:
    fileio.move_file(guard.check(source), guard.check(target))


def _guarded_remove(guard: WriteGuard, path: Path) -> None:
    fileio.remove_file(guard.check(path))


def _guarded_mkdirs(guard: WriteGuard, folder: Path) -> None:
    fileio.make_dirs(guard.check(folder))


def _guarded_rmdirs(guard: WriteGuard, folder: Path, stop_at: Path) -> None:
    guard.check(folder)
    fileio.remove_empty_dirs(folder, stop_at=stop_at)


def _guarded_fsync_dirs(guard: WriteGuard, folders: Iterable[Path]) -> None:
    for folder in sorted(set(folders)):
        if os.path.isdir(folder):
            fileio.fsync_dir(guard.check(folder))


def _temp_path(target: Path, token: str) -> Path:
    return target.with_name(f".{target.name}.{token}.tmp")


def _stop_at(guard: WriteGuard, folder: Path) -> Path:
    """Hasta dónde se pueden borrar carpetas vacías: la raíz del guard que contiene ``folder`` (excluida)."""
    for root in (guard.mod_root, *guard.extra_roots):
        try:
            Path(os.path.abspath(folder)).relative_to(os.path.abspath(root))
        except ValueError:
            continue
        return Path(root)
    return Path(folder).parent


def _sha_or_none(path: Path) -> str | None:
    try:
        return sha256_file(path)
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        return None


def _missing_dirs(folder: Path) -> list[Path]:
    """Carpetas de ``folder`` hacia arriba que aún no existen, la más profunda primero."""
    missing = []
    current = Path(folder)
    while not current.exists() and current.parent != current:
        missing.append(current)
        current = current.parent
    return missing


# --- transacción de guardado ---------------------------------------------------------------

class SaveTransaction:
    def __init__(self, guard: WriteGuard, journal_dir: Path, *, label: str, backup_bak: bool = True,
                 originals_dir: Path | None = None, trash_dir: Path | None = None) -> None:
        self._guard = guard
        self._journal_dir = Path(journal_dir)
        self._label = label
        self._backup_bak = backup_bak
        self._originals_dir = Path(originals_dir) if originals_dir is not None else self._journal_dir.parent / ORIGINALS_DIR
        self._trash_dir = Path(trash_dir) if trash_dir is not None else self._journal_dir.parent / TRASH_DIR
        self._txid = new_txid()
        self._writes: list[PlannedWrite] = []
        self._folders: list[Path] = []
        self._committed = False

    @property
    def txid(self) -> str:
        return self._txid

    @property
    def journal_path(self) -> Path:
        return self._journal_dir / f"{self._txid}.json"

    @property
    def writes(self) -> tuple[PlannedWrite, ...]:
        return tuple(self._writes)

    def add(self, write: PlannedWrite) -> None:
        if write.action is WriteAction.TRASH:
            if write.data is not None:
                raise ValueError("TRASH no lleva datos")
        elif write.data is None:
            raise ValueError(f"{write.action.value} necesita datos")
        key = os.path.normcase(os.path.abspath(write.target))
        if any(os.path.normcase(os.path.abspath(w.target)) == key for w in self._writes):
            raise ValueError(f"destino repetido en la transacción: {write.target}")
        self._writes.append(write)

    def add_folder(self, folder: Path) -> None:
        """Carpeta que debe existir tras confirmar (esqueleto de un mod nuevo); se crea vacía si no existe y, si
        se revierte, se borra si sigue vacía."""
        self._folders.append(Path(folder))

    # --- comprobaciones (sin escribir) ---------------------------------------------------

    def prepare(self) -> list[SaveProblem]:
        """Comprueba sin escribir: guard, nombres de Windows, longitud de ruta, colisiones de mayúsculas,
        huella esperada de cada destino (conflictos externos) y espacio libre. Bloqueantes primero."""
        problems: list[SaveProblem] = []
        seen_upper: dict[str, PlannedWrite] = {}
        for write in self._writes:
            target = Path(write.target)
            try:
                self._guard.check(target)
                if write.action is not WriteAction.TRASH:
                    self._guard.check(_temp_path(target, self._txid))
            except WriteOutsideModError:
                problems.append(SaveProblem(SAVE_OUTSIDE_MOD, write.rel, {"path": str(target)}))
                continue
            for name in self._checked_names(write):
                for code in windows_name_problems(name):
                    problems.append(SaveProblem(SAVE_WINDOWS_NAME, write.rel, {"name": name, "reason": code}))
            if write.action is not WriteAction.TRASH:
                longest = _temp_path(target, self._txid)
                if long_path_problem(longest) is not None:
                    problems.append(SaveProblem(SAVE_PATH_TOO_LONG, write.rel,
                                                {"length": len(os.path.abspath(longest))}, blocking=False))
            upper = os.path.abspath(target).upper()
            other = seen_upper.get(upper)
            if other is not None:
                problems.append(SaveProblem(SAVE_CASE_COLLISION, write.rel, {"other": str(other.rel)}))
            seen_upper[upper] = write
            sibling = self._case_sibling(target)
            if sibling is not None:
                problems.append(SaveProblem(SAVE_CASE_COLLISION, write.rel, {"other": sibling}))
            if not self._matches_expected(write):
                problems.append(SaveProblem(SAVE_CONFLICT, write.rel, {"path": str(target)}))
        problems.extend(self._space_problems())
        problems.sort(key=lambda p: not p.blocking)
        return problems

    def _checked_names(self, write: PlannedWrite) -> list[str]:
        if write.rel.startswith("@"):
            return [Path(write.target).name]
        return list(write.rel.parts)

    @staticmethod
    def _case_sibling(target: Path) -> str | None:
        """Otro archivo de la carpeta de destino con el mismo nombre salvo mayúsculas (Windows los confundiría)."""
        try:
            names = os.listdir(target.parent)
        except OSError:
            return None
        upper = target.name.upper()
        for name in sorted(names):
            if name != target.name and name.upper() == upper:
                return name
        return None

    @staticmethod
    def _matches_expected(write: PlannedWrite) -> bool:
        target = Path(write.target)
        try:
            current = Fingerprint.of_path(target)
        except FileNotFoundError:
            current = None
        except OSError:
            return False
        if write.expected is None:
            return current is None
        return write.expected.matches(current, target)

    def _space_problems(self) -> list[SaveProblem]:
        needed: dict[str, int] = {}
        probe: dict[str, Path] = {}
        for write in self._writes:
            if write.data is None:
                continue
            folder = Path(write.target).parent
            while not folder.exists() and folder.parent != folder:
                folder = folder.parent
            try:
                device = str(os.stat(folder).st_dev)
            except OSError:
                continue
            extra = 0
            if Path(write.target).exists():
                extra = Path(write.target).stat().st_size * 2   # .bak y originals/
            needed[device] = needed.get(device, 0) + len(write.data) + extra
            probe.setdefault(device, folder)
        problems = []
        for device, amount in needed.items():
            try:
                free = shutil.disk_usage(probe[device]).free
            except OSError:
                continue
            if free < amount + SPACE_MARGIN:
                problems.append(SaveProblem(SAVE_NO_SPACE, None, {"needed": amount, "free": free}))
        return problems

    # --- confirmación ---------------------------------------------------------------------

    def commit(self) -> SaveResult:
        """Ejecuta los pasos 1 a 4. Lanza (tras revertir) si no se puede completar; deja el diario si muere.

        Antes de tocar nada vuelve a comprobar el guard y la huella de cada destino
        (``WriteOutsideModError``, ``FileChangedError``).
        """
        if self._committed:
            raise RuntimeError("la transacción ya se confirmó")
        self._committed = True
        guard = self._guard
        for write in self._writes:
            guard.check(write.target)
            if not self._matches_expected(write):
                raise FileChangedError(write.target)
        for folder in self._folders:
            guard.check(folder)
        files = [self._file_record(i, w) for i, w in enumerate(self._writes)]
        record = {
            "format": JOURNAL_FORMAT, "txid": self._txid, "label": self._label, "state": JOURNAL_STAGING,
            "created": _now(), "files": files,
            "folders": [{"path": str(f), "created": [str(d) for d in _missing_dirs(f)]} for f in self._folders],
            "trash_dir": str(self._trash_dir), "private_backups": not self._backup_bak,
        }
        journal = self.journal_path
        progress = _Progress()
        try:
            self._write_journal(record)
            # 1. temporales
            for index, (write, file) in enumerate(zip(self._writes, files)):
                if write.action is not WriteAction.TRASH:
                    _guarded_stage(guard, Path(write.target), write.data, self._txid)
                    progress.staged.append(index)
                _fault("stage", index)
            _guarded_fsync_dirs(guard, (Path(w.target).parent for w in self._writes))
            record["state"] = JOURNAL_PREPARED
            self._write_journal(record)
            _fault("journal_prepared")
            # 2. copias
            backups: list[Path] = []
            for index, (write, file) in enumerate(zip(self._writes, files)):
                target = Path(write.target)
                if file["before_sha256"] is not None and write.action is not WriteAction.TRASH:
                    _guarded_copy(guard, target, Path(file["bak"]))
                    if not file["private_bak"]:
                        backups.append(Path(file["bak"]))
                if file["before_sha256"] is not None and file["original"] is not None:
                    original = Path(file["original"])
                    if not original.exists():
                        _guarded_copy(guard, target, original)
                _fault("backup", index)
            record["state"] = JOURNAL_BACKED_UP
            self._write_journal(record)
            _fault("journal_backed_up")
            # 3. confirmar
            record["state"] = JOURNAL_COMMITTING
            self._write_journal(record)
            for folder in self._folders:
                _guarded_mkdirs(guard, folder)
            for index, (write, file) in enumerate(zip(self._writes, files)):
                if write.action is WriteAction.TRASH:
                    continue
                _guarded_commit(guard, Path(file["temp"]), Path(write.target))
                progress.replaced.append(index)
                _fault("replace", index)
            for index, (write, file) in enumerate(zip(self._writes, files)):
                if write.action is not WriteAction.TRASH:
                    continue
                _guarded_move(guard, Path(write.target), Path(file["trash"]))
                progress.trashed.append(index)
                _fault("trash", index)
            _guarded_fsync_dirs(guard, [*(Path(w.target).parent for w in self._writes),
                                        *(Path(f["trash"]).parent for f in files if f["trash"])])
            record["state"] = JOURNAL_COMMITTED
            self._write_journal(record)
            _fault("journal_committed")
        except BaseException:
            # Confirmado en disco: ya no se revierte (recover() cierra el diario que quede).
            if record["state"] != JOURNAL_COMMITTED:
                self._rollback(record, files, progress)
            raise
        # 4. cerrar. Si falla, el guardado ya está hecho: recover() borrará el diario al abrir.
        _fault("close")
        try:
            self._close(record, files)
        except OSError:
            pass
        return SaveResult(
            self._txid,
            written=tuple(w.rel for w in self._writes if w.action is not WriteAction.TRASH),
            trashed=tuple(w.rel for w in self._writes if w.action is WriteAction.TRASH),
            backups=tuple(backups),
        )

    def _file_record(self, index: int, write: PlannedWrite) -> dict:
        target = Path(write.target)
        before = _sha_or_none(target)
        private = not self._backup_bak
        if private:
            bak = self._journal_dir / self._txid / f"{index:04d}.bak"
        else:
            bak = target.with_name(target.name + BACKUP_SUFFIX)
        rel = VPath.of(write.rel)
        original = self._originals_dir.joinpath(*rel.parts) if before is not None else None
        if original is not None and original.exists():
            original = None   # ya está: nunca se sobrescribe
        trash = self._trash_dir / self._txid / Path(*rel.parts)
        return {
            "rel": str(rel), "target": str(target), "action": write.action.value,
            "temp": None if write.action is WriteAction.TRASH else str(_temp_path(target, self._txid)),
            "before_sha256": before,
            "after_sha256": None if write.data is None else sha256_bytes(write.data),
            "bak": str(bak) if before is not None and write.action is not WriteAction.TRASH else None,
            "private_bak": private,
            "original": None if original is None else str(original),
            "trash": str(trash),
            "created_dirs": [str(d) for d in _missing_dirs(target.parent)],
        }

    def _write_journal(self, record: dict) -> None:
        data = (json.dumps(record, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        _guarded_write(self._guard, self.journal_path, data)
        _guarded_fsync_dirs(self._guard, [self._journal_dir])

    def _rollback(self, record: dict, files: list[dict], progress: _Progress) -> None:
        """Revierte en el propio proceso. Si algo falla al revertir, deja el diario para ``recover``."""
        guard = self._guard
        try:
            for index in reversed(progress.trashed):
                file = files[index]
                _guarded_move(guard, Path(file["trash"]), Path(file["target"]))
            for index in reversed(progress.replaced):
                _undo_replace(guard, files[index])
            for file in files:
                if file["temp"]:
                    _guarded_remove(guard, Path(file["temp"]))
            for folder in record.get("folders", ()):
                for created in folder["created"]:
                    _guarded_rmdirs(guard, Path(created), _stop_at(guard, Path(created)))
            _finish(guard, Path(self.journal_path), record, files)
        except BaseException:
            return

    def _close(self, record: dict, files: list[dict]) -> None:
        _finish(self._guard, self.journal_path, record, files)


class _Progress:
    def __init__(self) -> None:
        self.staged: list[int] = []
        self.replaced: list[int] = []
        self.trashed: list[int] = []


def _undo_replace(guard: WriteGuard, file: dict) -> None:
    """Deja ``target`` como antes de reemplazarlo: su copia de reversión o, si era nuevo, a la papelera."""
    target = Path(file["target"])
    if file["before_sha256"] is None:
        if target.exists():
            _guarded_move(guard, target, Path(file["trash"]))
        for created in file.get("created_dirs", ()):
            _guarded_rmdirs(guard, Path(created), _stop_at(guard, Path(created)))
    else:
        _guarded_copy(guard, Path(file["bak"]), target)


def _finish(guard: WriteGuard, journal: Path, record: dict, files: list[dict]) -> None:
    """Borra el diario, las copias de reversión privadas y las carpetas que quedan vacías."""
    _guarded_remove(guard, journal)
    journal_dir = journal.parent
    if record.get("private_backups"):
        for file in files:
            if file.get("bak"):
                _guarded_remove(guard, Path(file["bak"]))
        _guarded_rmdirs(guard, journal_dir / record["txid"], _stop_at(guard, journal_dir))
    _guarded_rmdirs(guard, journal_dir, _stop_at(guard, journal_dir))


def trash_file(guard: WriteGuard, trash_root: Path, txid: str, rel: VPath, source: Path) -> Path:
    """Mueve ``source`` a ``trash/<txid>/<rel>``; nada se borra de verdad (I6)."""
    target = Path(trash_root) / txid / Path(*VPath.of(rel).parts)
    _guarded_move(guard, Path(source), target)
    return target


# --- autoguardado de recuperación ------------------------------------------------------------

def write_recovery(guard: WriteGuard, recovery_root: Path, session: str, documents: Mapping[VPath, bytes]) -> None:
    """Autoguardado: ``recovery/<sesión>/<rel>`` con el ``snapshot()`` de cada documento sucio y un índice JSON.

    Los documentos van numerados (``0001.dat``…) para no depender de los nombres;
    el índice dice qué ruta es cada uno y se escribe al final, así que un corte a
    medias deja el autoguardado anterior entero. Sin documentos borra el de la sesión.
    """
    folder = Path(recovery_root) / session
    if not documents:
        clear_recovery(guard, recovery_root, session)
        return
    previous = _recovery_files(folder)
    entries = []
    for number, (rel, data) in enumerate(sorted(documents.items(), key=lambda item: VPath.of(item[0]).key), 1):
        name = f"{number:04d}.dat"
        _guarded_write(guard, folder / name, data)
        entries.append({"rel": str(rel), "file": name, "sha256": sha256_bytes(data)})
    index = {"format": JOURNAL_FORMAT, "session": session, "pid": os.getpid(), "host": socket.gethostname(),
             "written": _now(), "files": entries}
    _guarded_write(guard, folder / RECOVERY_INDEX, (json.dumps(index, ensure_ascii=False, indent=1) + "\n").encode())
    keep = {e["file"] for e in entries} | {RECOVERY_INDEX}
    for name in previous - keep:
        _guarded_remove(guard, folder / name)


def _recovery_files(folder: Path) -> set[str]:
    try:
        return {name for name in os.listdir(folder) if name.endswith(".dat")}
    except OSError:
        return set()


def clear_recovery(guard: WriteGuard, recovery_root: Path, session: str) -> None:
    folder = Path(recovery_root) / session
    if not folder.is_dir():
        return
    for name in sorted(_recovery_files(folder)):
        _guarded_remove(guard, folder / name)
    _guarded_remove(guard, folder / RECOVERY_INDEX)
    _guarded_rmdirs(guard, folder, _stop_at(guard, folder))


# --- utilidades para recovery.py (mismo guard) ---------------------------------------------

def restore_from_journal(guard: WriteGuard, file: dict, *, forward: bool) -> str:
    """Lleva un archivo del diario a su estado posterior (``forward``) o anterior; devuelve qué hizo.

    ``"kept"``, ``"replaced"``, ``"restored"``, ``"trashed"`` o ``"moved_back"``.
    Lo que no encaja con ninguno de los dos estados se guarda antes en la papelera
    (``<rel>.recovered``): nada desaparece (I6).
    """
    target = Path(file["target"])
    action = file["action"]
    current = _sha_or_none(target)
    trash = Path(file["trash"])
    if action == WriteAction.TRASH.value:
        if forward:
            if current is None:
                return "kept"
            _guarded_move(guard, target, trash)
            return "trashed"
        if current is not None:
            return "kept"
        _guarded_move(guard, trash, target)
        return "moved_back"
    after, before = file["after_sha256"], file["before_sha256"]
    if forward:
        if current == after:
            return "kept"
        _keep_unknown(guard, target, current, (before, after), trash)
        _guarded_commit(guard, Path(file["temp"]), target)
        return "replaced"
    if current == before:
        return "kept"
    if before is None:
        _keep_unknown(guard, target, current, (after,), trash)
        if target.exists():
            _guarded_move(guard, target, trash)
        for created in file.get("created_dirs", ()):
            _guarded_rmdirs(guard, Path(created), _stop_at(guard, Path(created)))
        return "trashed"
    _keep_unknown(guard, target, current, (after,), trash)
    _guarded_copy(guard, Path(file["bak"]), target)
    return "restored"


def _keep_unknown(guard: WriteGuard, target: Path, current: str | None, known: tuple, trash: Path) -> None:
    if current is not None and current not in known:
        _guarded_copy(guard, target, trash.with_name(trash.name + ".recovered"))


def finish_journal(guard: WriteGuard, journal: Path, record: dict) -> None:
    """Cierra un diario ya resuelto: borra temporales que queden, el diario y las carpetas vacías."""
    files = list(record.get("files", ()))
    for file in files:
        if file.get("temp"):
            _guarded_remove(guard, Path(file["temp"]))
    _finish(guard, journal, record, files)


def discard_prepared(guard: WriteGuard, journal: Path, record: dict) -> None:
    """Diario sin confirmar (``staging``/``prepared``): borra los temporales y las carpetas que creó."""
    for file in record.get("files", ()):
        if file.get("temp"):
            _guarded_remove(guard, Path(file["temp"]))
        for created in file.get("created_dirs", ()):
            _guarded_rmdirs(guard, Path(created), _stop_at(guard, Path(created)))
    for folder in record.get("folders", ()):
        for created in folder.get("created", ()):
            _guarded_rmdirs(guard, Path(created), _stop_at(guard, Path(created)))
    _finish(guard, journal, record, list(record.get("files", ())))


def sha_of(path: Path) -> str | None:
    return _sha_or_none(Path(path))
