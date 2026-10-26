"""p2: importación de recursos de mapa (para quien domina el bitmap).

Escenarios medidos:
  A) solo provinces.bmp (+ terrain.bmp para tierra/mar): colores → ids nuevos (tierra primero), validación,
     vecinos, fragmentos, posiciones y estados reconstruidos.
  B) provinces.bmp + definition.csv + default.map: conserva ids; informe de validación.
  C) orientación: PNG con el norte arriba; detección automática con positions.txt si existe.
  D) ida y vuelta: importar lo que exportó p1 da los mismos ids (hash) y la misma tabla.
  E) terrain.bmp guardado en RGB por error → índices con la paleta de la instalación (SimpleFix).
Uso: python3 -I p2_import.py VANILLA_ROOT P1_MOD_DIR
"""
import hashlib
import io
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

VAN, P1 = sys.argv[1], sys.argv[2]
R, T = {}, {}


class phase:
    def __init__(self, k): self.k = k
    def __enter__(self): self.t = time.perf_counter()
    def __exit__(self, *a): T[self.k] = round(time.perf_counter() - self.t, 3)


def sha(a): return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


def read_rgb(path):
    im = Image.open(path)
    info = {"format": im.format, "mode": im.mode, "size": im.size}
    if im.mode != "RGB":
        im = im.convert("RGB")
    a = np.asarray(im)
    return ((a[..., 0].astype(np.uint32) << 16) | (a[..., 1].astype(np.uint32) << 8) | a[..., 2]), info


def colors_to_ids(packed, definition=None):
    """Devuelve ids uint16, tabla id→color, colores sin id (con píxeles) e ids sin píxeles."""
    flat = packed.ravel()
    ucol, inv, cnt = np.unique(flat, return_inverse=True, return_counts=True)
    if definition is None:
        return inv.reshape(packed.shape).astype(np.uint16) + 1, ucol, cnt, [], []
    lut = {c: i for i, c in definition.items()}
    idmap = np.array([lut.get(int(c), 0) for c in ucol], np.uint16)
    ids = idmap[inv].reshape(packed.shape)
    unmapped = [(int(c), int(n)) for c, n, i in zip(ucol, cnt, idmap) if i == 0]
    present = set(idmap.tolist())
    no_px = [i for i in definition if i not in present]
    return ids, ucol, cnt, unmapped, no_px


def read_definition(path):
    d, dup_colors, bad = {}, [], []
    seen = {}
    for ln, line in enumerate(open(path, encoding="cp1252"), 1):
        p = line.strip().split(";")
        if len(p) < 4 or not p[0].strip().isdigit():
            continue
        try:
            r, g, b = (int(float(v)) for v in p[1:4])
        except ValueError:
            bad.append(ln); continue
        c = (r << 16) | (g << 8) | b
        i = int(p[0])
        if c in seen:
            dup_colors.append((seen[c], i))
        seen[c] = i; d[i] = c
    return d, dup_colors, bad


def sea_starts(path):
    dm = open(path, encoding="cp1252").read()
    return [int(x) for x in re.search(r"sea_starts\s*=\s*\{([^}]*)\}", dm).group(1).split()]


# ------------------------------------------------------------------ A) solo BMP (+ terrain.bmp)
with phase("A1_read_bmp"):
    packed, info = read_rgb(VAN + "/map/provinces.bmp")
H, W = packed.shape
with phase("A2_colors_to_ids_np_unique"):
    ids0, ucol, cnt, _, _ = colors_to_ids(packed)
R["A_unique_colors"] = int(ucol.size)
R["A_black_white_used"] = [int(cnt[ucol == 0].sum()), int(cnt[ucol == 0xFFFFFF].sum())]
with phase("A3_land_sea_from_terrain254"):
    ter = np.asarray(Image.open(VAN + "/map/terrain.bmp"))
    n0 = int(ids0.max())
    a0 = np.bincount(ids0.ravel(), minlength=n0 + 1)
    w254 = np.bincount(ids0.ravel(), weights=(ter.ravel() == 254), minlength=n0 + 1)
    sea0 = w254 > a0 / 2
with phase("A4_tiny_and_fragments"):
    frag = F.raster_fragments(ids0.astype(np.int32), True)
R["A_tiny_provinces_lt_6px"] = int(((a0 > 0) & (a0 < 6)).sum())
R["A_colors_in_several_pieces"] = int((frag[1:] > 1).sum())
with phase("A5_renumber_land_first"):
    order = np.r_[np.flatnonzero(~sea0[1:]) + 1, np.flatnonzero(sea0[1:]) + 1]
    remap = np.zeros(n0 + 1, np.uint16); remap[order] = np.arange(1, n0 + 1)
    ids = remap[ids0]
    NL = int((~sea0[1:]).sum())
R["A_land_sea"] = [NL, n0 - NL]
with phase("A6_neighbors"):
    pe = F.raster_edges(ids.astype(np.int32), True)
