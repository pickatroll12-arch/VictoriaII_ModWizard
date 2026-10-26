"""Prototipo mapforge (estudio): ideas de Azgaar FMG portadas a numpy, sin scipy.

Coordenadas: la fila del array es la y del juego (fila 0 = sur, H1 de wizard.md).
Todo es determinista con una semilla (numpy.random.Generator PCG64).
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import numpy as np

SEA_LEVEL = 20


# ----------------------------------------------------------------------------- rejilla
@dataclass
class Lattice:
    kind: str            # "square" | "hex"
    W: int
    H: int
    cols: int
    rows: int
    dx: float
    dy: float
    row_shift: np.ndarray   # (rows,) desplazamiento x de cada fila
    pts: np.ndarray         # (N, 2) float64 x, y
    wrap_x: bool

    @property
    def n(self) -> int:
        return self.rows * self.cols


def make_lattice(W: int, H: int, n_target: int, kind: str = "hex", jitter: float = 0.9,
                 wrap_x: bool = True, seed: int = 1) -> Lattice:
    """Rejilla con desplazamiento (FMG Lattice.placePoints): un punto por hueco, fila a fila."""
    rng = np.random.default_rng(seed)
    spacing = math.sqrt(W * H / n_target)
    if kind == "square":
        cols = max(3, round(W / spacing)); rows = max(3, round(H / spacing))
        dx = W / cols; dy = H / rows
        row_shift = np.zeros(rows)
        nd = min(dx, dy)
    else:  # hexágono «pointy»: filas impares desplazadas medio paso (FMG getRowShift)
        hex_side = math.sqrt(2 / math.sqrt(3))
        dx0 = spacing * hex_side
        cols = max(3, round(W / dx0)); dx = W / cols
        rows = max(3, round(H / (dx * math.sqrt(3) / 2))); dy = H / rows
        row_shift = ((np.arange(rows) & 1) - 0.5) * (dx / 2)
        nd = dx
    r, c = np.divmod(np.arange(rows * cols), cols)
    x = (c + 0.5) * dx + row_shift[r]
    y = (r + 0.5) * dy
    maxj = nd / 2 * jitter
    if kind == "square":
        jx = rng.uniform(-maxj, maxj, x.size); jy = rng.uniform(-maxj, maxj, x.size)
    else:
        rad = maxj * np.sqrt(rng.random(x.size)); ang = 2 * np.pi * rng.random(x.size)
        jx = rad * np.cos(ang); jy = rad * np.sin(ang)
    x = x + jx; y = np.clip(y + jy, 0, H - 1e-6)
    x = np.mod(x, W) if wrap_x else np.clip(x, 0, W - 1e-6)
    return Lattice(kind, W, H, cols, rows, dx, dy, row_shift, np.column_stack([x, y]), wrap_x)


def implicit_neighbors(lat: Lattice, mode: str) -> np.ndarray:
    """Vecinos implícitos por posición en la rejilla: (N, K) int32 con -1 de relleno."""
    rows, cols = lat.rows, lat.cols
    r, c = np.divmod(np.arange(lat.n), cols)
    if mode == "square4":
        offs = [(0, -1), (0, 1), (-1, 0), (1, 0)]
    elif mode == "square8":
        offs = [(0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    elif mode == "hex6":
        offs = None
    else:
        raise ValueError(mode)
    out = []
    if offs is not None:
        for dr, dc in offs:
            out.append(_slot(lat, r + dr, c + dc))
    else:
        odd = (r & 1).astype(bool)
        out.append(_slot(lat, r, c - 1)); out.append(_slot(lat, r, c + 1))
        for dr in (-1, 1):
            out.append(_slot(lat, r + dr, np.where(odd, c, c - 1)))
            out.append(_slot(lat, r + dr, np.where(odd, c + 1, c)))
    return np.column_stack(out).astype(np.int32)


def _slot(lat: Lattice, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    ok = (r >= 0) & (r < lat.rows)
    if lat.wrap_x:
        c = np.mod(c, lat.cols)
    else:
        ok &= (c >= 0) & (c < lat.cols)
    return np.where(ok, r * lat.cols + c, -1)


def to_csr(edges: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Aristas no dirigidas (E, 2) → CSR (indptr, indices) simétrico sin duplicados."""
    e = np.concatenate([edges, edges[:, ::-1]])
    e = np.unique(e, axis=0)
    indptr = np.zeros(n + 1, np.int64)
    np.add.at(indptr, e[:, 0] + 1, 1)
    np.cumsum(indptr, out=indptr)
    return indptr, e[:, 1].astype(np.int32)


def padded_from_csr(indptr: np.ndarray, indices: np.ndarray) -> np.ndarray:
    n = indptr.size - 1
    deg = np.diff(indptr)
    K = int(deg.max()) if n else 0
    out = np.full((n, K), -1, np.int32)
    row = np.repeat(np.arange(n), deg)
    pos = np.arange(indices.size) - indptr[row]
    out[row, pos] = indices
    return out


def edges_from_padded(nbr: np.ndarray) -> np.ndarray:
    i = np.repeat(np.arange(nbr.shape[0]), nbr.shape[1])
    j = nbr.ravel()
    m = (j >= 0) & (i < j)
    return np.column_stack([i[m], j[m]])


