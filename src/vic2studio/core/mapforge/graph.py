# Port of Azgaar's Fantasy Map Generator src/modules/lattice (placePoints) y utilidades de grafo (MIT, © Max Haniyeu)
"""Rejilla de celdas y grafo (wizard §18.3, paso 1).

Rejilla hexagonal «pointy» con jitter ≤ 0,3: sus 6 vecinos implícitos son exactamente los de Voronoi (precisión y
recobrado 1,0000 [R2]), así que no hace falta Delaunator. La fila del array es la y del juego (fila 0 = sur, H1).
Las aristas que cruzan la costura x = 0/W se marcan: las provincias y los estados no la cruzan (§18.3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Lattice:
    kind: str
    W: float
    H: float
    cols: int
    rows: int
    dx: float
    dy: float
    row_shift: np.ndarray
    pts: np.ndarray
    wrap_x: bool

    @property
    def n(self) -> int:
        return self.rows * self.cols

    def scaled(self, s: int) -> Lattice:
        """La misma rejilla en coordenadas divididas por ``s`` (la vista previa dibuja a W/s)."""
        return Lattice(self.kind, self.W / s, self.H / s, self.cols, self.rows, self.dx / s, self.dy / s,
                       self.row_shift / s, self.pts / s, self.wrap_x)


def make_lattice(W: int, H: int, n_target: int, *, kind: str = "hex", jitter: float = 0.3, wrap_x: bool = True,
                 seed: int = 1) -> Lattice:
    """Un punto por hueco, fila a fila (FMG ``placePoints``), con jitter en un disco."""
    rng = np.random.default_rng([int(seed), 1])
    spacing = math.sqrt(W * H / n_target)
    if kind == "square":
        cols = max(3, round(W / spacing))
        rows = max(3, round(H / spacing))
        dx, dy = W / cols, H / rows
        row_shift = np.zeros(rows)
        nd = min(dx, dy)
    else:
        hex_side = math.sqrt(2 / math.sqrt(3))
        cols = max(3, round(W / (spacing * hex_side)))
        dx = W / cols
        rows = max(3, round(H / (dx * math.sqrt(3) / 2)))
        dy = H / rows
        row_shift = ((np.arange(rows) & 1) - 0.5) * (dx / 2)
        nd = dx
    r, c = np.divmod(np.arange(rows * cols), cols)
    x = (c + 0.5) * dx + row_shift[r]
    y = (r + 0.5) * dy
    maxj = nd / 2 * jitter
    # Disco sin trigonometría de numpy: radio por sqrt (exacta) y dirección por rechazo en el cuadrado unidad.
    rad = maxj * np.sqrt(rng.random(x.size))
    ux = rng.uniform(-1, 1, (x.size, 4))
    uy = rng.uniform(-1, 1, (x.size, 4))
    ok = ux * ux + uy * uy
    pick = np.argmax((ok <= 1) & (ok > 1e-6), axis=1)
    vx = ux[np.arange(x.size), pick]
    vy = uy[np.arange(x.size), pick]
    norm = np.sqrt(vx * vx + vy * vy)
    norm[norm == 0] = 1
    x = x + rad * vx / norm
    y = np.clip(y + rad * vy / norm, 0, H - 1e-6)
    x = np.mod(x, W) if wrap_x else np.clip(x, 0, W - 1e-6)
    return Lattice(kind, float(W), float(H), int(cols), int(rows), float(dx), float(dy), row_shift,
                   np.column_stack([x, y]), wrap_x)


def _slot(lat: Lattice, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    ok = (r >= 0) & (r < lat.rows)
    if lat.wrap_x:
        c = np.mod(c, lat.cols)
    else:
        ok &= (c >= 0) & (c < lat.cols)
    return np.where(ok, r * lat.cols + c, -1)


def neighbors(lat: Lattice) -> np.ndarray:
    """Vecinos implícitos (N, 6) con -1 de relleno: los 6 del hexágono, o los 8 de la rejilla cuadrada."""
    r, c = np.divmod(np.arange(lat.n), lat.cols)
    out = []
    if lat.kind == "square":
        for dr, dc in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            out.append(_slot(lat, r + dr, c + dc))
    else:
        odd = (r & 1).astype(bool)
        out.append(_slot(lat, r, c - 1))
        out.append(_slot(lat, r, c + 1))
        for dr in (-1, 1):
            out.append(_slot(lat, r + dr, np.where(odd, c, c - 1)))
            out.append(_slot(lat, r + dr, np.where(odd, c + 1, c)))
    return np.column_stack(out).astype(np.int32)


def edges_from_padded(nbr: np.ndarray) -> np.ndarray:
    i = np.repeat(np.arange(nbr.shape[0]), nbr.shape[1])
    j = nbr.ravel()
    m = (j >= 0) & (i < j)
    return np.column_stack([i[m], j[m]]).astype(np.int64)


def seam_edges(lat: Lattice, edges: np.ndarray) -> np.ndarray:
    return np.abs(lat.pts[edges[:, 0], 0] - lat.pts[edges[:, 1], 0]) > lat.W / 2


def components(n: int, edges: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Componentes conexas por salto de punteros vectorizado. Las celdas fuera de ``mask`` quedan en -1."""
    lab = np.arange(n, dtype=np.int64)
    e = edges if mask is None else edges[mask[edges[:, 0]] & mask[edges[:, 1]]]
    if e.size:
        u, v = e[:, 0], e[:, 1]
        while True:
            lu, lv = lab[u], lab[v]
            m = np.minimum(lu, lv)
            old = lab.copy()
            np.minimum.at(lab, lu, m)
            np.minimum.at(lab, lv, m)
            while True:
                nl = lab[lab]
                if np.array_equal(nl, lab):
                    break
                lab = nl
            if np.array_equal(lab, old):
                break
    if mask is not None:
        lab = np.where(mask, lab, -1)
    return lab


