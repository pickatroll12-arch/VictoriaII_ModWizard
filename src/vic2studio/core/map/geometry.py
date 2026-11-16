"""Geometría sobre el ráster: cajas, puntos de etiqueta, fragmentos y distancias (wizard §16.1, §16.3). Contrato.

Todo en coordenadas del juego (``y`` = fila del ráster, norte en las ``y`` altas). ``Box`` es inclusiva, como
``ProvinceRaster.bbox``. La vista convierte con ``display_box`` (que usa ``raster.to_display_row``): es el único
sitio donde una caja cambia de orientación.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .raster import ProvinceRaster


@dataclass(frozen=True)
class Box:
    """Rectángulo inclusivo ``x0 y0 x1 y1`` (``x0 ≤ x1``, ``y0 ≤ y1``)."""

    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def height(self) -> int:
        return self.y1 - self.y0 + 1


def box_of(raster: ProvinceRaster, pids: Iterable[int]) -> Box | None:
    """Caja que envuelve a ``pids`` (los que no tienen píxeles no cuentan); None si ninguno tiene. Es lo que
    repinta ``MapCanvas.refresh(pids)``."""
    raise NotImplementedError


def display_box(box: Box, height: int) -> Box:
    """``box`` en filas de la vista (norte arriba): mismas ``x`` y las filas volteadas e intercambiadas."""
    raise NotImplementedError


def parts(raster: ProvinceRaster, pid: int, *, wrap_x: bool = True) -> int:
    """Número de trozos 4-conexos de ``pid`` (0 si no tiene píxeles; más de 1 = ``province_fragmented``). Con
    ``wrap_x`` dos trozos unidos por la costura cuentan como uno."""
    raise NotImplementedError


def label_point(raster: ProvinceRaster, pid: int) -> tuple[float, float] | None:
    """Punto ``(x, y)`` dentro de la provincia donde escribir su número (modo IDs): el centroide si cae en un
    píxel suyo; si no (provincias en C o partidas), su píxel más cercano al centroide. None si no tiene píxeles."""
    raise NotImplementedError


def distance_to(raster: ProvinceRaster, pid: int, x: float, y: float) -> float:
    """Distancia en píxeles de ``(x, y)`` a la provincia (0 si el punto cae en ella; ``inf`` si no tiene
    píxeles). Criterio 2: el punto ``unit`` de ``positions.txt`` cae «en su provincia o junto a ella»
    (distancia ≤ 2) en al menos el 95 % de los casos."""
    raise NotImplementedError
