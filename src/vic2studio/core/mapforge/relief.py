# Port of Azgaar's Fantasy Map Generator src/modules/heightmap-generator.ts (MIT, © Max Haniyeu)
"""Relieve por plantilla, nivel del mar y rasgos (wizard §18.3, pasos 2–4).

Las operaciones de FMG (Hill, Pit, Range, Trough, Strait, Mask, Add, Multiply, Smooth, Invert) se aplican por
anillos BFS vectorizados. Hill conserva el truncado a Uint8 de FMG (sin él, la colina no decae [R2]). Las potencias
van por ``math.pow`` (una tabla para los enteros 0–255), nunca por ufuncs de numpy: su resultado depende del SIMD
de la CPU (§18.3, aritmética reproducible).
"""

from __future__ import annotations

import math

import numpy as np

from ..cancel import CancelCheck, raise_if_cancelled
from .graph import Lattice, components
from .world import SEA_LEVEL

BLOB = {1000: .93, 2000: .95, 5000: .97, 10000: .98, 20000: .99, 30000: .991, 40000: .993, 50000: .994,
        60000: .995, 70000: .9955, 80000: .996, 90000: .9964, 100000: .9973}
LINE = {1000: .75, 2000: .77, 5000: .79, 10000: .81, 20000: .82, 30000: .83, 40000: .84, 50000: .86, 60000: .87,
        70000: .88, 80000: .91, 90000: .92, 100000: .93}


def _pow_table(exponent: float) -> np.ndarray:
    return np.array([math.pow(i, exponent) for i in range(256)], dtype=np.float64)


