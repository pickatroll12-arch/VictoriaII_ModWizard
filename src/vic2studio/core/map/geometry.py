"""Geometría sobre el ráster: cajas, puntos de etiqueta, fragmentos y distancias (wizard §16.1, §16.3). Contrato.

Todo en coordenadas del juego (``y`` = fila del ráster, norte en las ``y`` altas). ``Box`` es inclusiva, como
``ProvinceRaster.bbox``. La vista convierte con ``display_box`` (que usa ``raster.to_display_row``): es el único
sitio donde una caja cambia de orientación.
"""

from __future__ import annotations

from collections.abc import Iterable
import math
from dataclasses import dataclass

import numpy as np

from .raster import ProvinceRaster, to_display_row


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
    found = None
    size = raster.pixel_count.shape[0]
    for pid in pids:
        if not 0 < pid < size or raster.pixel_count[pid] == 0:
            continue
        x0, y0, x1, y1 = (int(v) for v in raster.bbox[pid])
        found = (x0, y0, x1, y1) if found is None else (min(found[0], x0), min(found[1], y0),
                                                       max(found[2], x1), max(found[3], y1))
    return None if found is None else Box(*found)


def display_box(box: Box, height: int) -> Box:
    """``box`` en filas de la vista (norte arriba): mismas ``x`` y las filas volteadas e intercambiadas."""
    return Box(box.x0, to_display_row(box.y1, height), box.x1, to_display_row(box.y0, height))


def _crop(raster: ProvinceRaster, pid: int) -> tuple[np.ndarray, int, int] | None:
    if not 0 < pid < raster.pixel_count.shape[0] or raster.pixel_count[pid] == 0:
        return None
    x0, y0, x1, y1 = (int(v) for v in raster.bbox[pid])
    return raster.ids[y0:y1 + 1, x0:x1 + 1] == pid, x0, y0


def _labels(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Etiquetas 4-conexas de ``mask`` (1…n; 0 fuera): propagación del mínimo hasta que no cambia, en numpy.
    Las cajas de una provincia son pequeñas, así que converge en pocas pasadas."""
    height, width = mask.shape
    big = np.iinfo(np.int64).max
    labels = np.where(mask, np.arange(1, mask.size + 1, dtype=np.int64).reshape(mask.shape), big)
    while True:
        previous = labels
        current = labels.copy()
        np.minimum(current[:, 1:], labels[:, :-1], out=current[:, 1:])
        np.minimum(current[:, :-1], labels[:, 1:], out=current[:, :-1])
        np.minimum(current[1:, :], labels[:-1, :], out=current[1:, :])
        np.minimum(current[:-1, :], labels[1:, :], out=current[:-1, :])
        current[~mask] = big
        # Saltos de puntero: cada etiqueta toma la de la etiqueta a la que apunta (converge mucho antes).
        flat = current.ravel()
        inside = flat != big
        targets = flat[inside] - 1
        flat[inside] = np.minimum(flat[inside], current.ravel()[targets])
        labels = current
        if np.array_equal(labels, previous):
            break
    unique, compact = np.unique(labels[mask], return_inverse=True)
    out = np.zeros(mask.shape, dtype=np.int64)
    out[mask] = compact + 1
    return out, int(unique.size)


def parts(raster: ProvinceRaster, pid: int, *, wrap_x: bool = True) -> int:
    """Número de trozos 4-conexos de ``pid`` (0 si no tiene píxeles; más de 1 = ``province_fragmented``). Con
    ``wrap_x`` dos trozos unidos por la costura cuentan como uno."""
    crop = _crop(raster, pid)
    if crop is None:
        return 0
    mask, x0, _ = crop
    labels, count = _labels(mask)
    if count <= 1 or not wrap_x or mask.shape[1] != raster.width:
        return count
    # La caja ocupa todo el ancho: los trozos que se tocan por la costura son uno.
    left, right = labels[:, 0], labels[:, -1]
    joined = {(int(a), int(b)) for a, b in zip(left, right) if a and b and a != b}
    parent = {i: i for i in range(1, count + 1)}

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for a, b in joined:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return len({find(i) for i in parent})


def _points(raster: ProvinceRaster, pid: int) -> tuple[np.ndarray, np.ndarray] | None:
    crop = _crop(raster, pid)
    if crop is None:
        return None
    mask, x0, y0 = crop
    ys, xs = np.nonzero(mask)
    return xs + x0, ys + y0


def label_point(raster: ProvinceRaster, pid: int) -> tuple[float, float] | None:
    """Punto ``(x, y)`` dentro de la provincia donde escribir su número (modo IDs): el centroide si cae en un
    píxel suyo; si no (provincias en C o partidas), su píxel más cercano al centroide. None si no tiene píxeles."""
    points = _points(raster, pid)
    if points is None:
        return None
    cx, cy = (float(v) for v in raster.centroid[pid])
    if raster.at(int(round(cx)), int(round(cy))) == pid:
        return cx, cy
    xs, ys = points
    best = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
    return float(xs[best]), float(ys[best])


def distance_to(raster: ProvinceRaster, pid: int, x: float, y: float) -> float:
    """Distancia en píxeles de ``(x, y)`` a la provincia (0 si el punto cae en ella; ``inf`` si no tiene
    píxeles). Criterio 2: el punto ``unit`` de ``positions.txt`` cae «en su provincia o junto a ella»
    (distancia ≤ 2) en al menos el 95 % de los casos."""
    points = _points(raster, pid)
    if points is None:
        return math.inf
    if raster.at(int(math.floor(x)), int(math.floor(y))) == pid:
        return 0.0
    xs, ys = points
    dx = np.abs(xs - x)
    if raster.width:
        dx = np.minimum(dx, raster.width - dx)
    return float(np.sqrt((dx ** 2 + (ys - y) ** 2).min()))
