"""Validación sintáctica de un mod completo: scripts Clausewitz y CSV de localización.

Recorre la carpeta del mod (más archivos extra, como el descriptor ``.mod`` de
la carpeta superior), analiza cada archivo con ``core.clausewitz`` o
``core.csvloc`` y reúne sus diagnósticos en un informe ordenado por gravedad.
Sin Qt: la interfaz lo ejecuta en un hilo y le pasa ``progress`` y ``cancelled``.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .clausewitz import Severity, parse_file
from .csvloc import read_csv_file

CLAUSEWITZ_SUFFIXES = frozenset({".txt", ".mod", ".gfx", ".gui", ".sfx", ".asset"})
CSV_SUFFIXES = frozenset({".csv"})
KIND_CLAUSEWITZ = "clausewitz"
KIND_CSV = "csv"
SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

READ_ERROR = "read_error"
CHECK_FAILED = "check_failed"
MESSAGES = {
    "es": {
        READ_ERROR: "No se pudo leer el archivo: {error}",
        CHECK_FAILED: "El análisis del archivo falló de forma inesperada: {error}",
    },
    "en": {
        READ_ERROR: "The file could not be read: {error}",
        CHECK_FAILED: "Checking the file failed unexpectedly: {error}",
    },
}


@dataclass(frozen=True)
class Issue:
    """Un diagnóstico de un archivo; ``diagnostic`` es el original (``None`` en fallos de lectura)."""

    path: Path
    relative: str
    kind: str
    code: str
    severity: Severity
    line: int | None
    column: int | None
    diagnostic: object | None = None
    args: dict = field(default_factory=dict, compare=False)

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
    suffix = Path(path).suffix.lower()
    if suffix in CLAUSEWITZ_SUFFIXES:
        return KIND_CLAUSEWITZ
    if suffix in CSV_SUFFIXES:
        return KIND_CSV
    return None


def collect_files(root: str | os.PathLike, extra: Iterable[str | os.PathLike] = ()) -> list[Path]:
    """Archivos validables: primero ``extra`` y luego los de ``root`` en orden alfabético.

    Se saltan las carpetas ocultas (``.git``…) y los duplicados por ruta real.
    """
    seen: set[str] = set()
    files: list[Path] = []

    def add(path: Path) -> None:
        real = os.path.normcase(os.path.realpath(path))
        if real not in seen:
            seen.add(real)
            files.append(path)

    for path in extra:
        path = Path(path)
        if path.is_file() and file_kind(path):
            add(path)
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted((d for d in dirs if not d.startswith(".")), key=str.casefold)
        for name in sorted(names, key=str.casefold):
            if file_kind(name):
                add(Path(folder, name))
    return files


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return Path(os.path.relpath(path, root)).as_posix()


def check_file(path: str | os.PathLike, root: str | os.PathLike | None = None) -> list[Issue]:
    """Diagnósticos de un archivo; nunca lanza (los fallos se devuelven como ``Issue``)."""
    path = Path(path)
    relative = _relative(path, Path(root)) if root is not None else path.as_posix()
    kind = file_kind(path) or KIND_CLAUSEWITZ
    try:
        if kind == KIND_CSV:
            diagnostics = read_csv_file(path).diagnostics
        else:
            diagnostics = parse_file(path).diagnostics
    except OSError as exc:
        return [Issue(path, relative, kind, READ_ERROR, Severity.ERROR, None, None, None,
                      {"error": exc.strerror or str(exc)})]
    except Exception as exc:  # noqa: BLE001 - un fallo interno no debe abortar la validación
        return [Issue(path, relative, kind, CHECK_FAILED, Severity.ERROR, None, None, None,
                      {"error": f"{type(exc).__name__}: {exc}"})]
    # csvloc tiene su propio Enum Severity con los mismos valores.
    return [Issue(path, relative, kind, d.code, Severity(d.severity.value), d.line, d.column, d)
            for d in diagnostics]


def check_mod(root: str | os.PathLike, *, extra_files: Iterable[str | os.PathLike] = (),
              progress: Callable[[int, int, str], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> ModCheckReport:
    """Valida todos los archivos Clausewitz y CSV de ``root`` (y ``extra_files``).

    ``progress(hechos, total, ruta_relativa)`` se llama tras cada archivo;
    si ``cancelled()`` devuelve True se detiene y el informe queda marcado.
    """
    root = Path(root)
    start = time.perf_counter()
    report = ModCheckReport(root)
    files = collect_files(root, extra_files)
    total = len(files)
    for done, path in enumerate(files, 1):
        if cancelled is not None and cancelled():
            report.cancelled = True
            break
        issues = check_file(path, root)
        report.files += 1
        if file_kind(path) == KIND_CSV:
            report.csv_files += 1
        else:
            report.clausewitz_files += 1
        report.issues.extend(issues)
        if progress is not None:
            progress(done, total, _relative(path, root))
    report.issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.relative.casefold(), i.line or 0, i.column or 0))
    report.elapsed = time.perf_counter() - start
    return report
