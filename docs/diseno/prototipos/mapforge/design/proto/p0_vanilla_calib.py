"""p0: calibración sobre vanilla (solo lectura) para el diseño del taller de mapas.

Mide: (a) relación text_scale ~ área; (b) hueco en píxeles de las adyacencias `sea`;
(c) clasificación tierra/mar de un BMP importado por mayoría de terrain.bmp (254) frente a sea_starts;
(d) colores únicos por bincount de 2^24 frente a np.unique; (e) detección de orientación con positions.txt;
(f) ambigüedad RGB→índice de las paletas de terrain.bmp y rivers.bmp; (g) offsets de posiciones frente a unit.
Uso: python3 -I p0_vanilla_calib.py /home/user/corpus/vanilla
"""
import json
import re
import sys
import time

import numpy as np
from PIL import Image

ROOT = sys.argv[1]
M = ROOT + "/map/"
res = {}
T = {}


def tic(k):
    T[k] = time.perf_counter()


def toc(k):
    T[k] = round(time.perf_counter() - T[k], 3)


# --- ids
tic("read_bmp_lut")
rgb = np.asarray(Image.open(M + "provinces.bmp").convert("RGB"))
H, W, _ = rgb.shape
packed = (rgb[..., 0].astype(np.uint32) << 16) | (rgb[..., 1].astype(np.uint32) << 8) | rgb[..., 2]
toc("read_bmp_lut")
tic("unique_colors_bincount")
cnt = np.bincount(packed.ravel(), minlength=1 << 24)
ucols = np.flatnonzero(cnt)
toc("unique_colors_bincount")
tic("unique_colors_np_unique")
u2 = np.unique(packed)
toc("unique_colors_np_unique")
res["unique_colors"] = int(ucols.size)
assert u2.size == ucols.size

lut = np.zeros(1 << 24, np.uint16)
names = {}
for line in open(M + "definition.csv", encoding="cp1252"):
    p = line.strip().split(";")
    if len(p) < 4 or not p[0].strip().isdigit():
        continue
    i = int(p[0]); r, g, b = (int(float(v)) for v in p[1:4])
    lut[(r << 16) | (g << 8) | b] = i
ids = lut[packed]
N = int(ids.max())
dm = open(M + "default.map", encoding="cp1252").read()
sea = set(int(x) for x in re.search(r"sea_starts\s*=\s*\{([^}]*)\}", dm).group(1).split())
is_sea = np.zeros(N + 1, bool); is_sea[list(sea)] = True
area = np.bincount(ids.ravel(), minlength=N + 1)

# --- (c) tierra/mar por mayoría del índice 254 de terrain.bmp
tic("classify_land_sea_terrain254")
ter = np.asarray(Image.open(M + "terrain.bmp"))
w254 = np.bincount(ids.ravel(), weights=(ter.ravel() == 254), minlength=N + 1)
pred_sea = w254 > area / 2
toc("classify_land_sea_terrain254")
valid = area > 0
valid[0] = False
res["landsea_by_terrain254_wrong"] = int((pred_sea[valid] != is_sea[valid]).sum())
res["landsea_by_terrain254_wrong_ids"] = np.flatnonzero(valid & (pred_sea != is_sea)).tolist()[:10]
# por rivers.bmp
riv = np.asarray(Image.open(M + "rivers.bmp"))
r254 = np.bincount(ids.ravel(), weights=(riv.ravel() == 254), minlength=N + 1)
res["landsea_by_rivers254_wrong"] = int(((r254 > area / 2)[valid] != is_sea[valid]).sum())

# --- (f) paletas: índices usados con el mismo RGB que otro índice
for name, img in (("terrain", Image.open(M + "terrain.bmp")), ("rivers", Image.open(M + "rivers.bmp"))):
    pal = np.array(img.getpalette()[:768]).reshape(256, 3)
    arr = np.asarray(img)
    used = np.flatnonzero(np.bincount(arr.ravel(), minlength=256))
    key = pal[:, 0] * 65536 + pal[:, 1] * 256 + pal[:, 2]
    amb = [int(i) for i in used if (key == key[i]).sum() > 1]
    res[f"{name}_palette_distinct"] = int(np.unique(key).size)
    res[f"{name}_used_indices"] = int(used.size)
    res[f"{name}_used_indices_ambiguous_rgb"] = amb
    # ¿se puede reconstruir el índice desde RGB eligiendo el índice usado más frecuente por color?
    rgbimg = np.asarray(img.convert("RGB"))
    k = (rgbimg[..., 0].astype(np.int64) << 16) | (rgbimg[..., 1].astype(np.int64) << 8) | rgbimg[..., 2]
    inv = {}
    hist = np.bincount(arr.ravel(), minlength=256)
    for i in np.argsort(-hist):
        inv.setdefault(int(key[i]), int(i))
    ks = np.array(sorted(inv)); vs = np.array([inv[x] for x in ks])
    back = vs[np.searchsorted(ks, k)]
    res[f"{name}_rgb_roundtrip_px_wrong"] = int((back != arr).sum())

