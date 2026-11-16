"""Provincias provisionales, estados, continentes y climas (wizard §18.3, pasos 8–11).

Todo sobre el grafo de celdas **sin las aristas de la costura** (ninguna provincia ni estado cruza x = 0/W, como en
vanilla). Las provincias son regiones de un Dijkstra multifuente con 2 iteraciones de Lloyd: en tierra con peso
idoneidad^0,75 (= sqrt(s·sqrt(s)), sin ``power``) y coste ×2,5 en montaña y ×1,5 en río; el mar es uniforme. Cada
isla recibe al menos una provincia.
"""

from __future__ import annotations

import numpy as np

from .graph import components, group, wrap_dx
from .world import CAT_INDEX, CATS, ProvisionalTable


def provinces(pts: np.ndarray, edges_ns: np.ndarray, h: np.ndarray, land: np.ndarray, suit: np.ndarray,
              river: np.ndarray, *, land_target: int, sea_target: int, size_variance: float, W: float,
              rng_land: np.random.Generator, rng_sea: np.random.Generator,
              mountain: float = 67, exclude: np.ndarray | None = None) -> np.ndarray:
    """Provincia provisional por celda: tierra 0..L0-1 y mar L0..P0-1 (-1 en las celdas de ``exclude``)."""
    n = h.size
    free = np.ones(n, bool) if exclude is None else ~exclude
    sea = ~land & free
    land = land & free
    comp_l = components(n, edges_ns, land)
    comp_s = components(n, edges_ns, sea)
    step = 1 + 1.5 * (h >= mountain) + 0.5 * river
    s = np.maximum(suit, 1e-6)
    if abs(size_variance - 0.75) < 1e-9:
        wl = np.sqrt(s * np.sqrt(s))
    else:   # otros exponentes: por tabla de 4 096 niveles calculada con math.pow
        import math

        lut = np.array([math.pow(i / 4095, size_variance) for i in range(4096)])
        wl = lut[np.clip((s / max(float(s.max()), 1e-12) * 4095).astype(np.int64), 0, 4095)] + 1e-9
    own_l = group(n, land, land_target, wl, step, pts, edges_ns, comp_l, rng_land, W) if land.any() \
        else np.full(n, -1, np.int64)
    own_s = group(n, sea, sea_target, np.ones(n), np.ones(n), pts, edges_ns, comp_s, rng_sea, W) \
        if sea.any() else np.full(n, -1, np.int64)
    # Compactar: los índices de región de ``group`` pueden tener huecos.
    out = np.full(n, -1, np.int64)
    nl = 0
    if land.any():
        ul, inv = np.unique(own_l[land], return_inverse=True)
        out[land] = inv
        nl = ul.size
    if sea.any():
        us, inv = np.unique(own_s[sea], return_inverse=True)
        out[sea] = inv + nl
    return out


def table(prov0: np.ndarray, land: np.ndarray, pts: np.ndarray, category: np.ndarray, suit: np.ndarray,
          temp: np.ndarray, edges: np.ndarray, W: float) -> tuple[ProvisionalTable, np.ndarray]:
    """La tabla de provincias provisionales (centroides sin trigonometría) y sus pares de vecinos (a < b)."""
    P0 = int(prov0.max()) + 1
    cells = np.bincount(prov0, minlength=P0)
    sea0 = np.bincount(prov0, weights=~land, minlength=P0) > cells / 2
    cx = np.bincount(prov0, weights=pts[:, 0], minlength=P0) / np.maximum(cells, 1)
    cy = np.bincount(prov0, weights=pts[:, 1], minlength=P0) / np.maximum(cells, 1)
    kc = np.bincount(prov0 * len(CATS) + category, minlength=P0 * len(CATS)).reshape(P0, len(CATS))
    kc[:, 0] = np.where(sea0, kc[:, 0], 0)
    dom = kc.argmax(1).astype(np.int8)
    psuit = np.bincount(prov0, weights=suit, minlength=P0) / np.maximum(cells, 1)
    ptemp = np.bincount(prov0, weights=temp, minlength=P0) / np.maximum(cells, 1)
    pa, pb = prov0[edges[:, 0]], prov0[edges[:, 1]]
    dm = pa != pb
    pairs = np.unique(np.sort(np.column_stack([pa[dm], pb[dm]]), 1), axis=0) if dm.any() \
        else np.zeros((0, 2), np.int64)
    t = ProvisionalTable(is_sea=sea0, cx=cx, cy=cy, cells=cells, dom_cat=dom, suit=psuit, temp=ptemp,
                         locked=np.zeros(P0, bool))
    return t, pairs


