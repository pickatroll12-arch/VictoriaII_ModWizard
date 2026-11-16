# Port of Azgaar's Fantasy Map Generator src/modules/temperature.ts y precipitation.ts (MIT, © Max Haniyeu)
"""Temperatura y precipitación por celda (wizard §18.3, paso 5).

Temperatura por la latitud de la fila (fila 0 = sur, H1) y −6,5 °C/km; precipitación por vientos del oeste en las
franjas templadas y del este en el resto, recorriendo las filas de la rejilla (FMG simplificado). Solo sumas,
productos y cuadrados: el resultado no depende de la CPU.
"""

from __future__ import annotations

import numpy as np

from .graph import Lattice
from .world import SEA_LEVEL


def temperature(lat: Lattice, h: np.ndarray, *, lat_s: float = -60.0, lat_n: float = 75.0, t_eq: float = 27.0,
                t_np: float = -30.0, t_sp: float = -25.0) -> np.ndarray:
    y = lat.pts[:, 1]
    latitude = lat_s + (y / lat.H) * (lat_n - lat_s)
    trop_n, trop_s = 16, -20
    tn = t_eq - trop_n * .15
    ts = t_eq + trop_s * .15
    gn = (tn - t_np) / (90 - trop_n)
    gs = (ts - t_sp) / (90 + trop_s)
    sea_t = np.where((latitude <= 16) & (latitude >= -20), t_eq - np.abs(latitude) * .15,
                     np.where(latitude > 0, tn - (latitude - trop_n) * gn, ts + (latitude - trop_s) * gs))
    hh = np.maximum(h, 18) - 18
    drop = np.where(h < SEA_LEVEL, 0, (hh * hh / 1000) * 6.5)
    return sea_t - drop


def precipitation(lat: Lattice, h: np.ndarray, temp: np.ndarray, *, modifier: float = 1.0, lat_s: float = -60.0,
                  lat_n: float = 75.0) -> np.ndarray:
    rows, cols = lat.rows, lat.cols
    H2 = h.reshape(rows, cols)
    T2 = temp.reshape(rows, cols)
    prec = np.zeros((rows, cols))
    latitude = lat_s + (np.arange(rows) + .5) / rows * (lat_n - lat_s)
    westerly = (np.abs(latitude) > 30) & (np.abs(latitude) < 60)
    for direction, sel in ((1, westerly), (-1, ~westerly)):
        if not sel.any():
            continue
        hh = H2[sel][:, ::direction]
        tt = T2[sel][:, ::direction]
        hum = np.full(hh.shape[0], 120.0 * modifier)
        p = np.zeros_like(hh)
        for k in range(cols):
            cur = hh[:, k]
            nxt = hh[:, (k + 1) % cols]
            water = cur < SEA_LEVEL
            frozen = tt[:, k] < -5
            hum = np.where(water & ~frozen, np.minimum(hum + 5 * modifier, 120 * modifier), hum)
            rel = nxt / 70
            loss = np.maximum(hum / (10 * modifier), 1) + np.maximum(nxt - cur, 0) * rel * rel
            loss = np.clip(loss, 1, np.maximum(hum, 1))
            loss = np.where(nxt > 85, hum, loss)
            land = ~water & ~frozen
            p[:, k] += np.where(land, loss, np.where(water, 5 * modifier, 0))
            hum = np.where(land, np.clip(hum - loss + np.where(loss > 1.5, 1, 0), 0, 120 * modifier), hum)
        prec[sel] = p[:, ::direction]
    return prec.ravel()
