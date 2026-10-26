"""Textos del núcleo en JSON, sin Qt (wizard §4).

Cada área deja sus textos en ``core/**/texts/<área>.<idioma>.json`` (objeto plano
de cadenas; claves con espacio de nombres, p. ej. ``project.save_conflict``).
``load_texts`` los reúne y lanza ``ValueError`` si una clave se repite entre
archivos; ``i18n.Translator`` los fusiona con sus catálogos para que la interfaz
los traduzca con ``tr()`` como cualquier otro. Las tablas ``MESSAGES`` que ya
tienen algunos módulos (``fileio``, ``modfile``, ``modcheck``…) siguen como están.
"""

from __future__ import annotations

from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parent
TEXTS_GLOB = "**/texts/*.{lang}.json"
LANGUAGES = ("es", "en")


def text_files(lang: str) -> list[Path]:
    """Archivos de textos de ``lang`` bajo ``core/``, ordenados por ruta."""
    raise NotImplementedError


def load_texts(lang: str) -> dict[str, str]:
    """Todas las claves de ``lang``; ``ValueError`` ante JSON mal formado o claves repetidas. En caché por idioma."""
    raise NotImplementedError


def text(key: str, lang: str = "en", /, **fmt) -> str:
    """Texto de ``key`` en ``lang`` (si falta, en inglés; si tampoco, la propia clave), con ``str.format(**fmt)``."""
    raise NotImplementedError