def wrap_dx(a: np.ndarray, b, W: float) -> np.ndarray:
    d = np.abs(a - b)
    return np.minimum(d, W - d)


def grow_regions(n: int, edges: np.ndarray, members: np.ndarray, seeds: np.ndarray, step_cost: np.ndarray,
                 pts: np.ndarray, W: float) -> np.ndarray:
    """Dijkstra multifuente vectorizado (Bellman-Ford por aristas) restringido a ``members``.

    Distancias con ``sqrt`` (exacta en IEEE) en lugar de ``hypot``; un empate lo gana la semilla de id menor."""
    e = edges[members[edges[:, 0]] & members[edges[:, 1]]]
    u = np.concatenate([e[:, 0], e[:, 1]])
    v = np.concatenate([e[:, 1], e[:, 0]])
    ddx = wrap_dx(pts[u, 0], pts[v, 0], W)
    ddy = pts[u, 1] - pts[v, 1]
    w = np.sqrt(ddx * ddx + ddy * ddy) * (step_cost[u] + step_cost[v]) * 0.5
    dist = np.full(n, np.inf)
    owner = np.full(n, -1, np.int64)
    dist[seeds] = 0
    owner[seeds] = np.arange(seeds.size)
    active = np.zeros(n, bool)
    active[seeds] = True
    big = np.iinfo(np.int64).max
    while True:
        sel = active[u]
        if not sel.any():
            break
        uu, vv = u[sel], v[sel]
        nd = dist[uu] + w[sel]
        best = np.full(n, np.inf)
        np.minimum.at(best, vv, nd)
        imp = best < dist
        if not imp.any():
            break
        win = imp[vv] & (nd == best[vv])
        dist[imp] = best[imp]
        cand = np.full(n, big)
        np.minimum.at(cand, vv[win], owner[uu[win]])
        owner[imp] = cand[imp]
        active = imp
    return owner


def group(n: int, members: np.ndarray, k_total: int, weight: np.ndarray, step_cost: np.ndarray, pts: np.ndarray,
          edges: np.ndarray, comp: np.ndarray, rng: np.random.Generator, W: float, *, lloyd: int = 2) -> np.ndarray:
    """Agrupa las celdas ``members`` en unas ``k_total`` regiones contiguas (semillas ∝ ``weight``, cada
    componente recibe al menos una) con ``lloyd`` iteraciones de Lloyd sobre el grafo. Devuelve el índice de región
    por celda (-1 fuera de ``members``)."""
    idx = np.nonzero(members)[0]
    if idx.size == 0:
        return np.full(n, -1, np.int64)
    ucomp, inv = np.unique(comp[idx], return_inverse=True)
    wsum = np.bincount(inv, weights=weight[idx])
    tot = math.fsum(wsum.tolist()) or 1.0
    quota = np.maximum(1, np.round(k_total * wsum / tot)).astype(int)
    seeds: list[int] = []
    for ci in range(ucomp.size):
        cand = idx[inv == ci]
        q = min(int(quota[ci]), cand.size)
        wc = weight[cand].astype(np.float64)
        s = math.fsum(wc.tolist())
        p = wc / s if s > 0 else np.full(cand.size, 1.0 / cand.size)
        p = p / p.sum()
        seeds.extend(rng.choice(cand, size=q, replace=False, p=p).tolist())
    seeds_arr = np.array(sorted(seeds), dtype=np.int64)
    owner = np.full(n, -1, np.int64)
    for it in range(lloyd + 1):
        owner = grow_regions(n, edges, members, seeds_arr, step_cost, pts, W)
        if it == lloyd:
            break
        o = owner[idx]
        okm = o >= 0
        oi, ii = o[okm], idx[okm]
        cw = np.bincount(oi, weights=weight[ii], minlength=seeds_arr.size)
        cx = np.bincount(oi, weights=pts[ii, 0] * weight[ii], minlength=seeds_arr.size) / np.maximum(cw, 1e-12)
        cy = np.bincount(oi, weights=pts[ii, 1] * weight[ii], minlength=seeds_arr.size) / np.maximum(cw, 1e-12)
        d2 = (pts[ii, 0] - cx[oi]) ** 2 + (pts[ii, 1] - cy[oi]) ** 2
        order = np.lexsort((ii, d2, oi))
        first = np.ones(order.size, bool)
        first[1:] = oi[order][1:] != oi[order][:-1]
        seeds_arr = ii[order[first]]
    # Celdas miembro inalcanzables (no debería pasar: cada componente tiene semilla): región propia nueva.
    lost = members & (owner < 0)
    if lost.any():
        owner[lost] = owner.max() + 1 + np.arange(int(lost.sum()))
    return owner
