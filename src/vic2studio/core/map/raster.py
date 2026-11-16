"""Ráster de provincias en coordenadas del juego (wizard §16.1, H1). Contrato de la iteración 5.

``ProvinceRaster.ids[y, x]`` es el id de la provincia del píxel ``(x, y)`` del juego: la fila del array es la ``y``
del motor (la de ``positions.txt`` y la de la cámara de los bookmarks), que es la fila de ``BmpImage.pixels`` y de
Pillow. El norte está en las ``y`` altas, así que la imagen tal cual tiene el sur arriba: **solo la vista se
voltea**, y la única conversión es ``to_display_row`` / ``from_display_row``. Ningún otro módulo resta ``alto - 1``.

Medido en vanilla (5616×2160, 3 248 ids, 27 colores sin fila): traducir colores con una LUT densa ``uint16`` de
2^24 entradas tarda 0,9 s (§16.5); los centroides, unos 0,9 s por eje con ``bincount`` ponderado, se calculan una
vez y van a la caché (``cache.py``). Todo es numpy sin bucles por píxel; nada de aquí lee ni escribe disco, y un
``ProvinceRaster`` ya construido es inmutable de hecho (nadie escribe en sus arrays): se puede leer desde
cualquier hilo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..cancel import CancelCheck
from .definition import RGB, DefinitionTable

NO_PROVINCE = 0                      # id de los píxeles cuyo color no tiene fila con id en definition.csv
# ``progress(hecho, total)`` de las funciones largas: pasos, no píxeles (traducir, contar, cajas, centroides).
ProgressFn = Callable[[int, int], None]
BUILD_STEPS = 4


@dataclass(frozen=True)
class UnknownColor:
    """Un color del BMP sin fila con id: cuántos píxeles tiene y uno de ellos ``(x, y)`` (el primero en orden de
    filas), para llevar al usuario hasta él (``bmp_color_unmapped``)."""

    rgb: RGB
    pixels: int
    sample: tuple[int, int]


@dataclass(eq=False)
class ProvinceRaster:
    """Ids por píxel y sus estadísticas por id. ``N`` es el mayor id de ``definition.csv``; el índice 0 de cada
    array agrupa los píxeles sin provincia (``NO_PROVINCE``).

    - ``ids``: ``(alto, ancho)`` ``uint16``.
    - ``pixel_count``: ``(N+1,)`` ``int64``; 0 = el id no tiene píxeles (``province_without_pixels``).
    - ``bbox``: ``(N+1, 4)`` ``int32`` con ``x0 y0 x1 y1`` **inclusivos** en coordenadas del juego; un id sin
      píxeles tiene ``(0, 0, -1, -1)``. Una provincia partida por la costura ``x = 0 / ancho-1`` tiene la caja
      del ancho entero (en vanilla no hay ninguna).
    - ``centroid``: ``(N+1, 2)`` ``float64`` con ``x y``: la media de los índices de sus píxeles (Berlín, 549:
      fila 1675,6); ``nan`` si no tiene píxeles.
    - ``unknown``: los colores sin fila, por píxeles descendentes y, a igualdad, por color.
    """

    ids: np.ndarray
    pixel_count: np.ndarray
    bbox: np.ndarray
    centroid: np.ndarray
    unknown: tuple[UnknownColor, ...] = ()

    @property
    def width(self) -> int:
        return int(self.ids.shape[1])

    @property
    def height(self) -> int:
        return int(self.ids.shape[0])

    @property
    def max_id(self) -> int:
        """``N``: el mayor id que cabe en los arrays por id."""
        return int(self.pixel_count.shape[0]) - 1

    @classmethod
    def build(cls, rgb: np.ndarray, table: DefinitionTable, *, progress: ProgressFn | None = None,
              cancelled: CancelCheck = None) -> ProvinceRaster:
        """Ráster de ``rgb`` (``BmpImage.pixels`` de 24 bits: ``(alto, ancho, 3)`` ``uint8``, fila 0 = ``y`` 0).

        Cada color se traduce con ``table.id_of`` (la primera fila con ese color); los que no tienen fila con id
        dan ``NO_PROVINCE`` y se listan en ``unknown``. Un id mayor que 65 535 lanza ``ValueError`` (no cabe en
        ``uint16``; el juego tampoco lo admite). Consulta ``cancelled`` entre pasos (``Cancelled``) y avisa a
        ``progress`` con ``(paso, BUILD_STEPS)``. Pensado para un hilo de tarea: no toca nada compartido.
        """
        raise NotImplementedError

    def at(self, x: int, y: int) -> int:
        """Id del píxel ``(x, y)`` del juego; ``NO_PROVINCE`` fuera del mapa en vertical. ``x`` da la vuelta
        (el mapa es cíclico en horizontal)."""
        raise NotImplementedError

    def neighbors(self, *, wrap_x: bool = True) -> dict[int, frozenset[int]]:
        """Vecinos por lado (4-conexos) de cada id con píxeles, sin ``NO_PROVINCE``. Con ``wrap_x`` la última
        columna toca la primera. Se calcula una vez por valor de ``wrap_x`` y se recuerda."""
        raise NotImplementedError

    def border_mask(self, group_lut: np.ndarray | None = None, *, wrap_x: bool = True) -> np.ndarray:
        """Atajo de ``borders.border_mask(self.ids, group_lut, wrap_x=wrap_x)``."""
        raise NotImplementedError

    def majority(self, layer: np.ndarray) -> np.ndarray:
        """Valor mayoritario de ``layer`` en cada provincia: ``(N+1,)`` ``int16`` con -1 donde no hay píxeles.

        ``layer`` es ``(alto, ancho)`` ``uint8`` con la misma orientación (los índices de ``terrain.bmp``): un
        ``bincount`` de ``id * 256 + índice`` (§16.2). A igualdad gana el índice menor. ``ValueError`` si el
        tamaño no coincide (``bmp_size_mismatch`` lo dice antes la coherencia)."""
        raise NotImplementedError

    def mask(self, pid: int) -> tuple[np.ndarray, tuple[int, int]]:
        """Máscara booleana de ``pid`` recortada a su caja y el origen ``(x0, y0)`` de la caja (para pintar la
        selección o rellenar sin recorrer el mapa entero). Una provincia sin píxeles da una máscara vacía."""
        raise NotImplementedError


def to_display_row(y: int, height: int) -> int:
    """Fila de la vista (norte arriba) de la ``y`` del juego: ``height - 1 - y``. Único punto de conversión."""
    raise NotImplementedError


def from_display_row(row: int, height: int) -> int:
    """La inversa de ``to_display_row`` (es la misma cuenta; existe para que el código diga lo que hace)."""
    raise NotImplementedError


def color_counts(rgb: np.ndarray) -> dict[RGB, int]:
    """Censo de colores de una imagen de 24 bits (``(alto, ancho, 3)`` ``uint8``): color → píxeles.

    Sustituye a ``validate.rules.provinces.bmp_colors`` (que leía la cabecera por su cuenta): quien quiera el
    censo de un archivo hace ``color_counts(read_bmp(datos).pixels)``."""
    raise NotImplementedError
