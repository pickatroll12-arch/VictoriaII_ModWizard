"""Protección de escritura e inspección de carpetas del juego y del mod (wizard §5.1, I1, H24).

``WriteGuard`` es la única puerta para escribir: solo admite el subárbol real del
mod, su descriptor y, si el mod es de solo lectura, la carpeta de proyecto que lo
sustituye (§5.4). Compara rutas reales (``realpath``), así que un enlace simbólico
que sale del mod se rechaza aunque su ruta aparente esté dentro.

``inspect_folder``, ``evaluate_game`` y ``evaluate_mod`` vienen de
``ui/pages/project_page.py`` (sin cambios): devuelven claves del catálogo de la
interfaz, que la página traduce. ``N_`` es local porque el núcleo no importa
``vic2studio.i18n`` (importa QtCore); la búsqueda estática de claves la reconoce
por su nombre.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..modcheck import GAME_EXECUTABLES
from ..modfile import ModDescriptor, find_descriptor

EXPECTED_FOLDERS = ("common", "history", "localisation", "map", "events", "decisions", "gfx", "interface")
GAME_DATA_MIN_FOLDERS = 5

# Código de WriteOutsideModError.
WRITE_OUTSIDE_MOD = "write_outside_mod"
MESSAGES = {
    "es": {WRITE_OUTSIDE_MOD: "No se escribe en {path}: está fuera del mod ({mod}). El juego base y los demás mods "
                              "son de solo lectura."},
    "en": {WRITE_OUTSIDE_MOD: "Not writing to {path}: it is outside the mod ({mod}). The base game and other mods "
                              "are read-only."},
}


def N_(key: str) -> str:
    """Marca una clave del catálogo de la interfaz sin traducirla (como ``vic2studio.i18n.N_``)."""
    return key


class WriteOutsideModError(PermissionError):
    """Intento de escribir fuera del mod (o de atravesar un enlace que sale de él)."""

    code = WRITE_OUTSIDE_MOD

    def __init__(self, path: str | os.PathLike, mod_root: str | os.PathLike):
        self.path = Path(path)
        self.mod_root = Path(mod_root)
        super().__init__(self.message("es"))

    def message(self, lang: str = "en") -> str:
        return MESSAGES.get(lang, MESSAGES["en"])[WRITE_OUTSIDE_MOD].format(path=self.path, mod=self.mod_root)


class WriteGuard:
    """Decide si se puede escribir en una ruta (I1).

    Admite: lo que esté bajo ``realpath(mod_root)``, cada uno de ``extra_files``
    (el descriptor ``<juego>/mod/<carpeta>.mod``) y lo que esté bajo ``extra_roots``
    (la carpeta de proyecto fuera del mod cuando este es de solo lectura). Todo lo
    demás, incluido un enlace que sale de esas raíces, lanza ``WriteOutsideModError``.
    """

    def __init__(self, mod_root: Path, *, extra_files: Sequence[Path] = (),
                 extra_roots: Sequence[Path] = ()) -> None:
        raise NotImplementedError

    @property
    def mod_root(self) -> Path:
        raise NotImplementedError

    def allows(self, target: str | os.PathLike) -> bool:
        raise NotImplementedError

    def check(self, target: str | os.PathLike) -> Path:
        """``realpath(target)`` si se admite; si no, lanza ``WriteOutsideModError``.

        ``target`` puede no existir todavía: se comprueba la carpeta existente más
        cercana y que el resto de la ruta no contenga ``..``.
        """
        raise NotImplementedError


# --- inspección de carpetas (sin Qt; antes en ui/pages/project_page.py) -------------------


@dataclass(frozen=True)
class FolderReport:
    path: Path | None
    exists: bool = False
    present: tuple[str, ...] = ()
    executable: str | None = None
    entries: int = 0
    descriptor: ModDescriptor | None = None

    @property
    def is_game(self) -> bool:
        return self.executable is not None


def inspect_folder(path: str | os.PathLike | None) -> FolderReport:
    if path is None or os.fspath(path) == "":
        return FolderReport(None)
    folder = Path(path)
    try:
        entries = {entry.name.lower(): entry for entry in os.scandir(folder)}
    except OSError:
        return FolderReport(folder)
    present = tuple(name for name in EXPECTED_FOLDERS if name in entries and entries[name].is_dir())
    executable = next((entries[name].name for name in GAME_EXECUTABLES
                       if name in entries and entries[name].is_file()), None)
    return FolderReport(folder, True, present, executable, len(entries), find_descriptor(folder))


def folder_key(path: str | os.PathLike) -> str:
    """Clave de una carpeta para compararla con otras (ruta real, sin distinguir mayúsculas en Windows)."""
    return os.path.normcase(os.path.realpath(path))


def same_folder(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    return folder_key(a) == folder_key(b)


def is_under(path: Path, root: Path) -> bool:
    """True si la ruta real de ``path`` está dentro de la de ``root`` (o es ella)."""
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(root))
    except ValueError:
        return False
    return True


def evaluate_game(report: FolderReport) -> tuple[str, str, dict]:
    """(nivel, clave de catálogo, formato) para la ruta del juego base."""
    if report.path is None:
        return "neutral", N_("check.not_set"), {}
    if not report.exists:
        return "error", N_("check.missing"), {}
    if report.is_game:
        return "ok", N_("check.game_ok"), {"exe": report.executable}
    if len(report.present) >= GAME_DATA_MIN_FOLDERS:
        return "warning", N_("check.game_no_exe"), {}
    return "error", N_("check.game_no_data"), {}


def evaluate_mod(report: FolderReport, game_path: Path | None) -> tuple[str, str, dict]:
    """El mod nunca puede ser el juego base, ni contenerlo, ni estar dentro de él salvo en su
    carpeta ``mod/``: así jamás se escribe sobre el original ni se validan sus archivos."""
    if report.path is None:
        return "neutral", N_("check.not_set"), {}
    if not report.exists:
        return "error", N_("check.missing"), {}
    if report.is_game or same_folder(report.path, game_path):
        return "error", N_("check.mod_is_game"), {}
    if game_path is not None:
        if is_under(game_path, report.path):
            return "error", N_("check.mod_contains_game"), {}
        if is_under(report.path, game_path) and not is_under(report.path, game_path / "mod"):
            return "error", N_("check.mod_inside_game"), {}
    if report.present:
        return "ok", N_("check.mod_ok"), {"count": len(report.present)}
    if report.entries == 0:
        return "warning", N_("check.mod_empty"), {}
    return "warning", N_("check.mod_unknown"), {}
