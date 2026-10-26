"""Preferencias persistentes de la aplicación (QSettings en formato INI).

Se usa siempre el formato INI, también en Windows, para que las preferencias
sean un archivo legible y fácil de aislar. ``VIC2STUDIO_SETTINGS_DIR`` desvía
el directorio de configuración (pruebas, capturas automáticas).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from . import APP_NAME, ORG_NAME

SETTINGS_DIR_ENV = "VIC2STUDIO_SETTINGS_DIR"

_applied_override: str | None = None


def use_settings_dir(directory: str | os.PathLike) -> None:
    """Redirige las preferencias de usuario a ``directory`` para todo el proceso."""
    global _applied_override
    _applied_override = os.fspath(directory)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _applied_override)


def app_settings() -> QSettings:
    override = os.environ.get(SETTINGS_DIR_ENV)
    if override and override != _applied_override:
        use_settings_dir(override)
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, ORG_NAME, APP_NAME)