deg = np.bincount(pe.ravel(), minlength=n0 + 1)
R["A_isolated"] = int((deg[1:] == 0).sum())
is_sea = np.zeros(n0 + 1, bool); is_sea[NL + 1:] = True
with phase("A7_states_on_province_graph"):
    le = pe[(~is_sea[pe[:, 0]]) & (~is_sea[pe[:, 1]])]
    ip, ix = F.to_csr(le, n0 + 1)
    pm = ~is_sea.copy(); pm[0] = False
    # centroides aproximados por submuestreo
    sub = ids[::4, ::4].ravel(); yy, xx = np.divmod(np.arange(sub.size), W // 4 + (W % 4 > 0))
    c_ = np.maximum(np.bincount(sub, minlength=n0 + 1), 1)
    pc = np.column_stack([np.bincount(sub, weights=xx * 4, minlength=n0 + 1) / c_, np.bincount(sub, weights=yy * 4, minlength=n0 + 1) / c_])
    comp = F.components(n0 + 1, le, pm)
    st = F.group_cells(n0 + 1, ip, ix, pm, round(NL / 4.92), np.ones(n0 + 1), np.ones(n0 + 1), pc, W, True, np.random.default_rng(1), 1, comp, "vec", le)
sz = np.bincount(st[1:NL + 1])
R["A_states_rebuilt"] = int((sz > 0).sum())
R["A_state_size_pctl_5_50_95"] = np.percentile(sz[sz > 0], [5, 50, 95]).tolist()

# ------------------------------------------------------------------ B) BMP + definition + default.map
with phase("B1_definition_and_lut"):
    d, dupc, bad = read_definition(VAN + "/map/definition.csv")
    idsB, _, _, unmapped, nopx = colors_to_ids(packed, d)
    ss = sea_starts(VAN + "/map/default.map")
ids_sorted = sorted(d)
R["B_definition"] = {"ids": len(d), "dup_colors": len(dupc), "bad_rows": bad[:5], "unmapped_colors": len(unmapped),
                     "unmapped_px": int(sum(n for _, n in unmapped)), "ids_without_pixels": len(nopx),
                     "gaps": int(max(d) - len(d)), "sea_starts_dups": len(ss) - len(set(ss))}

# ------------------------------------------------------------------ C) orientación
txt = open(VAN + "/map/positions.txt", encoding="cp1252").read()
units = [(int(a), float(x), float(y)) for a, x, y in re.findall(r"(?m)^(\d+)\s*=\s*\{\s*unit\s*=\s*\{\s*x\s*=\s*([\d.]+)\s*y\s*=\s*([\d.]+)", txt)]
with phase("C1_orientation_detect"):
    def inside(idsx):
        p = np.array([u[0] for u in units]); x = np.minimum(np.array([u[1] for u in units]).astype(int), W - 1)
        y = np.minimum(np.array([u[2] for u in units]).astype(int), H - 1)
        return float((idsx[y, x] == p).mean())
    north_up = idsB[::-1]                         # lo que daría un PNG dibujado con el norte arriba
    score_as_is, score_flip = inside(north_up), inside(north_up[::-1])
R["C_units_checked"] = len(units)
R["C_north_up_png_scores_as_is_vs_flipped"] = [round(score_as_is, 4), round(score_flip, 4)]
# sin positions: heurística por la fila más «polar»: ¿hay más mar en la fila 0 o en la H-1? (dudosa)
R["C_heuristic_sea_frac_row0_rowH"] = [round(float(is_sea[remap[ids0[0]]].mean()), 3), round(float(is_sea[remap[ids0[-1]]].mean()), 3)]

# ------------------------------------------------------------------ D) ida y vuelta del export de p1
with phase("D1_roundtrip_import_p1"):
    pk, inf = read_rgb(P1 + "/map/provinces.bmp")
    d1, dup1, bad1 = read_definition(P1 + "/map/definition.csv")
    idsD, _, _, um1, np1 = colors_to_ids(pk, d1)
    ss1 = sea_starts(P1 + "/map/default.map")
R["D_roundtrip"] = {"unmapped": len(um1), "ids_without_px": len(np1), "dup_colors": len(dup1),
                    "sea_starts_contiguous_after_land": ss1 == list(range(min(ss1), max(ss1) + 1)) and min(ss1) == max(d1) - len(ss1) + 1,
                    "ids_hash": sha(idsD)}
# reescribir el BMP con Pillow y releer: mismos ids
bio = io.BytesIO(); Image.open(P1 + "/map/provinces.bmp").save(bio, "BMP"); bio.seek(0)
pk2 = np.asarray(Image.open(bio).convert("RGB"))
R["D_bmp_rewrite_identical"] = bool((((pk2[..., 0].astype(np.uint32) << 16) | (pk2[..., 1].astype(np.uint32) << 8) | pk2[..., 2]) == pk).all())

# ------------------------------------------------------------------ E) terrain.bmp en RGB por error
with phase("E1_terrain_rgb_to_index"):
    tim = Image.open(VAN + "/map/terrain.bmp")
    pal = np.array(tim.getpalette()[:768]).reshape(256, 3)
    rgb = np.asarray(tim.convert("RGB"))
    key = (pal[:, 0] << 16) | (pal[:, 1] << 8) | pal[:, 2]
    k = (rgb[..., 0].astype(np.int64) << 16) | (rgb[..., 1].astype(np.int64) << 8) | rgb[..., 2]
    # índice preferido por color: el menor índice de tierra (0-63) o 254; los colores fuera de paleta → el más cercano
    pref = {}
    for i in list(range(64)) + [254] + list(range(64, 254)) + [255]:
        pref.setdefault(int(key[i]), i)
    ks = np.array(sorted(pref)); vs = np.array([pref[x] for x in ks])
    pos = np.clip(np.searchsorted(ks, k), 0, ks.size - 1)
    exact = ks[pos] == k
    back = vs[pos]
R["E_rgb_terrain_px_not_in_palette"] = int((~exact).sum())
R["E_rgb_terrain_index_mismatch_px"] = int((back != np.asarray(tim)).sum())
R["E_mismatch_detail_original_indices"] = np.unique(np.asarray(tim)[back != np.asarray(tim)]).tolist()[:10]
R["timings_s"] = T
print(json.dumps(R, indent=1))
