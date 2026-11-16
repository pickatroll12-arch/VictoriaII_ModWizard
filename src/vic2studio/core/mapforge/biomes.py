"""Categorías de terreno e idoneidad por celda (wizard §18.3, paso 7).

Matriz temperatura × humedad de ``data.biome_table``; h ≥ 67 → mountain, 44 ≤ h < 67 → hills; pantano en la tierra
baja y húmeda; farmlands en el ``farmland_share`` más idóneo de plains y woods. La idoneidad sigue la idea de
``rankCells`` de FMG: templado, bajo y con río es mejor.
"""

from __future__ import annotations

import numpy as np

from .data.biome_table import BIOME_TABLE
from .world import CAT_INDEX


def moisture(prec: np.ndarray, nbr: np.ndarray, river: np.ndarray) -> np.ndarray:
    vals = np.where(nbr >= 0, prec[np.maximum(nbr, 0)], 0.0)
    cnt = (nbr >= 0).sum(1) + 1
    return (vals.sum(1) + prec) / cnt + 4 * river


def categories(h: np.ndarray, land: np.ndarray, temp: np.ndarray, moist: np.ndarray, river: np.ndarray, *,
               hills: float = 44, mountain: float = 67, farmland_share: float = 0.2,
               table=BIOME_TABLE) -> tuple[np.ndarray, np.ndarray]:
    """``(category, suit)`` por celda (``category`` 0 = agua)."""
    n = h.size
    cat = np.full(n, CAT_INDEX["plains"], np.int8)
    for k, row in enumerate(table):
        t_hi = table[k + 1]["t_min"] if k + 1 < len(table) else np.inf
        m = (temp >= row["t_min"]) & (temp < t_hi)
        if not m.any():
            continue
        conds = [moist[m] > thr for thr, _ in row["bands"]]
        choices = [CAT_INDEX[name] for _, name in row["bands"]]
        cat[m] = np.select(conds, choices, CAT_INDEX[row["else"]]) if conds else CAT_INDEX[row["else"]]
    cat[land & (h < 24) & (moist > 40)] = CAT_INDEX["marsh"]
    cat[land & (h >= hills)] = CAT_INDEX["hills"]
    cat[land & (h >= mountain)] = CAT_INDEX["mountain"]
    suit = np.clip((temp + 5) / 30, 0.05, 1) * np.clip(1 - (h - 20) / 80, 0.1, 1) * (1 + 2 * river)
    suit = np.where(cat == CAT_INDEX["desert"], suit * 0.2, suit)
    suit = np.where(cat == CAT_INDEX["arctic"], suit * 0.1, suit)
    if land.any() and farmland_share > 0:
        thr = float(np.quantile(suit[land], 1 - farmland_share))
        farm = land & (suit > thr) & np.isin(cat, [CAT_INDEX["plains"], CAT_INDEX["woods"]])
        cat[farm] = CAT_INDEX["farmlands"]
    cat[~land] = CAT_INDEX["ocean"]
    suit = np.where(land, suit, 0.0)
    return cat, suit
