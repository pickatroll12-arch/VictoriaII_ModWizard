"""mf_lib: derivaciones del taller corregidas tras la verificación (v2). numpy + Pillow + stdlib.

- positions(): puntos secundarios por dirección unitaria × min(d, r) con 8 direcciones (M6); centroide sin
  trigonometría (corrección de envoltura solo para las provincias que tocan x=0 y x=W-1) (M2).
- suggest_straits(): igual que p1.
- learn_install(): paletas, frecuencias de índices de terrain.bmp por categoría, anchos de rivers.bmp usados y
  paleta del colormap por categoría (y bajo el mar), todo leído de la instalación en tiempo de ejecución (M4, m7).
- terrain_index_by_state_category(): un índice por (estado, categoría) entre los índices realmente usados (M4).
- draw_rivers(): trazos por tramo con 0 en el nacimiento, 1 en la confluencia, 4-conexos y anchos aprendidos (M5).
- dds_a8r8g8b8() con cabecera de vanilla (LINEARSIZE, mips hasta 1×1) y dds_dxt3() (m1, R7).
"""
from __future__ import annotations

import math
import re
import struct

import numpy as np
from PIL import Image


# ---------------------------------------------------------------- posiciones
def positions(ids: np.ndarray, is_sea: np.ndarray, NP: int, cap: int = 24, band: int = 256):
    H, W = ids.shape
    flat = ids.ravel()
    area = np.bincount(flat, minlength=NP + 1)
    touch = np.zeros(NP + 1, bool)
    touch[np.intersect1d(ids[:, 0], ids[:, -1])] = True               # provincias partidas por la costura
    sx = np.zeros(NP + 1); sy = np.zeros(NP + 1)
    xr = np.arange(W, dtype=np.float64)
    for y0 in range(0, H, band):
        blk = ids[y0:y0 + band]; bf = blk.ravel()
        X = np.tile(xr, blk.shape[0])
        X = X + W * (touch[bf] & (X < W / 2))
        sx += np.bincount(bf, weights=X, minlength=NP + 1)
        sy += np.bincount(bf, weights=np.repeat(np.arange(y0, y0 + blk.shape[0], dtype=np.float64), W), minlength=NP + 1)
    cx = (sx / np.maximum(area, 1)) % W; cy = sy / np.maximum(area, 1)
    # distancia al borde (erosiones 4-conexas con tope)
    cur = np.ones((H, W), bool)
    cur[:, :-1] &= ids[:, :-1] == ids[:, 1:]; cur[:, 1:] &= ids[:, 1:] == ids[:, :-1]
    cur[:, -1] &= ids[:, -1] == ids[:, 0]; cur[:, 0] &= ids[:, 0] == ids[:, -1]
    cur[:-1] &= ids[:-1] == ids[1:]; cur[1:] &= ids[1:] == ids[:-1]
    cur[0] = False; cur[-1] = False
    dist = cur.astype(np.uint8)
    tmp = np.empty_like(cur)
    for _ in range(cap - 1):
        np.copyto(tmp, cur)
        tmp[:, 1:] &= cur[:, :-1]; tmp[:, :-1] &= cur[:, 1:]; tmp[:, 0] &= cur[:, -1]; tmp[:, -1] &= cur[:, 0]
        tmp[1:] &= cur[:-1]; tmp[:-1] &= cur[1:]
        if not tmp.any():
            break
        dist += tmp; cur, tmp = tmp, cur
    del cur, tmp
    dflat = dist.ravel()
    CB = cap + 1                                                        # distancias 0..cap
    hist = np.bincount(flat.astype(np.int64) * CB + dflat, minlength=(NP + 1) * CB).reshape(NP + 1, CB)
    maxd = (CB - 1 - np.argmax(hist[:, ::-1] > 0, axis=1)).astype(np.int64)
    del hist
    cand = np.flatnonzero(dflat == maxd[flat])
    cp = flat[cand].astype(np.int64)
    cyy, cxx = np.divmod(cand, W)
    dxc = np.abs(cxx - cx[cp]); dxc = np.minimum(dxc, W - dxc)
    d2 = dxc ** 2 + (cyy - cy[cp]) ** 2
    o = np.lexsort((d2, cp)); first = np.ones(o.size, bool); first[1:] = cp[o][1:] != cp[o][:-1]
    ux = np.zeros(NP + 1, np.int64); uy = np.zeros(NP + 1, np.int64)
    ux[cp[o][first]] = cxx[o][first]; uy[cp[o][first]] = cyy[o][first]
    # puntos secundarios: dirección unitaria × min(d, r); 8 direcciones probadas en orden distinto por clave
    dirs = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    pid = np.arange(NP + 1)
    r = np.maximum(maxd - 1, 0)
    keys = {"building_construction": (6, 0), "military_construction": (7, 2), "factory": (8, 4), "fort": (10, 6), "railroad": (5, 1)}
    extra = {}
    for k, (dd, start) in keys.items():
        px = ux.copy(); py = uy.copy(); done = np.zeros(NP + 1, bool)
        for j in range(8):
            ddx, ddy = dirs[(start + j) % 8]
            norm = math.sqrt(ddx * ddx + ddy * ddy)
            step = np.minimum(dd, r).astype(np.float64)
            qx = (ux + np.round(ddx / norm * step).astype(np.int64)) % W
            qy = np.clip(uy + np.round(ddy / norm * step).astype(np.int64), 0, H - 1)
            ok = (~done) & (ids[qy, qx] == pid) & (dist[qy, qx] >= 2) & (step >= 2)
            px[ok] = qx[ok]; py[ok] = qy[ok]; done |= ok
        extra[k] = (px, py)
    del dist
    # naval_base: píxel de mar contiguo más cercano a unit
    a1 = ids[:, :-1].ravel(); b1 = ids[:, 1:].ravel()
    i1 = np.flatnonzero((~is_sea[a1]) & is_sea[b1]); sea_px = i1 + 1 + (i1 // (W - 1))
    i1b = np.flatnonzero(is_sea[a1] & (~is_sea[b1])); sea_px2 = i1b + (i1b // (W - 1))
    lp = np.concatenate([a1[i1], b1[i1b]]); sp = np.concatenate([sea_px, sea_px2])
    a2 = ids[:-1].ravel(); b2 = ids[1:].ravel()
    j1 = np.flatnonzero((~is_sea[a2]) & is_sea[b2]); j1b = np.flatnonzero(is_sea[a2] & (~is_sea[b2]))
    lp = np.concatenate([lp, a2[j1], b2[j1b]]).astype(np.int64); sp = np.concatenate([sp, j1 + W, j1b])
    syy, sxx = np.divmod(sp, W)
    ddx_ = np.abs(sxx - ux[lp]); ddx_ = np.minimum(ddx_, W - ddx_)
    dd_ = ddx_ ** 2 + (syy - uy[lp]) ** 2
    o = np.lexsort((dd_, lp)); first = np.ones(o.size, bool); first[1:] = lp[o][1:] != lp[o][:-1]
    nbx = np.full(NP + 1, -1, np.int64); nby = np.full(NP + 1, -1, np.int64)
    nbx[lp[o][first]] = sxx[o][first]; nby[lp[o][first]] = syy[o][first]
    # text_scale con libm de Python (no ufuncs SIMD/SVML: misma salida en cualquier CPU)
    text_scale = [round(0.749 * math.pow(max(int(a), 1), 0.214), 2) for a in area.tolist()]
    return dict(area=area, cx=cx, cy=cy, ux=ux, uy=uy, maxd=maxd, extra=extra, nbx=nbx, nby=nby, text_scale=text_scale)


# ---------------------------------------------------------------- estrechos (igual que p1)
def suggest_straits(ids, is_sea, pe, D=8):
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
    ll = pe[(~is_sea[pe[:, 0]]) & (~is_sea[pe[:, 1]])]
    nb = set(map(tuple, ll.tolist()))
    if P.size:
        P = P[np.array([(a, b) not in nb for a, b in P[:, :2].tolist()], bool)]
    if P.size:
        o = np.lexsort((P[:, 2], P[:, 3], P[:, 1], P[:, 0])); P = P[o]
        f = np.ones(len(P), bool); f[1:] = (P[1:, 0] != P[:-1, 0]) | (P[1:, 1] != P[:-1, 1])
        P = P[f]
    return P


# ---------------------------------------------------------------- aprendizaje de la instalación (en memoria)
CATS = ["ocean", "arctic", "farmlands", "forest", "hills", "woods", "mountain", "steppe", "plains", "jungle", "marsh", "desert"]


def learn_install(root: str, min_share: float = 0.005) -> dict:
    txt = open(root + "/map/terrain.txt", encoding="cp1252").read()
    cat_of = {int(m.group(1)): m.group(2) for m in re.finditer(r"text_(\d+)\s*=\s*\{\s*type\s*=\s*(\w+)", txt)}
    tim = Image.open(root + "/map/terrain.bmp"); ter = np.asarray(tim)
    rim = Image.open(root + "/map/rivers.bmp"); riv = np.asarray(rim)
    cnt = np.bincount(ter.ravel(), minlength=256)
    idx_by_cat: dict[str, list[tuple[int, float]]] = {}
    for c in set(cat_of.values()):
        ii = [i for i, cc in cat_of.items() if cc == c]
        tot = cnt[ii].sum()
        if tot == 0:
            continue
        ok = [(i, cnt[i] / tot) for i in sorted(ii) if cnt[i] / tot >= min_share]   # índices usados de verdad
        s = sum(w for _, w in ok)
        idx_by_cat[c] = [(i, w / s) for i, w in ok]
    rcnt = np.bincount(riv.ravel(), minlength=256)
    widths = [i for i in range(2, 12) if rcnt[i] > 0]
    width_share = [float(rcnt[i] / rcnt[widths].sum()) for i in widths]
    # paleta del colormap por categoría (colormap a W/3 con 4 px de margen) y bajo el agua
    cm = np.asarray(Image.open(root + "/map/terrain/colormap.dds").convert("RGB")).astype(np.float32)
    h3, w3 = cm.shape[0], cm.shape[1] - 8
    sub = ter[1::3, 1::3][:h3, :w3]; c2 = cm[:, 4:4 + w3]
    lut = np.full(256, -1)
    for i, c in cat_of.items():
        lut[i] = CATS.index(c) if c in CATS else CATS.index("desert")
    lut[254] = 0
    sc = lut[sub]
    pal = np.zeros((len(CATS), 3), np.float32)
    for k in range(len(CATS)):
        m = sc == k
        if m.sum() > 100:
            pal[k] = c2[m].mean(0)
    land_mean = c2[sc > 0].mean(0)
    for k in range(len(CATS)):
        if not pal[k].any():
            pal[k] = land_mean
    # agua (colormap_water) por profundidad aproximada: media del agua de vanilla
    wat = np.asarray(Image.open(root + "/map/terrain/colormap_water.dds").convert("RGB")).astype(np.float32)
    sea6 = (ter[2::6, 2::6] == 254)[:wat.shape[0], :wat.shape[1]]
    return dict(cat_of=cat_of, idx_by_cat=idx_by_cat, widths=widths, width_share=width_share,
                tpal=tim.getpalette()[:768], rpal=rim.getpalette()[:768], cm_pal=pal, cm_land_mean=land_mean,
                water_mean=wat[sea6].mean(0), cm_shape=cm.shape)


def terrain_index_by_state_category(pcat, ids, state_of_prov, idx_by_cat, rng):
    """Un índice de textura por (estado, categoría), elegido entre los usados por la instalación con su frecuencia."""
    nst = int(state_of_prov.max()) + 2
    lut = np.full((nst, len(CATS)), 254, np.uint8)
    for k, c in enumerate(CATS):
        if k == 0:
            continue
        opts = idx_by_cat.get(c) or idx_by_cat["plains"]
        ii = np.array([i for i, _ in opts]); ww = np.array([w for _, w in opts])
        lut[:, k] = ii[rng.choice(ii.size, size=nst, p=ww)]
    st_px = state_of_prov[ids] + 1                                   # -1 (mar) → 0
    return lut[st_px, pcat]


# ---------------------------------------------------------------- ríos
def draw_rivers(riv: np.ndarray, paths: list[tuple[np.ndarray, np.ndarray, np.ndarray]]):
    """riv: (H,W) uint8 con 254 en agua y 255 en tierra. paths: (xs, ys, width) por tramo, ya en orden (troncos
    primero). Cada tramo: 0 en el primer píxel; se detiene antes del agua (desembocadura) o al tocar otro río,
    marcando 1 en su último píxel (confluencia). Polilínea 4-conexa (escalera)."""
    H, W = riv.shape
    stats = {"paths": 0, "sources": 0, "confluences": 0, "mouths": 0, "dropped_short": 0}
    for xs, ys, wd in paths:
        # rasterizar la polilínea en escalera 4-conexa
        px, py, pw = [], [], []
        lx, ly = None, None
        for k in range(len(xs) - 1):
            x0, y0, x1, y1 = xs[k], ys[k], xs[k + 1], ys[k + 1]
            dx = x1 - x0
            if dx > W / 2: dx -= W
            if dx < -W / 2: dx += W
            ix0, iy0 = int(math.floor(x0)), int(math.floor(y0))           # extremos enteros: sin huecos
            idx_, idy = int(math.floor(x0 + dx)) - ix0, int(math.floor(y1)) - iy0
            n = abs(idx_) + abs(idy) + 1
            for t in range(n):
                fx = (ix0 + int(round(idx_ * t / max(n - 1, 1)))) % W
                fy = min(max(iy0 + int(round(idy * t / max(n - 1, 1))), 0), H - 1)
                if lx is not None and fx != lx and fy != ly:            # paso diagonal: insertar esquina
                    px.append(fx); py.append(ly); pw.append(wd[k])
                if (fx, fy) != (lx, ly):
                    px.append(fx); py.append(fy); pw.append(wd[k])
                lx, ly = fx, fy
        # quitar duplicados consecutivos y bucles
        seen = set(); qx, qy, qw = [], [], []
        for a, b, c in zip(px, py, pw):
            if (a, b) in seen:
                break
            seen.add((a, b)); qx.append(a); qy.append(b); qw.append(c)
        out = []; end = None
        mine = set()
        for i, (a, b, c) in enumerate(zip(qx, qy, qw)):
            if riv[b, a] == 254:
                end = "mouth"; break
            if riv[b, a] != 255:
                end = "conf_hit"; break
            touch = False
            for na, nb in (((a + 1) % W, b), ((a - 1) % W, b), (a, min(b + 1, H - 1)), (a, max(b - 1, 0))):
                if (na, nb) not in mine and riv[nb, na] not in (254, 255):
                    touch = True
            out.append((a, b, c)); mine.add((a, b))
            if touch:
                end = "conf"; break
        stats[f"end_{end}"] = stats.get(f"end_{end}", 0) + 1
        if out:
            stats.setdefault("_last", []).append((end, out[-1][0], out[-1][1], len(out)))
        if end == "conf_hit" and out:
            end = "conf"
        if len(out) < 3:
            stats["dropped_short"] += 1
            continue
        for a, b, c in out:
            riv[b, a] = c
        a, b, _ = out[0]; riv[b, a] = 0; stats["sources"] += 1
        if end == "conf":
            a, b, _ = out[-1]; riv[b, a] = 1; stats["confluences"] += 1
        elif end == "mouth":
            stats["mouths"] += 1
        stats["paths"] += 1
    return stats


def clean_isolated(riv):
    r = riv < 254
    n4 = np.zeros(r.shape, np.int8)
    n4[:, 1:] += r[:, :-1]; n4[:, :-1] += r[:, 1:]; n4[:, 0] += r[:, -1]; n4[:, -1] += r[:, 0]
    n4[1:] += r[:-1]; n4[:-1] += r[1:]
    iso = r & (n4 == 0)
    riv[iso] = 255
    return int(iso.sum())


def river_report(riv: np.ndarray) -> dict:
    r = (riv < 254)
    H, W = r.shape
    def sh(a, dy, dx):
        b = np.zeros_like(a)
        ys = slice(max(dy, 0), H + min(dy, 0)); yd = slice(max(-dy, 0), H + min(-dy, 0))
        b[ys] = np.roll(a, dx, axis=1)[yd]
        return b
    n4 = sum(sh(r, dy, dx).astype(np.int8) for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)))
    nd = sum(sh(r, dy, dx).astype(np.int8) for dy, dx in ((1, 1), (1, -1), (-1, 1), (-1, -1)))
    water = riv == 254
    w4 = sum(sh(water, dy, dx).astype(np.int8) for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)))
    ends = r & (n4 == 1)
    return {"river_px": int(r.sum()), "idx0": int((riv == 0).sum()), "idx1": int((riv == 1).sum()),
            "widths": {int(i): int((riv == i).sum()) for i in range(2, 12) if (riv == i).any()},
            "diag_only_px": int((r & (n4 == 0) & (nd > 0)).sum()), "isolated_px": int((r & (n4 == 0) & (nd == 0)).sum()),
            "endpoints": int(ends.sum()), "endpoints_source0": int((ends & (riv == 0)).sum()),
            "endpoints_conf1": int((ends & (riv == 1)).sum()), "endpoints_touch_water": int((ends & (w4 > 0)).sum()),
            "river_px_on_water": 0}


