"""Mide el prototipo: python3 bench.py N kind outdir [--full]
kind: hex | square. Imprime tiempos por fase y memoria pico (tracemalloc + ru_maxrss)."""
import json
import os
import resource
import sys
import time
import tracemalloc

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge as F  # noqa: E402

N = int(sys.argv[1]); KIND = sys.argv[2]; OUT = sys.argv[3]
FULL = "--full" in sys.argv
W, H = 5616, 2160
SEED = 7
os.makedirs(OUT, exist_ok=True)
res = {"N": N, "kind": KIND}
tracemalloc.start()
T = {}


def phase(name):
    class _P:
        def __enter__(self):
            tracemalloc.reset_peak(); self.t = time.perf_counter()
        def __exit__(self, *a):
            dt = time.perf_counter() - self.t
            T[name] = (round(dt, 3), round(tracemalloc.get_traced_memory()[1] / 2**20, 1))
    return _P()


rng = np.random.default_rng(SEED)
with phase("lattice"):
    JIT = float(os.environ.get("JITTER", "0.9"))
    lat = F.make_lattice(W, H, N, KIND, JIT, True, SEED)
res["cells"] = lat.n
with phase("neighbors_implicit"):
    nbr = F.implicit_neighbors(lat, "hex6" if KIND == "hex" else "square8")
    nbr4 = F.implicit_neighbors(lat, "square4") if KIND == "square" else None

