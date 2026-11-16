# Port of Azgaar's Fantasy Map Generator src/modules/states-generator.ts y cultures-generator.ts (expand) (MIT,
# © Max Haniyeu)
"""Dueños, culturas y religiones de Solo mapa (wizard §18.1 y §18.3, pasos 12–13).

«Repartir entre TAG existentes»: los K TAG con más provincias en la instalación efectiva reciben una capital nueva
(centros por idoneidad con separación W/40, ÷1,2 si no caben, como FMG) y se expanden por el grafo de provincias
más los cruces de una celda de mar, con coste por terreno y un tope de colonización. Las provincias sin dueño toman
la cultura y la religión del TAG más cercano (la misma expansión sin tope). «Mapa base» no tiene dueños: todas las
POPs usan la cultura y la religión más frecuentes de la instalación.
"""

from __future__ import annotations

import heapq

import numpy as np

from .data.biome_table import EXPANSION_COST
from .graph import wrap_dx
from .partition import expansion_cost
from .params import Owners
from .world import ProvisionalTable, TagInfo


def adjacency(t: ProvisionalTable, pairs: np.ndarray, prov0: np.ndarray, nbr: np.ndarray,
              land: np.ndarray) -> list[list[int]]:
    """Vecinos de tierra de cada provincia provisional, más los cruces por una celda de mar."""
    P0 = t.count
    adj: list[list[int]] = [[] for _ in range(P0)]
    landp = ~t.is_sea
    if pairs.size:
        for a, b in pairs[landp[pairs[:, 0]] & landp[pairs[:, 1]]].tolist():
            adj[a].append(b)
            adj[b].append(a)
    sea_c = np.flatnonzero(~land)
    if sea_c.size:
        nb = nbr[sea_c]
        ok = (nb >= 0) & land[np.maximum(nb, 0)]
        nbp = np.where(ok, prov0[np.maximum(nb, 0)], -1)
        cross = set()
        for i in range(nb.shape[1]):
            for j in range(i + 1, nb.shape[1]):
                a_, b_ = nbp[:, i], nbp[:, j]
                mm = (a_ >= 0) & (b_ >= 0) & (a_ != b_)
                if mm.any():
                    cross.update(map(tuple, np.column_stack([np.minimum(a_[mm], b_[mm]),
                                                             np.maximum(a_[mm], b_[mm])]).tolist()))
        for a, b in sorted(cross):
            if b not in adj[a]:
                adj[a].append(b)
                adj[b].append(a)
    return adj


def expand(t: ProvisionalTable, adj: list[list[int]], n_centers: int, rng: np.random.Generator, mindist: float,
           W: float, *, limit_frac: float = 1.0, centers: list[int] | None = None) -> tuple[list[int], np.ndarray]:
    """Centros (o los dados) y dueño por provincia provisional (-1 sin dueño)."""
    P0 = t.count
    landp = ~t.is_sea
    lp = np.flatnonzero(landp)
    pcost = expansion_cost(t, EXPANSION_COST)
    jit = 1.0 + rng.random(P0) * 0.2
    if centers is None:
        order = lp[np.argsort(-(t.suit[lp] * rng.uniform(0.6, 1.0, lp.size)), kind="stable")]
        centers = []
        cxl, cyl = t.cx.tolist(), t.cy.tolist()
        taken: set[int] = set()
        while len(centers) < min(n_centers, lp.size) and mindist > 1:
            for p in order.tolist():
                if p in taken:
                    continue
                if all(min(abs(cxl[p] - cxl[q]), W - abs(cxl[p] - cxl[q])) ** 2 + (cyl[p] - cyl[q]) ** 2
                       > mindist ** 2 for q in centers):
                    centers.append(p)
                    taken.add(p)
                if len(centers) == n_centers:
                    break
            mindist /= 1.2
    owner = np.full(P0, -1, np.int64)
    dist = np.full(P0, np.inf)
    hq = [(0.0, k, p) for k, p in enumerate(centers)]
    for _, k, p in hq:
        dist[p] = 0
        owner[p] = k
    heapq.heapify(hq)
    budget = limit_frac * lp.size
    count = len(centers)
    landl = landp.tolist()
    while hq:
        d, k, p = heapq.heappop(hq)
        if d > dist[p]:
            continue
        for q in adj[p]:
            if not landl[q]:
                continue
            nd = d + pcost[q] * jit[q]
            if nd < dist[q] and (owner[q] >= 0 or count < budget):
                if owner[q] < 0:
                    count += 1
                dist[q] = nd
                owner[q] = k
                heapq.heappush(hq, (nd, k, q))
    return list(centers), owner


def owners_for_map(t: ProvisionalTable, adj: list[list[int]], tags: list[TagInfo], *, mode: Owners, k: int,
                   colonized: float, W: float, rng: np.random.Generator,
                   top_culture: str, top_religion: str) -> dict:
    """Dueños y culturas de Solo mapa. Devuelve ``owner``/``capitals`` (índices en ``owners``), ``culture`` y
    ``religion`` (índices en ``cultures``/``religions``) y las listas de nombres."""
    P0 = t.count
    landp = ~t.is_sea
    use = tags[:max(0, k)] if mode is Owners.EXISTING_TAGS else []
    if not use or not landp.any():
        cultures, religions = [top_culture], [top_religion]
        culture = np.where(landp, 0, -1)
        religion = np.where(landp, 0, -1)
        return {"owner": np.full(P0, -1, np.int64), "capitals": np.zeros(0, np.int64), "owners": [],
                "culture": culture, "religion": religion, "cultures": cultures, "religions": religions}
    centers, owner = expand(t, adj, len(use), rng, W / 40, W, limit_frac=colonized)
    use = use[:len(centers)]
    _, nearest = expand(t, adj, len(centers), rng, W / 40, W, centers=centers)
    cultures: list[str] = []
    religions: list[str] = []
    cidx = []
    ridx = []
    for info in use:
        c = info.culture or top_culture
        r = info.religion or top_religion
        if c not in cultures:
            cultures.append(c)
        if r not in religions:
            religions.append(r)
        cidx.append(cultures.index(c))
        ridx.append(religions.index(r))
    cidx_a = np.array(cidx, np.int64)
    ridx_a = np.array(ridx, np.int64)
    src = np.where(owner >= 0, owner, nearest)
    # Una provincia inalcanzable (isla sin cruce corto): el centro más cercano.
    lost = landp & (src < 0)
    if lost.any():
        cent = np.array(centers)
        for p in np.flatnonzero(lost).tolist():
            dx = wrap_dx(t.cx[cent], t.cx[p], W)
            src[p] = int(np.argmin(dx * dx + (t.cy[cent] - t.cy[p]) ** 2))
    culture = np.where(landp, cidx_a[np.maximum(src, 0)], -1)
    religion = np.where(landp, ridx_a[np.maximum(src, 0)], -1)
    owner[~landp] = -1
    return {"owner": owner, "capitals": np.array(centers, np.int64), "owners": [u.tag for u in use],
            "civilized": [u.civilized for u in use], "culture": culture, "religion": religion,
            "cultures": cultures, "religions": religions}
