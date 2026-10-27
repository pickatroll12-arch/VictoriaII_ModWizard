"""Textos del núcleo en JSON, sin Qt (wizard §4).

Cada área deja sus textos en ``core/**/texts/<área>.<idioma>.json`` (objeto plano
de cadenas; claves con espacio de nombres, p. ej. ``project.save_conflict``).
``load_texts`` los reúne y lanza ``ValueError`` si una clave se repite entre
archivos; ``i18n.Translator`` los fusiona con sus catálogos para que la interfaz
los traduzca con ``tr()`` como cualquier otro. Las tablas ``MESSAGES`` que ya
tienen algunos módulos (``fileio``, ``modfile``, ``modcheck``…) siguen como están.
"""

from __future__ import annotations

import json
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parent
TEXTS_GLOB = "**/texts/*.{lang}.json"
LANGUAGES = ("es", "en")
FALLBACK_LANGUAGE = "en"

_cache: dict[str, dict[str, str]] = {}


def text_files(lang: str) -> list[Path]:
    """Archivos de textos de ``lang`` bajo ``core/``, ordenados por ruta."""
    return sorted(CORE_ROOT.glob(TEXTS_GLOB.format(lang=lang)))


def load_texts(lang: str) -> dict[str, str]:
    """Todas las claves de ``lang``; ``ValueError`` ante JSON mal formado o claves repetidas. En caché por idioma."""
    cached = _cache.get(lang)
    if cached is not None:
        return cached
    merged: dict[str, str] = {}
    origin: dict[str, Path] = {}
    for path in text_files(lang):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path}: JSON de textos ilegible ({exc})") from exc
        if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            raise ValueError(f"{path}: debe ser un objeto plano de cadenas")
        for key, value in data.items():
            if key in merged:
                raise ValueError(f"clave de texto repetida {key!r} en {origin[key]} y {path}")
            merged[key] = value
            origin[key] = path
    _cache[lang] = merged
    return merged


def clear_cache() -> None:
    """Olvida los textos cargados (pruebas)."""
    _cache.clear()


def text(key: str, lang: str = "en", /, **fmt) -> str:
    """Texto de ``key`` en ``lang`` (si falta, en inglés; si tampoco, la propia clave), con ``str.format(**fmt)``.

    Un formato que no encaja (falta un argumento) devuelve la plantilla sin formatear.
    """
    template = load_texts(lang).get(key) if lang in LANGUAGES else None
    if template is None:
        template = load_texts(FALLBACK_LANGUAGE).get(key, key)
    try:
        return template.format(**fmt)
    except (KeyError, IndexError, ValueError):
        return template
