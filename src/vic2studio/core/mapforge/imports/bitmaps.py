"""Importar bitmaps del juego al taller (wizard §18.6): provincias ya dibujadas y los recursos que falten.

Ranuras (``SLOTS``): ``provinces`` (BMP de 24 bits o PNG RGB), ``definition`` (``definition.csv``),
``default_map`` (``sea_starts``), ``terrain`` y ``rivers`` (8 bits con paleta; un RGB se convierte con la paleta de
la instalación), ``heightmap`` (gris de 8 o 16 bits, cualquier tamaño), ``mask`` (PNG de dos colores: claro =
tierra) y ``positions`` (``positions.txt``, para detectar la orientación y conservarla).

Orientación: un ``.bmp`` está en el orden del juego (fila 0 = ``y`` 0, como lo lee ``read_bmp``) y el resto (PNG,
JPG) con el norte arriba. Con ``positions.txt`` y ``definition.csv`` se comprueba: si los puntos ``unit`` caen mejor
en la imagen volteada, se avisa (``forge_orientation_suspect``) y se voltea.

``inspect`` lee, valida y deja todo en el orden del juego (``ImportReport``); ``build_world`` construye un
``ForgeWorld`` cuyas provincias son las del bitmap: la etapa de celdas calcula clima, ríos y biomas sobre la rejilla
y los agrega por provincia importada; estados, continentes, climas, dueños, economía y nombres salen del grafo de
provincias. El ráster no se reconcilia (las provincias ya son las finales).

Tierra/mar, por prioridad: ``sea_starts`` › mayoría de agua (254/255) en ``terrain.bmp`` › mayoría de 254 en
``rivers.bmp`` › altura < 20 › máscara. Ambigua: entre el 30 y el 70 % de agua, o menos de 50 px con mezcla.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from ...cancel import CancelCheck, raise_if_cancelled
from ..validate import ForgeIssue
from ..world import CAT_INDEX, CATS, SEA_LEVEL, InstallProfile
from . import heightmap as hm

SLOTS = ("provinces", "definition", "default_map", "terrain", "rivers", "heightmap", "mask", "positions")
VANILLA_SIZE = (5616, 2160)
TINY_PX = 6
AMBIGUOUS = (0.3, 0.7)
AMBIGUOUS_SMALL_PX = 50
TERRAIN_WATER = (254, 255)
RIVERS_WATER = 254
RIVERS_LAND = 255
RESERVED = {0x000000: "0,0,0", 0xFFFFFF: "255,255,255"}
LAND_SOURCES = ("sea_starts", "terrain", "rivers", "heightmap", "mask")


@dataclass
class ImportSet:
    """Archivos por ranura (ruta o bytes). ``flip_y`` fuerza la orientación (None: por extensión y posiciones)."""

    files: dict = field(default_factory=dict)
    flip_y: bool | None = None
    land_source: str | None = None

    def data(self, slot: str) -> bytes | None:
        v = self.files.get(slot)
        if v is None:
            return None
        if isinstance(v, (bytes, bytearray)):
            return bytes(v)
        try:
            return Path(v).read_bytes()
        except OSError:
            return None

    def name(self, slot: str) -> str:
        v = self.files.get(slot)
        if isinstance(v, (str, Path)):
            return Path(v).name
        return {"provinces": "provinces.bmp", "definition": "definition.csv", "default_map": "default.map",
                "terrain": "terrain.bmp", "rivers": "rivers.bmp", "heightmap": "heightmap.png",
                "mask": "mask.png", "positions": "positions.txt"}.get(slot, slot)

    def is_bmp(self, slot: str) -> bool:
        data = self.data(slot)
        return bool(data) and data[:2] == b"BM"


@dataclass
class ImportReport:
    """Lo que ``inspect`` sabe de una importación, todo en el orden del juego."""

    issues: list = field(default_factory=list)
    size: tuple = (0, 0)
    flip: bool = False
    pid: np.ndarray | None = None            # (H, W) int32: índice de color por píxel (0..P-1)
    colors: np.ndarray | None = None         # (P,) int64: color 0xRRGGBB de cada índice
    pixels: np.ndarray | None = None         # (P,) int64: píxeles de cada índice
    def_ids: np.ndarray | None = None        # (P,) int64: id de definition.csv (-1 sin fila)
    def_names: list | None = None
    water: np.ndarray | None = None          # (P,) float64: parte de agua
    sea: np.ndarray | None = None            # (P,) bool
    land_source: str | None = None
    pairs: np.ndarray | None = None          # (k, 2) índices vecinos (a < b)
    terrain: np.ndarray | None = None        # (H, W) uint8
    rivers: np.ndarray | None = None
    heights: np.ndarray | None = None        # (H, W) float64 0–100 (ya al tamaño del mapa)
    positions: bytes | None = None
    matrix: dict = field(default_factory=dict)
    seconds: dict = field(default_factory=dict)

    @property
    def count(self) -> int:
        return 0 if self.colors is None else int(self.colors.size)

    @property
    def errors(self) -> list:
        from ...clausewitz import Severity

        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def ok(self) -> bool:
        return not self.errors


# --- lectura de imágenes --------------------------------------------------------------------------------------

def _rgb(files: ImportSet, slot: str, report: ImportReport) -> np.ndarray | None:
    """RGB en el orden de la imagen tal como se lee (BMP: orden del juego; otros: norte arriba)."""
    data = files.data(slot)
    if data is None:
        return None
    if data[:2] == b"BM":
        from ...map.bmp import BmpError, read_bmp

        try:
            img = read_bmp(data)
            if img.bits == 24:
                return img.pixels
        except BmpError:
            pass
        pil = Image.open(io.BytesIO(data))
        report.issues.append(ForgeIssue("forge_not_24bit", {"file": files.name(slot), "mode": pil.mode},
                                        "map/provinces.bmp"))
        return np.asarray(pil.convert("RGB"), np.uint8)
    pil = Image.open(io.BytesIO(data))
    if pil.mode != "RGB":
        report.issues.append(ForgeIssue("forge_not_24bit", {"file": files.name(slot), "mode": pil.mode},
                                        "map/provinces.bmp"))
    return np.asarray(pil.convert("RGB"), np.uint8)


def _indexed(files: ImportSet, slot: str, palette: bytes | None, code: str, report: ImportReport) -> np.ndarray | None:
    """Índices de 8 bits; un RGB se convierte con la paleta de la instalación (el color exacto o el más cercano)."""
    data = files.data(slot)
    if data is None:
        return None
    if data[:2] == b"BM":
        from ...map.bmp import BmpError, read_bmp

        try:
            img = read_bmp(data)
            if img.bits == 8:
                return img.pixels
            mode, rgb = "RGB", img.pixels
        except BmpError:
            pil = Image.open(io.BytesIO(data))
            mode, rgb = pil.mode, np.asarray(pil.convert("RGB"), np.uint8)
    else:
        pil = Image.open(io.BytesIO(data))
        if pil.mode == "P":
            return np.asarray(pil, np.uint8)
        mode, rgb = pil.mode, np.asarray(pil.convert("RGB"), np.uint8)
    rel = f"map/{slot}.bmp"
    report.issues.append(ForgeIssue(code, {"file": files.name(slot), "mode": mode}, rel))
    return to_palette(rgb, palette)


def to_palette(rgb: np.ndarray, palette: bytes | None) -> np.ndarray:
    """RGB → índices de ``palette`` (768 bytes): exacto si está; si no, el más cercano (distancia al cuadrado)."""
    pal = np.frombuffer(palette or bytes(768), np.uint8).reshape(-1, 3).astype(np.int64)
    keys = (rgb[..., 0].astype(np.int64) << 16) | (rgb[..., 1].astype(np.int64) << 8) | rgb[..., 2]
    u, inv = np.unique(keys.ravel(), return_inverse=True)
    ur = np.column_stack([(u >> 16) & 255, (u >> 8) & 255, u & 255])
    best = np.empty(u.size, np.uint8)
    for i in range(0, u.size, 4096):
        d = ((ur[i:i + 4096, None, :] - pal[None, :, :]) ** 2).sum(2)
        best[i:i + 4096] = d.argmin(1)
    return best[inv].reshape(keys.shape)


# --- inspección --------------------------------------------------------------------------------------------------

def inspect(files: ImportSet, install: InstallProfile | None = None, *, progress=None,
            cancelled: CancelCheck = None) -> ImportReport:
    """Lee y valida los archivos (códigos de §18.11) y lo deja todo en el orden del juego."""
    from ..install import synthetic_profile

    install = install or synthetic_profile()
    rep = ImportReport()
    t0 = time.perf_counter()
    rgb = _rgb(files, "provinces", rep)
    if rgb is None:
        _matrix(files, rep)
        return rep
    H, W = rgb.shape[:2]
    rep.size = (W, H)
    if (W, H) != VANILLA_SIZE:
        rep.issues.append(ForgeIssue("forge_size", {"width": W, "height": H}))
    raise_if_cancelled(cancelled)
    # Censo de colores: np.unique sobre los colores más una LUT densa.
    keys = (rgb[..., 0].astype(np.int64) << 16) | (rgb[..., 1].astype(np.int64) << 8) | rgb[..., 2]
    colors = np.unique(keys)
    lut = np.zeros(1 << 24, np.int32)
    lut[colors] = np.arange(colors.size, dtype=np.int32)
    pid = lut[keys]
    del lut, keys
    rep.colors, rep.pixels = colors, np.bincount(pid.ravel(), minlength=colors.size)
    rep.seconds["census"] = round(time.perf_counter() - t0, 3)
    # Definición: id por color.
    rep.def_ids = np.full(colors.size, -1, np.int64)
    rep.def_names = [""] * colors.size
    def_data = files.data("definition")
    if def_data is not None:
        from ...map.definition import DefinitionTable

        table, _ = DefinitionTable.parse(def_data)
        pos = {int(c): i for i, c in enumerate(colors.tolist())}
        for row in table.rows():
            if row.id is None or row.rgb is None:
                continue
            k = (int(row.rgb[0]) << 16) | (int(row.rgb[1]) << 8) | int(row.rgb[2])
            i = pos.get(k)
            if i is not None and rep.def_ids[i] < 0:
                rep.def_ids[i] = row.id
                rep.def_names[i] = row.name
    # Orientación.
    flip = files.flip_y
    if flip is None:
        flip = not files.is_bmp("provinces")
        score = _orientation(files, pid, rep.def_ids)
        if score is not None:
            as_is, flipped = score
            if flipped > as_is:
                rep.issues.append(ForgeIssue("forge_orientation_suspect",
                                             {"file": files.name("provinces"), "score": round(100 * as_is, 1)},
                                             "map/provinces.bmp"))
                flip = not flip
    rep.flip = bool(flip)
    extra = rep.flip != (not files.is_bmp("provinces"))   # la detección volteó el conjunto entero
    if rep.flip:
        pid = np.ascontiguousarray(pid[::-1])
    rep.pid = pid
    raise_if_cancelled(cancelled)
    # Colores reservados y provincias diminutas.
    reserved = [c for c in RESERVED if c in set(colors.tolist())]
    if reserved:
        rep.issues.append(ForgeIssue("forge_color_reserved", {"count": len(reserved), "color": RESERVED[reserved[0]]},
                                     "map/provinces.bmp", len(reserved)))
    tiny = np.flatnonzero(rep.pixels < TINY_PX)
    if tiny.size:
        rep.issues.append(ForgeIssue("forge_tiny_province", {"count": int(tiny.size), "px": TINY_PX},
                                     "map/provinces.bmp", int(tiny.size)))
    # Vecinos, aisladas y costura.
    from ..reconcile import raster_edges

    pe = raster_edges((pid + 1).astype(np.int32), True)
    pe = pe[(pe[:, 0] > 0) & (pe[:, 1] > 0)] - 1 if pe.size else np.zeros((0, 2), np.int64)
    rep.pairs = np.unique(np.sort(pe, 1), axis=0) if pe.size else np.zeros((0, 2), np.int64)
    if colors.size > 1:
        deg = np.bincount(rep.pairs.ravel(), minlength=colors.size)
        lonely = np.flatnonzero(deg == 0)
        if lonely.size:
            first = int(rep.def_ids[lonely[0]]) if rep.def_ids[lonely[0]] >= 0 else int(lonely[0]) + 1
            rep.issues.append(ForgeIssue("province_isolated", {"count": int(lonely.size), "first": first},
                                         "map/provinces.bmp", int(lonely.size)))
    seam = np.intersect1d(np.unique(pid[:, 0]), np.unique(pid[:, -1]))
    if seam.size:
        rep.issues.append(ForgeIssue("forge_seam_province", {"count": int(seam.size)}, "map/provinces.bmp",
                                     int(seam.size)))
    rep.seconds["graph"] = round(time.perf_counter() - t0, 3)
    raise_if_cancelled(cancelled)
    # Terreno, ríos, altura y máscara (en el orden del juego: se voltean como las provincias).
    rep.terrain = _oriented(_indexed(files, "terrain", install.terrain_palette, "terrain_not_indexed", rep), files,
                            "terrain", extra)
    rep.rivers = _oriented(_indexed(files, "rivers", install.rivers_palette, "rivers_not_indexed", rep), files,
                           "rivers", extra)
    for slot in ("terrain", "rivers"):
        arr = getattr(rep, slot)
        if arr is not None and arr.shape != (H, W):
            setattr(rep, slot, None)
            rep.issues.append(ForgeIssue("heightmap_size", {"width": arr.shape[1], "height": arr.shape[0],
                                                            "expected_width": W, "expected_height": H},
                                         f"map/{slot}.bmp"))
    hdata = files.data("heightmap")
    if hdata is not None:
        gray, _ = hm.load_gray(hdata)
        gray = _oriented(gray, files, "heightmap", extra)
        if gray.shape != (H, W):
            rep.issues.append(ForgeIssue("heightmap_size", {"width": gray.shape[1], "height": gray.shape[0],
                                                            "expected_width": W, "expected_height": H}))
        rep.heights = hm.resample(hm.to_heights(np.ascontiguousarray(gray)), W, H)
    _land_sea(files, rep, install)
    if rep.terrain is not None:
        _check_terrain(rep, install)
    if rep.rivers is not None:
        _check_rivers(rep)
    rep.positions = files.data("positions")
    _matrix(files, rep)
    rep.seconds["total"] = round(time.perf_counter() - t0, 3)
    return rep


def _oriented(arr, files: ImportSet, slot: str, extra: bool):
    """Al orden del juego: un BMP ya viene así y el resto con el norte arriba. ``extra``: la detección por
    posiciones volteó las provincias, y con ellas todo el conjunto."""
    if arr is None:
        return None
    if not files.is_bmp(slot):
        arr = arr[::-1]
    if extra:
        arr = arr[::-1]
    return np.ascontiguousarray(arr)


def _orientation(files: ImportSet, pid: np.ndarray, def_ids: np.ndarray) -> tuple[float, float] | None:
    """Parte de puntos ``unit`` que caen en su provincia tal cual y volteando (None sin posiciones o sin ids)."""
    data = files.data("positions")
    if data is None or not (def_ids >= 0).any():
        return None
    from ...map.positions import unit_points

    pts = unit_points(data)
    H, W = pid.shape
    idx_of = {int(d): i for i, d in enumerate(def_ids.tolist()) if d >= 0}
    xs, ys, want = [], [], []
    for p, pt in pts.items():
        i = idx_of.get(int(p))
        if i is None:
            continue
        x, y = int(pt.x), int(pt.y)
        if 0 <= x < W and 0 <= y < H:
            xs.append(x)
            ys.append(y)
            want.append(i)
    if not want:
        return None
    xs, ys, want = np.array(xs), np.array(ys), np.array(want)
    # ``pid`` está en el orden de lectura: un PNG con el norte arriba hay que voltearlo para estar en el del juego.
    base = pid if files.is_bmp("provinces") else pid[::-1]
    as_is = float((base[ys, xs] == want).mean())
    flipped = float((base[::-1][ys, xs] == want).mean())
    return as_is, flipped


def _land_sea(files: ImportSet, rep: ImportReport, install: InstallProfile) -> None:
    P = rep.count
    pid = rep.pid
    sources: dict[str, np.ndarray] = {}
    dm = files.data("default_map")
    if dm is not None and (rep.def_ids >= 0).any():
        from ...map.default_map import DefaultMap
        from ...project.codecs import parse_bytes

        starts = set(DefaultMap(parse_bytes(dm).document).sea_starts())
        if starts:
            sources["sea_starts"] = np.array([float(d in starts) for d in rep.def_ids.tolist()])
    px_sources: dict[str, np.ndarray] = {}
    if rep.terrain is not None:
        px_sources["terrain"] = np.isin(rep.terrain, TERRAIN_WATER)
    if rep.rivers is not None:
        px_sources["rivers"] = rep.rivers == RIVERS_WATER
    if rep.heights is not None:
        px_sources["heightmap"] = rep.heights < SEA_LEVEL
    mdata = files.data("mask")
    if mdata is not None:
        g, _ = hm.load_gray(mdata)
        g = _oriented(g, files, "mask", rep.flip != (not files.is_bmp("provinces")))
        if g.shape == pid.shape:
            px_sources["mask"] = g < (32768 if g.dtype == np.uint16 else 128)
    for name, water_px in px_sources.items():
        sources[name] = np.bincount(pid.ravel(), weights=water_px.ravel(), minlength=P) / np.maximum(rep.pixels, 1)
    choice = files.land_source if files.land_source in sources else next(
        (s for s in LAND_SOURCES if s in sources), None)
    if choice is None:
        rep.issues.append(ForgeIssue("forge_land_sea_unknown", {}))
        rep.water = np.zeros(P)
        rep.sea = np.zeros(P, bool)
        return
    rep.land_source = choice
    rep.sea = sources[choice] > 0.5
    # La ambigüedad se mide con el primer recurso por píxeles (sea_starts no dice cuánta agua hay).
    share_src = next((s for s in LAND_SOURCES[1:] if s in sources), None)
    rep.water = sources[share_src] if share_src else sources[choice]
    if share_src:
        w = rep.water
        amb = ((w >= AMBIGUOUS[0]) & (w <= AMBIGUOUS[1])) | ((rep.pixels < AMBIGUOUS_SMALL_PX) & (w > 0) & (w < 1))
        if amb.any():
            rep.issues.append(ForgeIssue("forge_land_sea_ambiguous", {"count": int(amb.sum())},
                                         "map/provinces.bmp", int(amb.sum())))


def _check_terrain(rep: ImportReport, install: InstallProfile) -> None:
    known = set(install.cat_of) | set(TERRAIN_WATER)
    used = np.bincount(rep.terrain.ravel(), minlength=256)
    bad = [i for i in np.flatnonzero(used).tolist() if i not in known]
    if bad:
        n = int(used[bad].sum())
        rep.issues.append(ForgeIssue("terrain_index_invalid", {"count": n, "first": bad[0]}, "map/terrain.bmp", n))


def _check_rivers(rep: ImportReport) -> None:
    r = rep.rivers
    river = r < RIVERS_WATER
    if not river.any():
        return
    # Diagonales: dos píxeles de río en diagonal sin ningún píxel de río en las dos esquinas que los unirían.
    a, b, c, d = river[:-1, :-1], river[:-1, 1:], river[1:, :-1], river[1:, 1:]
    diag = int(((a & d & ~b & ~c) | (b & c & ~a & ~d)).sum())
    if diag:
        rep.issues.append(ForgeIssue("rivers_diagonal", {"count": diag}, "map/rivers.bmp", diag))
    if rep.sea is not None:
        wet = int((river & rep.sea[rep.pid]).sum())
        if wet:
            rep.issues.append(ForgeIssue("rivers_in_water", {"count": wet}, "map/rivers.bmp", wet))
    from ..reconcile import run_components

    comp, _, _ = run_components(river.astype(np.int32), wrap_x=False)
    rc = comp[river]
    total = np.unique(rc)
    with_source = np.unique(comp[r == 0])
    missing = int(np.setdiff1d(total, with_source).size)
    if missing:
        rep.issues.append(ForgeIssue("river_source_missing", {"count": missing}, "map/rivers.bmp", missing))


def _matrix(files: ImportSet, rep: ImportReport) -> None:
    """«Lo que falta se reconstruye»: de dónde sale cada paso (``file``, ``rule`` o ``generated``)."""
    has = {s: files.files.get(s) is not None for s in SLOTS}
    m = {
        "provinces": "file" if has["provinces"] else "generated",
        "land_sea": f"file:{rep.land_source}" if rep.land_source else ("generated" if not has["provinces"] else
                                                                          "missing"),
        "relief": "file" if has["heightmap"] else ("rule" if has["terrain"] else "generated"),
        "terrain": "file" if has["terrain"] else "generated",
        "rivers": "file" if has["rivers"] else "generated",
        "positions": "file" if has["positions"] else "generated",
        "definition": "file" if has["definition"] else "generated",
    }
    for step in ("states", "continents", "climates", "owners", "economy", "names"):
        m[step] = "generated"
    rep.matrix = m


# --- construcción del mundo -------------------------------------------------------------------------------------

def final_order(rep: ImportReport) -> np.ndarray:
    """Id final (1..N, tierra primero) de cada índice importado. Si ``definition.csv`` ya numera la tierra primero
    y sin huecos, se conservan sus ids (ida y vuelta con lo que exporta el taller)."""
    P = rep.count
    sea = rep.sea if rep.sea is not None else np.zeros(P, bool)
    d = rep.def_ids
    land_i, sea_i = np.flatnonzero(~sea), np.flatnonzero(sea)
    if (d >= 0).all():
        ld, sd = np.sort(d[land_i]), np.sort(d[sea_i])
        if np.array_equal(ld, np.arange(1, land_i.size + 1)) and \
                np.array_equal(sd, np.arange(land_i.size + 1, P + 1)):
            return d.astype(np.int64)
    key = np.where(d >= 0, d, (1 << 40) + np.arange(P))
    order = np.concatenate([land_i[np.argsort(key[land_i], kind="stable")],
                            sea_i[np.argsort(key[sea_i], kind="stable")]])
    out = np.empty(P, np.int64)
    out[order] = np.arange(1, P + 1)
    return out


def build_world(files: ImportSet, rep: ImportReport, params, install: InstallProfile | None = None, *,
                progress=None, cancelled: CancelCheck = None, with_textures: bool = True):
    """El ``ForgeWorld`` de una importación con provincias: rejilla y etapa de celdas sobre la altura importada (o el
    pseudorrelieve), provincias del bitmap y ráster sin reconciliar."""
    from .. import pipeline, reconcile
    from ..world import ProvisionalTable

    if rep.pid is None or rep.sea is None:
        raise ValueError("import without provinces or land/sea")
    W, H = rep.size
    final = final_order(rep)
    P = rep.count
    sea_f = np.zeros(P + 1, bool)
    sea_f[final] = rep.sea
    NL = int((~rep.sea).sum())
    params = params.with_(size=(W, H), land_provinces=max(1, NL), sea_provinces=max(0, P - NL))
    world = pipeline.new_world(params, install)
    c = world.cells
    lut = final.astype(np.uint16)
    ids_px = lut[rep.pid]                                        # (H, W) ids finales
    pix_sea = sea_f[ids_px]
    # Celda → provincia por el píxel de su punto; la tierra/mar de la celda es la de su provincia.
    cx = np.clip(c.pts[:, 0].astype(np.int64), 0, W - 1)
    cy = np.clip(c.pts[:, 1].astype(np.int64), 0, H - 1)
    cell_id = ids_px[cy, cx].astype(np.int64)
    cell_land = ~sea_f[cell_id]
    pcat_px = None
    if rep.terrain is not None:
        cat_lut = np.zeros(256, np.int8)
        for i, name in world.install.cat_of.items():
            if name in CAT_INDEX:
                cat_lut[i] = CAT_INDEX[name]
        pcat_px = cat_lut[rep.terrain]
        pcat_px[pix_sea] = 0
        pcat_px[~pix_sea & (pcat_px == 0)] = CAT_INDEX["plains"]
    if rep.heights is not None:
        hp = rep.heights.astype(np.float32)
        hp = np.where(pix_sea, np.minimum(hp, SEA_LEVEL - 1), np.maximum(hp, SEA_LEVEL + 1)).astype(np.float32)
    elif pcat_px is not None:
        hp = hm.pseudo_relief(pcat_px, pix_sea).astype(np.float32)
    else:
        hp = np.where(pix_sea, 10.0, 30.0).astype(np.float32)
    h = hp[cy, cx].astype(np.float64)
    h = np.where(cell_land, np.maximum(h, SEA_LEVEL), np.minimum(h, SEA_LEVEL - 1))
    world = world.evolve(cells=c.evolve(h=h, land=cell_land, ocean=~cell_land, lake=np.zeros(h.size, bool)))
    world = pipeline.run_cells(world, from_step="climate", until="biomes", progress=progress, cancelled=cancelled)
    c = world.cells
    cat = c.category
    if pcat_px is not None:
        cat = np.where(cell_land, pcat_px[cy, cx], 0).astype(cat.dtype)
    # Tabla de provincias: una fila por provincia importada (índice = id final - 1).
    prov0 = cell_id - 1
    yy, xx = np.indices((H, W))
    flat = ids_px.ravel().astype(np.int64) - 1
    px = np.bincount(flat, minlength=P).astype(np.float64)
    pcx = np.bincount(flat, weights=xx.ravel(), minlength=P) / np.maximum(px, 1)
    pcy = np.bincount(flat, weights=yy.ravel(), minlength=P) / np.maximum(px, 1)
    del yy, xx
    ncell = np.bincount(prov0, minlength=P)
    kc = np.bincount(prov0 * len(CATS) + cat.astype(np.int64), minlength=P * len(CATS)).reshape(P, len(CATS))
    if pcat_px is not None:
        kc = np.bincount(flat * len(CATS) + pcat_px.ravel().astype(np.int64),
                         minlength=P * len(CATS)).reshape(P, len(CATS))
    kc[:, 0] = np.where(sea_f[1:], kc[:, 0], 0)
    dom = kc.argmax(1).astype(np.int8)
    dom[~sea_f[1:] & (dom == 0)] = CAT_INDEX["plains"]
    dom[sea_f[1:]] = 0
    # Provincias sin celda: la celda más cercana a su centroide.
    suit = np.bincount(prov0, weights=c.suit, minlength=P) / np.maximum(ncell, 1)
    temp = np.bincount(prov0, weights=c.temp, minlength=P) / np.maximum(ncell, 1)
    empty = np.flatnonzero(ncell == 0)
    if empty.size:
        near = _nearest_cell(c.pts, pcx[empty], pcy[empty], W)
        suit[empty] = c.suit[near]
        temp[empty] = c.temp[near]
    t = ProvisionalTable(is_sea=sea_f[1:].copy(), cx=pcx, cy=pcy, cells=np.maximum(ncell, 1), dom_cat=dom,
                         suit=suit, temp=temp, locked=np.zeros(P, bool))
    pairs = rep.pairs
    pairs = np.unique(np.sort(final[pairs] - 1, 1), axis=0) if pairs.size else pairs
    ent = dict(world.entities)
    ent["pairs"] = pairs
    world = world.evolve(cells=c.evolve(category=cat, province0=prov0), provisional=t, entities=ent)
    world = pipeline.run_cells(world, from_step="states", progress=progress, cancelled=cancelled)
    # Nombres de definition.csv cuando los hay.
    names_p = list(world.entities.get("province_names") or [])
    for i, nm in enumerate(rep.def_names or []):
        if nm and nm.strip().lower() not in ("x", "") and i < P:
            names_p[int(final[i]) - 1] = nm.strip()
    ent = dict(world.entities)
    ent["province_names"] = names_p
    world = world.evolve(entities=ent, imported={**world.imported, "bitmaps": rep.matrix})
    # Ráster: los ids ya son los finales; la madre de cada id es su propia fila.
    t = world.provisional
    report: dict = {"import": {"flip": rep.flip, "land_source": rep.land_source, "seconds": rep.seconds}}
    times: dict = {}

    def tick(name: str, i: int):
        raise_if_cancelled(cancelled)
        if progress:
            progress(name, i, len(pipeline.RASTER_STEPS))
        times[name] = time.perf_counter()

    tick("raster", 0)
    par = np.arange(-1, P, dtype=np.int64)
    areas = np.bincount(ids_px.ravel(), minlength=P + 1)
    prov = {"state": t.state, "continent": t.continent, "climate": t.climate, "owner": t.owner,
            "culture": t.culture, "religion": t.religion, "life_rating": t.life_rating, "population": t.population,
            "goods": t.goods}
    attrs, rrep = reconcile.reconcile_attributes(par, NL, P, prov, areas,
                                                 t.capitals if t.capitals is not None else np.zeros(0, np.int64))
    report["reconcile"] = rrep
    colors = np.zeros(P + 1, np.int64)
    colors[final] = rep.colors
    names = [None] + names_p
    from ..rasterize import nearest_cells

    cell_r = nearest_cells(world.lattice, W, H, cell_class=world.cells.land, pix_class=~pix_sea, warp=None,
                           cancelled=cancelled)
    positions = None
    if rep.positions is not None:
        positions = _kept_positions(rep.positions, final, rep.def_ids)
    return pipeline.finish_raster(world, ids=ids_px, is_sea=sea_f, NL=NL, par=par, attrs=attrs, names=names,
                                  colors=colors, cell_r=cell_r, hp=hp, scale=1, report=report, tick=tick,
                                  times=times, cancelled=cancelled, with_textures=with_textures, pcat=pcat_px,
                                  terrain=rep.terrain, rivers=rep.rivers, positions=positions)


def _nearest_cell(pts: np.ndarray, x: np.ndarray, y: np.ndarray, W: float) -> np.ndarray:
    """La celda más cercana a cada punto (por bloques; solo para las provincias más pequeñas que una celda)."""
    out = np.empty(x.size, np.int64)
    for i in range(0, x.size, 256):
        dx = np.abs(pts[None, :, 0] - x[i:i + 256, None])
        dx = np.minimum(dx, W - dx)
        d = dx * dx + (pts[None, :, 1] - y[i:i + 256, None]) ** 2
        out[i:i + 256] = d.argmin(1)
    return out


def _kept_positions(data: bytes, final: np.ndarray, def_ids: np.ndarray):
    """``positions.txt`` importado se conserva solo si los ids no cambian (si no, se generan de nuevo)."""
    if not np.array_equal(final, def_ids):
        return None
    return {"__text__": data}


__all__ = ["SLOTS", "ImportSet", "ImportReport", "inspect", "build_world", "final_order", "to_palette"]
