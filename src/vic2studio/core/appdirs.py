"""Carpetas de la aplicación fuera de cualquier mod: datos (bloqueos, proyectos de mods de solo lectura) y cachés.

Sin Qt (wizard §4, §5.4, D16). ``VIC2STUDIO_DATA_DIR`` y ``VIC2STUDIO_CACHE_DIR``
las desvían (pruebas y capturas). Por defecto: en Linux, ``$XDG_DATA_HOME`` (o
``~/.local/share``) y ``$XDG_CACHE_HOME`` (o ``~/.cache``) con ``vic2studio``; en
Windows, ``%LOCALAPPDATA%\\Vic2Studio\\{data,cache}``. No crean nada: quien escribe
crea la carpeta a través de ``core.fileio``.
"""

from __future__ import annotations

from pathlib import Path

DATA_ENV = "VIC2STUDIO_DATA_DIR"
CACHE_ENV = "VIC2STUDIO_CACHE_DIR"
APP_FOLDER = "vic2studio"            # Linux
APP_FOLDER_WINDOWS = "Vic2Studio"    # Windows, dentro de %LOCALAPPDATA%


def data_dir() -> Path:
    raise NotImplementedError


def cache_dir() -> Path:
    raise NotImplementedError


def locks_dir() -> Path:
    """``<data_dir>/locks``: un ``<sha1(realpath(mod))>.lock`` por mod abierto."""
    raise NotImplementedError


def detached_project_dir(mod_root: Path) -> Path:
    """``<data_dir>/projects/<sha1(realpath(mod))>``: la carpeta ``.vic2studio`` de un mod de solo lectura."""
    raise NotImplementedError
