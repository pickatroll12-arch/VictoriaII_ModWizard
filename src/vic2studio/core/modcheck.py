"""Validación sintáctica de un mod completo: scripts Clausewitz y CSV de localización.

Recorre las carpetas del mod que lee el juego (más archivos extra, como el
descriptor ``.mod`` de la carpeta superior), analiza cada archivo con
``core.clausewitz`` o ``core.csvloc`` y reúne sus diagnósticos en un informe
ordenado por gravedad. De los scripts comprueba además que el juego pueda leer
su codificación y de los descriptores ``.mod``, sus campos (``check_descriptor``).
Sin Qt: la interfaz lo ejecuta en un hilo y le pasa ``progress`` y ``cancelled``.
"""

from __future__ import annotations

import codecs
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable

from .cancel import CancelCheck, Cancelled, raise_if_cancelled
from .clausewitz import Severity, parse_file
from .csvloc import is_localisation_csv, read_csv_file
from .encoding import GAME_ENCODING, GAME_UNREADABLE
from .modfile import DESCRIPTOR_SUFFIX, ModDescriptor, descriptor_from_result

CLAUSEWITZ_SUFFIXES = frozenset({".txt", ".mod", ".gfx", ".gui", ".sfx", ".asset", ".map"})
CSV_SUFFIXES = frozenset({".csv"})
KIND_CLAUSEWITZ = "clausewitz"
KIND_CSV = "csv"
SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
# Carpetas de primer nivel de las que el juego carga archivos. Lo demás (un léeme o
# un registro de cambios en la raíz, documentación, copias de otros mods...) no
# lo lee el juego y no se valida; de la raíz solo cuentan los descriptores .mod.
GAME_FOLDERS = frozenset({
    "common", "decisions", "events", "gfx", "history", "interface", "inventions", "localisation", "map",
    "music", "news", "poptypes", "sound", "technologies", "tutorial", "units",
})
# Una carpeta que los contiene es una instalación del juego: nunca se valida como parte del mod.
GAME_EXECUTABLES = ("v2game.exe", "victoria2.exe")
# Segundos mínimos entre dos avisos de progreso durante la exploración inicial.
SCAN_PROGRESS_INTERVAL = 0.1
# Diagnósticos convertidos en ``Issue`` entre dos consultas a ``cancelled``.
CANCEL_EVERY = 0x1000

# Aviso del parser para una codificación que no es la del juego (supone que el juego la lee como cp1252).
_PARSER_ENCODING_WARNING = "non_game_encoding"