def states(t: ProvisionalTable, pairs: np.ndarray, *, per_state: float, W: float,
           rng: np.random.Generator) -> np.ndarray:
    """Estado por provincia provisional (-1 en el mar). Una masa de menos de 3 provincias se une al estado de la
    provincia más cercana de otra masa (vanilla tolera 65 estados no conexos)."""
    P0 = t.count
    landp = ~t.is_sea
    st = np.full(P0, -1, np.int64)
    if not landp.any():
        return st
    pts0 = np.column_stack([t.cx, t.cy])
    ll = pairs[landp[pairs[:, 0]] & landp[pairs[:, 1]]] if pairs.size else pairs
    ll_ns = ll[wrap_dx(t.cx[ll[:, 0]], t.cx[ll[:, 1]], W) == np.abs(t.cx[ll[:, 0]] - t.cx[ll[:, 1]])] \
        if ll.size else ll
    comp = components(P0, ll_ns, landp)
    csize = np.bincount(comp[landp], minlength=P0)
    bigc = landp & (csize[np.maximum(comp, 0)] >= 3)
    if bigc.any():
        k = max(1, round(int(bigc.sum()) / per_state))
        st = group(P0, bigc, k, np.ones(P0), np.ones(P0), pts0, ll_ns, comp, rng, W, lloyd=1)
        smallp = np.flatnonzero(landp & ~bigc)
        bigp = np.flatnonzero(bigc)
        for p in smallp.tolist():
            dx = wrap_dx(t.cx[bigp], t.cx[p], W)
            st[p] = st[bigp[np.argmin(dx * dx + (t.cy[bigp] - t.cy[p]) ** 2)]]
    else:     # solo islas pequeñas: un estado por masa
        st = np.where(landp, comp, -1)
    st[t.is_sea] = -1
    u, inv = np.unique(st[landp], return_inverse=True)
    st[landp] = inv
    return st


def continents(t: ProvisionalTable, pairs: np.ndarray, *, k: int, W: float, rng: np.random.Generator) -> np.ndarray:
    """k-medias de centroides; cada masa de tierra va entera a su continente mayoritario, salvo las que superan
    el 25 % de la tierra."""
    P0 = t.count
    landp = ~t.is_sea
    cont = np.full(P0, -1, np.int64)
    lp = np.flatnonzero(landp)
    if lp.size == 0:
        return cont
    k = max(1, min(k, lp.size))
    pts0 = np.column_stack([t.cx, t.cy])
    cent = pts0[np.sort(rng.choice(lp, k, replace=False))].copy()
    lab = np.zeros(lp.size, np.int64)
    for _ in range(12):
        dxk = wrap_dx(pts0[lp, None, 0], cent[None, :, 0], W)
        lab = np.argmin(dxk ** 2 + (pts0[lp, None, 1] - cent[None, :, 1]) ** 2, axis=1)
        for j in range(k):
            if (lab == j).any():
                cent[j] = pts0[lp[lab == j]].mean(0)
    ll = pairs[landp[pairs[:, 0]] & landp[pairs[:, 1]]] if pairs.size else pairs
    massc = components(P0, ll, landp)[lp]
    um, inv = np.unique(massc * k + lab, return_inverse=True)
    cnt = np.bincount(inv)
    mm, kk = np.divmod(um, k)
    o = np.lexsort((kk, -cnt, mm))
    f2 = np.ones(o.size, bool)
    f2[1:] = mm[o][1:] != mm[o][:-1]
    mass_cont = dict(zip(mm[o][f2].tolist(), kk[o][f2].tolist()))
    msize = np.bincount(massc)
    cont[lp] = np.where(msize[massc] > 0.25 * lp.size, lab, [mass_cont[x] for x in massc.tolist()])
    # Continentes vacíos fuera: índices contiguos en orden de aparición estable.
    u, inv2 = np.unique(cont[lp], return_inverse=True)
    cont[lp] = inv2
    return cont


def climates(t: ProvisionalTable) -> np.ndarray:
    """0 mild, 1 temperate, 2 harsh, 3 inhospitable (por temperatura e idoneidad medias)."""
    return np.where(t.is_sea, -1, np.select([t.temp < -2, t.temp < 6, t.suit < 0.25], [3, 2, 1], 0)).astype(np.int64)


def expansion_cost(t: ProvisionalTable, costs: dict) -> np.ndarray:
    return np.array([costs.get(CATS[int(c)], 1.0) for c in t.dom_cat.tolist()])


def land_cells_of(prov0: np.ndarray, land: np.ndarray) -> np.ndarray:
    return np.bincount(prov0, weights=land, minlength=int(prov0.max()) + 1)


__all__ = ["provinces", "table", "states", "continents", "climates", "expansion_cost", "CAT_INDEX"]