# ---------------------------------------------------------------- DDS
def _dds_header(w, h, mips, linear, pf, caps1):
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if mips else 0)
    hdr = struct.pack("<4sI6I44x", b"DDS ", 124, flags, h, w, linear, 0, mips)
    caps = struct.pack("<4I4x", caps1, 0, 0, 0)
    return hdr + pf + caps


def dds_a8r8g8b8(img: np.ndarray, mips: bool = False) -> bytes:
    """Cabecera como la de vanilla: flags 0x81007 (0xa1007 con mips), pitchOrLinearSize = w·h·4, mips hasta 1×1."""
    h_, w_ = img.shape[:2]
    levels = [img]
    if mips:
        cur = img
        while cur.shape[0] > 1 or cur.shape[1] > 1:
            cur = np.asarray(Image.fromarray(cur, "RGBA").resize((max(1, cur.shape[1] // 2), max(1, cur.shape[0] // 2)), Image.BOX))
            levels.append(cur)
    pf = struct.pack("<2I4s5I", 32, 0x41, b"\0\0\0\0", 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    caps1 = 0x1000 | (0x400008 if mips else 0)
    body = b"".join(l[..., [2, 1, 0, 3]].tobytes() for l in levels)
    return _dds_header(w_, h_, len(levels) if mips else 0, w_ * h_ * 4, pf, caps1) + body


def dds_dxt3(rgb: np.ndarray) -> bytes:
    """DXT3 sin mips (como colormap_no_shadow de vanilla): alfa explícito 0xF y color BC1 de 4 niveles,
    extremos = mínimo y máximo por canal del bloque 4×4. Vectorizado."""
    h, w = rgb.shape[:2]
    assert h % 4 == 0 and w % 4 == 0
    b = rgb.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3).astype(np.int32)
    lo = b.min(1); hi = b.max(1)
    def to565(c):
        return ((c[:, 0] >> 3) << 11) | ((c[:, 1] >> 2) << 5) | (c[:, 2] >> 3)
    def from565(v):
        r = (v >> 11) & 31; g = (v >> 5) & 63; bb = v & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (bb << 3) | (bb >> 2)], 1)
    c0 = to565(hi); c1 = to565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    eq = c0 == c1                                     # bloque liso: forzar c0 > c1 para el modo de 4 colores
    c0 = np.where(eq & (c0 < 0xFFFF), c0 + 1, c0); c1 = np.where(eq & (c0 == 0xFFFF) & (c1 > 0), c1 - 1, c1)
    e0 = from565(c0); e1 = from565(c1)
    pal = np.stack([e0, e1, (2 * e0 + e1) // 3, (e0 + 2 * e1) // 3], 1)          # (B, 4, 3)
    d = ((b[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)                    # (B, 16, 4)
    idx = d.argmin(-1).astype(np.uint32)
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    nb = b.shape[0]
    out = np.zeros((nb, 16), np.uint8)
    out[:, 0:8] = 0xFF
    out[:, 8:10] = c0.astype("<u2").view(np.uint8).reshape(-1, 2)
    out[:, 10:12] = c1.astype("<u2").view(np.uint8).reshape(-1, 2)
    out[:, 12:16] = bits.astype("<u4").view(np.uint8).reshape(-1, 4)
    pf = struct.pack("<2I4s5I", 32, 0x4, b"DXT3", 0, 0, 0, 0, 0)
    return _dds_header(w, h, 0, nb * 16, pf, 0x1000) + out.tobytes()


def ascii_name(s: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^A-Za-z0-9 _-]", "", t).strip()
    return t or "x"