READ_ERROR = "read_error"
CHECK_FAILED = "check_failed"
FOLDER_ERROR = "folder_error"
NO_GAME_FOLDERS = "no_game_folders"
UNREADABLE_ENCODING = "unreadable_encoding"
STRAY_BOM = "stray_bom"
DESCRIPTOR_NO_NAME = "descriptor_no_name"
DESCRIPTOR_NO_PATH = "descriptor_no_path"
DESCRIPTOR_BAD_PATH = "descriptor_bad_path"
DESCRIPTOR_OTHER_FOLDER = "descriptor_other_folder"
DESCRIPTOR_MISSING_FOLDER = "descriptor_missing_folder"
DESCRIPTOR_BAD_USER_DIR = "descriptor_bad_user_dir"
DESCRIPTOR_BAD_REPLACE_PATH = "descriptor_bad_replace_path"
MESSAGES = {
    "es": {
        READ_ERROR: "No se pudo leer el archivo: {error}",
        CHECK_FAILED: "El análisis del archivo falló de forma inesperada: {error}",
        FOLDER_ERROR: "No se pudo recorrer la carpeta: {error}",
        NO_GAME_FOLDERS: (
            "«{folder}» no parece la carpeta raíz de un mod: no tiene ninguna de las carpetas que lee el juego "
            "(common, decisions, events, history...) ni un descriptor .mod, así que no se ha validado ningún "
            "archivo suyo."
        ),
        UNREADABLE_ENCODING: (
            "El archivo está codificado en {encoding} (Unicode de 16 bits): Victoria II no puede leerlo en "
            "absoluto. Guárdalo en Windows-1252 (ANSI)."
        ),
        STRAY_BOM: (
            "El archivo empieza por el BOM de UTF-8 pero el resto está en Windows-1252: el juego pega los bytes "
            "'ï»¿' a la primera clave y no la reconoce. Vuelve a guardarlo en ANSI sin el BOM."
        ),
        DESCRIPTOR_NO_NAME: "El descriptor no tiene «name»: el lanzador no sabrá qué nombre mostrar.",
        DESCRIPTOR_NO_PATH: "El descriptor no tiene «path»: el juego no sabrá dónde está el mod.",
        DESCRIPTOR_BAD_PATH: "«path» debe tener la forma \"mod/<carpeta>\", no \"{path}\".",
        DESCRIPTOR_OTHER_FOLDER: (
            "«path» apunta a la carpeta «{folder}», pero el mod está en «{actual}»: el juego no lo encontrará."
        ),
        DESCRIPTOR_MISSING_FOLDER: "«path» apunta a «{path}», que no existe en la carpeta del juego.",
        DESCRIPTOR_BAD_USER_DIR: (
            "«user_dir» debe ser un nombre de carpeta válido en Windows, sin barras ni los caracteres "
            "<>:\"|?*: \"{user_dir}\"."
        ),
        DESCRIPTOR_BAD_REPLACE_PATH: (
            "«replace_path» debe ser una carpeta relativa a la del juego, sin «..» ni unidad: \"{replace_path}\"."
        ),
    },
    "en": {
        READ_ERROR: "The file could not be read: {error}",
        CHECK_FAILED: "Checking the file failed unexpectedly: {error}",
        FOLDER_ERROR: "The folder could not be read: {error}",
        NO_GAME_FOLDERS: (
            "“{folder}” does not look like the root folder of a mod: it has none of the folders the game reads "
            "(common, decisions, events, history...) and no .mod descriptor, so none of its files were checked."
        ),
        UNREADABLE_ENCODING: (
            "The file is encoded as {encoding} (16-bit Unicode): Victoria II cannot read it at all. "
            "Save it as Windows-1252 (ANSI)."
        ),
        STRAY_BOM: (
            "The file starts with a UTF-8 BOM but the rest is in Windows-1252: the game glues the bytes "
            "'ï»¿' to the first key and does not recognise it. Save it again as ANSI without the BOM."
        ),
        DESCRIPTOR_NO_NAME: "The descriptor has no “name”: the launcher will not know what name to show.",
        DESCRIPTOR_NO_PATH: "The descriptor has no “path”: the game will not know where the mod is.",
        DESCRIPTOR_BAD_PATH: "“path” must look like \"mod/<folder>\", not \"{path}\".",
        DESCRIPTOR_OTHER_FOLDER: (
            "“path” points to the folder “{folder}”, but the mod is in “{actual}”: the game will not find it."
        ),
        DESCRIPTOR_MISSING_FOLDER: "“path” points to “{path}”, which does not exist in the game folder.",
        DESCRIPTOR_BAD_USER_DIR: (
            "“user_dir” must be a valid Windows folder name, without slashes or the characters "
            "<>:\"|?*: \"{user_dir}\"."
        ),
        DESCRIPTOR_BAD_REPLACE_PATH: (
            "“replace_path” must be a folder relative to the game folder, without “..” or a drive: \"{replace_path}\"."
        ),
    },
}
_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class Issue:
    """Un diagnóstico de un archivo; ``diagnostic`` es el original (``None`` en fallos de lectura).

    ``diagnostic`` no cuenta al comparar ni en el hash (los de Clausewitz no son
    hashables): lo identifican la ruta, el código, la posición y ``args``.
    """

    path: Path
    relative: str
    kind: str
    code: str
    severity: Severity
    line: int | None
    column: int | None
    diagnostic: object | None = field(default=None, compare=False)
    args: dict = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash((self.path, self.relative, self.kind, self.code, self.severity, self.line, self.column,
                     tuple(sorted(self.args.items()))))

    def message(self, lang: str = "en") -> str:
        if self.diagnostic is not None:
            return self.diagnostic.message(lang)
        table = MESSAGES.get(lang, MESSAGES["en"])
        return table.get(self.code, self.code).format(**self.args)


