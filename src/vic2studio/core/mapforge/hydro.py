# Port of Azgaar's Fantasy Map Generator src/modules/river-generator.ts (drainWater) (MIT, © Max Haniyeu)
"""Agua (wizard §18.3, paso 6): relleno de depresiones, receptores, caudal y celdas de río.

``priority_flood`` (Barnes 2014, variante +ε) sustituye a ``resolveDepressions`` de FMG. El receptor de cada celda
es su vecino más bajo; el caudal se acumula en orden de altura descendente (orden estable: el id desempata).
"""

from __future__ import annotations

import heapq

import numpy as np

from ..cancel import CancelCheck, raise_if_cancelled


def priority_flood(h: np.ndarray, nbr: np.ndarray, is_water: np.ndarray, eps: float = 1e-3) -> np.ndarray:
    filled = h.astype(np.float64).copy()
    done = is_water.copy()
    touch = np.where(nbr >= 0, is_water[np.maximum(nbr, 0)], False).any(1) & ~is_water
    heap = [(float(filled[i]), int(i)) for i in np.nonzero(touch)[0]]
    heapq.heapify(heap)
    done[touch] = True
    nbl = nbr.tolist()
    fl = filled.tolist()
    dn = done.tolist()
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


def flow(filled: np.ndarray, nbr: np.ndarray, rain: np.ndarray, is_water: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hn = np.where(nbr >= 0, filled[np.maximum(nbr, 0)], np.inf)
    k = np.argmin(hn, axis=1)
    rows = np.arange(nbr.shape[0])
    recv = nbr[rows, k].astype(np.int64)
    recv = np.where((hn[rows, k] < filled) & ~is_water, recv, -1)
    order = np.argsort(-filled, kind="stable")
    flux = rain.astype(np.float64).copy()
    flux[is_water] = 0
    fl = flux.tolist()
    rv = recv.tolist()
    for c in order.tolist():
        r = rv[c]
        if r >= 0:
            fl[r] += fl[c]
    return recv, np.array(fl)


def hydrology(h: np.ndarray, nbr: np.ndarray, prec: np.ndarray, land: np.ndarray, water: np.ndarray, *,
              flux_quantile: float, cancelled: CancelCheck = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(recv, flux, river)``: ríos en las celdas de tierra con caudal ≥ el cuantil pedido."""
    filled = priority_flood(h, nbr, water)
    raise_if_cancelled(cancelled)
    recv, flux = flow(filled, nbr, prec / 10, water)
    if land.any() and flux_quantile < 1:
        thr = float(np.quantile(flux[land], flux_quantile))
        river = land & (flux >= thr) & (flux > 0)
    else:
        river = np.zeros(h.size, bool)
    return recv, flux, river
