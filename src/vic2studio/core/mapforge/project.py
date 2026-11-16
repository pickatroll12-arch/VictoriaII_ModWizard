"""Proyecto del taller (wizard §18.4 y §18.7): ``<mod>/.vic2studio/mapforge/<nombre>/``.

Se guardan **los resultados** de la etapa de celdas, no solo los parámetros: abrir el proyecto no recalcula nada
de esa etapa, así que otro PC con otra CPU ve el mismo mundo. Archivos:

- ``project.json``: parámetros, rejilla, versiones de numpy y Pillow, huellas, nombres y sha256 de lo exportado;
- ``edits.jsonl``: una ``EditOp`` por línea (UTF-8 sin BOM);
- ``cells.pack``: los arrays de la etapa de celdas y de la tabla provisional (cabecera JSON + zlib; no se usa
  ``numpy.save``, porque solo ``core/fileio.py`` y el diario escriben en disco: estos bytes los escribe el
  guardado del ``Workspace``).

El juego no carga ``.vic2studio``; la exportación del mod (§14.1) la excluye.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import PIL

from .edits import EditOp
from .params import ForgeParams
from .world import ForgeWorld, ProvisionalTable, StepState

FOLDER = ".vic2studio/mapforge"
MAGIC = b"VMFP1\n"
CELL_KEYS = ("h", "land", "ocean", "lake", "temp", "prec", "flux", "recv", "river", "category", "suit", "province0")
PROV_KEYS = ("is_sea", "cx", "cy", "cells", "dom_cat", "suit", "temp", "state", "continent", "climate", "owner",
             "culture", "religion", "life_rating", "population", "capitals", "locked")
ENTITY_KEYS = ("owners", "civilized", "cultures", "religions", "province_names", "state_names", "continent_names",
               "climate_names", "names_seed")


def pack_arrays(arrays: dict[str, np.ndarray]) -> bytes:
    header = []
    body = []
    offset = 0
    for name in sorted(arrays):
        a = np.ascontiguousarray(arrays[name])
        raw = a.tobytes()
        header.append({"name": name, "dtype": a.dtype.str, "shape": list(a.shape), "offset": offset,
                       "size": len(raw)})
        body.append(raw)
        offset += len(raw)
    head = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return MAGIC + struct.pack("<I", len(head)) + head + zlib.compress(b"".join(body), 6)


def unpack_arrays(data: bytes) -> dict[str, np.ndarray]:
    if not data.startswith(MAGIC):
        raise ValueError("not a mapforge pack")
    n = struct.unpack("<I", data[len(MAGIC):len(MAGIC) + 4])[0]
    start = len(MAGIC) + 4
    header = json.loads(data[start:start + n].decode("utf-8"))
    body = zlib.decompress(data[start + n:])
    out = {}
    for item in header:
        raw = body[item["offset"]:item["offset"] + item["size"]]
        out[item["name"]] = np.frombuffer(raw, dtype=np.dtype(item["dtype"])).reshape(item["shape"]).copy()
    return out


def environment() -> dict[str, str]:
    return {"numpy": np.__version__, "pillow": PIL.__version__}


@dataclass
class MapForgeProject:
    name: str
    params: ForgeParams
    edits: list = field(default_factory=list)
    exported: dict = field(default_factory=dict)       # rel → sha256 de lo exportado
    env: dict = field(default_factory=environment)
    digests: dict = field(default_factory=dict)

    @property
    def folder(self) -> str:
        return f"{FOLDER}/{self.name}"

    # --- serialización ------------------------------------------------------------------------------------

    def files(self, world: ForgeWorld | None) -> dict[str, bytes]:
        """Los bytes del proyecto (para ``put_bytes`` dentro de una transacción)."""
        meta = {"name": self.name, "params": self.params.to_json(), "env": environment(),
                "digests": self.digests, "exported": self.exported}
        out = {}
        if world is not None and world.cells.h is not None:
            meta["digests"] = {"cells": world.cells_digest(), "world": world.world_digest()}
            meta["steps"] = {k: v.status for k, v in world.steps.items()}
            meta["entities"] = {k: _jsonable(world.entities.get(k)) for k in ENTITY_KEYS if k in world.entities}
            meta["install_digest"] = world.install.source_digest if world.install else ""
            arrays = {f"cell.{k}": getattr(world.cells, k) for k in CELL_KEYS if getattr(world.cells, k) is not None}
            t = world.provisional
            if t is not None:
                arrays.update({f"prov.{k}": np.asarray(getattr(t, k)) for k in PROV_KEYS
                               if getattr(t, k) is not None})
                if t.goods is not None:
                    meta["goods"] = t.goods
            if "pairs" in world.entities:
                arrays["pairs"] = np.asarray(world.entities["pairs"])
            out[f"{self.folder}/cells.pack"] = pack_arrays(arrays)
        out[f"{self.folder}/project.json"] = (json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True)
                                              + "\n").encode("utf-8")
        edits = "".join(json.dumps(e.to_json(), ensure_ascii=False, sort_keys=True) + "\n" for e in self.edits)
        out[f"{self.folder}/edits.jsonl"] = edits.encode("utf-8")
        return out

    def save(self, ws, world: ForgeWorld | None) -> None:
        """Pone los archivos del proyecto en el ``Workspace`` (dentro de la transacción de quien llama)."""
        from ..project.binary import put_bytes

        for rel, data in self.files(world).items():
            put_bytes(ws, rel, data)

    @classmethod
    def load(cls, read, name: str, install=None) -> tuple[MapForgeProject, ForgeWorld | None, list[str]]:
        """Abre un proyecto con ``read(rel) -> bytes | None``. Devuelve el proyecto, el mundo (sin recalcular la
        etapa de celdas) y los avisos (``forge_env_changed``)."""
        from .pipeline import new_world

        folder = f"{FOLDER}/{name}"
        raw = read(f"{folder}/project.json")
        if raw is None:
            raise FileNotFoundError(f"{folder}/project.json")
        meta = json.loads(raw.decode("utf-8"))
        params = ForgeParams.from_json(meta.get("params") or {})
        edits_raw = read(f"{folder}/edits.jsonl") or b""
        edits = [EditOp.from_json(json.loads(line)) for line in edits_raw.decode("utf-8").splitlines()
                 if line.strip()]
        project = cls(name=name, params=params, edits=edits, exported=dict(meta.get("exported") or {}),
                      env=dict(meta.get("env") or {}), digests=dict(meta.get("digests") or {}))
        warnings = []
        if project.env and project.env != environment():
            warnings.append("forge_env_changed")
        pack = read(f"{folder}/cells.pack")
        if pack is None:
            return project, None, warnings
        arrays = unpack_arrays(pack)
        world = new_world(params, install)
        cells = world.cells.evolve(**{k: arrays[f"cell.{k}"] for k in CELL_KEYS if f"cell.{k}" in arrays})
        prov = None
        if "prov.is_sea" in arrays:
            vals = {k: arrays[f"prov.{k}"] for k in PROV_KEYS if f"prov.{k}" in arrays}
            vals["goods"] = meta.get("goods")
            prov = ProvisionalTable(**vals)
        entities = dict(meta.get("entities") or {})
        if "pairs" in arrays:
            entities["pairs"] = arrays["pairs"]
        steps = {k: StepState(v) for k, v in (meta.get("steps") or {}).items()}
        world = world.evolve(cells=cells, provisional=prov, entities=entities, steps=steps, edits=tuple(edits))
        if project.digests.get("cells") and world.cells_digest() != project.digests["cells"]:
            warnings.append("forge_env_changed")
        return project, world, warnings


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def workspace_reader(project) -> callable:
    """``read(rel)`` que prefiere el documento abierto (sin guardar) y si no lee el disco del mod."""
    root = Path(project.mod_root)

    def read(rel: str) -> bytes | None:
        from ..project.codecs import codec_for

        handle = project.ws.peek(rel)
        if handle is not None and not handle.deleted:
            return codec_for(handle.kind).snapshot(handle.model)
        path = root / rel
        try:
            return path.read_bytes()
        except OSError:
            return None

    return read


def list_projects(project) -> list[str]:
    folder = Path(project.mod_root) / FOLDER
    try:
        return sorted(p.name for p in folder.iterdir() if (p / "project.json").is_file())
    except OSError:
        return []


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
