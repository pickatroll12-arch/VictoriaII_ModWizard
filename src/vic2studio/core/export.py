"""Exportar el mod a un zip limpio (wizard §22, iteración 10).

El zip lleva lo que el juego necesita y nada del Studio:

- en la raíz, el descriptor ``<nombre>.mod`` (si está junto a la carpeta, como en ``<juego>/mod``);
- la carpeta del mod con sus archivos, sin ``.vic2studio/`` (proyecto, diario, papelera y originales), sin copias
  ``*.bak``, sin temporales (``.<nombre>.<token>.tmp`` del diario, ``~$…``, ``*.swp``, ``*~``), sin los archivos que
  añade el sistema (``Thumbs.db``, ``desktop.ini``, ``.DS_Store``) y sin carpetas de control de versiones.

Con ``prune_identical`` deja fuera además las copias idénticas byte a byte al archivo del juego en la misma ruta,
salvo en las carpetas de ``replace_path`` (allí la copia es la única que el juego ve) y salvo el descriptor.

Los errores de validación bloquean la exportación, nunca el guardado: ``write_zip_export`` los recibe del que
llama (la interfaz pasa los que no son heredados del juego) y se niega si hay alguno. El destino no puede estar
dentro del mod ni del juego: el zip se escribe con ``fileio.write_zip``, atómico, donde el usuario diga.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import fileio

STUDIO_DIR = ".vic2studio"

SKIP_STUDIO = "studio"
SKIP_BACKUP = "backup"
SKIP_TEMP = "temp"
SKIP_SYSTEM = "system"
SKIP_VCS = "vcs"
SKIP_LINK = "link"
SKIP_IDENTICAL = "identical"
SKIP_REASONS = (SKIP_STUDIO, SKIP_BACKUP, SKIP_TEMP, SKIP_SYSTEM, SKIP_VCS, SKIP_LINK, SKIP_IDENTICAL)

VCS_DIRS = frozenset({".git", ".svn", ".hg", "__macosx"})
SYSTEM_FILES = frozenset({"thumbs.db", "desktop.ini", ".ds_store", "ehthumbs.db"})

DEST_NOT_ZIP = "dest_not_zip"
DEST_INSIDE_MOD = "dest_inside_mod"
DEST_INSIDE_GAME = "dest_inside_game"


class ExportBlocked(Exception):
    """Hay errores de validación: el zip no se escribe."""

    def __init__(self, count: int):
        super().__init__(count)
        self.count = count


class ExportDestinationError(ValueError):
    """El destino no vale (``code``: ``dest_not_zip``, ``dest_inside_mod`` o ``dest_inside_game``)."""

    def __init__(self, code: str, path: str):
        super().__init__(code, path)
        self.code = code
        self.path = path


@dataclass(frozen=True)
class ZipMember:
    arcname: str      # ruta dentro del zip, con «/»
    source: Path
    size: int


@dataclass(frozen=True)
class Skipped:
    rel: str          # ruta relativa a la carpeta del mod, con «/»
    reason: str       # uno de SKIP_REASONS


@dataclass
class ZipPlan:
    mod_root: Path
    folder: str                                  # nombre de la carpeta del mod dentro del zip
    descriptor: Path | None = None               # el .mod que va en la raíz del zip (None si no hay o está dentro)
    members: list[ZipMember] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(m.size for m in self.members)

    def skipped_by(self, reason: str) -> list[Skipped]:
        return [s for s in self.skipped if s.reason == reason]

    def counts(self) -> dict[str, int]:
        """Cuántos archivos se quedan fuera por cada motivo (solo los motivos con alguno)."""
        out: dict[str, int] = {}
        for s in self.skipped:
            out[s.reason] = out.get(s.reason, 0) + 1
        return out


@dataclass(frozen=True)
class ZipResult:
    path: Path
    files: int
    bytes_in: int
    bytes_out: int


def skip_reason(rel_parts: tuple[str, ...]) -> str | None:
    """Por qué un archivo del mod (sus partes de ruta) no va al zip, o None si va."""
    lowered = [p.lower() for p in rel_parts]
    if lowered and lowered[0] == STUDIO_DIR:
        return SKIP_STUDIO
    if any(p in VCS_DIRS for p in lowered[:-1]):
        return SKIP_VCS
    name = lowered[-1]
    if name.endswith(fileio.BACKUP_SUFFIX):
        return SKIP_BACKUP
    if name.endswith((".tmp", ".swp", "~")) or name.startswith("~$"):
        return SKIP_TEMP
    if name in SYSTEM_FILES or name.startswith("._"):
        return SKIP_SYSTEM
    return None


def _walk(root: Path):
    """Los archivos bajo ``root`` en orden estable, sin seguir enlaces de carpeta; (partes, ruta, es_enlace)."""
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs.sort(key=str.lower)
        base = Path(folder)
        rel_base = base.relative_to(root).parts
        for d in list(dirs):
            if (base / d).is_symlink():
                dirs.remove(d)
                yield (*rel_base, d), base / d, True
        for name in sorted(files, key=str.lower):
            path = base / name
            yield (*rel_base, name), path, path.is_symlink()


def _game_file(game_root: Path, parts: tuple[str, ...]) -> Path | None:
    """El archivo del juego en la misma ruta, sin distinguir mayúsculas (como el motor en Windows)."""
    direct = game_root.joinpath(*parts)
    if direct.is_file():
        return direct
    current = game_root
    for part in parts:
        try:
            names = {p.name.lower(): p for p in current.iterdir()}
        except OSError:
            return None
        current = names.get(part.lower())
        if current is None:
            return None
    return current if current.is_file() else None


def _same_bytes(a: Path, b: Path, size: int) -> bool:
    try:
        if b.stat().st_size != size:
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                ca, cb = fa.read(1 << 20), fb.read(1 << 20)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def _under_replaced(parts: tuple[str, ...], replaced: tuple[str, ...]) -> bool:
    rel = "/".join(parts).lower()
    return any(rel == r or rel.startswith(r + "/") for r in replaced)


def plan_zip(mod_root: str | os.PathLike, *, descriptor: str | os.PathLike | None = None,
             game_root: str | os.PathLike | None = None, replace_paths=(), prune_identical: bool = False,
             cancelled=None) -> ZipPlan:
    """Qué entra en el zip y qué se queda fuera (y por qué). Solo lee."""
    root = Path(mod_root)
    desc = Path(descriptor) if descriptor is not None else None
    if desc is not None and not desc.is_file():
        desc = None
    inside = desc is not None and _is_within(desc, root)
    plan = ZipPlan(root, root.name, None if inside else desc)
    replaced = tuple(str(r).replace("\\", "/").strip("/").lower() for r in replace_paths)
    game = Path(game_root) if game_root is not None and prune_identical else None
    for parts, path, is_link in _walk(root):
        if cancelled is not None and cancelled():
            raise InterruptedError(str(root))
        rel = "/".join(parts)
        reason = SKIP_LINK if is_link else skip_reason(parts)
        if reason is None and inside and path == desc:
            plan.members.append(ZipMember(f"{plan.folder}/{rel}", path, path.stat().st_size))
            continue
        size = 0 if reason else path.stat().st_size
        if reason is None and game is not None and not _under_replaced(parts, replaced) \
                and not rel.lower().endswith(".mod"):
            other = _game_file(game, parts)
            if other is not None and _same_bytes(path, other, size):
                reason = SKIP_IDENTICAL
        if reason is not None:
            plan.skipped.append(Skipped(rel, reason))
        else:
            plan.members.append(ZipMember(f"{plan.folder}/{rel}", path, size))
    if plan.descriptor is not None:
        plan.members.insert(0, ZipMember(plan.descriptor.name, plan.descriptor, plan.descriptor.stat().st_size))
    return plan


def _is_within(path: Path, folder: Path) -> bool:
    try:
        p, f = os.path.realpath(path), os.path.realpath(folder)
    except OSError:
        return False
    p, f = os.path.normcase(p), os.path.normcase(f)
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def check_destination(dest: str | os.PathLike, *, mod_root: str | os.PathLike,
                      game_root: str | os.PathLike | None = None) -> str | None:
    """None si ``dest`` vale; si no, el código del problema."""
    path = Path(dest)
    if path.suffix.lower() != ".zip":
        return DEST_NOT_ZIP
    if _is_within(path, Path(mod_root)):
        return DEST_INSIDE_MOD
    if game_root is not None and _is_within(path, Path(game_root)):
        return DEST_INSIDE_GAME
    return None


def write_zip_export(plan: ZipPlan, dest: str | os.PathLike, *, game_root: str | os.PathLike | None = None,
                     errors: int = 0, cancelled=None) -> ZipResult:
    """Escribe el zip del plan en ``dest``. ``errors``: errores de validación sin resolver (bloquean)."""
    if errors:
        raise ExportBlocked(errors)
    code = check_destination(dest, mod_root=plan.mod_root, game_root=game_root)
    if code is not None:
        raise ExportDestinationError(code, str(dest))
    size = fileio.write_zip(dest, ((m.arcname, m.source) for m in plan.members), cancelled=cancelled)
    return ZipResult(Path(dest), len(plan.members), plan.total_bytes, size)


def default_zip_name(plan: ZipPlan, version: str = "") -> str:
    """``<carpeta>[_<versión>].zip`` con solo caracteres seguros en cualquier sistema."""
    stem = plan.folder + (f"_{version}" if version else "")
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem).strip("._") or "mod"
    return safe + ".zip"


__all__ = [
    "ZipPlan", "ZipMember", "Skipped", "ZipResult", "ExportBlocked", "ExportDestinationError", "plan_zip",
    "write_zip_export", "check_destination", "skip_reason", "default_zip_name", "SKIP_REASONS",
]