# ----------------------------------------------------------------------------- relieve (plantillas FMG)
class Heightmap:
    """HeightmapGenerator de FMG con operaciones vectorizadas por anillos BFS."""

    BLOB = {1000: .93, 2000: .95, 5000: .97, 10000: .98, 20000: .99, 30000: .991, 40000: .993,
            50000: .994, 60000: .995, 70000: .9955, 80000: .996, 90000: .9964, 100000: .9973}
    LINE = {1000: .75, 2000: .77, 5000: .79, 10000: .81, 20000: .82, 30000: .83, 40000: .84,
            50000: .86, 60000: .87, 70000: .88, 80000: .91, 90000: .92, 100000: .93}

    def __init__(self, lat: Lattice, nbr: np.ndarray, rng: np.random.Generator):
        self.lat, self.nbr, self.rng = lat, nbr, rng
        self.h = np.zeros(lat.n, np.float64)
        key = min(self.BLOB, key=lambda k: abs(k - lat.n))
        self.blob, self.line = self.BLOB[key], self.LINE[key]

    # utilidades de FMG
    def _num(self, s: str) -> float:
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
        lo = int(a) / 100; hi = int(b[0]) / 100 if b else lo
        return self.rng.uniform(lo * length, hi * length) if hi > lo else lo * length

    def find_slot(self, x: float, y: float) -> int:
        lat = self.lat
        r = int(min(max(y / lat.dy, 0), lat.rows - 1))
        c = int(min(max((x - lat.row_shift[r]) / lat.dx, 0), lat.cols - 1))
        return r * lat.cols + c

    def _rings(self, sources: np.ndarray, used: np.ndarray):
        """Generador de anillos BFS (arrays de celdas) desde `sources`."""
        frontier = np.unique(sources)
        used[frontier] = True
        while frontier.size:
            yield frontier
            cand = self.nbr[frontier].ravel()
            cand = cand[cand >= 0]
            cand = np.unique(cand[~used[cand]])
            used[cand] = True
            frontier = cand

    def hill(self, count, height, rx, ry, sign=1):
        for _ in range(self._num(count)):
            h0 = min(max(self._num(height), 0), 100)
            for _t in range(50):
                start = self.find_slot(self._pt(rx, self.lat.W), self._pt(ry, self.lat.H))
                if sign < 0 and self.h[start] >= 20:
                    break
                if sign > 0 and self.h[start] + h0 <= 90:
                    break
            change = np.zeros(self.lat.n)
            change[start] = h0
            used = np.zeros(self.lat.n, bool); used[start] = True
            frontier = np.array([start])
            while frontier.size:          # anillo a anillo; solo se expande lo que supera 1 (FMG)
                cand = self.nbr[frontier].ravel(); cand = cand[cand >= 0]
                cand = np.unique(cand[~used[cand]])
                if not cand.size:
                    break
                used[cand] = True
                nb = self.nbr[cand]
                pv = np.where(nb >= 0, change[np.maximum(nb, 0)], 0)
                # padre = media de los vecinos ya asignados (el máximo sesgaría el ruido hacia arriba)
                par = pv.sum(1) / np.maximum((pv > 0).sum(1), 1)
                v = np.floor(par ** self.blob * self.rng.uniform(0.9, 1.1, cand.size))   # FMG guarda change en Uint8Array: el truncado hace que decaiga
                change[cand] = v
                frontier = cand[v > 1]
            self.h = np.floor(np.clip(self.h + sign * change, 0, 100))

    def range_(self, count, height, rx, ry, sign=1, randomness=0.15):
        lat, pts = self.lat, self.lat.pts
        for _ in range(self._num(count)):
            h = min(max(self._num(height), 0), 100)
            sx, sy = self._pt(rx, lat.W), self._pt(ry, lat.H)
            for _t in range(50):
                ex = self.rng.random() * lat.W * .8 + lat.W * .1
                ey = self.rng.random() * lat.H * .7 + lat.H * .15
                d = abs(ey - sy) + abs(ex - sx)
                if lat.W / 8 <= d <= lat.W / (3 if sign > 0 else 2):
                    break
            cur, end = self.find_slot(sx, sy), self.find_slot(ex, ey)
            used = np.zeros(lat.n, bool); used[cur] = True; ridge = [cur]
            while cur != end and len(ridge) < 4 * (lat.cols + lat.rows):   # paseo voraz (FMG getRange)
                nb = self.nbr[cur]; nb = nb[(nb >= 0)]; nb = nb[~used[nb]]
                if nb.size == 0:
                    break
                dd = ((pts[end] - pts[nb]) ** 2).sum(1)
                dd = np.where(self.rng.random(nb.size) > 1 - randomness, dd / 2, dd)
                cur = int(nb[np.argmin(dd)]); used[cur] = True; ridge.append(cur)
            ridge = np.array(ridge)
            used2 = np.zeros(lat.n, bool)
            levels = 0
            for ring in self._rings(ridge, used2):
                levels += 1
                self.h[ring] = np.clip(self.h[ring] + sign * h * self.rng.uniform(.85, 1.15, ring.size), 0, 100)
                h = h ** self.line - 1
                if h < 2:
                    break
            for d, c in enumerate(ridge):            # prominencias (FMG: cada 6 celdas)
                if d % 6:
                    continue
                for _l in range(levels):
                    nb = self.nbr[c]; nb = nb[nb >= 0]
                    m = int(nb[np.argmin(self.h[nb])])
                    self.h[m] = (self.h[c] * 2 + self.h[m]) / 3
                    c = m

    def smooth(self, fr=2, add=0):
        nb = self.nbr
        vals = np.where(nb >= 0, self.h[np.maximum(nb, 0)], 0)
        cnt = (nb >= 0).sum(1) + 1
        mean = (vals.sum(1) + self.h) / cnt
        fr = float(fr)
        self.h = mean + add if fr == 1 else np.clip((self.h * (fr - 1) + mean + add) / fr, 0, 100)

    def mask(self, power=1.0):
        x, y = self.lat.pts[:, 0], self.lat.pts[:, 1]
        nx = 2 * x / self.lat.W - 1; ny = 2 * y / self.lat.H - 1
        dist = (1 - nx ** 2) * (1 - ny ** 2)
        if power < 0:
            dist = 1 - dist
        fr = abs(power) or 1
        self.h = np.clip((self.h * (fr - 1) + self.h * dist) / fr, 0, 100)

    def modify(self, rng_s, add=0.0, mult=1.0):
        lo, hi = (20, 100) if rng_s == "land" else (0, 100) if rng_s == "all" else map(float, rng_s.split("-"))
        land = lo == 20
        h = self.h; sel = (h >= lo) & (h <= hi); v = h[sel]
        if add:
            v = np.maximum(v + add, 20) if land else v + add
        if mult != 1:
            v = (v - 20) * mult + 20 if land else v * mult
        h[sel] = np.clip(v, 0, 100)

    def invert(self, prob, axes):
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
            t, a2, a3, a4, a5 = (line.split() + ["0"] * 5)[:5]
            if t == "Hill": self.hill(a2, a3, a4, a5, +1)
            elif t == "Pit": self.hill(a2, a3, a4, a5, -1)
            elif t == "Range": self.range_(a2, a3, a4, a5, +1, .15)
            elif t == "Trough": self.range_(a2, a3, a4, a5, -1, .2)
            elif t == "Smooth": self.smooth(float(a2))
            elif t == "Mask": self.mask(float(a2))
            elif t == "Add": self.modify(a3, add=float(a2))
            elif t == "Multiply": self.modify(a3, mult=float(a2))
            elif t == "Invert": self.invert(a2, a3)
            else: raise ValueError(t)


