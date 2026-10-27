"""Colores del juego (wizard §9): enteros 0–255, salvo en ``religion.txt`` (0–1); fuera de rango es un aviso."""

from __future__ import annotations

from collections.abc import Sequence

RGB = tuple[int, int, int]
FORBIDDEN_PROVINCE_COLORS: frozenset[RGB] = frozenset({(0, 0, 0), (255, 255, 255)})


def parse_color(values: Sequence[str], *, unit: bool = False) -> RGB | None:
    """``"10 20 30"`` partido en 3 valores → (10, 20, 30); con ``unit`` (religión) escala 0–1 a 0–255. None si
    no son 3 números."""
    raise NotImplementedError


def color_problem(values: Sequence[str], *, unit: bool = False) -> str | None:
    """Código del problema de un color (``color_out_of_range``, ``color_malformed``) o None."""
    raise NotImplementedError
