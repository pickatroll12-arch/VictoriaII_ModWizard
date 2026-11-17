"""Importar un «Export to JSON → Full» (o «PackCells») de Azgaar's Fantasy Map Generator (wizard §18.6; 9b).

Se procesa en este orden:

1. **Leer** (``read_fmg_json``): las celdas de ``pack`` con sus polígonos (``v`` → ``vertices[].p``), vecinos
   (``c``), altura (``h``, agua < 20), rasgo (``f``), provincia, estado, cultura y religión; y las listas de
   estados, provincias, culturas, burgos y ríos. Una versión de FMG posterior a la última comprobada da
   ``fmg_version_unknown`` (se importa igual).
2. **Encajar y rasterizar** (``to_import``): escala uniforme rellenando con océano (``fmg_aspect`` si la forma no
   es la del lienzo), cada polígono con ``ImageDraw.polygon`` y la y volteada (fila 0 = sur, el orden del juego).
3. **Agrupar** las celdas en provincias de Victoria II **dentro** de cada provincia de FMG (o de cada rasgo, para la
   tierra sin provincia y para el agua), troceando por el punto más lejano y la celda más cercana, y partiendo cada
   trozo en sus componentes conexas: ninguna provincia del juego cruza una provincia de FMG. El relleno de océano
   va en bloques del tamaño de una provincia de mar.
4. **Construir** (``fmg_to_world``): el mundo de ``bitmaps.build_world`` con los ajustes de FMG: las provincias de
   FMG pasan a ser estados (troceados por encima de ``MAX_STATE`` provincias) y, en «Mundo», los estados de FMG
   pasan a ser países, con su nombre y el de su cultura.

Los ríos no se copian de ``rivers[].cells``: salen de la hidrología del taller sobre la altura importada (ver el
informe de la iteración 9b).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ...cancel import CancelCheck, raise_if_cancelled
from ..validate import ForgeIssue
from ..world import SEA_LEVEL
from ..names import cp1252_name
from .bitmaps import ImportReport, ImportSet

KNOWN_VERSION = (1, 108)          # la última versión de FMG con la que se comprobó la forma del JSON
MAX_STATE = 8                     # provincias por estado como mucho (una provincia de FMG grande se trocea)
ASPECT_TOLERANCE = 0.05


@dataclass
class FmgWorld:
    """Lo que el taller usa de un JSON de FMG (con el norte arriba, en las coordenadas de FMG)."""

    version: str = ""
    width: float = 0.0
    height: float = 0.0
    polys: list = field(default_factory=list)                 # vértices de cada celda
    vertices: np.ndarray | None = None                        # (V, 2)
    centers: np.ndarray | None = None                         # (N, 2)
    neighbors: list = field(default_factory=list)             # celdas vecinas de cada celda
    h: np.ndarray | None = None
    feature: np.ndarray | None = None
    province: np.ndarray | None = None
    state: np.ndarray | None = None
    culture: np.ndarray | None = None
    religion: np.ndarray | None = None
    burg: np.ndarray | None = None
    states: dict = field(default_factory=dict)                # id → entrada de FMG (sin las borradas)
    provinces: dict = field(default_factory=dict)
    cultures: dict = field(default_factory=dict)
    religions: dict = field(default_factory=dict)
    burgs: dict = field(default_factory=dict)
    rivers: list = field(default_factory=list)
    issues: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.polys)


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:2])


def _entries(items) -> dict:
    out = {}
    for item in items or ():
        if isinstance(item, dict) and "i" in item and not item.get("removed"):
            out[int(item["i"])] = item
    return out


def read_fmg_json(source) -> FmgWorld:
    """Lee el JSON (ruta, ``bytes`` o ``str``). Lanza ``ValueError`` si no tiene celdas de ``pack``."""
    if isinstance(source, (bytes, bytearray)):
        obj = json.loads(bytes(source).decode("utf-8"))
    elif isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith("{")):
        obj = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        obj = json.loads(source)
    pack = obj.get("pack") if isinstance(obj.get("pack"), dict) else None
    if pack is None and isinstance(obj.get("cells"), dict):
        pack = obj["cells"]
    if pack is None or not isinstance(pack.get("cells"), list) or not pack["cells"]:
        raise ValueError("FMG JSON without pack cells")
    info = obj.get("info") or {}
    cells = pack["cells"]
    fmg = FmgWorld(version=str(info.get("version") or ""))
    verts = pack.get("vertices") or []
    fmg.vertices = np.array([v.get("p", (0, 0)) if isinstance(v, dict) else (0, 0) for v in verts], np.float64) \
        .reshape(-1, 2)
    n = len(cells)

    def col(key: str, default: int = 0) -> np.ndarray:
        return np.array([int(c.get(key, default) or 0) for c in cells], np.int64)

    fmg.polys = [list(c.get("v") or ()) for c in cells]
    fmg.neighbors = [[int(x) for x in (c.get("c") or ()) if 0 <= int(x) < n] for c in cells]
    fmg.centers = np.array([c.get("p", (0, 0)) for c in cells], np.float64).reshape(-1, 2)
    fmg.h = col("h")
    fmg.feature = col("f")
    fmg.province = col("province")
    fmg.state = col("state")
    fmg.culture = col("culture")
    fmg.religion = col("religion")
    fmg.burg = col("burg")
    fmg.states = _entries(pack.get("states"))
    fmg.provinces = _entries(pack.get("provinces"))
    fmg.cultures = _entries(pack.get("cultures"))
    fmg.religions = _entries(pack.get("religions"))
    fmg.burgs = _entries(pack.get("burgs"))
    fmg.rivers = [r for r in (pack.get("rivers") or ()) if isinstance(r, dict)]
    width = float(info.get("width") or 0)
    height = float(info.get("height") or 0)
    if width <= 0 or height <= 0:
        pts = fmg.vertices if fmg.vertices.size else fmg.centers
        width, height = float(pts[:, 0].max()), float(pts[:, 1].max())
    fmg.width, fmg.height = width, height
    v = version_tuple(fmg.version)
    if not v or v > KNOWN_VERSION:
        fmg.issues.append(ForgeIssue("fmg_version_unknown", {
            "version": fmg.version or "?", "known": ".".join(map(str, KNOWN_VERSION))}))
    return fmg


# --- encaje, rasterizado y agrupación ----------------------------------------------------------------------------

@dataclass
class FmgFit:
    scale: float
    ox: float
    oy: float


def fit(fmg: FmgWorld, W: int, H: int) -> FmgFit:
    s = min(W / fmg.width, H / fmg.height)
    return FmgFit(s, (W - fmg.width * s) / 2.0, (H - fmg.height * s) / 2.0)


def rasterize_cells(fmg: FmgWorld, W: int, H: int, f: FmgFit, cancelled: CancelCheck = None) -> np.ndarray:
    """(H, W) int32 con la celda de FMG de cada píxel (-1 en el relleno de océano), **norte arriba**."""
    img = Image.new("I", (W, H), 0)
    draw = ImageDraw.Draw(img)
    V = fmg.vertices
    for i, poly in enumerate(fmg.polys):
        if i % 4096 == 0:
            raise_if_cancelled(cancelled)
        if len(poly) < 3:
            continue
        pts = [(f.ox + V[k, 0] * f.scale, f.oy + V[k, 1] * f.scale) for k in poly if 0 <= k < len(V)]
        if len(pts) >= 3:
            draw.polygon(pts, fill=i + 1)
    cell = np.asarray(img, np.int64) - 1
    # Huecos dentro del área de FMG (redondeo de los bordes): del vecino de la izquierda o de arriba.
    x0, x1 = int(round(f.ox)), int(round(f.ox + fmg.width * f.scale))
    y0, y1 = int(round(f.oy)), int(round(f.oy + fmg.height * f.scale))
    inside = np.zeros((H, W), bool)
    inside[max(0, y0):min(H, y1), max(0, x0):min(W, x1)] = True
    for _ in range(8):
        gap = inside & (cell < 0)
        if not gap.any():
            break
        left = np.roll(cell, 1, axis=1)
        up = np.roll(cell, 1, axis=0)
        right = np.roll(cell, -1, axis=1)
        down = np.roll(cell, -1, axis=0)
        fill = np.where(left >= 0, left, np.where(up >= 0, up, np.where(right >= 0, right, down)))
        cell = np.where(gap, fill, cell)
    return cell.astype(np.int32)


def _split_group(cells: np.ndarray, centers: np.ndarray, k: int) -> np.ndarray:
    """Etiqueta 0..k-1 de cada celda: semillas por el punto más lejano y cada celda a la semilla más cercana."""
    if k <= 1 or cells.size <= 1:
        return np.zeros(cells.size, np.int64)
    pts = centers[cells]
    mid = pts.mean(0)
    seeds = [int(np.argmin(((pts - mid) ** 2).sum(1)))]
    dist = ((pts - pts[seeds[0]]) ** 2).sum(1)
    for _ in range(1, min(k, cells.size)):
        nxt = int(np.argmax(dist))
        seeds.append(nxt)
        dist = np.minimum(dist, ((pts - pts[nxt]) ** 2).sum(1))
    d = ((pts[:, None, :] - pts[None, seeds, :]) ** 2).sum(2)
    return d.argmin(1).astype(np.int64)


def _components(members: list[int], label: dict[int, int], neighbors: list) -> list[list[int]]:
    """Componentes conexas (por vecinos de FMG) de las celdas con la misma etiqueta."""
    seen: set[int] = set()
    out = []
    for start in members:
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            c = stack.pop()
            comp.append(c)
            for nb in neighbors[c]:
                if nb not in seen and label.get(nb) == label[start]:
                    seen.add(nb)
                    stack.append(nb)
        out.append(comp)
    return out


def group_cells(fmg: FmgWorld, cell_px: np.ndarray, land_target: int, sea_target: int) -> tuple[np.ndarray, list]:
    """Provincia del juego (0..P-1) de cada celda de FMG, y la provincia de FMG (o ``None``) de cada una."""
    n = fmg.count
    land = fmg.h >= SEA_LEVEL
    px = np.bincount(cell_px[cell_px >= 0].ravel(), minlength=n).astype(np.float64)
    land_px = max(1.0, px[land].sum())
    sea_px = max(1.0, px[~land].sum())
    target_land = land_px / max(1, land_target)
    target_sea = sea_px / max(1, sea_target)
    keys: dict[tuple, list[int]] = {}
    for c in range(n):
        if land[c]:
            key = ("p", int(fmg.province[c])) if fmg.province[c] > 0 else ("f", int(fmg.feature[c]))
        else:
            key = ("s", int(fmg.feature[c]))
        keys.setdefault(key, []).append(c)
    out = np.full(n, -1, np.int64)
    fmg_prov: list = []
    for key in sorted(keys):
        members = np.array(keys[key], np.int64)
        area = px[members].sum()
        target = target_sea if key[0] == "s" else target_land
        k = max(1, int(round(area / target)))
        lab = _split_group(members, fmg.centers, k)
        label = {int(c): int(lab_) for c, lab_ in zip(members.tolist(), lab.tolist())}
        for comp in _components(members.tolist(), label, fmg.neighbors):
            if px[comp].sum() <= 0:
                continue
            out[comp] = len(fmg_prov)
            fmg_prov.append(key[1] if key[0] == "p" else None)
    # Celdas sin píxeles (más pequeñas que un píxel): con su vecina más grande.
    for c in np.flatnonzero(out < 0).tolist():
        nbs = [nb for nb in fmg.neighbors[c] if out[nb] >= 0 and land[nb] == land[c]]
        if nbs:
            out[c] = out[max(nbs, key=lambda nb: px[nb])]
    return out, fmg_prov


def _colors(n: int, seed: int = 9) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out: set[int] = set()
    vals = []
    while len(vals) < n:
        for v in rng.integers(1, 0xFFFFFF, size=n * 2).tolist():
            if v not in out and v != 0xFFFFFF:
                out.add(v)
                vals.append(v)
                if len(vals) == n:
                    break
    return np.array(vals, np.int64)


def to_import(fmg: FmgWorld, params, *, cancelled: CancelCheck = None) -> tuple[ImportReport, dict]:
    """El ``ImportReport`` (en el orden del juego) que ``bitmaps.build_world`` sabe construir, y lo que hace falta
    para los ajustes de FMG: ``cell_px`` (celda de FMG por píxel, fila 0 = sur), ``fmg_province`` de cada
    provincia importada y la provincia del juego de cada celda (``group``)."""
    W, H = params.width, params.height
    f = fit(fmg, W, H)
    rep = ImportReport(size=(W, H), flip=False, land_source="fmg")
    rep.issues = list(fmg.issues)
    if abs((fmg.width / fmg.height) / (W / H) - 1.0) > ASPECT_TOLERANCE:
        rep.issues.append(ForgeIssue("fmg_aspect", {"width": int(fmg.width), "height": int(fmg.height),
                                                    "target_width": W, "target_height": H}))
    cell_img = rasterize_cells(fmg, W, H, f, cancelled)
    raise_if_cancelled(cancelled)
    group, fmg_prov = group_cells(fmg, cell_img, params.land_target(), params.sea_target())
    G = len(fmg_prov)
    pid = np.where(cell_img >= 0, group[np.maximum(cell_img, 0)], -1)
    # Relleno de océano: bloques del tamaño de una provincia de mar.
    pad = pid < 0
    if pad.any():
        land_cells = fmg.h >= SEA_LEVEL
        sea_px = max(1, int((~land_cells[cell_img[cell_img >= 0]]).sum()))
        side = max(8, int(np.sqrt(sea_px / max(1, params.sea_target()))))
        yy, xx = np.nonzero(pad)
        block = (yy // side) * ((W + side - 1) // side) + (xx // side)
        ub, inv = np.unique(block, return_inverse=True)
        pid[yy, xx] = G + inv
        fmg_prov = fmg_prov + [None] * ub.size
    # Ninguna provincia en x = 0 y en x = W − 1 a la vez (la costura): se parte por la mitad.
    both = np.intersect1d(np.unique(pid[:, 0]), np.unique(pid[:, W - 1]))
    for p in both.tolist():
        right = (pid == p) & (np.arange(W)[None, :] >= W // 2)
        pid[right] = len(fmg_prov)
        fmg_prov.append(fmg_prov[p])
    # Índices compactos, y la y al orden del juego.
    used, pid = np.unique(pid, return_inverse=True)
    pid = pid.reshape(H, W).astype(np.int32)[::-1].copy()
    cell_px = cell_img[::-1].copy()
    fmg_prov = [fmg_prov[int(u)] for u in used]
    remap = np.full(max(G, int(used.max()) + 1), -1, np.int64)
    remap[used] = np.arange(used.size)
    group = np.where(group >= 0, remap[np.maximum(group, 0)], -1)
    P = int(used.size)
    rep.pid = pid
    rep.colors = _colors(P)
    rep.pixels = np.bincount(pid.ravel(), minlength=P)
    rep.def_ids = np.full(P, -1, np.int64)
    rep.def_names = [""] * P
    # Agua por provincia: la mayoría de sus píxeles.
    water_px = np.where(cell_px >= 0, fmg.h[np.maximum(cell_px, 0)] < SEA_LEVEL, True)
    rep.water = np.bincount(pid.ravel(), weights=water_px.ravel(), minlength=P) / np.maximum(rep.pixels, 1)
    rep.sea = rep.water >= 0.5
    heights = np.where(cell_px >= 0, fmg.h[np.maximum(cell_px, 0)], 5).astype(np.float64)
    rep.heights = np.where(rep.sea[pid], np.minimum(heights, SEA_LEVEL - 1), np.maximum(heights, SEA_LEVEL + 1))
    from ..reconcile import raster_edges

    pe = raster_edges((pid + 1).astype(np.int32), True)
    pe = pe[(pe[:, 0] > 0) & (pe[:, 1] > 0)] - 1 if pe.size else np.zeros((0, 2), np.int64)
    rep.pairs = np.unique(np.sort(pe, 1), axis=0) if pe.size else np.zeros((0, 2), np.int64)
    rep.matrix = {"provinces": "file:fmg", "land_sea": "file:fmg", "relief": "file:fmg", "terrain": "generated",
                  "rivers": "generated", "positions": "generated", "definition": "generated",
                  "states": "file:fmg", "continents": "generated", "climates": "generated",
                  "owners": "file:fmg" if params.level.value == "world" else "generated", "economy": "generated",
                  "names": "file:fmg"}
    extra = {"cell_px": cell_px, "fmg_province": fmg_prov, "group": group}
    return rep, extra


# --- construcción -------------------------------------------------------------------------------------------

def _state_split(provs: list[int], pairs: np.ndarray, limit: int) -> list[list[int]]:
    """Trocea una provincia de FMG (sus provincias del juego) en estados de ``limit`` como mucho, en el orden de un
    recorrido en anchura por la vecindad: trozos casi siempre contiguos."""
    if len(provs) <= limit:
        return [provs]
    inside = set(provs)
    adj: dict[int, list[int]] = {p: [] for p in provs}
    for a, b in pairs.tolist():
        if a in inside and b in inside:
            adj[a].append(b)
            adj[b].append(a)
    order, seen = [], set()
    for start in provs:
        if start in seen:
            continue
        queue = [start]
        seen.add(start)
        while queue:
            p = queue.pop(0)
            order.append(p)
            for q in sorted(adj[p]):
                if q not in seen:
                    seen.add(q)
                    queue.append(q)
    return [order[i:i + limit] for i in range(0, len(order), limit)]


def fmg_to_world(fmg: FmgWorld, params, install=None, *, progress=None, cancelled: CancelCheck = None,
                 with_textures: bool = True):
    """El ``ForgeWorld`` de un JSON de FMG (ver el docstring del módulo) y su ``ImportReport``."""
    from ..params import Level
    from . import bitmaps

    if params.level is Level.WORLD:
        n_states = len([s for s in fmg.states if s > 0 and (fmg.state[fmg.h >= SEA_LEVEL] == s).any()])
        params = params.with_(countries=max(1, n_states))
    rep, extra = to_import(fmg, params, cancelled=cancelled)

    def adjust(world):
        return _apply_fmg(world, fmg, rep, extra)

    world = bitmaps.build_world(ImportSet(), rep, params, install, progress=progress, cancelled=cancelled,
                                with_textures=with_textures, adjust=adjust)
    return world, rep


def _apply_fmg(world, fmg: FmgWorld, rep: ImportReport, extra: dict):
    """Estados desde las provincias de FMG y, en «Mundo», países desde los estados de FMG (en la tabla provisional,
    antes del ráster: la tabla tiene una fila por provincia importada, en el orden de ``final_order``)."""
    from ..nations import _adjective, _unique_keys, assign_tags
    from ..names import key_name
    from ..params import Level
    from .bitmaps import final_order

    t = world.provisional
    final = final_order(rep)                         # índice importado → id final
    P = rep.count
    row_of = final - 1                               # índice importado → fila de la tabla
    fmg_prov = extra["fmg_province"]
    ent = dict(world.entities)
    # Estados: provincias del juego agrupadas por provincia de FMG (o por rasgo, sin provincia).
    pairs = ent.get("pairs")
    pairs = pairs if pairs is not None else np.zeros((0, 2), np.int64)
    by_key: dict = {}
    land_rows = [int(row_of[i]) for i in range(P) if not rep.sea[i]]
    key_of_row = {int(row_of[i]): fmg_prov[i] for i in range(P)}
    for r in land_rows:
        by_key.setdefault(key_of_row[r] if key_of_row[r] is not None else ("free", r), []).append(r)
    state = np.full(t.count, -1, np.int64)
    names = []
    for key in sorted(by_key, key=lambda k: (isinstance(k, tuple), k if not isinstance(k, tuple) else k[1])):
        provs = sorted(by_key[key])
        base = cp1252_name(fmg.provinces.get(key, {}).get("name")) if not isinstance(key, tuple) else None
        for j, part in enumerate(_state_split(provs, pairs, MAX_STATE)):
            state[part] = len(names)
            names.append(base if base and j == 0 else (f"{base} {j + 1}" if base else None))
    old_names = ent.get("state_names") or []
    ent["state_names"] = [n or (old_names[i] if i < len(old_names) else f"State {i + 1}")
                          for i, n in enumerate(names)]
    t = t.evolve(state=state)
    if world.params.level is Level.WORLD and ent.get("world"):
        t, ent = _fmg_countries(world, fmg, rep, extra, t, ent, row_of)
        data = ent["world"]
        countries = data["countries"]
        taken = {x.tag for x in (world.install.tags if world.install else [])}
        tags = assign_tags([c["name"] for c in countries], taken)
        ent["world"] = dict(data, countries=[dict(c, tag=tag) for c, tag in zip(countries, tags)])
        ent["owners"] = tags
        cultures = data["cultures"]
        keys = _unique_keys([key_name(c["name"]) for c in cultures],
                            reserved={g["key"] for g in data["groups"]})
        ent["world"]["cultures"] = [dict(c, key=k) for c, k in zip(cultures, keys)]
        ent["world"]["countries"] = [dict(c, culture=k, adjective=_adjective(c["name"]))
                                     for c, k in zip(ent["world"]["countries"], keys)]
        ent["cultures"] = keys
    return world.evolve(provisional=t, entities=ent)


def _fmg_countries(world, fmg: FmgWorld, rep: ImportReport, extra: dict, t, ent, row_of):
    """Dueño de cada provincia = el estado de FMG con más celdas en ella; capital = la del burgo capital del estado
    (o su provincia mayor). Los nombres de país y de cultura son los de FMG."""
    group = extra["group"]
    P = rep.count
    land = fmg.h >= SEA_LEVEL
    order = sorted(s for s in fmg.states if s > 0 and (fmg.state[land] == s).any())
    order = order[:len(ent["world"]["countries"])]
    index_of = {s: i for i, s in enumerate(order)}
    votes = np.zeros((P, len(order) + 1), np.int64)
    for c in np.flatnonzero(land & (group >= 0)).tolist():
        votes[group[c], index_of.get(int(fmg.state[c]), len(order))] += 1
    owner = np.full(t.count, -1, np.int64)
    for i in range(P):
        if rep.sea[i] or votes[i].sum() == 0:
            continue
        best = int(votes[i, :len(order)].argmax()) if votes[i, :len(order)].any() else -1
        owner[int(row_of[i])] = best
    # Tierra sin estado en FMG: el país vecino más común (o el primero).
    pairs = ent.get("pairs")
    for _ in range(4):
        free = np.flatnonzero((owner < 0) & ~t.is_sea)
        if not free.size or pairs is None or not len(pairs):
            break
        for r in free.tolist():
            nb = [owner[b] for a, b in pairs.tolist() if a == r and owner[b] >= 0] + \
                 [owner[a] for a, b in pairs.tolist() if b == r and owner[a] >= 0]
            if nb:
                owner[r] = max(set(nb), key=nb.count)
    owner[(owner < 0) & ~t.is_sea] = 0
    n = len(order)
    capitals = np.zeros(n, np.int64)
    sizes = np.bincount(owner[owner >= 0], weights=t.cells[owner >= 0], minlength=n)
    for i, s in enumerate(order):
        burg = fmg.burgs.get(int(fmg.states[s].get("capital") or 0), {})
        cell = int(burg.get("cell", -1)) if burg else -1
        row = int(row_of[group[cell]]) if 0 <= cell < fmg.count and group[cell] >= 0 else -1
        if row < 0 or owner[row] != i:
            mine = np.flatnonzero(owner == i)
            row = int(mine[np.argmax(t.cells[mine])]) if mine.size else -1
        capitals[i] = max(row, 0)
    data = ent["world"]
    countries = [dict(c) for c in data["countries"][:n]]
    cultures = [dict(c) for c in data["cultures"][:n]]
    civ_order = np.argsort(-sizes, kind="stable")
    k_civ = sum(1 for c in data["countries"] if c["civilized"])
    for i, s in enumerate(order):
        name = cp1252_name(fmg.states[s].get("name"), countries[i]["name"])
        countries[i]["name"] = name
        countries[i]["civilized"] = bool(i in civ_order[:k_civ].tolist())
        cul = fmg.cultures.get(int(fmg.states[s].get("culture") or 0), {})
        cultures[i]["name"] = cp1252_name(cul.get("name"), cultures[i]["name"])
    ent["world"] = dict(data, countries=countries, cultures=cultures)
    ent["civilized"] = [c["civilized"] for c in countries]
    rel = np.asarray(t.religion) if t.religion is not None else np.zeros(t.count, np.int64)
    rel_of_country = [int(rel[capitals[i]]) if capitals[i] < rel.size and rel[capitals[i]] >= 0 else 0
                      for i in range(n)]
    religion = np.where(owner >= 0, np.array(rel_of_country + [0], np.int64)[np.maximum(owner, 0)], -1)
    t = t.evolve(owner=owner, culture=np.where(owner >= 0, owner, -1), religion=religion, capitals=capitals)
    return t, ent


__all__ = ["FmgWorld", "read_fmg_json", "to_import", "fmg_to_world", "rasterize_cells", "group_cells",
           "KNOWN_VERSION", "MAX_STATE"]