@dataclass
class ModCheckReport:
    root: Path
    files: int = 0
    clausewitz_files: int = 0
    csv_files: int = 0
    issues: list[Issue] = field(default_factory=list)
    elapsed: float = 0.0
    cancelled: bool = False

    def count(self, severity: Severity) -> int:
        return sum(1 for issue in self.issues if issue.severity is severity)

    def files_with(self, severity: Severity = Severity.ERROR) -> list[str]:
        """Rutas relativas (sin repetir, ordenadas) con algún diagnóstico de esa gravedad."""
        return sorted({i.relative for i in self.issues if i.severity is severity}, key=str.casefold)


def file_kind(path: str | os.PathLike) -> str | None:
    """Tipo de validación de ``path``; ``None`` si no se valida (un CSV fuera de ``localisation/``...)."""
    suffix = Path(path).suffix.lower()
    if suffix in CLAUSEWITZ_SUFFIXES:
        return KIND_CLAUSEWITZ
    if suffix in CSV_SUFFIXES and is_localisation_csv(path):
        return KIND_CSV
    return None


def contains_game(names: Iterable[str]) -> bool:
    """True si entre los nombres de una carpeta está el ejecutable del juego."""
    return any(name.lower() in GAME_EXECUTABLES for name in names)


def is_mod_root(root: str | os.PathLike) -> bool:
    """True si ``root`` tiene alguna carpeta de ``GAME_FOLDERS`` o algún descriptor ``.mod``.

    Es lo único que ``collect_files`` recorre de ``root``: de una subcarpeta del mod
    (``events``, ``map``...) no valida nada. False si no se puede leer.
    """
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.name.casefold() in GAME_FOLDERS and entry.is_dir():
                    return True
                if entry.name.lower().endswith(DESCRIPTOR_SUFFIX) and entry.is_file():
                    return True
    except OSError:
        pass
    return False


def collect_files(root: str | os.PathLike, extra: Iterable[str | os.PathLike] = (), *,
                  cancelled: CancelCheck = None, progress: Callable[[int, str], None] | None = None,
                  errors: list[tuple[Path, OSError]] | None = None) -> list[Path]:
    """Archivos validables: primero ``extra`` y luego los de ``root`` en orden alfabético.

    De ``root`` solo se recorren las carpetas que lee el juego (``GAME_FOLDERS``)
    y, de la raíz, los descriptores ``.mod`` (ver ``is_mod_root``). Se saltan las carpetas ocultas
    (``.git``…), las que contienen una instalación del juego y los duplicados por
    ruta real. ``progress(encontrados, carpeta_relativa)`` informa del recorrido
    como mucho cada ``SCAN_PROGRESS_INTERVAL`` s; ``cancelled`` se consulta en cada
    carpeta (lanza ``core.cancel.Cancelled``). Las carpetas que no se pueden leer
    (``root`` incluida, si no existe) se anotan en ``errors``.
    """
    root = Path(root)
    seen: set[str] = set()
    files: list[Path] = []
    last_report = time.perf_counter()

    def add(path: Path) -> None:
        real = os.path.normcase(os.path.realpath(path))
        if real not in seen:
            seen.add(real)
            files.append(path)

    def failed(error: OSError) -> None:
        if errors is not None:
            errors.append((Path(error.filename) if error.filename else root, error))

    for path in extra:
        path = Path(path)
        if path.is_file() and file_kind(path):
            add(path)
    for folder, dirs, names in os.walk(root, onerror=failed):
        raise_if_cancelled(cancelled)
        top = Path(folder) == root
        dirs[:] = sorted((d for d in dirs if not d.startswith(".") and (not top or d.casefold() in GAME_FOLDERS)),
                         key=str.casefold)
        if not top and contains_game(names):
            dirs[:] = []
            continue
        for name in sorted(names, key=str.casefold):
            if top and not name.lower().endswith(DESCRIPTOR_SUFFIX):
                continue
            if file_kind(os.path.join(folder, name)):
                add(Path(folder, name))
        if progress is not None and time.perf_counter() - last_report >= SCAN_PROGRESS_INTERVAL:
            last_report = time.perf_counter()
            progress(len(files), _relative(Path(folder), root))
    return files


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return Path(os.path.relpath(path, root)).as_posix()


def _folder_exists(base: Path, relative: str) -> bool:
    """Si existe ``base/relative`` sin distinguir mayúsculas, como en Windows."""
    current = base
    for part in PureWindowsPath(relative).parts:
        if (current / part).is_dir():
            current = current / part
            continue
        try:
            current = next(p for p in current.iterdir() if p.is_dir() and p.name.casefold() == part.casefold())
        except (OSError, StopIteration):
            return False
    return True


