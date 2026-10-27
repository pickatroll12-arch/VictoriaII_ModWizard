"""Nombres de archivo que crea el Studio (wizard §9): sin caracteres que Windows no admite, ni punto o espacio final."""

from __future__ import annotations

from ..vfs.paths import WINDOWS_DEVICES

INVALID_FILE_CHARS = '<>:"/\\|?*'
# Nombre que se usa cuando no queda nada tras limpiar.
FALLBACK_NAME = "unnamed"


def clean_file_name(name: str) -> str:
    """``name`` sin ``INVALID_FILE_CHARS`` ni caracteres de control, y sin punto ni espacio al final.

    Un nombre de dispositivo de Windows (``CON``, ``nul``…, también ``CON.algo``) gana un ``_`` final en su
    primera parte; si no queda nada, ``FALLBACK_NAME``.
    """
    cleaned = "".join(c for c in name if c not in INVALID_FILE_CHARS and ord(c) >= 32 and c != "\x7f")
    cleaned = cleaned.strip(" ").rstrip(". ")
    if not cleaned:
        return FALLBACK_NAME
    head, dot, tail = cleaned.partition(".")
    if head.rstrip(" ").upper() in WINDOWS_DEVICES:
        cleaned = head.rstrip(" ") + "_" + dot + tail
    return cleaned


def country_file_name(name: str) -> str:
    """Nombre del archivo de país de ``common/countries/`` para un nombre de país (``"Prussia"`` → ``Prussia.txt``)."""
    base = name[:-4] if name.lower().endswith(".txt") else name
    return clean_file_name(base) + ".txt"
