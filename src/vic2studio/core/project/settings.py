"""``<mod>/.vic2studio/project.json`` ⇄ ``ProjectSettings`` (wizard §5.4, §6.4).

Leer no crea nada (I4): sin archivo se usan los valores por defecto. El JSON se
escribe con el siguiente guardado que lo cambie, a través del diario. Las claves
desconocidas se conservan al reescribirlo.
"""

from __future__ import annotations

from pathlib import Path

from ..modfile import ModDescriptor
from .model import ProjectSettings


def default_prefix(mod_root: Path, descriptor: ModDescriptor | None = None) -> str:
    """Nombre de la carpeta del mod en mayúsculas, solo letras y cifras (``VSM``, ``DAM``)."""
    raise NotImplementedError


def default_settings(mod_root: Path, descriptor: ModDescriptor | None = None) -> ProjectSettings:
    raise NotImplementedError


def load_settings(path: Path, *, mod_root: Path, descriptor: ModDescriptor | None = None) -> ProjectSettings:
    """``path`` es el project.json; si no existe o es ilegible, valores por defecto (sin escribir nada)."""
    raise NotImplementedError


def render_settings(settings: ProjectSettings, existing: bytes | None = None) -> bytes:
    """JSON UTF-8 con sangría 2 y salto final; conserva las claves de ``existing`` que no conoce."""
    raise NotImplementedError
