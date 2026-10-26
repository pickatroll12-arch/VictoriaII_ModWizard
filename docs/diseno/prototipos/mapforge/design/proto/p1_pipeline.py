"""p1: pipeline completo del taller (mapa + mundo) en numpy/Pillow, por fases medidas.

Reutiliza las funciones del prototipo de r2-azgaar (forge.py) para rejilla, relieve, ríos y ráster,
y añade lo que el diseño necesita medir:
  - agrupación de provincias SOBRE EL GRAFO DE CELDAS (independiente de la resolución) y comparación
    vista previa (W/4) frente a render final;
  - compactación de ids (tierra antes que mar), colores, posiciones completas, vecinos y estrechos;
  - terrain.bmp por píxel y dominancia por provincia; colormap/colormap_water/no_shadow/political y minimapa (DDS propio);
  - estados, continentes, climas, países, culturas, religiones, POPs, RGO y life rating;
  - textos de todos los archivos en memoria y escritura con fsync (simula el diario);
  - banderas TGA 93×64 de 32 bits (5 variantes por país);
  - determinismo (sha256 de las salidas con la misma semilla).
Uso: python3 -I p1_pipeline.py W H N SEED OUTDIR [--write] [--terrain-txt RUTA]
"""
from __future__ import annotations

import hashlib
import heapq
import io
import json
import math
import os
import re
import resource
import struct
import sys
import time
import tracemalloc
import zlib

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "r2-azgaar", "proto"))
import forge as F  # noqa: E402

W, H, N, SEED = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
OUT = sys.argv[5]
WRITE = "--write" in sys.argv
TERRAIN_TXT = sys.argv[sys.argv.index("--terrain-txt") + 1] if "--terrain-txt" in sys.argv else None
os.makedirs(OUT, exist_ok=True)
TRACE = "--trace" in sys.argv
if TRACE:
    tracemalloc.start()
T: dict[str, tuple[float, float]] = {}
R: dict[str, object] = {"W": W, "H": H, "N": N, "seed": SEED}
HASH: dict[str, str] = {}


class phase:
    def __init__(self, name): self.name = name
    def __enter__(self):
        if TRACE:
            tracemalloc.reset_peak()
        self.t = time.perf_counter()
    def __exit__(self, *a):
        T[self.name] = (round(time.perf_counter() - self.t, 3), round(tracemalloc.get_traced_memory()[1] / 2**20, 1) if TRACE else None)


def rng_for(step: str) -> np.random.Generator:
    """Un generador por paso: regenerar un paso no cambia los demás (FMG reinicia Alea en cada paso)."""
    return np.random.default_rng([SEED, zlib.crc32(step.encode())])