TEMPLATE = """Hill 8 35-55 5-95 15-85
Range 6 30-50 5-95 15-85
Smooth 2 0 0 0"""
CONTINENTS = """Hill 1 80-85 60-80 40-60
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
with phase("heightmap_3ops"):
    hm = F.Heightmap(lat, nbr, np.random.default_rng(SEED))
    hm.run_template(TEMPLATE)
    # nivel del mar automático: la tierra ocupa el 34 % (vanilla: 34,2 %)
    q = np.quantile(hm.h, 1 - 0.34)
    h = np.clip(hm.h + (F.SEA_LEVEL - q) - 0.5, 0, 100)
if FULL:
    with phase("heightmap_fmg_continents_13ops"):
        hm2 = F.Heightmap(lat, nbr, np.random.default_rng(SEED)); hm2.run_template(CONTINENTS)
land = h >= F.SEA_LEVEL
res["land_cells"] = int(land.sum())

with phase("features_components"):
    e_imp = F.edges_from_padded(nbr)
    comp_land = F.components(lat.n, e_imp, land)
    comp_water = F.components(lat.n, e_imp, ~land)
    # océano = componente de agua más grande; el resto son lagos (FMG: border → ocean)
    wl = comp_water[~land]; big = np.bincount(wl).argmax()
    is_ocean = (comp_water == big)
res["islands"] = int(np.unique(comp_land[land]).size)
res["lakes"] = int(np.unique(comp_water[(~land) & ~is_ocean]).size)

with phase("climate"):
    temp = F.temperature(lat, h)
    prec = F.precipitation(lat, h, temp)

with phase("rivers_flood_flow"):
    filled = F.priority_flood(h, nbr, is_ocean)
    recv, flux = F.flow(filled, nbr, prec / 10, is_ocean)
thr = np.quantile(flux[land], 0.93)
river_cells = land & (flux >= thr)
res["river_cells"] = int(river_cells.sum())

# --- ráster de celdas a 5616x2160
with phase("noise_warp"):
    amp = 0.35 * lat.dx
    warp = (F.value_noise(W, H, int(lat.dx * 2), amp, rng) + F.value_noise(W, H, int(lat.dx / 2) or 1, amp / 3, rng),
            F.value_noise(W, H, int(lat.dx * 2), amp, rng) + F.value_noise(W, H, int(lat.dx / 2) or 1, amp / 3, rng))
with phase("raster_3x3_plain"):
    ras3 = F.rasterize(lat, W, H, reach=1)
with phase("raster_5x5_plain"):
    ras5 = F.rasterize(lat, W, H, reach=2)
res["raster_3x3_vs_5x5_mismatch_px"] = int((ras3 != ras5).sum())
del ras3
with phase("raster_3x3_warp"):
    ras_w = F.rasterize(lat, W, H, reach=1, warp=warp)
# costa suave: altura bilineal por píxel y asignación restringida por clase
with phase("pixel_landmask_bilinear"):
    g = h.reshape(lat.rows, lat.cols).astype(np.float32)
    if lat.wrap_x:
        g = np.concatenate([g, g[:, :1]], axis=1)
    big = np.asarray(Image.fromarray(g, mode="F").resize((W + int(round(W / lat.cols)), H), Image.BILINEAR))
    off = int(round(W / lat.cols / 2))
    hp = big[:, off:off + W]
    pix_land = (hp + warp[0] * 0) >= F.SEA_LEVEL
with phase("raster_3x3_warp_classed"):
    ras = F.rasterize(lat, W, H, cell_class=land, pix_class=pix_land, reach=1, warp=warp)
pix_land = land[ras]
res["land_px_frac"] = round(float(pix_land.mean()), 4)

# --- vecindad: implícita frente a la del ráster (verdad para el juego)
with phase("raster_edges"):
    e_true = F.raster_edges(ras5, True)
def prf(e_imp, e_true):
    a = set(map(tuple, e_imp.tolist())); b = set(map(tuple, e_true.tolist()))
    tp = len(a & b); return {"implicit": len(a), "raster": len(b), "precision": round(tp / len(a), 4), "recall": round(tp / len(b), 4)}
res["adj_" + ("hex6" if KIND == "hex" else "square8") + "_vs_raster5x5"] = prf(e_imp, e_true)
if nbr4 is not None:
    res["adj_square4_vs_raster5x5"] = prf(F.edges_from_padded(nbr4), e_true)
e_true_w = F.raster_edges(ras, True)
res["adj_implicit_vs_raster_warp_classed"] = prf(e_imp, e_true_w)
# ráster a media resolución como grafo previo
with phase("raster_half_res_edges"):
    lat2 = F.Lattice(lat.kind, W // 2, H // 2, lat.cols, lat.rows, lat.dx / 2, lat.dy / 2, lat.row_shift / 2, lat.pts / 2, True)
    e_half = F.raster_edges(F.rasterize(lat2, W // 2, H // 2, reach=2), True)
res["adj_raster_half_vs_full"] = prf(e_half, e_true)
del ras5

# --- provincias sobre el grafo del ráster final
with phase("group_provinces"):
    indptr, indices = F.to_csr(e_true_w, lat.n)
    comp_l = F.components(lat.n, e_true_w, land)
    comp_s = F.components(lat.n, e_true_w, ~land)
    suit = np.clip((temp + 5) / 30, 0.05, 1) * np.clip(1 - (h - 20) / 80, 0.1, 1) * (1 + 2 * river_cells)
    step = 1 + 1.5 * (h >= 60) + 0.5 * river_cells          # montañas y ríos frenan (FMG getHeightCost/getRiverCost)
    own_l = F.group_cells(lat.n, indptr, indices, land, 2700, suit, step, lat.pts, W, True, rng, 2, comp_l, "vec", e_true_w)
    own_s = F.group_cells(lat.n, indptr, indices, ~land, 545, np.ones(lat.n), np.ones(lat.n), lat.pts, W, True, rng, 2, comp_s, "vec", e_true_w)
with phase("group_provinces_heapq_land_only"):
    _o = F.group_cells(lat.n, indptr, indices, land, 2700, suit, step, lat.pts, W, True, np.random.default_rng(1), 2, comp_l, "heap")
    nl = int(own_l[land].max()) + 1
    prov_of_cell = np.where(land, own_l + 1, own_s + 1 + nl).astype(np.int32)
with phase("province_raster_lut"):
    pid = prov_of_cell[ras]
res["land_provinces"] = nl; res["sea_provinces"] = int(own_s[~land].max()) + 1
area = np.bincount(pid.ravel())
res["empty_province_ids"] = int((np.bincount(pid.ravel(), minlength=int(prov_of_cell.max()) + 1)[1:] == 0).sum())
la = area[1:nl + 1]; sa = area[nl + 1:]
la = la[la > 0]; sa = sa[sa > 0]
res["land_area_px_pctl_5_25_50_75_95"] = np.percentile(la, [5, 25, 50, 75, 95]).astype(int).tolist()
res["sea_area_px_pctl_5_25_50_75_95"] = np.percentile(sa, [5, 25, 50, 75, 95]).astype(int).tolist()
with phase("fragments_check"):
    frags = F.raster_fragments(pid, True)
res["provinces_with_fragments"] = int((frags[1:] > 1).sum())
with phase("fix_fragments"):
    is_sea_p = np.zeros(int(pid.max()) + 1, bool); is_sea_p[nl + 1:] = True
    pid, merged, flipped, created, is_sea_p = F.fix_fragments2(pid, is_sea_p, True)
res["fragments_merged_flipped_new"] = [merged, flipped, created]
res["provinces_with_fragments_after_fix"] = int((F.raster_fragments(pid, True)[1:] > 1).sum())
# fragmentos con la costa por celdas (opción A: Voronoi deformado, sin clase por píxel)
pid_a = prov_of_cell[ras_w]
res["provinces_with_fragments_optionA_warp"] = int((F.raster_fragments(pid_a, True)[1:] > 1).sum())
pid_p = prov_of_cell[F.rasterize(lat, W, H, reach=1)]
res["provinces_with_fragments_plain_voronoi"] = int((F.raster_fragments(pid_p, True)[1:] > 1).sum())
del pid_a, pid_p

# --- estados (regiones) de ~5 provincias sobre el grafo de provincias
with phase("states"):
    pe = F.raster_edges(pid, True)
    npv = int(pid.max()) + 1
    ip2, ix2 = F.to_csr(pe, npv)
    pmask = np.zeros(npv, bool); pmask[:is_sea_p.size] = ~is_sea_p[:npv]; pmask[0] = False
    pmask &= np.bincount(pid.ravel(), minlength=npv)[:npv] > 0
    cx = np.bincount(pid.ravel() % 1, minlength=1)  # placeholder para no medir centroides aquí
    ys, xs = np.divmod(np.arange(W * H, dtype=np.int64)[::97], W)
    sub = pid.ravel()[::97]
    pc = np.column_stack([np.bincount(sub, weights=xs, minlength=npv) / np.maximum(np.bincount(sub, minlength=npv), 1),
                          np.bincount(sub, weights=ys, minlength=npv) / np.maximum(np.bincount(sub, minlength=npv), 1)])
    comp_p = F.components(npv, pe, pmask)
    own_st = F.group_cells(npv, ip2, ix2, pmask, round(nl / 4.92), np.ones(npv), np.ones(npv), pc, W, True, rng, 1, comp_p, "vec", pe)
st_sizes = np.bincount(own_st[pmask])
res["states"] = int(st_sizes.size)
res["provs_per_state_pctl_5_25_50_75_95"] = np.percentile(st_sizes, [5, 25, 50, 75, 95]).tolist()

# --- exportación mínima
with phase("export_bmp_csv"):
    npv = int(pid.max())
    cols = np.random.default_rng(SEED).choice(2**24 - 2, size=npv, replace=False) + 1   # sin 0x000000 ni 0xFFFFFF
    lut = np.zeros((npv + 1, 3), np.uint8)
    lut[1:, 0] = cols >> 16; lut[1:, 1] = (cols >> 8) & 255; lut[1:, 2] = cols & 255
    rgb = lut[pid]
    Image.fromarray(rgb, "RGB").save(os.path.join(OUT, "provinces.bmp"))
    with open(os.path.join(OUT, "definition.csv"), "w", encoding="cp1252", newline="") as f:
        f.write("province;red;green;blue;x;x\r\n")
        for i in range(1, npv + 1):
            f.write(f"{i};{lut[i,0]};{lut[i,1]};{lut[i,2]};Prov{i};x\r\n")
    # (el prototipo no renumera: la compactación tierra→mar y la retirada de ids vacíos es un paso aparte)
with phase("export_rivers_bmp"):
    riv = np.where(pix_land, 255, 254).astype(np.uint8)
    lw = np.clip(2 + 9 * (np.log(flux) - np.log(thr)) / (np.log(flux.max()) - np.log(thr) + 1e-9), 2, 11).astype(np.uint8)
    pts = lat.pts
    segs = 0
    for c in np.nonzero(river_cells)[0].tolist():
        r = int(recv[c])
        if r < 0:
            continue
        x0, y0 = pts[c]; x1, y1 = pts[r]
        if abs(x1 - x0) > W / 2:
            continue                                    # cruce de la costura: el prototipo lo omite
        n = int(abs(x1 - x0) + abs(y1 - y0)) + 1
        t = np.linspace(0, 1, n)
        xs = np.round(x0 + (x1 - x0) * t).astype(int); ys_ = np.round(y0 + (y1 - y0) * t).astype(int)
        # escalera 4-conexa: tras cada paso diagonal se inserta el píxel de esquina
        xs2 = np.repeat(xs, 2)[1:]; ys2 = np.repeat(ys_, 2)[:-1]
        xs2 = np.clip(xs2, 0, W - 1); ys2 = np.clip(ys2, 0, H - 1)
        ok = pix_land[ys2, xs2]
        riv[ys2[ok], xs2[ok]] = lw[c]
        segs += 1
    res["river_segments"] = segs
    pal = [0, 255, 0, 255, 0, 0] + [0, 0, 255] * 252 + [122, 122, 122, 255, 255, 255]
    im = Image.fromarray(riv, "P"); im.putpalette(pal); im.save(os.path.join(OUT, "rivers.bmp"))

res["phases_s_peakMiB"] = T
res["total_s"] = round(sum(v[0] for v in T.values()), 2)
res["ru_maxrss_MiB"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
print(json.dumps(res, indent=1))
with open(os.path.join(OUT, f"bench_{KIND}_{N}.json"), "w") as f:
    json.dump(res, f, indent=1)
