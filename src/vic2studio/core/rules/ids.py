"""Reglas de identificadores: TAG, ids de provincia y de evento (wizard §9).

Solo comprueban la forma; si un nombre ya está usado lo dice el índice. Devuelven
el código del problema (``tag_invalid``…) o None, sin textos: los mensajes son de
``core/validate``.
"""

from __future__ import annotations

import re

TAG_RE = re.compile(r"[A-Z][A-Z0-9]{2}")
RESERVED_TAGS = frozenset({"REB"})
SCRIPT_WORDS = frozenset({"AND", "NOT", "ALL", "ANY", "OR", "THIS", "FROM"})
DYNAMIC_TAG_RE = re.compile(r"D[0-9]{2}")         # D01–D50: dominios dinámicos de HoD (H11)
EVENT_ID_RANGE = (1, 2**31 - 1)

TAG_INVALID = "tag_invalid"


def tag_problem(tag: str) -> str | None:
    """``TAG_INVALID`` si ``tag`` no puede ser un TAG: patrón, REB, palabra de guion o nombre de dispositivo de
    Windows (``CON``, ``PRN``, ``AUX``, ``NUL``: su bandera ``CON.tga`` no se podría crear); None si vale."""
    raise NotImplementedError


def province_id_problem(value: int, max_provinces: int) -> str | None:
    """Código si ``value`` no cumple ``1 ≤ id < max_provinces``; None si vale."""
    raise NotImplementedError


def event_id_problem(value: int) -> str | None:
    raise NotImplementedError