# ----------------------------------------------------------------------------- componentes conexas
def components(n: int, edges: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Etiquetas de componentes conexas (salto de punteros vectorizado). Celdas fuera de mask = -1."""
    lab = np.arange(n, dtype=np.int64)
    if mask is not None:
        e = edges[mask[edges[:, 0]] & mask[edges[:, 1]]]
    else:
        e = edges
    u, v = e[:, 0], e[:, 1]
    while True:
        lu, lv = lab[u], lab[v]
        m = np.minimum(lu, lv)
        old = lab.copy()
        np.minimum.at(lab, lu, m)
        np.minimum.at(lab, lv, m)
        while True:                      # compresión completa
            nl = lab[lab]
            if np.array_equal(nl, lab):
                break
            lab = nl
        if np.array_equal(lab, old):
            break
    if mask is not None:
        lab = np.where(mask, lab, -1)
    return lab


# ----------------------------------------------------------------------------- clima simplificado
def temperature(lat: Lattice, h: np.ndarray, lat_s=-60.0, lat_n=75.0, t_eq=27, t_np=-30, t_sp=-25) -> np.ndarray:
    """FMG Temperature.compute: gradiente por latitud + 6,5 °C/km. Fila 0 = sur (H1)."""
    y = lat.pts[:, 1]
    latitude = lat_s + (y / lat.H) * (lat_n - lat_s)
    trop_n, trop_s = 16, -20
    tn = t_eq - trop_n * .15; ts = t_eq + trop_s * .15
    gn = (tn - t_np) / (90 - trop_n); gs = (ts - t_sp) / (90 + trop_s)
    sea_t = np.where((latitude <= 16) & (latitude >= -20), t_eq - np.abs(latitude) * .15,
                     np.where(latitude > 0, tn - (latitude - trop_n) * gn, ts + (latitude - trop_s) * gs))
    drop = np.where(h < SEA_LEVEL, 0, ((np.maximum(h, 18) - 18) ** 2 / 1000) * 6.5)
    return sea_t - drop


def precipitation(lat: Lattice, h: np.ndarray, temp: np.ndarray, modifier=1.0) -> np.ndarray:
    """FMG Precipitation (solo vientos del oeste y del este por fila), vectorizado por columnas."""
    rows, cols = lat.rows, lat.cols
    H2 = h.reshape(rows, cols); T2 = temp.reshape(rows, cols)
    prec = np.zeros((rows, cols))
    latitude = -60 + (np.arange(rows) + .5) / rows * 135
    westerly = (np.abs(latitude) > 30) & (np.abs(latitude) < 60)      # bandas templadas: oeste
    for direction, sel in ((1, westerly), (-1, ~westerly)):
        hh = H2[sel][:, ::direction]; tt = T2[sel][:, ::direction]
        hum = np.full(hh.shape[0], 120.0 * modifier)
        p = np.zeros_like(hh)
        for k in range(cols):                       # se recorre la fila: vector por todas las filas
            cur = hh[:, k]; nxt = hh[:, (k + 1) % cols]
            water = cur < SEA_LEVEL
            frozen = tt[:, k] < -5
            hum = np.where(water & ~frozen, np.minimum(hum + 5 * modifier, 120 * modifier), hum)
            loss = np.maximum(hum / (10 * modifier), 1) + np.maximum(nxt - cur, 0) * (nxt / 70) ** 2
            loss = np.clip(loss, 1, np.maximum(hum, 1))
            loss = np.where(nxt > 85, hum, loss)
            land = ~water & ~frozen
            p[:, k] += np.where(land, loss, np.where(water, 5 * modifier, 0))
            hum = np.where(land, np.clip(hum - loss + np.where(loss > 1.5, 1, 0), 0, 120 * modifier), hum)
        prec[sel] = p[:, ::direction]
    return prec.ravel()


# ----------------------------------------------------------------------------- agua
def priority_flood(h: np.ndarray, nbr: np.ndarray, is_ocean: np.ndarray, eps=1e-3) -> np.ndarray:
    """Relleno de depresiones (Barnes 2014, variante +ε) desde el océano. Sustituye a
    FMG resolveDepressions (iterativo, hasta `resolveDepressionsSteps` pasadas)."""
    n = h.size
    filled = h.astype(np.float64).copy()
    done = is_ocean.copy()
    # semilla: celdas de tierra o lago que tocan el océano
    nb = nbr
    touch = (np.where(nb >= 0, is_ocean[np.maximum(nb, 0)], False)).any(1) & ~is_ocean
    heap = [(float(filled[i]), int(i)) for i in np.nonzero(touch)[0]]
    heapq.heapify(heap)
    done[touch] = True
    nbl = nbr.tolist(); fl = filled.tolist(); dn = done.tolist()
    while heap:
        hv, c = heapq.heappop(heap)
        for m in nbl[c]:
            if m < 0 or dn[m]:
                continue
            dn[m] = True
            if fl[m] <= hv:
                fl[m] = hv + eps
            heapq.heappush(heap, (fl[m], m))
    return np.array(fl)


def flow(filled: np.ndarray, nbr: np.ndarray, rain: np.ndarray, is_ocean: np.ndarray):
    """Receptor = vecino más bajo; acumulación en orden de altura descendente (FMG drainWater)."""
    nb = nbr
    hn = np.where(nb >= 0, filled[np.maximum(nb, 0)], np.inf)
    k = np.argmin(hn, axis=1)
    recv = nb[np.arange(nb.shape[0]), k]
    recv = np.where((hn[np.arange(nb.shape[0]), k] < filled) & ~is_ocean, recv, -1)
    order = np.argsort(-filled, kind="stable")
    flux = rain.astype(np.float64).copy()
    flux[is_ocean] = 0
    # acumulación vectorizada por niveles topológicos sería posible; en Python plano son ~N iteraciones
    fl = flux.tolist(); rv = recv.tolist()
    for c in order.tolist():
        r = rv[c]
        if r >= 0:
            fl[r] += fl[c]
    return recv, np.array(fl)


# ----------------------------------------------------------------------------- ráster
def rasterize(lat: Lattice, W: int, H: int, cell_class: np.ndarray | None = None,
              pix_class: np.ndarray | None = None, band: int = 64, reach: int = 1, warp=None):
    """Vecino más cercano por cubos (§18.3): para cada píxel, solo las semillas de los huecos
    vecinos (reach=1 → 3×3, reach=2 → 5×5). Con cell_class, la tierra solo toma celdas de tierra
    y el mar solo de mar (si ninguna candidata coincide, gana la más cercana sin restricción).
    warp: (dxf, dyf) campos (H, W) float32 de desplazamiento para bordes no rectos."""
    out = np.empty((H, W), np.int32)
    px = np.arange(W, dtype=np.float32) + 0.5
    P = lat.pts.astype(np.float32)
    offs = range(-reach, reach + 1)
    for y0 in range(0, H, band):
        y1 = min(H, y0 + band)
        yy = (np.arange(y0, y1, dtype=np.float32) + 0.5)[:, None] * np.ones((1, W), np.float32)
        xx = np.broadcast_to(px, (y1 - y0, W)).copy()
        if warp is not None:
            xx += warp[0][y0:y1]; yy += warp[1][y0:y1]
            if lat.wrap_x:
                xx %= W
            np.clip(yy, 0, H - 1e-3, out=yy)
        rr0 = np.floor(yy / lat.dy).astype(np.int32)
        best = np.full(xx.shape, np.inf, np.float32); bid = np.zeros(xx.shape, np.int32)
        if cell_class is not None:
            pcls = pix_class[y0:y1]
            best_any = np.full(xx.shape, np.inf, np.float32); bid_any = np.zeros(xx.shape, np.int32)
        for dr in offs:
            rr = rr0 + dr
            okr = (rr >= 0) & (rr < lat.rows)
            rrc = np.clip(rr, 0, lat.rows - 1)
            cc0 = np.floor((xx - lat.row_shift[rrc]) / lat.dx).astype(np.int32)
            for dc in offs:
                cc = cc0 + dc
                if lat.wrap_x:
                    cc %= lat.cols; ok = okr
                else:
                    ok = okr & (cc >= 0) & (cc < lat.cols); cc = np.clip(cc, 0, lat.cols - 1)
                cid = rrc * lat.cols + cc
                ddx = np.abs(P[cid, 0] - xx)
                if lat.wrap_x:
                    ddx = np.minimum(ddx, W - ddx)
                d = ddx * ddx + (P[cid, 1] - yy) ** 2
                d[~ok] = np.inf
                if cell_class is not None:
                    better_any = d < best_any
                    best_any[better_any] = d[better_any]; bid_any[better_any] = cid[better_any]
                    d = np.where(cell_class[cid] == pcls, d, np.inf)
                better = d < best
                best[better] = d[better]; bid[better] = cid[better]
        if cell_class is not None:
            miss = ~np.isfinite(best)
            bid[miss] = bid_any[miss]
        out[y0:y1] = bid
    return out


def raster_edges(ids: np.ndarray, wrap_x: bool = True) -> np.ndarray:
    """Pares de etiquetas distintas en píxeles vecinos (4-conexión), únicos, (E, 2) con a<b."""
    parts = []
    a, b = ids[:, :-1].ravel(), ids[:, 1:].ravel(); m = a != b; parts.append(np.column_stack([a[m], b[m]]))
    a, b = ids[:-1, :].ravel(), ids[1:, :].ravel(); m = a != b; parts.append(np.column_stack([a[m], b[m]]))
    if wrap_x:
        a, b = ids[:, -1], ids[:, 0]; m = a != b; parts.append(np.column_stack([a[m], b[m]]))
    e = np.concatenate(parts).astype(np.int64)
    e = np.sort(e, axis=1)
    key = np.unique(e[:, 0] * (int(ids.max()) + 1) + e[:, 1])
    return np.column_stack(np.divmod(key, int(ids.max()) + 1))


def value_noise(W: int, H: int, cells: int, amp: float, rng: np.random.Generator) -> np.ndarray:
    """Ruido de valor suave (rejilla gruesa + interpolación bilineal de Pillow) para deformar bordes."""
    from PIL import Image
    gw = max(2, W // cells); gh = max(2, H // cells)
    g = rng.uniform(-amp, amp, (gh, gw)).astype(np.float32)
    return np.asarray(Image.fromarray(g, mode="F").resize((W, H), Image.BILINEAR), dtype=np.float32)


# ----------------------------------------------------------------------------- provincias
def grow_regions(n: int, indptr, indices, members: np.ndarray, seeds: np.ndarray,
                 step_cost: np.ndarray, pts: np.ndarray, W: float, wrap_x: bool):
    """Dijkstra multi-fuente (FMG States/Provinces.expand) restringido a `members`."""
    owner = np.full(n, -1, np.int64)
    dist = np.full(n, np.inf)
    heap = []
    for k, s in enumerate(seeds.tolist()):
        dist[s] = 0; owner[s] = k; heap.append((0.0, s, k))
    heapq.heapify(heap)
    ip = indptr.tolist(); ix = indices.tolist(); mem = members.tolist(); sc = step_cost.tolist()
    px = pts[:, 0].tolist(); py = pts[:, 1].tolist(); dl = dist.tolist(); ow = owner.tolist()
    while heap:
        d, c, k = heapq.heappop(heap)
        if d > dl[c]:
            continue
        for j in range(ip[c], ip[c + 1]):
            m = ix[j]
            if not mem[m]:
                continue
            ddx = abs(px[m] - px[c])
            if wrap_x and ddx > W / 2:
                ddx = W - ddx
            nd = d + math.hypot(ddx, py[m] - py[c]) * (sc[m] + sc[c]) * 0.5
            if nd < dl[m]:
                dl[m] = nd; ow[m] = k
                heapq.heappush(heap, (nd, m, k))
    return np.array(ow), np.array(dl)


def group_cells(n, indptr, indices, members, k_total, weight, step_cost, pts, W, wrap_x, rng,
                lloyd_iters=2, comp=None, engine="vec", edges=None):
    """Agrupa las celdas `members` en ~k_total regiones contiguas.
    Semillas ∝ weight; cada componente (isla) recibe al menos 1. Luego Lloyd sobre el grafo."""
    idx = np.nonzero(members)[0]
    if comp is None:
        comp = np.zeros(n, np.int64)
    cl = comp[idx]
    ucomp, inv = np.unique(cl, return_inverse=True)
    wsum = np.bincount(inv, weights=weight[idx])
    quota = np.maximum(1, np.round(k_total * wsum / wsum.sum())).astype(int)
    seeds = []
    for ci in range(ucomp.size):
        cand = idx[inv == ci]
        q = min(quota[ci], cand.size)
        p = weight[cand] / weight[cand].sum()
        seeds.extend(rng.choice(cand, size=q, replace=False, p=p).tolist())
    seeds = np.array(seeds)
    for it in range(lloyd_iters + 1):
        if engine == "vec":
            owner, _ = grow_regions_vec(n, edges, members, seeds, step_cost, pts, W, wrap_x)
        else:
            owner, _ = grow_regions(n, indptr, indices, members, seeds, step_cost, pts, W, wrap_x)
        if it == lloyd_iters:
            break
        # nueva semilla: la celda miembro más cercana al centroide ponderado (sin envoltura en el prototipo)
        o = owner[idx]
        cx = np.bincount(o, weights=pts[idx, 0] * weight[idx], minlength=seeds.size)
        cy = np.bincount(o, weights=pts[idx, 1] * weight[idx], minlength=seeds.size)
        cw = np.bincount(o, weights=weight[idx], minlength=seeds.size)
        cx /= np.maximum(cw, 1e-9); cy /= np.maximum(cw, 1e-9)
        d2 = (pts[idx, 0] - cx[o]) ** 2 + (pts[idx, 1] - cy[o]) ** 2
        order = np.lexsort((d2, o))
        first = np.ones(order.size, bool); first[1:] = o[order][1:] != o[order][:-1]
        seeds = idx[order[first]]
    return owner


# ----------------------------------------------------------------------------- fragmentos (ráster)
def raster_fragments(ids: np.ndarray, wrap_x: bool = True) -> np.ndarray:
    """Número de componentes 4-conexas por etiqueta, por tramos (runs) + unión-búsqueda vectorizada."""
    H, W = ids.shape
    starts_all, ends_all, lab_all, row_off = [], [], [], [0]
    for y in range(H):
        r = ids[y]
        b = np.flatnonzero(np.diff(r)) + 1
        s = np.concatenate([[0], b]); e = np.concatenate([b, [W]])
        starts_all.append(s); ends_all.append(e); lab_all.append(r[s]); row_off.append(row_off[-1] + s.size)
    S = np.concatenate(starts_all); E = np.concatenate(ends_all); L = np.concatenate(lab_all)
    nr = S.size
    pairs = []
    for y in range(H - 1):
        a0, a1, b0, b1 = row_off[y], row_off[y + 1], row_off[y + 1], row_off[y + 2]
        brk = np.union1d(S[a0:a1], S[b0:b1])               # segmentos comunes
        ia = a0 + np.searchsorted(S[a0:a1], brk, side="right") - 1
        ib = b0 + np.searchsorted(S[b0:b1], brk, side="right") - 1
        m = L[ia] == L[ib]
        pairs.append(np.column_stack([ia[m], ib[m]]))
        if y == 0 or True:
            pass
    if wrap_x:
        first = np.array(row_off[:-1]); last = np.array(row_off[1:]) - 1
        m = (L[first] == L[last]) & (first != last)
        pairs.append(np.column_stack([first[m], last[m]]))
    P = np.concatenate(pairs)
    lab = components(nr, P)
    roots = np.unique(np.column_stack([L, lab]), axis=0)
    return np.bincount(roots[:, 0], minlength=int(ids.max()) + 1)


def run_components(ids: np.ndarray, wrap_x: bool = True) -> np.ndarray:
    """Etiqueta de componente 4-conexa por píxel (misma técnica de tramos que raster_fragments)."""
    H, W = ids.shape
    flat = ids.ravel()
    brk = np.flatnonzero(np.diff(flat)) + 1
    rowb = np.arange(1, H) * W
    starts = np.union1d(np.concatenate([[0], brk]), rowb)          # cada fila empieza tramo
    lens = np.diff(np.concatenate([starts, [flat.size]]))
    L = flat[starts]
    srow = starts // W
    row_off = np.searchsorted(srow, np.arange(H + 1))
    S = starts - srow * W
    pairs = []
    for y in range(H - 1):
        a0, a1, b0, b1 = row_off[y], row_off[y + 1], row_off[y + 1], row_off[y + 2]
        brk2 = np.union1d(S[a0:a1], S[b0:b1])
        ia = a0 + np.searchsorted(S[a0:a1], brk2, side="right") - 1
        ib = b0 + np.searchsorted(S[b0:b1], brk2, side="right") - 1
        m = L[ia] == L[ib]
        pairs.append(np.column_stack([ia[m], ib[m]]))
    if wrap_x:
        first = row_off[:-1]; last = row_off[1:] - 1
        m = (L[first] == L[last]) & (first != last)
        pairs.append(np.column_stack([first[m], last[m]]))
    lab = components(S.size, np.concatenate(pairs))
    _, lab = np.unique(lab, return_inverse=True)
    return np.repeat(lab, lens).reshape(H, W), L, lab


def fix_fragments(pid: np.ndarray, is_sea: np.ndarray, wrap_x: bool = True, max_rounds: int = 5):
    """Deja una sola componente por provincia: los trozos menores pasan a la provincia vecina
    de la misma clase (tierra/mar) con la que comparten frontera. Devuelve (pid, trozos movidos)."""
    moved = 0
    for _ in range(max_rounds):
        comp, L, runlab = run_components(pid, wrap_x)
        ncomp = int(comp.max()) + 1
        comp_prov = np.zeros(ncomp, np.int64); comp_prov[runlab] = L
        size = np.bincount(comp.ravel(), minlength=ncomp)
        # componente principal = la mayor de cada provincia
        order = np.lexsort((-size, comp_prov))
        main = np.zeros(ncomp, bool)
        first = np.ones(order.size, bool); first[1:] = comp_prov[order][1:] != comp_prov[order][:-1]
        main[order[first]] = True
        if main.all():
            break
        e = raster_edges(comp, wrap_x)
        e = np.concatenate([e, e[:, ::-1]])
        a, b = e[:, 0], e[:, 1]
        ok = ~main[a] & main[b] & (is_sea[comp_prov[a]] == is_sea[comp_prov[b]])
        target = np.full(ncomp, -1, np.int64)
        target[a[ok]] = comp_prov[b[ok]]
        newprov = np.where(target >= 0, target, comp_prov)
        moved += int((target >= 0).sum())
        pid = newprov[comp].astype(pid.dtype)
    return pid, moved


def grow_regions_vec(n: int, edges: np.ndarray, members: np.ndarray, seeds: np.ndarray,
                     step_cost: np.ndarray, pts: np.ndarray, W: float, wrap_x: bool, max_iter: int = 10000):
    """Igual que grow_regions pero vectorizado (Bellman-Ford por aristas): converge en tantas
    pasadas como saltos tiene la región más ancha, no en N pops de un montículo."""
    e = edges[members[edges[:, 0]] & members[edges[:, 1]]]
    u = np.concatenate([e[:, 0], e[:, 1]]); v = np.concatenate([e[:, 1], e[:, 0]])
    ddx = np.abs(pts[u, 0] - pts[v, 0])
    if wrap_x:
        ddx = np.minimum(ddx, W - ddx)
    w = np.hypot(ddx, pts[u, 1] - pts[v, 1]) * (step_cost[u] + step_cost[v]) * 0.5
    dist = np.full(n, np.inf); owner = np.full(n, -1, np.int64)
    dist[seeds] = 0; owner[seeds] = np.arange(seeds.size)
    active = np.zeros(n, bool); active[seeds] = True
    for _ in range(max_iter):
        sel = active[u]
        if not sel.any():
            break
        uu, vv, nd = u[sel], v[sel], dist[u[sel]] + w[sel]
        best = np.full(n, np.inf)
        np.minimum.at(best, vv, nd)
        imp = best < dist
        if not imp.any():
            break
        win = imp[vv] & (nd == best[vv])
        dist[imp] = best[imp]
        owner[vv[win]] = owner[uu[win]]
        active = imp
    return owner, dist


def fix_fragments2(pid: np.ndarray, is_sea: np.ndarray, wrap_x: bool = True, islet_px: int = 40):
    """Una sola pasada de etiquetado; la resolución se hace sobre el grafo de trozos.
    Trozo menor con vecino principal de su clase → se funde con él; si no tiene (islote de tierra
    en el mar o al revés): < islet_px píxeles cambia de clase (se funde con el vecino), si no → provincia nueva.
    Devuelve (pid, fundidos, cambiados_de_clase, provincias_nuevas)."""
    comp, L, runlab = run_components(pid, wrap_x)
    ncomp = int(comp.max()) + 1
    cprov = np.zeros(ncomp, np.int64); cprov[runlab] = L
    size = np.bincount(comp.ravel(), minlength=ncomp)
    order = np.lexsort((-size, cprov))
    main = np.zeros(ncomp, bool)
    first = np.ones(order.size, bool); first[1:] = cprov[order][1:] != cprov[order][:-1]
    main[order[first]] = True
    if main.all():
        return pid, 0, 0, 0, np.asarray(is_sea)
    e = raster_edges(comp, wrap_x); e = np.concatenate([e, e[:, ::-1]])
    adj: dict[int, list[int]] = {}
    frag = np.nonzero(~main)[0]
    fs = set(frag.tolist())
    for a, b in e[np.isin(e[:, 0], frag)].tolist():
        adj.setdefault(a, []).append(b)
    newprov = cprov.copy(); resolved = main.copy()
    merged = flipped = created = 0
    nextid = int(pid.max()) + 1
    pending = sorted(fs, key=lambda c: -size[c])
    for _round in range(10):
        left = []
        for c in pending:
            same = [b for b in adj.get(c, []) if resolved[b] and is_sea[newprov[b]] == is_sea[cprov[c]]]
            if same:
                newprov[c] = newprov[same[0]]; resolved[c] = True; merged += 1
            else:
                left.append(c)
        if len(left) == len(pending):
            break
        pending = left
    is_sea = list(is_sea)
    for c in pending:
        anyn = [b for b in adj.get(c, []) if resolved[b]]
        if size[c] < islet_px and anyn:
            newprov[c] = newprov[anyn[0]]; flipped += 1
        else:
            newprov[c] = nextid; is_sea.append(is_sea[cprov[c]]); nextid += 1; created += 1
        resolved[c] = True
    return newprov[comp].astype(pid.dtype), merged, flipped, created, np.asarray(is_sea)


def _slot_xy(lat: Lattice, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Posición sin jitter de un hueco (también fuera del mapa: anillo de contorno, FMG getLatticeRing)."""
    shift = ((r & 1) - 0.5) * (lat.dx / 2) if lat.kind == "hex" else np.zeros_like(r, dtype=float)
    return np.column_stack([(c + 0.5) * lat.dx + shift, (r + 0.5) * lat.dy])


def hex_voronoi_polygons(lat: Lattice) -> np.ndarray:
    """Polígonos de Voronoi exactos de una rejilla hexagonal con jitter ≤ 0,3 (su Delaunay es la
    triangulación implícita: medido 100 % de vecinos). (N, 6, 2): circuncentros de (i, n_k, n_k+1)
    con los 6 vecinos en orden angular. Vecinos fuera del mapa = huecos virtuales sin jitter."""
    n = lat.n
    r, c = np.divmod(np.arange(n), lat.cols)
    odd = (r & 1).astype(bool)
    offs = [(0, -1 + 0 * c), (0, 1 + 0 * c)]
    nr = []; nc = []
    for dr, dc in ((0, -1), (0, 1)):
        nr.append(r + dr); nc.append(c + dc)
    for dr in (-1, 1):
        nr.append(r + dr); nc.append(np.where(odd, c, c - 1))
        nr.append(r + dr); nc.append(np.where(odd, c + 1, c))
    NR = np.column_stack(nr); NC = np.column_stack(nc)
    inside = (NR >= 0) & (NR < lat.rows)
    NCw = np.mod(NC, lat.cols) if lat.wrap_x else NC
    inside &= (NCw >= 0) & (NCw < lat.cols)
    idx = np.where(inside, NR * lat.cols + np.clip(NCw, 0, lat.cols - 1), 0)
    pos = lat.pts[idx]                                         # (N,6,2)
    virt = _slot_xy(lat, NR.ravel(), NC.ravel()).reshape(n, 6, 2)
    pos = np.where(inside[..., None], pos, virt)
    P = lat.pts[:, None, :]
    dxv = pos[..., 0] - P[..., 0]
    if lat.wrap_x:                                             # desenrollar la costura
        dxv = np.where(dxv > lat.W / 2, dxv - lat.W, np.where(dxv < -lat.W / 2, dxv + lat.W, dxv))
    pos = np.stack([P[..., 0] + dxv, pos[..., 1]], -1)
    ang = np.arctan2(pos[..., 1] - P[..., 1], pos[..., 0] - P[..., 0])
    o = np.argsort(ang, axis=1)
    pos = np.take_along_axis(pos, o[..., None], 1)
    a = np.broadcast_to(P, pos.shape); b = pos; cc = np.roll(pos, -1, axis=1)
    ax, ay, bx, by, cx, cy = a[..., 0], a[..., 1], b[..., 0], b[..., 1], cc[..., 0], cc[..., 1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ad, bd, cd = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (ad * (by - cy) + bd * (cy - ay) + cd * (ay - by)) / d
    uy = (ad * (cx - bx) + bd * (ax - cx) + cd * (bx - ax)) / d
    return np.stack([ux, uy], -1)


def draw_polygons(polys: np.ndarray, W: int, H: int, wrap_x: bool = True, subdiv: int = 0,
                  noise: tuple[np.ndarray, np.ndarray] | None = None, amp: float = 0.0) -> np.ndarray:
    """Rellena cada polígono con id+1 (Pillow, modo I). Con subdiv y noise, cada arista se parte en
    subdiv tramos y sus puntos se desplazan con el campo de ruido evaluado en su posición: las aristas
    compartidas salen idénticas en los dos polígonos (mismos puntos, mismo ruido)."""
    from PIL import Image, ImageDraw
    if subdiv:
        a = polys; b = np.roll(polys, -1, axis=1)
        t = (np.arange(subdiv) / subdiv)[None, None, :, None]
        pts = (a[:, :, None, :] + (b - a)[:, :, None, :] * t).reshape(polys.shape[0], -1, 2)
    else:
        pts = polys
    if noise is not None:
        xi = np.clip(np.mod(pts[..., 0], W).astype(int), 0, W - 1); yi = np.clip(pts[..., 1].astype(int), 0, H - 1)
        pts = pts + np.stack([noise[0][yi, xi], noise[1][yi, xi]], -1) * amp
    im = Image.new("I", (W, H), 0)
    d = ImageDraw.Draw(im)
    lst = pts.tolist()
    xmin = pts[..., 0].min(1); xmax = pts[..., 0].max(1)
    for i, pg in enumerate(lst):
        d.polygon([tuple(p) for p in pg], fill=i + 1)
        if wrap_x and xmin[i] < 0:
            d.polygon([(x + W, y) for x, y in pg], fill=i + 1)
        if wrap_x and xmax[i] > W:
            d.polygon([(x - W, y) for x, y in pg], fill=i + 1)
    return np.asarray(im, dtype=np.int32) - 1


def fill_gaps(ids: np.ndarray, max_pass: int = 16) -> tuple[np.ndarray, int]:
    """Rellena píxeles -1 copiando un vecino 4-conexo ya asignado (pasadas vectorizadas)."""
    n = 0
    for n in range(1, max_pass + 1):
        g = ids < 0
        if not g.any():
            return ids, n - 1
        for sh, ax in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            src = np.roll(ids, sh, axis=ax)
            m = g & (src >= 0)
            ids[m] = src[m]
            g = ids < 0
    return ids, n
