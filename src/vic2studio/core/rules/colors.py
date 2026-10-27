"""Colores del juego (wizard §9): enteros 0–255, salvo en ``religion.txt`` (0–1); fuera de rango es un aviso."""

from __future__ import annotations

from collections.abc import Sequence

RGB = tuple[int, int, int]
FORBIDDEN_PROVINCE_COLORS: frozenset[RGB] = frozenset({(0, 0, 0), (255, 255, 255)})

COLOR_MALFORMED = "color_malformed"
COLOR_OUT_OF_RANGE = "color_out_of_range"


def _numbers(values: Sequence[str]) -> list[float] | None:
    if isinstance(values, str):
        values = values.split()
    if len(values) != 3:
        return None
    try:
        return [float(str(v)) for v in values]
    except ValueError:
        return None


def parse_color(values: Sequence[str], *, unit: bool = False) -> RGB | None:
    """``"10 20 30"`` partido en 3 valores → (10, 20, 30); con ``unit`` (religión) escala 0–1 a 0–255. None si
    no son 3 números.

    Fuera de rango se recorta a 0–255 (el juego hace lo mismo al pintar); con ``unit``, un valor mayor que 1 se
    toma ya en 0–255 (hay mods que lo escriben así).
    """
    numbers = _numbers(values)
    if numbers is None:
        return None
    if unit and all(n <= 1 for n in numbers):
        numbers = [n * 255 for n in numbers]
    return tuple(max(0, min(255, int(round(n)))) for n in numbers)  # type: ignore[return-value]


def color_problem(values: Sequence[str], *, unit: bool = False) -> str | None:
    """Código del problema de un color (``color_out_of_range``, ``color_malformed``) o None."""
    numbers = _numbers(values)
    if numbers is None:
        return COLOR_MALFORMED
    high = 1 if unit else 255
    if any(n < 0 or n > high for n in numbers):
        return COLOR_OUT_OF_RANGE
    return None
