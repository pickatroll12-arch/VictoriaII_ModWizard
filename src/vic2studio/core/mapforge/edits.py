"""Ediciones manuales del taller (wizard §18.4): ``EditOp`` y su reaplicación después de su paso.

- Independientes de la rejilla (coordenadas normalizadas 0–1 del juego): ``relief_stroke`` {tool: raise | lower |
  smooth | flatten, pts_norm, r_norm, strength} y ``landsea_stroke`` {pts_norm, r_norm, to: land | sea}.
- Ligadas a la rejilla (``lattice_sha`` de la ``LatticeSpec`` vigente): ``paint_category`` {cells, cat},
  ``river_cells`` {cells, on}, ``lock`` {cell} y ``set_owner`` {cells, owner}. Si la rejilla cambia, pasan a
  ``forge_edit_conflict``.
- De entidades por uid: ``rename`` {uid, name} (``p:<celda>`` provincia que contiene esa celda, ``s:<celda>`` su
  estado).

Al regenerar un paso se reaplican sus ediciones; las que ya no aplican se listan en ``conflicts``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from .world import CAT_INDEX, SEA_LEVEL, ForgeWorld

STEP_OF_KIND = {"relief_stroke": "relief", "landsea_stroke": "relief", "river_cells": "hydro",
                "paint_category": "biomes", "lock": "provinces", "set_owner": "owners", "rename": "names"}
GRID_BOUND = {"paint_category", "river_cells", "lock", "set_owner"}


@dataclass(frozen=True)
class EditOp:
    step: str
    kind: str
    payload: Mapping = field(default_factory=dict)
    uid: str = ""

    def to_json(self) -> dict:
        return {"step": self.step, "kind": self.kind, "payload": dict(self.payload), "uid": self.uid}

    @classmethod
    def from_json(cls, data: dict) -> EditOp:
        return cls(str(data["step"]), str(data["kind"]), dict(data.get("payload") or {}), str(data.get("uid", "")))


@dataclass(frozen=True)
class EditConflict:
    edit: EditOp
    reason: str            # lattice_changed | out_of_range | unknown_kind


def make(kind: str, payload: Mapping, *, uid: str | None = None) -> EditOp:
    step = STEP_OF_KIND[kind]
    if uid is None:
        uid = hashlib.sha256(repr((kind, sorted(payload.items()))).encode()).hexdigest()[:12]
    return EditOp(step, kind, dict(payload), uid)


def lattice_sha(world: ForgeWorld) -> str:
    spec = world.params.lattice_spec()
    return hashlib.sha256(repr((spec.cells, spec.seed, spec.kind, spec.jitter, spec.wrap_x,
                                world.params.size)).encode()).hexdigest()[:12]


def edits_for(world: ForgeWorld, step: str) -> list[EditOp]:
    return [e for e in world.edits if e.step == step]


def _valid(world: ForgeWorld, e: EditOp) -> bool:
    if e.kind in GRID_BOUND and e.payload.get("lattice_sha") not in (None, lattice_sha(world)):
        return False
    return True


def conflicts(world: ForgeWorld) -> list[EditConflict]:
    out = []
    n = world.lattice.n
    for e in world.edits:
        if e.kind not in STEP_OF_KIND:
            out.append(EditConflict(e, "unknown_kind"))
        elif not _valid(world, e):
            out.append(EditConflict(e, "lattice_changed"))
        elif e.kind in GRID_BOUND:
            cells = e.payload.get("cells", [e.payload.get("cell")])
            if any(c is None or not 0 <= int(c) < n for c in cells):
                out.append(EditConflict(e, "out_of_range"))
    return out


def _disc_cells(world: ForgeWorld, pts_norm, r_norm: float) -> np.ndarray:
    """Celdas a distancia ≤ r de la polilínea del trazo (normalizado; x envuelve)."""
    W, H = world.lattice.W, world.lattice.H
    pts = world.cells.pts
    r = float(r_norm) * W
    hit = np.zeros(pts.shape[0], bool)
    for x, y in pts_norm:
        dx = np.abs(pts[:, 0] - float(x) * W)
        dx = np.minimum(dx, W - dx)
        dy = pts[:, 1] - float(y) * H
        hit |= dx * dx + dy * dy <= r * r
    return hit


def apply_relief_edits(world: ForgeWorld, h: np.ndarray) -> np.ndarray:
    h = h.copy()
    nbr = world.cells.nbr
    for e in edits_for(world, "relief"):
        hit = _disc_cells(world, e.payload.get("pts_norm", ()), e.payload.get("r_norm", 0.02))
        if not hit.any():
            continue
        if e.kind == "landsea_stroke":
            h[hit] = SEA_LEVEL + 3 if e.payload.get("to") == "land" else SEA_LEVEL - 3
            continue
        tool = e.payload.get("tool", "raise")
        s = float(e.payload.get("strength", 10))
        if tool == "raise":
            h[hit] += s
        elif tool == "lower":
            h[hit] -= s
        elif tool == "flatten":
            h[hit] = float(np.mean(h[hit]))
        elif tool == "smooth":
            vals = np.where(nbr[hit] >= 0, h[np.maximum(nbr[hit], 0)], 0)
            cnt = (nbr[hit] >= 0).sum(1) + 1
            h[hit] = (vals.sum(1) + h[hit]) / cnt
        np.clip(h, 0, 100, out=h)
    return h


def _cells_of(e: EditOp) -> np.ndarray:
    return np.asarray([int(c) for c in e.payload.get("cells", ())], np.int64)


def apply_river_edits(world: ForgeWorld, river: np.ndarray) -> np.ndarray:
    river = river.copy()
    land = world.cells.land
    for e in edits_for(world, "hydro"):
        if not _valid(world, e):
            continue
        cells = _cells_of(e)
        cells = cells[(cells >= 0) & (cells < river.size)]
        river[cells] = bool(e.payload.get("on", False)) & land[cells]
    return river


def apply_category_edits(world: ForgeWorld, cat: np.ndarray) -> np.ndarray:
    cat = cat.copy()
    land = world.cells.land
    for e in edits_for(world, "biomes"):
        if not _valid(world, e):
            continue
        k = CAT_INDEX.get(str(e.payload.get("cat")))
        if not k:
            continue
        cells = _cells_of(e)
        cells = cells[(cells >= 0) & (cells < cat.size)]
        cat[cells[land[cells]]] = k
    return cat


def apply_locks(world: ForgeWorld, locked: np.ndarray, prov0: np.ndarray) -> np.ndarray:
    locked = locked.copy()
    for e in edits_for(world, "provinces"):
        if e.kind != "lock" or not _valid(world, e):
            continue
        cell = int(e.payload.get("cell", -1))
        if 0 <= cell < prov0.size:
            locked[prov0[cell]] = bool(e.payload.get("on", True))
    return locked


def apply_owner_edits(world: ForgeWorld, owner: np.ndarray, owners: list) -> np.ndarray:
    owner = owner.copy()
    prov0 = world.cells.province0
    sea = world.provisional.is_sea
    for e in edits_for(world, "owners"):
        if e.kind != "set_owner" or not _valid(world, e):
            continue
        tag = e.payload.get("owner")
        k = owners.index(tag) if tag in owners else -1
        cells = _cells_of(e)
        cells = cells[(cells >= 0) & (cells < prov0.size)]
        provs = np.unique(prov0[cells])
        provs = provs[~sea[provs]]
        owner[provs] = k
    return owner


def apply_name_edits(world: ForgeWorld) -> ForgeWorld:
    prov0 = world.cells.province0
    t = world.provisional
    ent = world.entities
    pn = list(ent.get("province_names") or [])
    sn = list(ent.get("state_names") or [])
    for e in edits_for(world, "names"):
        uid = str(e.payload.get("uid", ""))
        name = str(e.payload.get("name", "")).strip()
        if not name or ":" not in uid:
            continue
        kind, _, cell = uid.partition(":")
        try:
            c = int(cell)
        except ValueError:
            continue
        if not 0 <= c < prov0.size:
            continue
        p = int(prov0[c])
        if kind == "p" and p < len(pn):
            pn[p] = name
        elif kind == "s" and t.state is not None and t.state[p] >= 0 and t.state[p] < len(sn):
            sn[int(t.state[p])] = name
    ent = dict(ent)
    ent["province_names"] = pn
    ent["state_names"] = sn
    return world.evolve(entities=ent)


def apply_pixel_terrain(world: ForgeWorld, pcat: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """Anulaciones de terreno por píxel (reservado: en la 9a el pincel de categoría actúa por celdas)."""
    return pcat


def add(world: ForgeWorld, edit: EditOp) -> ForgeWorld:
    """El mundo con ``edit`` añadida (sustituye a otra con el mismo uid)."""
    rest = tuple(e for e in world.edits if e.uid != edit.uid)
    return world.evolve(edits=rest + (edit,))


def remove(world: ForgeWorld, uid: str) -> ForgeWorld:
    return world.evolve(edits=tuple(e for e in world.edits if e.uid != uid))