class Heightmap:
    """Generador de alturas de FMG sobre una rejilla con vecinos implícitos (``nbr`` (N, K), -1 de relleno)."""

    def __init__(self, lat: Lattice, nbr: np.ndarray, rng: np.random.Generator, *, cancelled: CancelCheck = None,
                 heights: np.ndarray | None = None):
        self.lat, self.nbr, self.rng = lat, nbr, rng
        self.h = np.zeros(lat.n, np.float64) if heights is None else heights.astype(np.float64).copy()
        key = min(BLOB, key=lambda k: abs(k - lat.n))
        self.blob, self.line = BLOB[key], LINE[key]
        self.blob_table = _pow_table(self.blob)
        self.cancelled = cancelled

    # --- utilidades de FMG ------------------------------------------------------------------------------

    def _num(self, s: str) -> int:
        s = str(s)
        try:
            v = float(s)
            return int(v) + (1 if self.rng.random() < v - int(v) else 0)
        except ValueError:
            sign = -1 if s[0] == "-" else 1
            if s[0] == "-":
                s = s[1:]
            a, b = s.split("-")
            return int(self.rng.integers(int(float(a)) * sign, int(float(b)) + 1))

    def _pt(self, rng_s: str, length: float) -> float:
        a, *b = rng_s.split("-")
        lo = float(a) / 100
        hi = float(b[0]) / 100 if b else lo
        return self.rng.uniform(lo * length, hi * length) if hi > lo else lo * length

    def find_slot(self, x: float, y: float) -> int:
        lat = self.lat
        r = int(min(max(y / lat.dy, 0), lat.rows - 1))
        c = int(min(max((x - lat.row_shift[r]) / lat.dx, 0), lat.cols - 1))
        return r * lat.cols + c

    def _rings(self, sources: np.ndarray, used: np.ndarray):
        frontier = np.unique(sources)
        used[frontier] = True
        while frontier.size:
            yield frontier
            cand = self.nbr[frontier].ravel()
            cand = cand[cand >= 0]
            cand = np.unique(cand[~used[cand]])
            used[cand] = True
            frontier = cand

    # --- operaciones ------------------------------------------------------------------------------------

    def hill(self, count, height, rx, ry, sign=1) -> None:
        for _ in range(self._num(count)):
            raise_if_cancelled(self.cancelled)
            h0 = min(max(self._num(height), 0), 100)
            start = 0
            for _t in range(50):
                start = self.find_slot(self._pt(rx, self.lat.W), self._pt(ry, self.lat.H))
                if sign < 0 and self.h[start] >= 20:
                    break
                if sign > 0 and self.h[start] + h0 <= 90:
                    break
            change = np.zeros(self.lat.n)
            change[start] = h0
            used = np.zeros(self.lat.n, bool)
            used[start] = True
            frontier = np.array([start])
            while frontier.size:
                cand = self.nbr[frontier].ravel()
                cand = cand[cand >= 0]
                cand = np.unique(cand[~used[cand]])
                if not cand.size:
                    break
                used[cand] = True
                nb = self.nbr[cand]
                pv = np.where(nb >= 0, change[np.maximum(nb, 0)], 0)
                par = pv.sum(1) / np.maximum((pv > 0).sum(1), 1)
                par_i = np.clip(np.floor(par), 0, 255).astype(np.int64)
                v = np.floor(self.blob_table[par_i] * self.rng.uniform(0.9, 1.1, cand.size))
                change[cand] = v
                frontier = cand[v > 1]
            self.h = np.floor(np.clip(self.h + sign * change, 0, 100))

    def _ridge(self, start: int, end: int, randomness: float) -> np.ndarray:
        lat, pts = self.lat, self.lat.pts
        cur = start
        used = np.zeros(lat.n, bool)
        used[cur] = True
        ridge = [cur]
        while cur != end and len(ridge) < 4 * (lat.cols + lat.rows):
            nb = self.nbr[cur]
            nb = nb[nb >= 0]
            nb = nb[~used[nb]]
            if nb.size == 0:
                break
            dd = ((pts[end] - pts[nb]) ** 2).sum(1)
            dd = np.where(self.rng.random(nb.size) > 1 - randomness, dd / 2, dd)
            cur = int(nb[np.argmin(dd)])
            used[cur] = True
            ridge.append(cur)
        return np.array(ridge)

    def range_(self, count, height, rx, ry, sign=1, randomness=0.15) -> None:
        lat = self.lat
        for _ in range(self._num(count)):
            raise_if_cancelled(self.cancelled)
            h = float(min(max(self._num(height), 0), 100))
            sx, sy = self._pt(rx, lat.W), self._pt(ry, lat.H)
            ex, ey = sx, sy
            for _t in range(50):
                ex = self.rng.random() * lat.W * .8 + lat.W * .1
                ey = self.rng.random() * lat.H * .7 + lat.H * .15
                d = abs(ey - sy) + abs(ex - sx)
                if lat.W / 8 <= d <= lat.W / (3 if sign > 0 else 2):
                    break
            ridge = self._ridge(self.find_slot(sx, sy), self.find_slot(ex, ey), randomness)
            self._raise_along(ridge, h, sign)

    def _raise_along(self, ridge: np.ndarray, h: float, sign: int) -> None:
        levels = 0
        used = np.zeros(self.lat.n, bool)
        for ring in self._rings(ridge, used):
            levels += 1
            self.h[ring] = np.clip(self.h[ring] + sign * h * self.rng.uniform(.85, 1.15, ring.size), 0, 100)
            h = math.pow(h, self.line) - 1
            if h < 2:
                break
        for d, c in enumerate(ridge.tolist()):
            if d % 6:
                continue
            for _l in range(levels):
                nb = self.nbr[c]
                nb = nb[nb >= 0]
                m = int(nb[np.argmin(self.h[nb])])
                self.h[m] = (self.h[c] * 2 + self.h[m]) / 3
                c = m

    def strait(self, width, direction) -> None:
        """Un estrecho de borde a borde (FMG ``addStrait``): baja el relieve a lo largo de un camino voraz."""
        lat = self.lat
        w = min(self._num(width), max(1, lat.cols // 3))
        if w < 1 or self.rng.random() < 0.05 and w == 1:
            return
        vertical = direction == "vertical"
        if vertical:
            sx = lat.W * (0.3 + self.rng.random() * 0.4)
            ex = lat.W * (0.3 + self.rng.random() * 0.4)
            start, end = self.find_slot(sx, lat.H - 1), self.find_slot(ex, 0)
        else:
            sy = lat.H * (0.3 + self.rng.random() * 0.4)
            ey = lat.H * (0.3 + self.rng.random() * 0.4)
            start, end = self.find_slot(0, sy), self.find_slot(lat.W - 1, ey)
        ridge = self._ridge(start, end, 0.2)
        used = np.zeros(lat.n, bool)
        for k, ring in enumerate(self._rings(ridge, used)):
            if k >= w:
                break
            # FMG: h = h^0,8 por anillo (por tabla) y, en el eje, por debajo del nivel del mar.
            hi = np.clip(np.floor(self.h[ring]), 0, 255).astype(np.int64)
            self.h[ring] = _pow_table(0.8)[hi]
            if k == 0:
                self.h[ring] = np.minimum(self.h[ring], SEA_LEVEL - 5)

    def smooth(self, fr=2, add=0) -> None:
        nb = self.nbr
        vals = np.where(nb >= 0, self.h[np.maximum(nb, 0)], 0)
        cnt = (nb >= 0).sum(1) + 1
        mean = (vals.sum(1) + self.h) / cnt
        fr = float(fr)
        self.h = mean + add if fr == 1 else np.clip((self.h * (fr - 1) + mean + add) / fr, 0, 100)

    def mask(self, power=1.0) -> None:
        x, y = self.lat.pts[:, 0], self.lat.pts[:, 1]
        nx = 2 * x / self.lat.W - 1
        ny = 2 * y / self.lat.H - 1
        dist = (1 - nx * nx) * (1 - ny * ny)
        if power < 0:
            dist = 1 - dist
        fr = abs(power) or 1
        self.h = np.clip((self.h * (fr - 1) + self.h * dist) / fr, 0, 100)

    def modify(self, rng_s, add=0.0, mult=1.0) -> None:
        if rng_s == "land":
            lo, hi = 20.0, 100.0
        elif rng_s == "all":
            lo, hi = 0.0, 100.0
        else:
            lo, hi = (float(v) for v in rng_s.split("-"))
        land = lo == 20
        h = self.h
        sel = (h >= lo) & (h <= hi)
        v = h[sel]
        if add:
            v = np.maximum(v + add, 20) if land else v + add
        if mult != 1:
            v = (v - 20) * mult + 20 if land else v * mult
        h[sel] = np.clip(v, 0, 100)

    def invert(self, prob, axes) -> None:
        if self.rng.random() >= float(prob):
            return
        g = self.h.reshape(self.lat.rows, self.lat.cols)
        if axes != "y":
            g = g[:, ::-1]
        if axes != "x":
            g = g[::-1, :]
        self.h = g.ravel().copy()

    def run_template(self, text: str) -> None:
        for line in text.strip().splitlines():
            words = line.split()
            if not words or words[0].startswith("#"):
                continue
            t, a2, a3, a4, a5 = (words + ["0"] * 5)[:5]
            if t == "Hill":
                self.hill(a2, a3, a4, a5, +1)
            elif t == "Pit":
                self.hill(a2, a3, a4, a5, -1)
            elif t == "Range":
                self.range_(a2, a3, a4, a5, +1, .15)
            elif t == "Trough":
                self.range_(a2, a3, a4, a5, -1, .2)
            elif t == "Strait":
                self.strait(a2, a3)
            elif t == "Smooth":
                self.smooth(float(a2))
            elif t == "Mask":
                self.mask(float(a2))
            elif t == "Add":
                self.modify(a3, add=float(a2))
            elif t == "Multiply":
                self.modify(a3, mult=float(a2))
            elif t == "Invert":
                self.invert(a2, a3)
            else:
                raise ValueError(t)


def sea_level(h: np.ndarray, land_fraction: float) -> np.ndarray:
    """Desplaza las alturas para que la fracción de tierra sea ``land_fraction`` (solo mueve el nivel del mar)."""
    order = np.sort(h, kind="stable")
    k = min(max(int(round((1 - land_fraction) * (h.size - 1))), 0), h.size - 1)
    q = float(order[k])
    return np.clip(h + (SEA_LEVEL - q) - 0.5, 0, 100)


def features(h: np.ndarray, edges: np.ndarray, min_lake_cells: int) -> tuple[np.ndarray, np.ndarray, np.ndarray,
                                                                             np.ndarray]:
    """El océano es la mayor masa de agua; los lagos de ≥ ``min_lake_cells`` celdas son mar interior y los menores
    pasan a tierra. Devuelve ``(h, land, ocean, lake)``."""
    n = h.size
    h = h.copy()
    land = h >= SEA_LEVEL
    water = ~land
    if not water.any():
        return h, land, np.zeros(n, bool), np.zeros(n, bool)
    comp = components(n, edges, water)
    big = int(np.bincount(comp[water]).argmax())
    ocean = comp == big
    lake = water & ~ocean
    size = np.bincount(np.where(lake, comp, 0), minlength=n)
    small = lake & (size[np.maximum(comp, 0)] < min_lake_cells)
    h[small] = SEA_LEVEL
    land = h >= SEA_LEVEL
    lake = ~land & ~ocean
    return h, land, ocean, lake
