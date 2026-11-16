"""Fragmentos, ids y reconciliación (wizard §18.3, pasos 19–21).

- ``fix_fragments``: una pasada de etiquetado por tramos **sin envoltura** (un trozo al otro lado de la costura es
  un fragmento). Un trozo menor se funde con el vecino principal de su clase; si no tiene, un islote de menos de
  ``islet_px`` cambia de clase y uno mayor pasa a ser una provincia hija.
- ``compact_ids``: tierra 1..L y mar L+1..N, ``max_provinces`` = N+1.
- ``reconcile_attributes``: cada provincia final hereda los atributos de su provisional madre; una capital que
  desaparece pasa a la mayor provincia del país; un estado vacío se elimina.
"""

from __future__ import annotations

import numpy as np

from .graph import components


def raster_edges(ids: np.ndarray, wrap_x: bool = True) -> np.ndarray:
    """Pares de etiquetas distintas en píxeles vecinos (4-conexión), únicos, (E, 2) con a < b."""
    parts = []
    a, b = ids[:, :-1].ravel(), ids[:, 1:].ravel()
    m = a != b
    parts.append(np.column_stack([a[m], b[m]]))
    a, b = ids[:-1, :].ravel(), ids[1:, :].ravel()
    m = a != b
    parts.append(np.column_stack([a[m], b[m]]))
    if wrap_x:
        a, b = ids[:, -1], ids[:, 0]
        m = a != b
        parts.append(np.column_stack([a[m], b[m]]))
    e = np.concatenate(parts).astype(np.int64)
    if e.size == 0:
        return np.zeros((0, 2), np.int64)
    e = np.sort(e, axis=1)
    base = int(ids.max()) + 1
    key = np.unique(e[:, 0] * base + e[:, 1])
    return np.column_stack(np.divmod(key, base))


def run_components(ids: np.ndarray, wrap_x: bool = True):
    """Componente 4-conexa por píxel por tramos y unión-búsqueda vectorizada: ``(comp, label_of_run, run_comp)``."""
    H, W = ids.shape
    flat = ids.ravel()
    brk = np.flatnonzero(np.diff(flat)) + 1
    rowb = np.arange(1, H) * W
    starts = np.union1d(np.concatenate([[0], brk]), rowb)
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
        first = row_off[:-1]
        last = row_off[1:] - 1
        m = (L[first] == L[last]) & (first != last)
        pairs.append(np.column_stack([first[m], last[m]]))
    P = np.concatenate(pairs) if pairs else np.zeros((0, 2), np.int64)
    lab = components(S.size, P.astype(np.int64))
    _, lab = np.unique(lab, return_inverse=True)
    return np.repeat(lab, lens).reshape(H, W), L, lab


def fix_fragments(pid: np.ndarray, is_sea: np.ndarray, *, wrap_x: bool = False, islet_px: int = 40):
    """``(pid, merged, flipped, created, is_sea)``: una sola componente por provincia."""
    comp, L, runlab = run_components(pid, wrap_x)
    ncomp = int(comp.max()) + 1
    cprov = np.zeros(ncomp, np.int64)
    cprov[runlab] = L
    size = np.bincount(comp.ravel(), minlength=ncomp)
    order = np.lexsort((np.arange(ncomp), -size, cprov))
    main = np.zeros(ncomp, bool)
    first = np.ones(order.size, bool)
    first[1:] = cprov[order][1:] != cprov[order][:-1]
    main[order[first]] = True
    is_sea = np.asarray(is_sea, bool)
    if main.all():
        return pid, 0, 0, 0, is_sea
    e = raster_edges(comp, wrap_x)
    e = np.concatenate([e, e[:, ::-1]])
    frag = np.nonzero(~main)[0]
    adj: dict[int, list[int]] = {}
    sel = e[np.isin(e[:, 0], frag)]
    sel = sel[np.lexsort((sel[:, 1], sel[:, 0]))]
    for a, b in sel.tolist():
        adj.setdefault(a, []).append(b)
    newprov = cprov.copy()
    resolved = main.copy()
    merged = flipped = created = 0
    nextid = int(pid.max()) + 1
    pending = sorted(frag.tolist(), key=lambda c: (-int(size[c]), c))
    sea_list = list(is_sea.tolist())
    for _round in range(10):
        left = []
        for c in pending:
            same = [b for b in adj.get(c, []) if resolved[b] and sea_list[newprov[b]] == sea_list[cprov[c]]]
            if same:
                newprov[c] = newprov[same[0]]
                resolved[c] = True
                merged += 1
            else:
                left.append(c)
        if len(left) == len(pending):
            break
        pending = left
    for c in pending:
        anyn = [b for b in adj.get(c, []) if resolved[b]]
        if size[c] < islet_px and anyn:
            newprov[c] = newprov[anyn[0]]
            flipped += 1
        else:
            newprov[c] = nextid
            sea_list.append(sea_list[cprov[c]])
            nextid += 1
            created += 1
        resolved[c] = True
    return newprov[comp].astype(pid.dtype), merged, flipped, created, np.asarray(sea_list, bool)