# --- positions.txt: bloques por provincia (regex simple)
txt = open(M + "positions.txt", encoding="cp1252").read()
blocks = {}
for m in re.finditer(r"(?m)^(\d+)\s*=\s*\{", txt):
    blocks[int(m.group(1))] = m.end()
starts = sorted(blocks.items(), key=lambda kv: kv[1])
pos = {}
for k, (pid, s) in enumerate(starts):
    e = starts[k + 1][1] if k + 1 < len(starts) else len(txt)
    body = txt[s:e]
    d = {}
    for key in ("unit", "text_position", "building_construction", "military_construction", "factory"):
        mm = re.search(key + r"\s*=\s*\{\s*x\s*=\s*([\d.]+)\s*y\s*=\s*([\d.]+)", body)
        if mm:
            d[key] = (float(mm.group(1)), float(mm.group(2)))
    for key in ("fort", "naval_base", "railroad"):
        mm = re.search(r"\b" + key + r"\s*=\s*\{\s*x\s*=\s*([\d.]+)\s*y\s*=\s*([\d.]+)", body)
        if mm:
            d["bp_" + key] = (float(mm.group(1)), float(mm.group(2)))
    mm = re.search(r"text_scale\s*=\s*([\d.]+)", body)
    if mm:
        d["text_scale"] = float(mm.group(1))
    pos[pid] = d

# (a) text_scale ~ a * sqrt(area)^b
xs, ys = [], []
for pid, d in pos.items():
    if "text_scale" in d and area[pid] > 0 and not is_sea[pid]:
        xs.append(np.log(area[pid])); ys.append(np.log(d["text_scale"]))
b, a = np.polyfit(xs, ys, 1)
res["text_scale_fit_land"] = {"scale = A * area^B": [round(float(np.exp(a)), 3), round(float(b), 3)],
                              "r": round(float(np.corrcoef(xs, ys)[0, 1]), 3), "n": len(xs)}

# (e) orientación: fracción de unit dentro de su provincia, tal cual y volteado
def inside_frac(idarr):
    ok = tot = 0
    for pid, d in pos.items():
        if "unit" in d:
            x, y = d["unit"]; xi = min(W - 1, int(x)); yi = min(H - 1, int(y))
            tot += 1; ok += int(idarr[yi, xi] == pid)
    return round(ok / tot, 4)
tic("orientation_check")
res["unit_inside_as_is"] = inside_frac(ids)
res["unit_inside_flipped"] = inside_frac(ids[::-1])
toc("orientation_check")

# (g) distancia (px) de cada clave a unit, mediana, en tierra
for key in ("text_position", "building_construction", "military_construction", "factory", "bp_fort", "bp_railroad"):
    dd = [np.hypot(d[key][0] - d["unit"][0], d[key][1] - d["unit"][1]) for p, d in pos.items()
          if key in d and "unit" in d and not is_sea[p]]
    res["dist_to_unit_median_" + key] = round(float(np.median(dd)), 1)
# naval_base: distancia al píxel de tierra de su provincia más cercano (¿en el borde?)
nb_on_sea = 0; nbt = 0
for p, d in pos.items():
    if "bp_naval_base" in d:
        x, y = d["bp_naval_base"]; nbt += 1
        nb_on_sea += int(is_sea[ids[min(H - 1, int(y)), min(W - 1, int(x))]])
res["naval_base_on_sea_px"] = [nb_on_sea, nbt]

# (b) hueco de las adyacencias sea: distancia mínima entre píxeles de A y B
tic("sea_adjacency_gaps")
ys_all, xs_all = np.divmod(np.arange(W * H, dtype=np.int64), W)
order = np.argsort(ids.ravel(), kind="stable")
bounds = np.searchsorted(ids.ravel()[order], np.arange(N + 2))
def pix(p):
    o = order[bounds[p]:bounds[p + 1]]
    return np.column_stack([xs_all[o], ys_all[o]]).astype(np.float64)
gaps = []
for line in open(M + "adjacencies.csv", encoding="cp1252"):
    if line.startswith("#") or ";" not in line:
        continue
    f = line.split(";")
    if len(f) < 4 or f[2] != "sea":
        continue
    a, b = int(f[0]), int(f[1])
    A, B = pix(a), pix(b)
    if A.shape[0] > 3000:
        A = A[:: A.shape[0] // 3000 + 1]
    if B.shape[0] > 3000:
        B = B[:: B.shape[0] // 3000 + 1]
    dx = np.abs(A[:, None, 0] - B[None, :, 0]); dx = np.minimum(dx, W - dx)
    dmin = float(np.sqrt((dx ** 2 + (A[:, None, 1] - B[None, :, 1]) ** 2).min()))
    gaps.append(dmin)
toc("sea_adjacency_gaps")
g = np.array(gaps)
res["sea_adjacency_gap_px_pctl_0_25_50_75_90_100"] = np.percentile(g, [0, 25, 50, 75, 90, 100]).round(1).tolist()
res["sea_adjacency_n"] = int(g.size)

res["timings_s"] = T
print(json.dumps(res, indent=1))