def _is_relative_folder(text: str) -> bool:
    path = PureWindowsPath(text)
    return bool(text.strip()) and not path.drive and not path.root and ".." not in path.parts


def check_descriptor(descriptor: ModDescriptor, *, mod_dir: str | os.PathLike | None = None,
                     game_dir: str | os.PathLike | None = None, root: str | os.PathLike | None = None) -> list[Issue]:
    """Problemas de los campos de un descriptor que el juego no perdona (no los de sintaxis).

    Con ``mod_dir`` comprueba que ``path`` apunte a esa carpeta (por nombre, como
    el juego); con ``game_dir``, que exista dentro de la carpeta del juego.
    ``root`` solo sirve para la ruta relativa de los ``Issue``.
    """
    path = descriptor.file
    relative = _relative(path, Path(root)) if root is not None else path.as_posix()
    issues: list[Issue] = []

    def add(code: str, severity: Severity, **args) -> None:
        issues.append(Issue(path, relative, KIND_CLAUSEWITZ, code, severity, None, None, None, args))

    if not descriptor.name:
        add(DESCRIPTOR_NO_NAME, Severity.WARNING)
    parts = PureWindowsPath(descriptor.path).parts
    if not descriptor.path:
        add(DESCRIPTOR_NO_PATH, Severity.ERROR)
    elif len(parts) != 2 or parts[0].casefold() != "mod" or not _is_relative_folder(descriptor.path):
        add(DESCRIPTOR_BAD_PATH, Severity.ERROR, path=descriptor.path)
    elif mod_dir is not None and descriptor.folder_name.casefold() != Path(mod_dir).name.casefold():
        add(DESCRIPTOR_OTHER_FOLDER, Severity.ERROR, folder=descriptor.folder_name, actual=Path(mod_dir).name)
    elif game_dir is not None and not _folder_exists(Path(game_dir), descriptor.path):
        add(DESCRIPTOR_MISSING_FOLDER, Severity.ERROR, path=descriptor.path)
    user_dir = descriptor.user_dir
    if user_dir and (_INVALID_FOLDER_CHARS.search(user_dir) or user_dir != user_dir.strip(" .")):
        add(DESCRIPTOR_BAD_USER_DIR, Severity.ERROR, user_dir=user_dir)
    for replace_path in descriptor.replace_paths:
        if not _is_relative_folder(replace_path):
            add(DESCRIPTOR_BAD_REPLACE_PATH, Severity.ERROR, replace_path=replace_path)
    return issues


def _starts_with_stray_bom(path: Path) -> bool:
    """True si el archivo empieza por los bytes de un BOM UTF-8 (``encoding.STRAY_BOM`` si se lee como cp1252)."""
    with path.open("rb") as file:
        return file.read(len(codecs.BOM_UTF8)) == codecs.BOM_UTF8


