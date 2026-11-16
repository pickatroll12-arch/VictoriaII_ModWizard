"""Lienzo del mapa y sus piezas (wizard §16.1). Contrato de la iteración 5: ``MapCanvas`` en ``canvas.py``.

Todo lo de aquí pinta: los datos salen de ``session.map`` (``ui/session_map.py``) y de ``core.map``.
"""

from __future__ import annotations

from .canvas import PICK_BRUSH, PICK_MULTI, PICK_NONE, PICK_SINGLE, MapCanvas

__all__ = ["MapCanvas", "PICK_NONE", "PICK_SINGLE", "PICK_MULTI", "PICK_BRUSH"]
