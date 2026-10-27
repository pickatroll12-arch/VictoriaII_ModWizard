"""Carpetas de la aplicación fuera de cualquier mod: datos (bloqueos, proyectos de mods de solo lectura) y cachés.

Sin Qt (wizard §4, §5.4, D16). ``VIC2STUDIO_DATA_DIR`` y ``VIC2STUDIO_CACHE_DIR``
las desvían (pruebas y capturas). Por defecto: en Linux, ``$XDG_DATA_HOME`` (o
``~/.local/share``) y ``$XDG_CACHE_HOME`` (o ``~/.cache``) con ``vic2studio``; en
Windows, ``%LOCALAPPDATA%\\Vic2Studio\\{data,cache}``. No crean nada: quien escribe
crea la carpeta a través de ``core.fileio``.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

DATA_ENV = "VIC2STUDIO_DATA_DIR"
CACHE_ENV = "VIC2STUDIO_CACHE_DIR"
APP_FOLDER = "vic2studio"            # Linux
APP_FOLDER_WINDOWS = "Vic2Studio"    # Windows, dentro de %LOCALAPPDATA%


def _is_windows() -> bool:
    return os.name == "nt"


def _base(env: str, kind: str, xdg: str, fallback: str) -> Path:
    override = os.environ.get(env)
    if override:
        return Path(override)
    if _is_windows():
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / APP_FOLDER_WINDOWS / kind
    root = os.environ.get(xdg) or str(Path.home() / fallback)
    return Path(root) / APP_FOLDER


def data_dir() -> Path:
    return _base(DATA_ENV, "data", "XDG_DATA_HOME", ".local/share")


def cache_dir() -> Path:
    return _base(CACHE_ENV, "cache", "XDG_CACHE_HOME", ".cache")


def mod_key(mod_root: str | os.PathLike) -> str:
    """``sha1`` de la ruta real del mod (sin distinguir mayúsculas en Windows): nombre estable por mod."""
    real = os.path.normcase(os.path.realpath(mod_root))
    return hashlib.sha1(real.encode("utf-8", "surrogatepass")).hexdigest()


def locks_dir() -> Path:
    """``<data_dir>/locks``: un ``<sha1(realpath(mod))>.lock`` por mod abierto."""
    return data_dir() / "locks"


def detached_project_dir(mod_root: Path) -> Path:
    """``<data_dir>/projects/<sha1(realpath(mod))>``: la carpeta ``.vic2studio`` de un mod de solo lectura."""
    return data_dir() / "projects" / mod_key(mod_root)
