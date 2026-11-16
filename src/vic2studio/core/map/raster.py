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

from ..cancel import CancelCheck, raise_if_cancelled
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
    _neighbors: dict = None   # type: ignore[assignment]  # wrap_x → vecinos (perezoso)

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
        rgb = np.asarray(rgb)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("se esperaba una imagen de 24 bits (alto, ancho, 3)")
        height, width = rgb.shape[:2]
        step = _Steps(progress, cancelled)
        keys = _color_keys(rgb)
        lut = np.zeros(1 << 24, dtype=np.uint16)
        largest = 0
        assigned: set[int] = set()
        for row in table.rows():
            if row.id is None or row.rgb is None:
                continue
            if row.id > 0xFFFF:
                raise ValueError(f"id de provincia demasiado grande para el ráster: {row.id}")
            largest = max(largest, row.id)
            key = (row.rgb[0] << 16) | (row.rgb[1] << 8) | row.rgb[2]
            if key not in assigned and 0 <= key < (1 << 24) and row.id > 0:
                assigned.add(key)
                lut[key] = row.id
        ids = lut[keys]
        del lut
        step()
        flat = ids.ravel()
        missing = np.flatnonzero(flat == NO_PROVINCE)
        unknown: list[UnknownColor] = []
        if missing.size:
            colors, first, counts = np.unique(keys.ravel()[missing], return_index=True, return_counts=True)
            for color, start, count in zip(colors.tolist(), first.tolist(), counts.tolist()):
                index = int(missing[start])
                unknown.append(UnknownColor(((color >> 16) & 255, (color >> 8) & 255, color & 255), int(count),
                                            (index % width, index // width)))
            unknown.sort(key=lambda item: (-item.pixels, item.rgb))
        size = max(largest, int(flat.max()) if flat.size else 0) + 1
        pixel_count = np.bincount(flat, minlength=size).astype(np.int64)
        step()
        bbox = _bboxes(ids, size)
        step()
        centroid = np.full((size, 2), np.nan, dtype=np.float64)
        present = pixel_count > 0
        xs = np.bincount(flat, weights=np.tile(np.arange(width, dtype=np.float64), height), minlength=size)
        ys = np.bincount(flat, weights=np.repeat(np.arange(height, dtype=np.float64), width), minlength=size)
        centroid[present, 0] = xs[present] / pixel_count[present]
        centroid[present, 1] = ys[present] / pixel_count[present]
        step()
        return cls(ids, pixel_count, bbox, centroid, tuple(unknown))

    def at(self, x: int, y: int) -> int:
        """Id del píxel ``(x, y)`` del juego; ``NO_PROVINCE`` fuera del mapa en vertical. ``x`` da la vuelta
        (el mapa es cíclico en horizontal)."""
        if not 0 <= y < self.height or self.width == 0:
            return NO_PROVINCE
        return int(self.ids[y, x % self.width])

    def neighbors(self, *, wrap_x: bool = True) -> dict[int, frozenset[int]]:
        """Vecinos por lado (4-conexos) de cada id con píxeles, sin ``NO_PROVINCE``. Con ``wrap_x`` la última
        columna toca la primera. Se calcula una vez por valor de ``wrap_x`` y se recuerda."""
        if self._neighbors is None:
            self._neighbors = {}
        if wrap_x in self._neighbors:
            return self._neighbors[wrap_x]
        ids = self.ids.astype(np.int64)
        pairs = [(ids[:, :-1], ids[:, 1:]), (ids[:-1, :], ids[1:, :])]
        if wrap_x and self.width > 1:
            pairs.append((ids[:, -1], ids[:, 0]))
        codes = []
        for a, b in pairs:
            a = a.ravel()
            b = b.ravel()
            keep = (a != b) & (a != NO_PROVINCE) & (b != NO_PROVINCE)
            low = np.minimum(a[keep], b[keep])
            high = np.maximum(a[keep], b[keep])
            codes.append(low * 65536 + high)
        unique = np.unique(np.concatenate(codes)) if codes else np.zeros(0, dtype=np.int64)
        found: dict[int, set[int]] = {int(pid): set() for pid in np.flatnonzero(self.pixel_count) if pid}
        for code in unique.tolist():
            low, high = divmod(code, 65536)
            found.setdefault(low, set()).add(high)
            found.setdefault(high, set()).add(low)
        result = {pid: frozenset(near) for pid, near in found.items()}
        self._neighbors[wrap_x] = result
        return result

    def border_mask(self, group_lut: np.ndarray | None = None, *, wrap_x: bool = True) -> np.ndarray:
        """Atajo de ``borders.border_mask(self.ids, group_lut, wrap_x=wrap_x)``."""
        from .borders import border_mask

        return border_mask(self.ids, group_lut, wrap_x=wrap_x)

    def majority(self, layer: np.ndarray) -> np.ndarray:
        """Valor mayoritario de ``layer`` en cada provincia: ``(N+1,)`` ``int16`` con -1 donde no hay píxeles.

        ``layer`` es ``(alto, ancho)`` ``uint8`` con la misma orientación (los índices de ``terrain.bmp``): un
        ``bincount`` de ``id * 256 + índice`` (§16.2). A igualdad gana el índice menor. ``ValueError`` si el
        tamaño no coincide (``bmp_size_mismatch`` lo dice antes la coherencia)."""
        layer = np.asarray(layer)
        if layer.shape != self.ids.shape:
            raise ValueError(f"tamaño distinto: {layer.shape} frente a {self.ids.shape}")
        size = self.max_id + 1
        combined = self.ids.astype(np.int64).ravel() * 256 + layer.astype(np.int64).ravel()
        counts = np.bincount(combined, minlength=size * 256).reshape(size, 256)
        result = counts.argmax(axis=1).astype(np.int16)
        result[self.pixel_count == 0] = -1
        return result

    def mask(self, pid: int) -> tuple[np.ndarray, tuple[int, int]]:
        """Máscara booleana de ``pid`` recortada a su caja y el origen ``(x0, y0)`` de la caja (para pintar la
        selección o rellenar sin recorrer el mapa entero). Una provincia sin píxeles da una máscara vacía."""
        if not 0 < pid <= self.max_id or self.pixel_count[pid] == 0:
            return np.zeros((0, 0), dtype=bool), (0, 0)
        x0, y0, x1, y1 = (int(v) for v in self.bbox[pid])
        return self.ids[y0:y1 + 1, x0:x1 + 1] == pid, (x0, y0)


def to_display_row(y: int, height: int) -> int:
    """Fila de la vista (norte arriba) de la ``y`` del juego: ``height - 1 - y``. Único punto de conversión."""
    return height - 1 - y


def from_display_row(row: int, height: int) -> int:
    """La inversa de ``to_display_row`` (es la misma cuenta; existe para que el código diga lo que hace)."""
    return height - 1 - row


def color_counts(rgb: np.ndarray) -> dict[RGB, int]:
    """Censo de colores de una imagen de 24 bits (``(alto, ancho, 3)`` ``uint8``): color → píxeles.

    Sustituye a ``validate.rules.provinces.bmp_colors`` (que leía la cabecera por su cuenta): quien quiera el
    censo de un archivo hace ``color_counts(read_bmp(datos).pixels)``."""
    keys = _color_keys(np.asarray(rgb)).ravel()
    colors, counts = np.unique(keys, return_counts=True)
    return {((c >> 16) & 255, (c >> 8) & 255, c & 255): int(n) for c, n in zip(colors.tolist(), counts.tolist())}


def _color_keys(rgb: np.ndarray) -> np.ndarray:
    """``(alto, ancho)`` ``uint32`` con ``r<<16 | g<<8 | b``."""
    return (rgb[..., 0].astype(np.uint32) << 16) | (rgb[..., 1].astype(np.uint32) << 8) | rgb[..., 2].astype(np.uint32)


def _first_last(flat: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Primera y última posición de cada id en ``flat`` (-1 si no aparece). Orden estable: radix para uint16."""
    order = np.argsort(flat, kind="stable")
    sorted_ids = flat[order]
    ids = np.arange(size)
    starts = np.searchsorted(sorted_ids, ids, side="left")
    ends = np.searchsorted(sorted_ids, ids, side="right")
    present = ends > starts
    first = np.full(size, -1, dtype=np.int64)
    last = np.full(size, -1, dtype=np.int64)
    first[present] = order[starts[present]]
    last[present] = order[ends[present] - 1]
    return first, last


def _bboxes(ids: np.ndarray, size: int) -> np.ndarray:
    height, width = ids.shape
    bbox = np.tile(np.array([0, 0, -1, -1], dtype=np.int32), (size, 1))
    first, last = _first_last(ids.ravel(), size)
    present = first >= 0
    bbox[present, 1] = first[present] // width
    bbox[present, 3] = last[present] // width
    first_t, last_t = _first_last(np.ascontiguousarray(ids.T).ravel(), size)
    bbox[present, 0] = first_t[present] // height
    bbox[present, 2] = last_t[present] // height
    return bbox


class _Steps:
    def __init__(self, progress, cancelled) -> None:
        self.progress = progress
        self.cancelled = cancelled
        self.done = 0

    def __call__(self) -> None:
        raise_if_cancelled(self.cancelled)
        self.done += 1
        if self.progress is not None:
            self.progress(self.done, BUILD_STEPS)
