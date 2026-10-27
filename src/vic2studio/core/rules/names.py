"""Nombres de archivo que crea el Studio (wizard §9): sin caracteres que Windows no admite, ni punto o espacio final."""

from __future__ import annotations

INVALID_FILE_CHARS = '<>:"/\\|?*'


def clean_file_name(name: str) -> str:
    """``name`` sin ``INVALID_FILE_CHARS`` ni caracteres de control, y sin punto ni espacio al final."""
    raise NotImplementedError


def country_file_name(name: str) -> str:
    """Nombre del archivo de país de ``common/countries/`` para un nombre de país (``"Prussia"`` → ``Prussia.txt``)."""
    raise NotImplementedError
