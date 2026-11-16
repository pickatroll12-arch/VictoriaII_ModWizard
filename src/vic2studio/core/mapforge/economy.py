"""RGO, life rating, población y tabla de presencia de POPs (wizard §18.3, pasos 14–15, y §18.5).

La población es ∝ área × idoneidad, normalizada con ``math.fsum``. La tabla de presencia sustituye a «una POP de
cada tipo»: sin dueño no hay POPs urbanas; con dueño, además burócratas y oficiales; la capital de un país
civilizado, además artesanos de fábrica, oficinistas y capitalistas.
"""

from __future__ import annotations

import math

import numpy as np

from .data.biome_table import GOODS_BY_CATEGORY, LIFE_RATING_TARGET, MINING_GOODS
from .world import CATS, ProvisionalTable


def trade_goods(t: ProvisionalTable, rng: np.random.Generator, available: list[str] | None) -> list:
    allowed = set(available or [])
    out: list = [None] * t.count
    for p in np.flatnonzero(~t.is_sea).tolist():
        options = GOODS_BY_CATEGORY.get(CATS[int(t.dom_cat[p])], ("grain",))
        if allowed:
            options = tuple(g for g in options if g in allowed) or tuple(sorted(allowed))[:1] or ("grain",)
        out[p] = str(options[int(rng.integers(len(options)))])
    return out


def life_rating(t: ProvisionalTable) -> np.ndarray:
    """Cuantiles de idoneidad sobre la distribución objetivo (orden estable, el id desempata)."""
    lr = np.zeros(t.count, np.int64)
    lp = np.flatnonzero(~t.is_sea)
    if lp.size == 0:
        return lr
    target = np.repeat([v for v, _ in LIFE_RATING_TARGET], [w for _, w in LIFE_RATING_TARGET])
    rank = np.argsort(np.argsort(t.suit[lp], kind="stable"), kind="stable") / max(lp.size - 1, 1)
    lr[lp] = target[np.minimum((rank * target.size).astype(int), target.size - 1)]
    return lr


def population(t: ProvisionalTable, total: int) -> np.ndarray:
    w = t.cells.astype(np.float64) * np.maximum(t.suit, 0.02)
    w[t.is_sea] = 0
    tot = math.fsum(w.tolist())
    if tot <= 0:
        return np.zeros(t.count, np.int64)
    return np.array([int(round(x / tot * total)) for x in w.tolist()], np.int64)


def presence(goods: str | None, owned: bool, civilized_capital: bool) -> dict[str, float]:
    """Mezcla de tipos de POP de una provincia de tierra (fracciones de su población)."""
    rural = "labourers" if goods in MINING_GOODS else "farmers"
    mix = {rural: 0.80, "artisans": 0.06, "clergymen": 0.02, "aristocrats": 0.015, "soldiers": 0.025}
    if owned:
        mix.update({"bureaucrats": 0.006, "officers": 0.004})
    if owned and civilized_capital:
        mix.update({"craftsmen": 0.03, "clerks": 0.006, "capitalists": 0.002})
    return mix


URBAN_TYPES = frozenset({"craftsmen", "clerks", "capitalists", "bureaucrats", "officers"})
