"""p3: «sobre vanilla»: un continente nuevo generado dentro de una caja de océano del mapa existente.

Mide: búsqueda de la caja, relieve en la caja (misma densidad de celdas que 60 000 en el mapa completo),
provincias nuevas (ids N+1…), mar recortado (provincias de mar existentes que pierden píxeles o se parten),
arreglo de fragmentos limitado a la caja ampliada y tamaño del parche (RasterPatch) para deshacer.
Uso: python3 -I p3_overlay.py VANILLA_ROOT
"""
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "r2-azgaar", "proto"))
import forge as F  # noqa: E402

VAN = sys.argv[1]
R, T = {}, {}


class phase:
    def __init__(self, k): self.k = k
    def __enter__(self): self.t = time.perf_counter()
    def __exit__(self, *a): T[self.k] = round(time.perf_counter() - self.t, 3)


with phase("0_load_vanilla_ids_lut"):
    a = np.asarray(Image.open(VAN + "/map/provinces.bmp").convert("RGB"))
    pk = (a[..., 0].astype(np.uint32) << 16) | (a[..., 1].astype(np.uint32) << 8) | a[..., 2]
    lut = np.zeros(1 << 24, np.uint16)
    for line in open(VAN + "/map/definition.csv", encoding="cp1252"):
        p = line.strip().split(";")
        if len(p) >= 4 and p[0].strip().isdigit():
            r, g, b = (int(float(v)) for v in p[1:4]); lut[(r << 16) | (g << 8) | b] = int(p[0])
    ids = lut[pk]; del pk, a
H, W = ids.shape
dm = open(VAN + "/map/default.map", encoding="cp1252").read()
sea = set(int(x) for x in re.search(r"sea_starts\s*=\s*\{([^}]*)\}", dm).group(1).split())
N0 = int(ids.max())
is_sea = np.zeros(N0 + 1, bool); is_sea[list(sea)] = True
smask = is_sea[ids]

BW, BH = 720, 480
with phase("1_find_ocean_box"):
    # imagen integral de tierra a 1/8 y caja sin tierra lo más lejos posible de la costa
    lm = (~smask)[::8, ::8].astype(np.int32)
    ii = np.pad(lm.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    bw, bh = BW // 8, BH // 8
    s = ii[bh:, bw:] - ii[:-bh, bw:] - ii[bh:, :-bw] + ii[:-bh, :-bw]
    m = 8  # margen de mar alrededor
    ii2 = np.pad(np.pad(lm, m, mode="wrap").cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    s2 = ii2[bh + 2 * m:, bw + 2 * m:] - ii2[:-bh - 2 * m, bw + 2 * m:] - ii2[bh + 2 * m:, :-bw - 2 * m] + ii2[:-bh - 2 * m, :-bw - 2 * m]
    s2 = s2[:s.shape[0], :s.shape[1]]
    ok = np.argwhere((s == 0) & (s2 == 0))
    y8, x8 = ok[len(ok) // 2]
    y0, x0 = int(y8 * 8), int(x8 * 8)
R["box_xywh"] = [x0, y0, BW, BH]
box = ids[y0:y0 + BH, x0:x0 + BW].copy()
R["sea_provinces_in_box_before"] = int(np.unique(box).size)

with phase("2_relief_cells_in_box"):
    nbox = int(60000 * BW * BH / (W * H))
    lat = F.make_lattice(BW, BH, nbox, "hex", 0.3, False, 11)
    nbr = F.implicit_neighbors(lat, "hex6")
    hm = F.Heightmap(lat, nbr, np.random.default_rng(11))
    hm.run_template("Hill 1 80-90 40-60 40-60\nHill 5 20-30 25-75 25-75\nRange 2 30-50 30-70 30-70\nSmooth 2 0 0 0\nMask 1 0 0 0")
    q = np.quantile(hm.h, 1 - 0.30)
    h = np.clip(hm.h + (F.SEA_LEVEL - q) - 0.5, 0, 100)
    land = h >= F.SEA_LEVEL
R["cells_in_box"] = int(lat.n); R["land_cells"] = int(land.sum())

with phase("3_group_new_land_provinces"):
    e = F.edges_from_padded(nbr)
    ip, ix = F.to_csr(e, lat.n)
    comp = F.components(lat.n, e, land)
    target = max(1, int(land.sum() / 7.3))                 # 7,3 celdas por provincia (r2 con 60 000)
    own = F.group_cells(lat.n, ip, ix, land, target, np.ones(lat.n), np.ones(lat.n), lat.pts, BW, False, np.random.default_rng(12), 2, comp, "vec", e)

with phase("4_raster_box_and_merge"):
    g = h.reshape(lat.rows, lat.cols).astype(np.float32)
    hp = np.asarray(Image.fromarray(g, "F").resize((BW, BH), Image.BILINEAR))
    pix_land = hp >= F.SEA_LEVEL
    pix_land[:4] = pix_land[-4:] = False; pix_land[:, :4] = pix_land[:, -4:] = False   # costa dentro de la caja
    cr = F.rasterize(lat, BW, BH, cell_class=land, pix_class=pix_land, reach=1)
    newp = np.where(pix_land & land[cr], own[cr] + 1, 0)
    used = np.unique(newp[newp > 0])
    remap = np.zeros(int(newp.max()) + 1, np.int64); remap[used] = np.arange(N0 + 1, N0 + 1 + used.size)
    nb = np.where(newp > 0, remap[newp], box).astype(np.uint16)
    ids2 = ids.copy(); ids2[y0:y0 + BH, x0:x0 + BW] = nb
R["new_land_provinces"] = int(used.size)

with phase("5_fragments_in_expanded_box"):
    m = 64
    ya, yb = max(0, y0 - m), min(H, y0 + BH + m); xa, xb = max(0, x0 - m), min(W, x0 + BW + m)
    sub = ids2[ya:yb, xa:xb].astype(np.int32)
    fr = F.raster_fragments(sub, False)
    affected_sea = np.unique(box)
    frag_sea = [int(p) for p in affected_sea if fr[p] > 1]
    is_sea2 = np.r_[is_sea, np.zeros(used.size, bool)]
    fixed, merged, flipped, created, _ = F.fix_fragments2(sub, is_sea2[: int(sub.max()) + 1].copy(), False)
    ids2[ya:yb, xa:xb] = fixed
R["sea_provinces_split_by_new_land"] = len(frag_sea)
R["fix_merged_flipped_created"] = [merged, flipped, created]
before = np.bincount(ids.ravel(), minlength=N0 + 1)
after = np.bincount(ids2.ravel(), minlength=ids2.max() + 1)[:N0 + 1]
shr = [(int(p), round(float(after[p] / before[p]), 3)) for p in affected_sea]
R["sea_provinces_area_kept_frac"] = shr
R["sea_provinces_vanished"] = int(sum(1 for p in affected_sea if after[p] == 0))
R["existing_land_pixels_changed"] = int(((ids != ids2) & ~smask).sum())
R["raster_patch_MB_uint16_before_after"] = round(2 * 2 * (yb - ya) * (xb - xa) / 2**20, 2)
R["timings_s"] = T
print(json.dumps(R, indent=1))
