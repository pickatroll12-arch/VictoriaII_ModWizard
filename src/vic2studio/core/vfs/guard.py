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

from ..fileio import BACKUP_SUFFIX
from ..modcheck import GAME_EXECUTABLES
from ..modfile import ModDescriptor, find_descriptor

EXPECTED_FOLDERS = ("common", "history", "localisation", "map", "events", "decisions", "gfx", "interface")
GAME_DATA_MIN_FOLDERS = 5

# Código de WriteOutsideModError e InvalidModRootError.
WRITE_OUTSIDE_MOD = "write_outside_mod"
INVALID_MOD_ROOT = "invalid_mod_root"
MESSAGES = {
    "es": {WRITE_OUTSIDE_MOD: "No se escribe en {path}: está fuera del mod ({mod}). El juego base y los demás mods "
                              "son de solo lectura.",
           INVALID_MOD_ROOT: "{path} no puede ser la carpeta de un mod: es el juego base, lo contiene, está dentro "
                             "de él fuera de mod/ o es la propia carpeta mod/ con todos los mods."},
    "en": {WRITE_OUTSIDE_MOD: "Not writing to {path}: it is outside the mod ({mod}). The base game and other mods "
                              "are read-only.",
           INVALID_MOD_ROOT: "{path} cannot be a mod folder: it is the base game, contains it, is inside it outside "
                             "mod/ or is the mod/ folder itself, which holds every mod."},
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

    def __reduce__(self):
        return (type(self), (self.path, self.mod_root))

    def message(self, lang: str = "en") -> str:
        return MESSAGES.get(lang, MESSAGES["en"])[WRITE_OUTSIDE_MOD].format(path=self.path, mod=self.mod_root)


class InvalidModRootError(ValueError):
    """La carpeta elegida como mod no puede serlo (``mod_root_problem``): abrirla escribiría fuera del mod (I1)."""

    code = INVALID_MOD_ROOT

    def __init__(self, path: str | os.PathLike, problem: str):
        self.path = Path(path)
        self.problem = problem
        super().__init__(self.message("es"))

    def __reduce__(self):
        return (type(self), (self.path, self.problem))

    def message(self, lang: str = "en") -> str:
        return MESSAGES.get(lang, MESSAGES["en"])[INVALID_MOD_ROOT].format(path=self.path)


class WriteGuard:
    """Decide si se puede escribir en una ruta (I1).

    Admite: lo que esté bajo ``realpath(mod_root)``, cada uno de ``extra_files``
    (el descriptor ``<juego>/mod/<carpeta>.mod``) y lo que esté bajo ``extra_roots``
    (la carpeta de proyecto fuera del mod cuando este es de solo lectura). Todo lo
    demás, incluido un enlace que sale de esas raíces, lanza ``WriteOutsideModError``.

    Junto a cada archivo de ``extra_files`` admite también sus compañeros del
    guardado: su ``.bak`` y sus temporales ``.<nombre>.<token>.tmp`` (en la misma
    carpeta). Las rutas se comparan con ``os.path.normcase(os.path.realpath(...))``:
    en Windows sin distinguir mayúsculas; en Linux una carpeta que solo difiere en
    mayúsculas es otra carpeta y se rechaza.
    """

    def __init__(self, mod_root: Path, *, extra_files: Sequence[Path] = (),
                 extra_roots: Sequence[Path] = ()) -> None:
        self._mod_root = Path(mod_root)
        self._roots = tuple(_real(root) for root in (self._mod_root, *extra_roots))
        self._files = tuple(_real(file) for file in extra_files)
        self._extra_files = tuple(Path(file) for file in extra_files)
        self._extra_roots = tuple(Path(root) for root in extra_roots)

    @property
    def mod_root(self) -> Path:
        return self._mod_root

    @property
    def extra_files(self) -> tuple[Path, ...]:
        return self._extra_files

    @property
    def extra_roots(self) -> tuple[Path, ...]:
        return self._extra_roots

    def allows(self, target: str | os.PathLike) -> bool:
        try:
            self.check(target)
        except WriteOutsideModError:
            return False
        return True

    def check(self, target: str | os.PathLike) -> Path:
        """``realpath(target)`` si se admite; si no, lanza ``WriteOutsideModError``.

        ``target`` puede no existir todavía: se comprueba la carpeta existente más
        cercana y que el resto de la ruta no contenga ``..``.
        """
        raw = os.fspath(target)
        if not isinstance(raw, str) or not raw or "\0" in raw:
            raise WriteOutsideModError(raw, self._mod_root)
        # Un «..» se rechaza siempre: tras un enlace simbólico no lleva a donde aparenta.
        if ".." in Path(raw).parts or ".." in raw.replace("\\", "/").split("/"):
            raise WriteOutsideModError(raw, self._mod_root)
        real = os.path.realpath(raw)
        key = os.path.normcase(real)
        if any(_inside(key, root) for root in self._roots) or self._is_extra_file(key):
            return Path(real)
        raise WriteOutsideModError(raw, self._mod_root)

    def _is_extra_file(self, key: str) -> bool:
        folder, name = os.path.split(key)
        for file in self._files:
            file_folder, file_name = os.path.split(file)
            if folder != file_folder:
                continue
            if name == file_name or name == file_name + os.path.normcase(BACKUP_SUFFIX):
                return True
            if name.startswith("." + file_name + ".") and name.endswith(os.path.normcase(".tmp")):
                return True
        return False


def _real(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.realpath(path))


def _inside(key: str, root: str) -> bool:
    return key == root or key.startswith(root.rstrip(os.sep) + os.sep)


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


def mod_root_problem(mod_root: Path, game_root: Path | None) -> str | None:
    """Clave de catálogo si ``mod_root`` no puede ser un mod de ``game_root``; ``None`` si puede.

    No puede ser el juego base, ni contenerlo, ni estar dentro de él fuera de ``mod/``, ni ser la propia
    ``<juego>/mod`` (tendría dentro todos los mods y sus ``.mod``).
    """
    if game_root is None:
        return None
    if same_folder(mod_root, game_root):
        return N_("check.mod_is_game")
    if is_under(game_root, mod_root):
        return N_("check.mod_contains_game")
    mods = Path(game_root) / "mod"
    if same_folder(mod_root, mods):
        return N_("check.mod_is_mods_folder")
    if is_under(mod_root, game_root) and not is_under(mod_root, mods):
        return N_("check.mod_inside_game")
    return None


def evaluate_mod(report: FolderReport, game_path: Path | None) -> tuple[str, str, dict]:
    """El mod nunca puede ser el juego base, ni contenerlo, ni estar dentro de él salvo en su
    carpeta ``mod/``, ni ser esa carpeta ``mod/``: así jamás se escribe sobre el original ni en otros mods."""
    if report.path is None:
        return "neutral", N_("check.not_set"), {}
    if not report.exists:
        return "error", N_("check.missing"), {}
    if report.is_game:
        return "error", N_("check.mod_is_game"), {}
    problem = mod_root_problem(report.path, game_path)
    if problem is not None:
        return "error", problem, {}
    if report.present:
        return "ok", N_("check.mod_ok_one") if len(report.present) == 1 else N_("check.mod_ok"), \
            {"count": len(report.present)}
    if report.entries == 0:
        return "warning", N_("check.mod_empty"), {}
    return "warning", N_("check.mod_unknown"), {}