def parents_of_created(pid: np.ndarray, pid0: np.ndarray, p0: int, n_total: int) -> np.ndarray:
    """Madre (1-based, provisional + 1) de cada etiqueta; las creadas por ``fix`` toman la mayoritaria."""
    parent = np.arange(n_total)
    newm = pid > p0
    if newm.any():
        k = pid[newm].astype(np.int64) * (p0 + 1) + pid0[newm]
        uk, uc = np.unique(k, return_counts=True)
        a, b = np.divmod(uk, p0 + 1)
        o = np.lexsort((b, -uc, a))
        f = np.ones(o.size, bool)
        f[1:] = a[o][1:] != a[o][:-1]
        parent[a[o][f]] = b[o][f]
    return parent


def compact_ids(pid: np.ndarray, is_sea: np.ndarray) -> tuple[np.ndarray, np.ndarray, int, int]:
    """``(ids uint16, remap, L, N)``: tierra 1..L y mar L+1..N, en el orden de las etiquetas."""
    cnt = np.bincount(pid.ravel(), minlength=is_sea.size)
    present = np.flatnonzero(cnt[1:] > 0) + 1
    land_ids = present[~is_sea[present]]
    sea_ids = present[is_sea[present]]
    remap = np.zeros(is_sea.size, np.int64)
    remap[land_ids] = np.arange(1, land_ids.size + 1)
    remap[sea_ids] = np.arange(land_ids.size + 1, present.size + 1)
    return remap[pid].astype(np.uint16), remap, int(land_ids.size), int(present.size)


def reconcile_attributes(par: np.ndarray, nl: int, n: int, prov: dict, areas: np.ndarray,
                         capitals0: np.ndarray) -> tuple[dict, dict]:
    """Atributos por id final desde la madre provisional. ``prov`` trae arrays por provisional (o listas).

    Devuelve los atributos finales y el informe (hijas, desaparecidas, capitales reasignadas, huecos)."""
    out: dict = {}
    land = slice(1, nl + 1)
    pl = par[land]
    for key, arr in prov.items():
        if isinstance(arr, list):
            vals: list = [None] * (n + 1)
            for i, p in enumerate(pl.tolist(), start=1):
                vals[i] = arr[p]
            out[key] = vals
        else:
            a = np.asarray(arr)
            fill = 0 if a.dtype.kind in "iu" and key in ("life_rating", "population") else -1
            res = np.full(n + 1, fill, a.dtype if a.dtype.kind in "iuf" else np.int64)
            res[land] = a[pl]
            out[key] = res
    p0 = int(max(par.max(), 0)) + 1 if par.size else 0
    dup = np.bincount(pl, minlength=max(p0, 1)) if pl.size else np.zeros(1, np.int64)
    owner = out.get("owner")
    caps: list[int] = []
    reassigned = 0
    for k, c in enumerate(capitals0.tolist()):
        kids = np.flatnonzero(pl == c) + 1
        if kids.size:
            caps.append(int(kids[np.argmax(areas[kids])]))
        else:
            mine = np.flatnonzero(owner[land] == k) + 1 if owner is not None else np.zeros(0, np.int64)
            caps.append(int(mine[np.argmax(areas[mine])]) if mine.size else -1)
            reassigned += 1
    # Población de las hijas: la de la madre repartida por área.
    if "population" in out:
        pop = out["population"].astype(np.float64)
        share = np.zeros(n + 1)
        tot_area = np.bincount(pl, weights=areas[land], minlength=dup.size)
        share[land] = areas[land] / np.maximum(tot_area[pl], 1)
        out["population"] = np.round(pop * share).astype(np.int64)
    # Estados compactados (un estado vacío desaparece).
    if "state" in out:
        st = out["state"]
        m = st[land] >= 0
        u, inv = np.unique(st[land][m], return_inverse=True)
        st2 = st.copy()
        idx = np.flatnonzero(m) + 1
        st2[idx] = inv
        out["state"] = st2
    report = {"children": int((dup > 1).sum()), "capitals_reassigned": reassigned,
              "land_without_state": int((out["state"][land] < 0).sum()) if "state" in out else 0}
    out["capitals"] = caps
    return out, report