def check_file(path: str | os.PathLike, root: str | os.PathLike | None = None, *,
               cancelled: CancelCheck = None) -> list[Issue]:
    """Diagnósticos de un archivo; los fallos se devuelven como ``Issue``.

    Un ``.csv`` se analiza como localización aunque no esté en ``localisation/``
    (quien lo pide sabrá por qué). De un script se comprueba además que el juego
    pueda leerlo: UTF-16 da ``unreadable_encoding`` (en lugar del aviso
    ``non_game_encoding`` del parser) y un BOM UTF-8 delante de texto cp1252,
    ``stray_bom``. Un descriptor ``.mod`` se revisa también con
    ``check_descriptor``, contra la carpeta ``root`` si se indica. Solo lanza
    ``core.cancel.Cancelled``, si ``cancelled()`` devuelve True a mitad del archivo.
    """
    path = Path(path)
    relative = _relative(path, Path(root)) if root is not None else path.as_posix()
    suffix = path.suffix.lower()
    kind = KIND_CSV if suffix in CSV_SUFFIXES else KIND_CLAUSEWITZ

    def problem(code: str, severity: Severity, line: int | None = None, column: int | None = None,
                **args) -> Issue:
        return Issue(path, relative, kind, code, severity, line, column, None, args)

    before: list[Issue] = []
    after: list[Issue] = []
    try:
        if kind == KIND_CSV:
            diagnostics = read_csv_file(path, cancelled=cancelled).diagnostics
        else:
            result = parse_file(path, cancelled=cancelled)
            diagnostics = result.diagnostics
            if result.encoding in GAME_UNREADABLE:
                diagnostics = [d for d in diagnostics if d.code != _PARSER_ENCODING_WARNING]
                before.append(problem(UNREADABLE_ENCODING, Severity.ERROR, encoding=result.encoding.upper()))
            elif result.encoding == GAME_ENCODING and _starts_with_stray_bom(path):
                before.append(problem(STRAY_BOM, Severity.WARNING, 1, 1))
            if suffix == DESCRIPTOR_SUFFIX:
                after = check_descriptor(descriptor_from_result(path, result), mod_dir=root, root=root)
    except Cancelled:
        raise
    except OSError as exc:
        return [problem(READ_ERROR, Severity.ERROR, error=exc.strerror or str(exc))]
    except Exception as exc:  # noqa: BLE001 - un fallo interno no debe abortar la validación
        return [problem(CHECK_FAILED, Severity.ERROR, error=f"{type(exc).__name__}: {exc}")]
    issues = before
    # Un archivo enorme puede dar cientos de miles de diagnósticos: convertirlos también se puede cancelar.
    for start in range(0, len(diagnostics), CANCEL_EVERY):
        raise_if_cancelled(cancelled)
        # csvloc tiene su propio Enum Severity con los mismos valores.
        issues.extend(Issue(path, relative, kind, d.code, Severity(d.severity.value), d.line, d.column, d)
                      for d in diagnostics[start:start + CANCEL_EVERY])
    return issues + after


def check_mod(root: str | os.PathLike, *, extra_files: Iterable[str | os.PathLike] = (),
              progress: Callable[[int, int, str], None] | None = None,
              cancelled: CancelCheck = None) -> ModCheckReport:
    """Valida los archivos Clausewitz y CSV de localización de ``root`` (ver ``collect_files``) y ``extra_files``.

    ``progress(hechos, total, ruta_relativa)``: durante la exploración inicial,
    con total 0 y la carpeta que se recorre; después, antes de cada archivo, con
    los ya analizados y el que empieza; y al acabar, ``(total, total, "")``. Si
    ``cancelled()`` devuelve True (también a mitad de un archivo) se detiene y el
    informe queda marcado. Una carpeta que no se puede leer, ``root`` incluida,
    da un ``Issue`` ``folder_error``; una ``root`` legible que no es la raíz de un
    mod (``is_mod_root``), un aviso ``no_game_folders`` en vez de un informe vacío.
    """
    root = Path(root)
    start = time.perf_counter()
    report = ModCheckReport(root)
    errors: list[tuple[Path, OSError]] = []
    scanned = None if progress is None else (lambda found, folder: progress(0, 0, folder))
    try:
        files = collect_files(root, extra_files, cancelled=cancelled, progress=scanned, errors=errors)
    except Cancelled:
        report.cancelled = True
        files = []
    report.issues.extend(Issue(path, _relative(path, root), KIND_CLAUSEWITZ, FOLDER_ERROR, Severity.ERROR,
                               None, None, None, {"error": error.strerror or str(error)})
                         for path, error in errors)
    # Sin carpetas del juego no se recorre nada de root, así que cualquier error sería de la propia root.
    if not errors and not report.cancelled and not is_mod_root(root):
        report.issues.append(Issue(root, _relative(root, root), KIND_CLAUSEWITZ, NO_GAME_FOLDERS, Severity.WARNING,
                                   None, None, None, {"folder": root.name or str(root)}))
    total = len(files)
    for done, path in enumerate(files):
        if cancelled is not None and cancelled():
            report.cancelled = True
            break
        relative = _relative(path, root)
        if progress is not None:
            progress(done, total, relative)
        try:
            issues = check_file(path, root, cancelled=cancelled)
        except Cancelled:
            report.cancelled = True
            break
        report.files += 1
        if file_kind(path) == KIND_CSV:
            report.csv_files += 1
        else:
            report.clausewitz_files += 1
        report.issues.extend(issues)
    if progress is not None and not report.cancelled:
        progress(total, total, "")
    report.issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.relative.casefold(), i.line or 0, i.column or 0))
    report.elapsed = time.perf_counter() - start
    return report