def sha(a) -> str:
    return hashlib.sha256(a if isinstance(a, (bytes, bytearray)) else np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


# ============================================================ 1. grafo de celdas (resolución independiente)
with phase("01_lattice_neighbors"):
    lat = F.make_lattice(W, H, N, "hex", 0.3, True, SEED)
    nbr = F.implicit_neighbors(lat, "hex6")
    edges = F.edges_from_padded(nbr)
n = lat.n
# coordenadas normalizadas (0-1) para que todo lo que dependa de posiciones sea igual a cualquier escala
U = lat.pts / np.array([W, H])

TEMPLATE = """Hill 1 80-85 60-80 40-60
Hill 1 80-85 20-30 40-60
Hill 6-7 15-30 25-75 15-85
Multiply 0.6 land 0 0
Hill 8-10 5-10 15-85 20-80
Range 1-2 30-60 5-15 25-75
Range 1-2 30-60 80-95 25-75
Range 0-3 30-60 80-90 20-80
Smooth 3 0 0 0
Trough 3-4 15-20 15-85 20-80
Trough 3-4 5-10 45-55 45-55
Pit 3-4 10-20 15-85 20-80
Mask 4 0 0 0"""
with phase("02_relief_template13_sealevel"):
    hm = F.Heightmap(lat, nbr, rng_for("heightmap"))
    hm.run_template(TEMPLATE)
    q = np.quantile(hm.h, 1 - 0.34)
    h = np.clip(hm.h + (F.SEA_LEVEL - q) - 0.5, 0, 100)
# pincel de relieve entre pasos (edición manual): subir un círculo de radio 0,03 en (0,5, 0,5)
with phase("02b_brush_raise_cells"):
    d = np.hypot((U[:, 0] - 0.5) * (W / H), U[:, 1] - 0.5)
    h = np.clip(h + 15 * np.clip(1 - d / 0.03, 0, 1), 0, 100)
land = h >= F.SEA_LEVEL

with phase("03_features_lakes"):
    comp_w = F.components(n, edges, ~land)
    big = np.bincount(comp_w[~land]).argmax()
    is_ocean = comp_w == big
    # lagos pequeños (< 4 celdas) se vuelven tierra (marsh); los demás son provincias de mar interior
    lake = (~land) & ~is_ocean
    lsize = np.bincount(np.where(lake, comp_w, 0), minlength=n)
    small = lake & (lsize[np.maximum(comp_w, 0)] < 4)
    h[small] = F.SEA_LEVEL; land = h >= F.SEA_LEVEL
    lake = (~land) & ~is_ocean
    comp_l = F.components(n, edges, land)
R["land_cells"] = int(land.sum()); R["lakes"] = int(np.unique(comp_w[lake]).size); R["islands"] = int(np.unique(comp_l[land]).size)

with phase("04_climate"):
    temp = F.temperature(lat, h)
    prec = F.precipitation(lat, h, temp)
with phase("05_hydro"):
    filled = F.priority_flood(h, nbr, is_ocean | lake)
    recv, flux = F.flow(filled, nbr, prec / 10, is_ocean | lake)
    thr = np.quantile(flux[land], 0.93)
    river = land & (flux >= thr)

# --- biomas → categoría de terreno de Victoria II (por celda)
CATS = ["ocean", "arctic", "farmlands", "forest", "hills", "woods", "mountain", "steppe", "plains", "jungle", "marsh", "desert"]
CI = {c: i for i, c in enumerate(CATS)}
with phase("06_biomes_terrain_cells"):
    moist = prec.copy()
    nb = np.where(nbr >= 0, moist[np.maximum(nbr, 0)], np.nan)
    moist = np.nanmean(np.column_stack([moist, nb]), axis=1) + 4 * river
    cat = np.full(n, CI["plains"], np.int8)
    cat[temp < -4] = CI["arctic"]
    m = (temp >= -4) & (temp < 5); cat[m] = np.where(moist[m] > 25, CI["forest"], CI["steppe"])
    m = (temp >= 5) & (temp < 18); cat[m] = np.select([moist[m] > 45, moist[m] > 25, moist[m] > 10], [CI["forest"], CI["woods"], CI["plains"]], CI["steppe"])
    m = temp >= 18; cat[m] = np.select([moist[m] > 50, moist[m] > 15, moist[m] > 8], [CI["jungle"], CI["plains"], CI["steppe"]], CI["desert"])
    wet = land & (h < 24) & (moist > 40); cat[wet] = CI["marsh"]
    cat[land & (h >= 44)] = CI["hills"]; cat[land & (h >= 67)] = CI["mountain"]
    suit = np.clip((temp + 5) / 30, 0.05, 1) * np.clip(1 - (h - 20) / 80, 0.1, 1) * (1 + 2 * river)
    suit[cat == CI["desert"]] *= 0.2; suit[cat == CI["arctic"]] *= 0.1
    fert = land & (suit > np.quantile(suit[land], 0.8)) & np.isin(cat, [CI["plains"], CI["woods"]])
    cat[fert] = CI["farmlands"]
    cat[~land] = CI["ocean"]

# ============================================================ 2. provincias sobre el grafo de celdas
with phase("07_group_provinces_cellgraph"):
    indptr, indices = F.to_csr(edges, n)
    comp_s = F.components(n, edges, ~land)
    step = 1 + 1.5 * (h >= 67) + 0.5 * river
    own_l = F.group_cells(n, indptr, indices, land, 2700, suit ** 0.7, step, lat.pts, W, True, rng_for("prov_land"), 2, comp_l, "vec", edges)
    own_s = F.group_cells(n, indptr, indices, ~land, 545, np.ones(n), np.ones(n), lat.pts, W, True, rng_for("prov_sea"), 2, comp_s, "vec", edges)
    nl0 = int(own_l[land].max()) + 1
    prov_of_cell = np.where(land, own_l, own_s + nl0).astype(np.int64)        # 0-based, provisional

# ============================================================ 3. ráster a la resolución pedida
def coarse_noise(rng, gw, gh, amp):
    g = rng.uniform(-amp, amp, (gh, gw)).astype(np.float32)
    return g


with phase("08_warp_field"):
    rw = rng_for("warp")
    gw, gh = lat.cols // 2, lat.rows // 2                       # rejilla de ruido ligada a la rejilla de celdas
    g1 = coarse_noise(rw, gw, gh, 0.35); g2 = coarse_noise(rw, gw, gh, 0.35)
    gf1 = coarse_noise(rw, gw * 4, gh * 4, 0.12); gf2 = coarse_noise(rw, gw * 4, gh * 4, 0.12)
    def up(g):
        return np.asarray(Image.fromarray(g, "F").resize((W, H), Image.BILINEAR), np.float32)
    warp = ((up(g1) + up(gf1)) * lat.dx, (up(g2) + up(gf2)) * lat.dx)
with phase("09_pixel_landmask"):
    g = h.reshape(lat.rows, lat.cols).astype(np.float32)
    g = np.concatenate([g, g[:, :1]], axis=1)
    bigh = np.asarray(Image.fromarray(g, "F").resize((W + int(round(W / lat.cols)), H), Image.BILINEAR))
    off = int(round(W / lat.cols / 2))
    hp = bigh[:, off:off + W]
    pix_land = hp >= F.SEA_LEVEL
with phase("10_raster_cells_classed"):
    cell_r = F.rasterize(lat, W, H, cell_class=land, pix_class=pix_land, reach=1, warp=warp)
    del warp, bigh
with phase("11_pid_fix_fragments"):
    pid = prov_of_cell[cell_r] + 1
    is_sea_p = np.zeros(int(pid.max()) + 1, bool); is_sea_p[nl0 + 1:] = True
    pid, merged, flipped, created, is_sea_p = F.fix_fragments2(pid, is_sea_p, True)
R["fragments_merged_flipped_new"] = [merged, flipped, created]

with phase("12_compact_ids_land_first"):
    cnt = np.bincount(pid.ravel(), minlength=is_sea_p.size)
    present = np.flatnonzero(cnt[1:] > 0) + 1
    land_ids = present[~is_sea_p[present]]; sea_ids = present[is_sea_p[present]]
    remap = np.zeros(is_sea_p.size, np.int32)
    remap[land_ids] = np.arange(1, land_ids.size + 1)
    remap[sea_ids] = np.arange(land_ids.size + 1, land_ids.size + sea_ids.size + 1)
    ids = remap[pid].astype(np.uint16)
    NL, NP = int(land_ids.size), int(present.size)
    is_sea = np.zeros(NP + 1, bool); is_sea[NL + 1:] = True
    # provincia de cada celda tras el arreglo: mayoría de sus píxeles
    cpk = cell_r.ravel().astype(np.int64) * (NP + 1) + ids.ravel()
    uk, uc = np.unique(cpk, return_counts=True)
    cc, pp = np.divmod(uk, NP + 1)
    o = np.lexsort((-uc, cc)); first = np.ones(o.size, bool); first[1:] = cc[o][1:] != cc[o][:-1]
    cell_prov = np.zeros(n, np.int64); cell_prov[cc[o][first]] = pp[o][first]
    del pid
R["land_provinces"] = NL; R["sea_provinces"] = NP - NL
pix_land = ~is_sea[ids]                     # la clase final manda (fix_fragments puede cambiar islotes)
HASH["ids"] = sha(ids)
area = np.bincount(ids.ravel(), minlength=NP + 1)
R["land_area_px_pctl_5_25_50_75_95"] = np.percentile(area[1:NL + 1], [5, 25, 50, 75, 95]).astype(int).tolist()
R["empty_ids_after_compact"] = int((area[1:] == 0).sum())

# ============================================================ 4. derivados geométricos
with phase("13_raster_neighbors"):
    pe = F.raster_edges(ids.astype(np.int32), True)
    pe = pe[(pe[:, 0] > 0)]
deg = np.bincount(pe.ravel(), minlength=NP + 1)
R["isolated_provinces"] = int((deg[1:] == 0).sum())
coastal = np.zeros(NP + 1, bool)
ls = pe[(~is_sea[pe[:, 0]]) & is_sea[pe[:, 1]]]
coastal[ls[:, 0]] = True
R["coastal_land"] = int(coastal.sum())

with phase("14_positions"):
    # centroides por filas (sin arrays de coordenadas por píxel): media circular en x
    flat = ids.ravel()
    cxs = np.zeros(NP + 1); cys = np.zeros(NP + 1); sy_ = np.zeros(NP + 1)
    cosx = np.cos(np.arange(W) * (2 * np.pi / W)); sinx = np.sin(np.arange(W) * (2 * np.pi / W))
    BAND = 256
    for y0 in range(0, H, BAND):
        blk = ids[y0:y0 + BAND]; bf = blk.ravel()
        cxs += np.bincount(bf, weights=np.tile(cosx, blk.shape[0]), minlength=NP + 1)
        cys += np.bincount(bf, weights=np.tile(sinx, blk.shape[0]), minlength=NP + 1)
        sy_ += np.bincount(bf, weights=np.repeat(np.arange(y0, y0 + blk.shape[0], dtype=np.float64), W), minlength=NP + 1)
    cx = (np.arctan2(cys, cxs) % (2 * np.pi)) * W / (2 * np.pi)
    cy = sy_ / np.maximum(area, 1)
    # distancia al borde con tope (erosiones 4-conexas en el sitio)
    cur = np.ones((H, W), bool)
    cur[:, :-1] &= ids[:, :-1] == ids[:, 1:]; cur[:, 1:] &= ids[:, 1:] == ids[:, :-1]
    cur[:, -1] &= ids[:, -1] == ids[:, 0]; cur[:, 0] &= ids[:, 0] == ids[:, -1]
    cur[:-1] &= ids[:-1] == ids[1:]; cur[1:] &= ids[1:] == ids[:-1]
    cur[0] = False; cur[-1] = False
    dist = cur.astype(np.uint8)
    CAP = 24
    tmp = np.empty_like(cur)
    for _ in range(CAP - 1):
        np.copyto(tmp, cur)
        tmp[:, 1:] &= cur[:, :-1]; tmp[:, :-1] &= cur[:, 1:]; tmp[:, 0] &= cur[:, -1]; tmp[:, -1] &= cur[:, 0]
        tmp[1:] &= cur[:-1]; tmp[:-1] &= cur[1:]
        if not tmp.any():
            break
        dist += tmp; cur, tmp = tmp, cur
    del cur, tmp
    dflat = dist.ravel()
    hist = np.bincount(flat.astype(np.int64) * CAP + dflat, minlength=(NP + 1) * CAP).reshape(NP + 1, CAP)
    maxd = (CAP - 1 - np.argmax(hist[:, ::-1] > 0, axis=1)).astype(np.uint8)
    cand = np.flatnonzero(dflat == maxd[flat])
    cp = flat[cand]
    cyy, cxx = np.divmod(cand, W)
    dxc = np.abs(cxx - cx[cp]); dxc = np.minimum(dxc, W - dxc)
    d2 = dxc ** 2 + (cyy - cy[cp]) ** 2
    o = np.lexsort((d2, cp)); first = np.ones(o.size, bool); first[1:] = cp[o][1:] != cp[o][:-1]
    ux = np.zeros(NP + 1); uy = np.zeros(NP + 1)
    ux[cp[o][first]] = cxx[o][first]; uy[cp[o][first]] = cyy[o][first]
    del dist, dflat, hist
    # puntos secundarios: desplazamientos dentro de la provincia (mediana vanilla 6-16 px de unit)
    def offset_point(dx, dy):
        r = np.maximum(maxd.astype(float) - 1, 0)
        px = np.clip(np.round(ux + dx * np.minimum(r, abs(dx) if dx else r)), 0, W - 1).astype(int) % W
        py = np.clip(np.round(uy + dy * np.minimum(r, abs(dy) if dy else r)), 0, H - 1).astype(int)
        ok = ids[py, px] == np.arange(NP + 1)
        return np.where(ok, px, ux), np.where(ok, py, uy)
    pts_extra = {k: offset_point(*v) for k, v in {"building_construction": (8, 6), "military_construction": (-7, 6),
                                                  "factory": (9, -7), "fort": (-10, -10), "railroad": (4, -4)}.items()}
    # naval_base: píxel de mar contiguo a la provincia costera más cercano a unit
    a1 = ids[:, :-1].ravel(); b1 = ids[:, 1:].ravel()
    i1 = np.flatnonzero((~is_sea[a1]) & is_sea[b1]); sea_px = i1 + 1 + (i1 // (W - 1))   # índice plano del mar
    i1b = np.flatnonzero(is_sea[a1] & (~is_sea[b1])); sea_px2 = i1b + (i1b // (W - 1))
    lp = np.concatenate([a1[i1], b1[i1b]]); sp = np.concatenate([sea_px, sea_px2])
    a2 = ids[:-1].ravel(); b2 = ids[1:].ravel()
    j1 = np.flatnonzero((~is_sea[a2]) & is_sea[b2]); j1b = np.flatnonzero(is_sea[a2] & (~is_sea[b2]))
    lp = np.concatenate([lp, a2[j1], b2[j1b]]); sp = np.concatenate([sp, j1 + W, j1b])
    sy, sx = np.divmod(sp, W)
    ddx = np.abs(sx - ux[lp]); ddx = np.minimum(ddx, W - ddx)
    dd = ddx ** 2 + (sy - uy[lp]) ** 2
    o = np.lexsort((dd, lp)); first = np.ones(o.size, bool); first[1:] = lp[o][1:] != lp[o][:-1]
    nbx = np.full(NP + 1, np.nan); nby = np.full(NP + 1, np.nan)
    nbx[lp[o][first]] = sx[o][first] + 0.5; nby[lp[o][first]] = sy[o][first] + 0.5
    nb_rot = np.arctan2(uy - nby, ux - nbx) % (2 * np.pi)
    # text_scale = 0,749·área^0,214 (ajuste sobre vanilla, p0) y rotación por el eje principal
    text_scale = np.round(0.749 * np.maximum(area, 1) ** 0.214, 2)
    # momentos de segundo orden por bandas (x desenrollada respecto al centroide circular)
    sxx = np.zeros(NP + 1); syy = np.zeros(NP + 1); sxy = np.zeros(NP + 1)
    xr = np.arange(W, dtype=np.float64)
    for y0 in range(0, H, BAND):
        blk = ids[y0:y0 + BAND]; bf = blk.ravel()
        X = np.tile(xr, blk.shape[0]) - cx[bf]; X = (X + W / 2) % W - W / 2
        Y = np.repeat(np.arange(y0, y0 + blk.shape[0], dtype=np.float64), W) - cy[bf]
        sxx += np.bincount(bf, weights=X * X, minlength=NP + 1); syy += np.bincount(bf, weights=Y * Y, minlength=NP + 1)
        sxy += np.bincount(bf, weights=X * Y, minlength=NP + 1)
    theta = 0.5 * np.arctan2(2 * sxy, sxx - syy)
    lam = np.sqrt(np.maximum(((sxx - syy) / 2) ** 2 + sxy ** 2, 0))
    elong = (((sxx + syy) / 2 + lam) / np.maximum((sxx + syy) / 2 - lam, 1e-9))
    rot = np.where(elong > 4, theta % (2 * np.pi), np.nan)          # solo provincias alargadas (vanilla: 18 %)
unit_inside = float((ids[uy[1:].astype(int), ux[1:].astype(int)] == np.arange(1, NP + 1)).mean())
R["unit_inside_frac"] = round(unit_inside, 5)
R["naval_base_on_sea_frac_coastal"] = round(float(np.isfinite(nbx[coastal]).mean()), 4)
R["positions_extra_inside_frac"] = round(float(np.mean([(ids[py[1:].astype(int), px[1:].astype(int)] == np.arange(1, NP + 1)).mean() for px, py in pts_extra.values()])), 4)
R["text_rotation_set_frac_land"] = round(float(np.isfinite(rot[1:NL + 1]).mean()), 3)

with phase("15_straits"):
    # tierra propagada por el mar: id de tierra más cercano y distancia (dilataciones 4-conexas, tope D)
    D = 8                                                          # p90 de los huecos de vanilla = 7,8 px (p0)
    src = np.where(is_sea[ids], 0, ids).astype(np.uint16)
    dsea = np.where(src > 0, 0, 255).astype(np.uint8)
    seam = is_sea[ids]
    for k in range(1, D // 2 + 1):
        for sh, ax in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            s2 = np.roll(src, sh, axis=ax); d2_ = np.roll(dsea, sh, axis=ax)
            m = seam & (src == 0) & (s2 > 0) & (d2_ == k - 1)
            src[m] = s2[m]; dsea[m] = k
    pairs = []
    for sh, ax in ((1, 0), (1, 1)):
        s2 = np.roll(src, sh, axis=ax); d2_ = np.roll(dsea, sh, axis=ax)
        m = seam & (src > 0) & (s2 > 0) & (src != s2) & (dsea.astype(int) + d2_ <= D)
        pairs.append(np.column_stack([np.minimum(src[m], s2[m]), np.maximum(src[m], s2[m]), ids[m], dsea[m].astype(int) + d2_[m]]))
    P = np.concatenate(pairs).astype(np.int64)
    # excluir pares ya vecinos por tierra
    nbset = set(map(tuple, pe[(~is_sea[pe[:, 0]]) & (~is_sea[pe[:, 1]])].tolist()))
    keep = np.array([(a, b) not in nbset for a, b in P[:, :2].tolist()], bool) if P.size else np.zeros(0, bool)
    P = P[keep]
    # un estrecho por par de masas de tierra (el de menor hueco) + otros por par de provincias si gap ≤ D/2
    if P.size:
        o = np.lexsort((P[:, 3], P[:, 1], P[:, 0])); P = P[o]
        firstp = np.ones(len(P), bool); firstp[1:] = (P[1:, 0] != P[:-1, 0]) | (P[1:, 1] != P[:-1, 1])
        P = P[firstp]
    # masas de tierra (componentes de provincias de tierra)
    le = pe[(~is_sea[pe[:, 0]]) & (~is_sea[pe[:, 1]])]
    lm = F.components(NP + 1, le, ~is_sea)
    if P.size:
        ka, kb = lm[P[:, 0]], lm[P[:, 1]]
        diffmass = ka != kb
        Q = P[diffmass]; kk = np.column_stack([np.minimum(ka, kb), np.maximum(ka, kb)])[diffmass]
        o = np.lexsort((Q[:, 3], kk[:, 1], kk[:, 0])); Q = Q[o]; kk = kk[o]
        fm = np.ones(len(Q), bool); fm[1:] = (kk[1:, 0] != kk[:-1, 0]) | (kk[1:, 1] != kk[:-1, 1])
        straits = Q[fm | (Q[:, 3] <= D // 2)]
    else:
        straits = np.zeros((0, 4), np.int64)
R["strait_candidates"] = int(len(P)); R["straits_suggested"] = int(len(straits))
R["landmasses"] = int(np.unique(lm[1:NL + 1]).size)

# ============================================================ 5. grupos: estados, continentes, climas
with phase("16_states_continents_climates"):
    ip2, ix2 = F.to_csr(le, NP + 1)
    pmask = ~is_sea.copy(); pmask[0] = False
    pc = np.column_stack([cx, cy])
    comp_p = F.components(NP + 1, le, pmask)
    own_st = F.group_cells(NP + 1, ip2, ix2, pmask, round(NL / 4.92), np.ones(NP + 1), np.ones(NP + 1), pc, W, True, rng_for("states"), 1, comp_p, "vec", le)
    # continentes: k-medias de centroides de las masas grandes (≥ 3 % de la tierra); islas → masa más cercana
    k_cont = 6
    rc = rng_for("continents")
    landp = np.arange(1, NL + 1)
    cent = pc[rc.choice(landp, k_cont, replace=False)]
    for _ in range(12):
        dxk = np.abs(pc[landp, None, 0] - cent[None, :, 0]); dxk = np.minimum(dxk, W - dxk)
        lab = np.argmin(dxk ** 2 + (pc[landp, None, 1] - cent[None, :, 1]) ** 2, axis=1)
        for k in range(k_cont):
            if (lab == k).any():
                cent[k] = pc[landp[lab == k]].mean(0)
    # una masa de tierra no se parte entre continentes salvo si es enorme: voto mayoritario por masa
    mass = lm[landp]
    mk = mass * k_cont + lab
    um, uc2 = np.unique(mk, return_counts=True)
    mm_, kk_ = np.divmod(um, k_cont)
    o = np.lexsort((-uc2, mm_)); f2 = np.ones(o.size, bool); f2[1:] = mm_[o][1:] != mm_[o][:-1]
    mass_cont = dict(zip(mm_[o][f2].tolist(), kk_[o][f2].tolist()))
    msize = np.bincount(mass)
    cont = np.where(msize[mass] > 0.25 * NL, lab, np.array([mass_cont[m] for m in mass.tolist()]))
    # clima por provincia: temperatura y habitabilidad medias de sus celdas
    ctemp = np.bincount(cell_prov, weights=temp, minlength=NP + 1) / np.maximum(np.bincount(cell_prov, minlength=NP + 1), 1)
    csuit = np.bincount(cell_prov, weights=suit, minlength=NP + 1) / np.maximum(np.bincount(cell_prov, minlength=NP + 1), 1)
    clim = np.select([ctemp < -2, ctemp < 6, csuit < 0.25], [3, 2, 1], 0)  # inhospitable, harsh, temperate, mild
R["states"] = int(np.unique(own_st[1:NL + 1]).size)
R["state_size_pctl"] = np.percentile(np.bincount(own_st[1:NL + 1]), [5, 25, 50, 75, 95]).tolist()
R["continent_sizes"] = np.bincount(cont, minlength=k_cont).tolist()

# ============================================================ 6. terreno por píxel, dominancia y texturas
with phase("17_terrain_bmp_pixels"):
    tidx = {c: [] for c in CATS}
    if TERRAIN_TXT:
        for mm in re.finditer(r"text_(\d+)\s*=\s*\{\s*type\s*=\s*(\w+)", open(TERRAIN_TXT, encoding="cp1252").read()):
            tidx.setdefault(mm.group(2), []).append(int(mm.group(1)))
    else:   # sin instalación: 4 índices por categoría en orden (prueba)
        for i, c in enumerate(CATS[1:]):
            tidx[c] = [4 * i + k for k in range(4)]
    pcat = cat[cell_r]
    pcat[(~pix_land)] = CI["ocean"]
    pcat[pix_land & (pcat == CI["ocean"])] = CI["plains"]
    hcls = np.where(hp >= 67, CI["mountain"], np.where(hp >= 44, CI["hills"], -1))
    pcat = np.where(pix_land & (hcls >= 0) & (pcat != CI["arctic"]), hcls, pcat).astype(np.int8)
    # variante de textura dentro de la categoría por ruido grueso (no por píxel: evita sal y pimienta)
    var = np.asarray(Image.fromarray(rng_for("tvar").integers(0, 4, (H // 64 + 1, W // 64 + 1)).astype(np.uint8)).resize((W, H), Image.NEAREST))
    lut_t = np.full((len(CATS), 4), 254, np.uint8)
    for c in CATS[1:]:
        ix = tidx.get(c) or tidx["plains"]
        lut_t[CI[c]] = [ix[k % len(ix)] for k in range(4)]
    terr = lut_t[pcat, var]
    terr[~pix_land] = 254
    # dominancia por provincia (categoría con más píxeles)
    k2 = ids.ravel().astype(np.int64) * len(CATS) + pcat.ravel()
    bc = np.bincount(k2, minlength=(NP + 1) * len(CATS)).reshape(NP + 1, len(CATS))
    dom = bc.argmax(1); share = bc.max(1) / np.maximum(bc.sum(1), 1)
R["terrain_dominant_share_land_pctl_5_25_50"] = np.percentile(share[1:NL + 1], [5, 25, 50]).round(3).tolist()
R["terrain_land_px_with_254"] = int(((terr == 254) & pix_land).sum())
R["water_mask_mismatch_px"] = int(((terr == 254) != is_sea[ids]).sum())
HASH["terrain"] = sha(terr)

with phase("18_rivers_bmp"):
    riv = np.where(is_sea[ids], 254, 255).astype(np.uint8)
    lw = np.clip(2 + 9 * (np.log(flux) - np.log(thr)) / (np.log(flux.max()) - np.log(thr) + 1e-9), 2, 11).astype(np.uint8)
    pts = lat.pts
    c0 = np.nonzero(river & (recv >= 0))[0]; c1 = recv[c0]
    x0, y0 = pts[c0, 0], pts[c0, 1]; x1, y1 = pts[c1, 0], pts[c1, 1]
    dxs = x1 - x0; dxs = np.where(dxs > W / 2, dxs - W, np.where(dxs < -W / 2, dxs + W, dxs))   # costura
    m_ = (np.abs(dxs) + np.abs(y1 - y0)).astype(int) + 1
    seg = np.repeat(np.arange(c0.size), m_)
    t = (np.arange(seg.size) - np.repeat(np.cumsum(m_) - m_, m_)) / np.repeat(np.maximum(m_ - 1, 1), m_)
    xs_ = np.round(x0[seg] + dxs[seg] * t).astype(int); ys_ = np.round(y0[seg] + (y1 - y0)[seg] * t).astype(int)
    # escalera 4-conexa: tras cada paso diagonal se inserta la esquina (x nuevo, y viejo)
    xs2 = np.empty(2 * xs_.size, int); ys2 = np.empty(2 * ys_.size, int)
    xs2[0::2] = xs_; ys2[0::2] = ys_
    xs2[1::2] = np.roll(xs_, -1); ys2[1::2] = ys_
    same = np.repeat(np.r_[seg[1:] == seg[:-1], False], 2); same[0::2] = True
    xs2 = xs2[same] % W; ys2 = np.clip(ys2[same], 0, H - 1); w2 = lw[c0][np.repeat(seg, 2)[same]]
    ok = riv[ys2, xs2] != 254
    o_ = np.argsort(w2[ok], kind="stable")                   # el ancho mayor gana en los cruces
    riv[ys2[ok][o_], xs2[ok][o_]] = w2[ok][o_]
HASH["rivers"] = sha(riv)

def dds_rgba(img: np.ndarray, mips: bool = False) -> bytes:
    """DDS A8R8G8B8 sin comprimir (D11); filas en orden de almacenamiento = fila 0 del array (H1, R1 §0.2)."""
    h_, w_ = img.shape[:2]
    levels = [img]
    if mips:
        cur = img
        while min(cur.shape[:2]) > 1:
            cur = np.asarray(Image.fromarray(cur, "RGBA").resize((max(1, cur.shape[1] // 2), max(1, cur.shape[0] // 2)), Image.BOX))
            levels.append(cur)
    flags = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | (0x20000 if mips else 0)
    hdr = struct.pack("<4sI6I44x", b"DDS ", 124, flags, h_, w_, w_ * 4, 0, len(levels) if mips else 0)
    pf = struct.pack("<2I4s5I", 32, 0x41, b"\0\0\0\0", 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    caps = struct.pack("<4I4x", 0x1000 | (0x400008 if mips else 0), 0, 0, 0)
    body = b"".join(l[..., [2, 1, 0, 3]].tobytes() for l in levels)
    return hdr + pf + caps + body


with phase("19_colormaps_minimap"):
    W3, H3 = W // 3, H // 3
    sub_cat = pcat[1::3, 1::3][:H3, :W3]
    sub_h = np.asarray(Image.fromarray(hp, "F").resize((W3, H3), Image.BILINEAR))
    base = np.array([[90, 110, 140], [235, 235, 240], [150, 160, 90], [60, 95, 50], [140, 125, 85], [95, 125, 65],
                     [130, 120, 115], [185, 170, 120], [160, 165, 100], [45, 100, 45], [85, 110, 95], [215, 190, 140]], np.float32)
    col = base[sub_cat]
    gy, gx = np.gradient(sub_h)
    shade = np.clip(1 + 0.06 * (gx - gy), 0.6, 1.3)[..., None]          # luz del noroeste
    grain = (np.asarray(Image.fromarray(rng_for("grain").uniform(-8, 8, (H3 // 8 + 1, W3 // 8 + 1)).astype(np.float32), "F").resize((W3, H3), Image.BILINEAR)))[..., None]
    cm = np.clip(col * shade + grain, 0, 255).astype(np.uint8)
    pad = 4
    cm = np.concatenate([cm[:, -pad:], cm, cm[:, :pad]], axis=1)                 # 1880 = W/3 + 8 (envoltura)
    cm4 = np.dstack([cm, np.full(cm.shape[:2], 255, np.uint8)])
    b_colormap = dds_rgba(cm4)
    W6, H6 = W // 6, H // 6
    hw = np.asarray(Image.fromarray(hp, "F").resize((W6, H6), Image.BILINEAR))
    depth = np.clip((F.SEA_LEVEL - hw) / F.SEA_LEVEL, 0, 1)
    wat = np.stack([20 + 40 * (1 - depth), 60 + 60 * (1 - depth), 90 + 70 * (1 - depth)], -1)
    wat = np.where((hw >= F.SEA_LEVEL)[..., None], 128, wat).astype(np.uint8)
    b_water = dds_rgba(np.dstack([wat, np.full(wat.shape[:2], 255, np.uint8)]), mips=True)
    nos = np.clip(col + grain, 0, 255).astype(np.uint8)
    b_noshadow = dds_rgba(np.dstack([nos, np.full(nos.shape[:2], 255, np.uint8)]))
    pol = np.where(sub_cat[..., None] == 0, 90, 200).astype(np.uint8).repeat(3, -1)
    pol = np.concatenate([pol[:, -pad:], pol, pol[:, :pad]], axis=1)
    b_political = dds_rgba(np.dstack([pol, np.full(pol.shape[:2], 255, np.uint8)]))
    mini = np.asarray(Image.fromarray(cm[::-1]).resize((266, 102), Image.BOX))[::-1]
    b_minimap = dds_rgba(np.dstack([mini, np.full(mini.shape[:2], 255, np.uint8)]))
# relectura con Pillow para verificar los DDS
chk = {}
for k, b in {"colormap": b_colormap, "colormap_water": b_water, "colormap_no_shadow": b_noshadow, "colormap_political": b_political, "minimap": b_minimap}.items():
    im = Image.open(io.BytesIO(b)); chk[k] = [im.size, im.mode, len(b)]
R["dds_reread_pillow"] = chk
HASH["colormap"] = sha(b_colormap)

# ============================================================ 7. mundo: países, culturas, religiones, POPs, RGO
with phase("20_world_countries_cultures_pops"):
    landmask = np.zeros(NP + 1, bool); landmask[1:NL + 1] = True
    w_edge = le
    u_, v_ = np.concatenate([w_edge[:, 0], w_edge[:, 1]]), np.concatenate([w_edge[:, 1], w_edge[:, 0]])
    adj = [[] for _ in range(NP + 1)]
    for a, b in zip(u_.tolist(), v_.tolist()):
        adj[a].append(b)
    for a, b, *_ in straits.tolist():
        adj[a].append(b); adj[b].append(a)
    psuit = csuit
    tcost = {CI["mountain"]: 4.0, CI["hills"]: 2.0, CI["marsh"]: 2.0, CI["desert"]: 3.0, CI["arctic"]: 5.0, CI["jungle"]: 2.5}
    pcost = np.array([tcost.get(int(c), 1.0) for c in dom])

    def expand(n_centers, rng, mindist, limit_frac=1.0, cost=pcost):
        jit = 1.0 + rng.random(NP + 1) * 0.2
        order = np.argsort(-(psuit[1:NL + 1] * rng.uniform(0.6, 1.0, NL))) + 1
        centers = []
        cxl, cyl = cx.tolist(), cy.tolist()
        while len(centers) < n_centers and mindist > 1:
            for p in order.tolist():
                if p in centers:
                    continue
                if all(min(abs(cxl[p] - cxl[q]), W - abs(cxl[p] - cxl[q])) ** 2 + (cyl[p] - cyl[q]) ** 2 > mindist ** 2 for q in centers):
                    centers.append(p)
                if len(centers) == n_centers:
                    break
            mindist /= 1.2                                  # FMG: si no caben, se reduce la separación
        owner = np.full(NP + 1, -1, np.int64); dist_ = np.full(NP + 1, np.inf)
        hq = [(0.0, p, k) for k, p in enumerate(centers)]
        for _, p, k in hq:
            dist_[p] = 0; owner[p] = k
        heapq.heapify(hq)
        cap = np.quantile(np.full(1, 1.0), 1) * 1e18
        budget = limit_frac * NL
        taken = len(centers)
        while hq:
            dd_, p, k = heapq.heappop(hq)
            if dd_ > dist_[p]:
                continue
            for q in adj[p]:
                if not landmask[q]:
                    continue
                nd = dd_ + cost[q] * jit[q]
                if nd < dist_[q] and (owner[q] >= 0 or taken < budget):
                    if owner[q] < 0:
                        taken += 1
                    dist_[q] = nd; owner[q] = k
                    heapq.heappush(hq, (nd, q, k))
        return np.array(centers), owner
    caps, country = expand(60, rng_for("countries"), W / 40, limit_frac=0.85)
    cul_c, culture = expand(24, rng_for("cultures"), W / 18)
    culture[landmask & (culture < 0)] = 0
    # grupos culturales: culturas vecinas en grupos de ~3 (k-medias simple sobre centros)
    gk = 8
    cc_ = pc[cul_c]
    grp = np.argmin(((cc_[:, None, :] - cc_[None, rng_for("cgroups").choice(len(cul_c), gk, replace=False), :]) ** 2).sum(-1), axis=1)
    religion = grp[culture] % 4
    # población (1836): proporcional a área × idoneidad; mezcla de tipos de POP inspirada en vanilla (proporciones propias)
    pw = area * np.maximum(psuit, 0.02); pw[NL + 1:] = 0; pw[0] = 0
    popsize = np.round(pw / pw.sum() * 250e6).astype(np.int64)        # total del mundo (parámetro; vanilla ≈ 255 M)
    mix = {"farmers": 0.62, "labourers": 0.16, "artisans": 0.06, "clergymen": 0.015, "soldiers": 0.02,
           "aristocrats": 0.012, "bureaucrats": 0.006, "officers": 0.003, "craftsmen": 0.06, "clerks": 0.01, "capitalists": 0.004}
    goods_by_cat = {"plains": ["grain", "cattle", "wool"], "farmlands": ["grain", "fruit", "cotton"], "forest": ["timber", "fur"],
                    "woods": ["timber", "cattle"], "hills": ["coal", "iron", "wool"], "mountain": ["iron", "coal", "precious_metal"],
                    "steppe": ["cattle", "wool"], "jungle": ["tropical_wood", "rubber", "coffee"], "marsh": ["rice", "fish"],
                    "desert": ["sulphur", "cattle"], "arctic": ["fur", "fish"]}
    rg = rng_for("rgo")
    goods = [None] + [rg.choice(goods_by_cat[CATS[int(dom[p])]]) if CATS[int(dom[p])] in goods_by_cat else "grain" for p in range(1, NL + 1)]
    # life rating: cuantiles de la idoneidad → distribución objetivo (forma medida en la instalación; aquí una propia)
    target = np.repeat([10, 15, 20, 25, 30, 35, 40, 45, 50], [2, 3, 6, 10, 14, 45, 12, 5, 3])
    rk = np.argsort(np.argsort(psuit[1:NL + 1])) / max(NL - 1, 1)
    lr = np.zeros(NP + 1, int); lr[1:NL + 1] = target[np.minimum((rk * target.size).astype(int), target.size - 1)]
R["countries"] = int(len(caps)); R["unowned_land"] = int((country[1:NL + 1] < 0).sum())
R["life_rating_hist"] = dict(zip(*[x.tolist() for x in np.unique(lr[1:NL + 1], return_counts=True)]))

# ============================================================ 8. textos y archivos en memoria
SYL = ["ka", "lo", "ver", "an", "dra", "mi", "sul", "te", "ron", "ba", "el", "is", "or", "ven", "ga", "thi", "mar", "du", "sen", "ul"]
import random as _random
def mkname(rng):
    return "".join(rng.choice(SYL) for _ in range(rng.randint(2, 3))).capitalize()
CRLF = "\r\n"
files: dict[str, bytes] = {}
with phase("21_render_text_files"):
    rn = _random.Random(zlib.crc32(b"names") ^ SEED)
    ux, uy, text_scale, rot, nbx, nby, nb_rot = (a.tolist() for a in (ux, uy, text_scale, rot, nbx, nby, nb_rot))
    pts_extra = {k: (a.tolist(), b.tolist()) for k, (a, b) in pts_extra.items()}
    country_l, culture_l, religion_l, popsize_l, lr_l, dom_l, cont_l = (a.tolist() for a in (country, culture, religion, popsize, lr, dom, cont))
    is_sea_l = is_sea.tolist()
    pname = [None] + [mkname(rn) for _ in range(NP)]
    TAGS = []
    while len(TAGS) < len(caps):
        t = "".join(rn.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(3))
        if t not in TAGS and t not in ("REB", "CON", "PRN", "AUX", "NUL"):
            TAGS.append(t)
    gen = "# Generado por Victoria II Mod Studio (Taller de mapas)" + CRLF
    lut_rgb = (rng_for("colors").choice(2**24 - 2, size=NP, replace=False) + 1)
    files["map/definition.csv"] = (gen + "province;red;green;blue;x;x" + CRLF + "".join(
        f"{i};{c >> 16};{(c >> 8) & 255};{c & 255};{pname[i]};x{CRLF}" for i, c in zip(range(1, NP + 1), lut_rgb.tolist()))).encode("cp1252")
    files["map/default.map"] = (gen + f"max_provinces = {NP + 1}{CRLF}sea_starts = {{{CRLF}\t" + " ".join(map(str, range(NL + 1, NP + 1))) + f"{CRLF}}}{CRLF}").encode("cp1252")
    pos_lines = [gen]
    bx = {k: v for k, v in pts_extra.items()}
    for p in range(1, NP + 1):
        L = [f"{p} = {{", f"\tunit = {{ x = {ux[p]:.3f} y = {uy[p]:.3f} }}", f"\ttext_position = {{ x = {ux[p]:.3f} y = {uy[p]:.3f} }}",
             f"\ttext_scale = {text_scale[p]:.2f}"]
        if rot[p] == rot[p]:
            L.append(f"\ttext_rotation = {rot[p]:.4f}")
        if not is_sea_l[p]:
            for k in ("building_construction", "military_construction", "factory"):
                L.append(f"\t{k} = {{ x = {bx[k][0][p]:.3f} y = {bx[k][1][p]:.3f} }}")
            bp = [f"\t\tfort = {{ x = {bx['fort'][0][p]:.3f} y = {bx['fort'][1][p]:.3f} }}",
                  f"\t\trailroad = {{ x = {bx['railroad'][0][p]:.3f} y = {bx['railroad'][1][p]:.3f} }}"]
            if nbx[p] == nbx[p]:
                bp.append(f"\t\tnaval_base = {{ x = {nbx[p]:.3f} y = {nby[p]:.3f} }}")
                L.append(f"\tbuilding_rotation = {{ naval_base = {nb_rot[p]:.4f} }}")
            L += ["\tbuilding_position = {"] + bp + ["\t}"]
        L.append("}")
        pos_lines.append(CRLF.join(L) + CRLF)
    files["map/positions.txt"] = "".join(pos_lines).encode("cp1252")
    adj_lines = [gen.replace("# ", "#"), "#From;To;Type;Through;Data;Comment" + CRLF]
    for a, b, th, gap in straits.tolist():
        adj_lines.append(f"{a};{b};sea;{th};0;Estrecho {pname[a]}-{pname[b]}{CRLF}")
    files["map/adjacencies.csv"] = "".join(adj_lines).encode("cp1252")
    st_names = {}
    reg = [gen]
    for s in np.unique(own_st[1:NL + 1]).tolist():
        mem = (np.flatnonzero(own_st[1:NL + 1] == s) + 1).tolist()
        sid = f"STATE_{mem[0]}"; st_names[sid] = mkname(rn)
        reg.append(f"{sid} = {{ " + " ".join(map(str, mem)) + f" }}{CRLF}")
    files["map/region.txt"] = "".join(reg).encode("cp1252")
    files["map/region_sea.txt"] = gen.encode("cp1252")
    CONT = ["europe", "asia", "africa", "north_america", "south_america", "oceania"]
    files["map/continent.txt"] = (gen + "".join(f"{CONT[k]} = {{{CRLF}\tprovinces = {{{CRLF}\t\t" + " ".join(map(str, (np.flatnonzero(np.asarray(cont_l) == k) + 1).tolist())) + f"{CRLF}\t}}{CRLF}}}{CRLF}" for k in range(k_cont))).encode("cp1252")
    CL = ["mild_climate", "temperate_climate", "harsh_climate", "inhospitable_climate"]
    files["map/climate.txt"] = (gen + "".join(f"{CL[k]} = {{ }}{CRLF}" for k in range(4)) + "".join(f"{CL[k]} = {{{CRLF}\t" + " ".join(map(str, (np.flatnonzero(clim[1:NL + 1] == k) + 1).tolist())) + f"{CRLF}}}{CRLF}" for k in range(4))).encode("cp1252")
    for p in range(1, NL + 1):
        own = TAGS[country_l[p]] if country_l[p] >= 0 else None
        body = gen
        if own:
            body += f"owner = {own}{CRLF}controller = {own}{CRLF}add_core = {own}{CRLF}"
        body += f"trade_goods = {goods[p]}{CRLF}life_rating = {lr_l[p]}{CRLF}terrain = {CATS[dom_l[p]]}{CRLF}"
        files[f"history/provinces/studio/{p} - {pname[p]}.txt"] = body.encode("cp1252")
    CUL = [mkname(rn).lower() for _ in range(len(cul_c))]
    REL = ["catholic", "sunni", "mahayana", "animist"]
    pops = [gen]
    for p in range(1, NL + 1):
        tot = popsize_l[p]; c = CUL[culture_l[p]]; r_ = REL[religion_l[p]]
        pops.append(f"{p} = {{{CRLF}" + "".join(f"\t{k} = {{ culture = {c} religion = {r_} size = {max(1, int(tot * v))} }}{CRLF}" for k, v in mix.items()) + f"}}{CRLF}")
    files["history/pops/1836.1.1/00_STU_pops.txt"] = "".join(pops).encode("cp1252")
    files["history/pops/1861.4.14/00_STU_pops.txt"] = files["history/pops/1836.1.1/00_STU_pops.txt"]
    files["common/countries.txt"] = (gen + "".join(f'{t} = "countries/{t}.txt"{CRLF}' for t in TAGS)).encode("cp1252")
    for k, t in enumerate(TAGS):
        files[f"common/countries/{t}.txt"] = f"color = {{ {rn.randint(30, 230)} {rn.randint(30, 230)} {rn.randint(30, 230)} }}{CRLF}graphical_culture = EuropeanGC{CRLF}".encode("cp1252")
        files[f"history/countries/{t} - {mkname(rn)}.txt"] = (f"capital = {caps[k]}{CRLF}primary_culture = {CUL[culture[caps[k]]]}{CRLF}religion = {REL[religion[caps[k]]]}{CRLF}"
                                                             f"government = absolute_monarchy{CRLF}plurality = 0.0{CRLF}nationalvalue = nv_order{CRLF}literacy = 0.1{CRLF}civilized = yes{CRLF}").encode("cp1252")
    cult = [gen, f"studio_group = {{{CRLF}\tleader = european{CRLF}\tunit = EuropeanGC{CRLF}"]
    for c in CUL:
        cult.append(f"\t{c} = {{{CRLF}\t\tcolor = {{ 100 100 100 }}{CRLF}\t\tfirst_names = {{ " + " ".join(mkname(rn) for _ in range(50)) + f" }}{CRLF}\t\tlast_names = {{ " + " ".join(mkname(rn) for _ in range(50)) + f" }}{CRLF}\t}}{CRLF}")
    cult.append("}" + CRLF)
    files["common/cultures.txt"] = "".join(cult).encode("cp1252")
    loc = ["key;English;French;German;;Spanish;;;;;;;;;x" + CRLF]
    for p in range(1, NP + 1):
        loc.append(f"PROV{p};{pname[p]};{pname[p]};{pname[p]};;{pname[p]};;;;;;;;;x{CRLF}")
    for sid, nm in st_names.items():
        loc.append(f"{sid};{nm};{nm};{nm};;{nm};;;;;;;;;x{CRLF}")
    files["localisation/00_STU_map.csv"] = "".join(loc).encode("cp1252")
R["files_generated"] = len(files); R["text_bytes"] = sum(len(b) for b in files.values())

with phase("22_flags_tga"):
    flags = {}
    rf = rng_for("flags")
    for t in TAGS:
        for var_ in ("", "_communist", "_fascist", "_monarchy", "_republic"):
            cols = rf.integers(0, 256, (3, 3)).astype(np.uint8)
            img = np.zeros((64, 93, 4), np.uint8); img[..., 3] = 255
            kind = rf.integers(0, 3)
            if kind == 0:
                for k in range(3): img[:, k * 31:(k + 1) * 31, :3] = cols[k]
            elif kind == 1:
                for k in range(3): img[k * 21:(k + 1) * 22, :, :3] = cols[k]
            else:
                img[..., :3] = cols[0]; img[26:38, :, :3] = cols[1]; img[:, 30:42, :3] = cols[1]
            bio = io.BytesIO(); Image.fromarray(img, "RGBA").save(bio, "TGA")
            flags[f"gfx/flags/{t}{var_}.tga"] = bio.getvalue()
    tga = Image.open(io.BytesIO(next(iter(flags.values()))))
R["flag_check"] = [tga.size, tga.mode, tga.info.get("orientation"), len(flags)]
files.update(flags)

with phase("23_bmp_encode"):
    lut = np.zeros((NP + 1, 3), np.uint8)
    lut[1:, 0] = lut_rgb >> 16; lut[1:, 1] = (lut_rgb >> 8) & 255; lut[1:, 2] = lut_rgb & 255
    bio = io.BytesIO(); Image.fromarray(lut[ids], "RGB").save(bio, "BMP"); files["map/provinces.bmp"] = bio.getvalue()
    for name, arr in (("terrain", terr), ("rivers", riv)):
        im = Image.fromarray(arr, "P"); im.putpalette(list(range(256)) * 3)
        bio = io.BytesIO(); im.save(bio, "BMP"); files[f"map/{name}.bmp"] = bio.getvalue()
    files["map/terrain/colormap.dds"] = b_colormap; files["map/terrain/colormap_water.dds"] = b_water
    files["map/terrain/colormap_no_shadow.dds"] = b_noshadow; files["map/terrain/colormap_political.dds"] = b_political
    files["gfx/interface/minimap.dds"] = b_minimap
R["bmp_offsets"] = {k: struct.unpack("<I", files[f"map/{k}.bmp"][10:14])[0] for k in ("provinces", "terrain", "rivers")}
R["total_files"] = len(files); R["total_MB"] = round(sum(len(b) for b in files.values()) / 2**20, 1)

if WRITE:
    with phase("24_write_fsync_all"):
        root = os.path.join(OUT, "mod")
        for rel, b in files.items():
            p = os.path.join(root, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp"
            with open(tmp, "wb") as f:
                f.write(b); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, p)

HASH["all_files"] = sha(b"".join(hashlib.sha256(files[k]).digest() for k in sorted(files)))
np.save(os.path.join(OUT, "ids_small.npy"), ids[::4, ::4] if W > 2000 else ids)
np.save(os.path.join(OUT, "cell_prov.npy"), cell_prov)
Image.fromarray(lut[ids][::-1][:: max(1, W // 1404), :: max(1, W // 1404)]).save(os.path.join(OUT, "preview_north_up.png"))
R["phases_s_peakMiB"] = T
R["total_s"] = round(sum(v[0] for v in T.values()), 2)
R["ru_maxrss_MiB"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
R["hash"] = HASH
print(json.dumps(R, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
json.dump(R, open(os.path.join(OUT, "result.json"), "w"), indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
