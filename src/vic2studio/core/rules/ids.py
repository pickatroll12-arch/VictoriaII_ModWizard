"""Reglas de identificadores: TAG, ids de provincia y de evento (wizard §9).

Solo comprueban la forma; si un nombre ya está usado lo dice el índice. Devuelven
el código del problema (``tag_invalid``…) o None, sin textos: los mensajes son de
``core/validate``.
"""

from __future__ import annotations

import re

from ..vfs.paths import WINDOWS_DEVICES

TAG_RE = re.compile(r"[A-Z][A-Z0-9]{2}")
RESERVED_TAGS = frozenset({"REB"})
SCRIPT_WORDS = frozenset({"AND", "NOT", "ALL", "ANY", "OR", "THIS", "FROM"})
DYNAMIC_TAG_RE = re.compile(r"D[0-9]{2}")         # D01–D50: dominios dinámicos de HoD (H11)
EVENT_ID_RANGE = (1, 2**31 - 1)

TAG_INVALID = "tag_invalid"
PROVINCE_ID_INVALID = "province_id_invalid"
EVENT_ID_INVALID = "event_id_invalid"


def tag_problem(tag: str) -> str | None:
    """``TAG_INVALID`` si ``tag`` no puede ser un TAG: patrón, REB, palabra de guion o nombre de dispositivo de
    Windows (``CON``, ``PRN``, ``AUX``, ``NUL``: su bandera ``CON.tga`` no se podría crear); None si vale."""
    if not isinstance(tag, str) or TAG_RE.fullmatch(tag) is None:
        return TAG_INVALID
    if tag in RESERVED_TAGS or tag in SCRIPT_WORDS or tag in WINDOWS_DEVICES:
        return TAG_INVALID
    return None


def province_id_problem(value: int, max_provinces: int) -> str | None:
    """Código si ``value`` no cumple ``1 ≤ id < max_provinces``; None si vale."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value < max_provinces:
        return PROVINCE_ID_INVALID
    return None


def event_id_problem(value: int) -> str | None:
    """Código si ``value`` no es un id de evento que el juego admita (entero de 32 bits positivo)."""
    low, high = EVENT_ID_RANGE
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return EVENT_ID_INVALID
    return None
