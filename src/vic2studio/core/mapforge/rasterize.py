"""Etapa de ráster (wizard §18.3, pasos 18, 24 y 25): provincias provisionales → píxeles, terreno y ríos.

- ``raster``: vecino más cercano por cubos 3×3 con un campo de deformación ligado a la rejilla (bordes no rectos) y
  la costa por altura bilineal por píxel (la tierra solo toma celdas de tierra y el mar de mar).
- ``terrain_pixels``: categoría por píxel (la de la celda; la altura bilineal fuerza colinas y montañas salvo en el
  ártico) e índice de ``terrain.bmp`` por (estado, categoría) entre los que la instalación usa (§18.5).
- ``river_pixels``: un tramo por nacimiento que baja por los receptores, dibujado en escalera 4-conexa con 0 en el
  nacimiento y 1 en la confluencia, y los anchos y cuotas de la instalación.

Se comprueba la cancelación en cada banda de 64 filas.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from ..cancel import CancelCheck, raise_if_cancelled
from .graph import Lattice
from .world import CAT_INDEX, CATS, SEA_LEVEL

BAND = 64


def _up(g: np.ndarray, w: int, h: int) -> np.ndarray:
    return np.asarray(Image.fromarray(g.astype(np.float32), "F").resize((w, h), Image.BILINEAR), np.float32)


def warp_field(lat: Lattice, w: int, h: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    gw, gh = max(2, lat.cols // 2), max(2, lat.rows // 2)
    g1 = rng.uniform(-0.35, 0.35, (gh, gw))
    g2 = rng.uniform(-0.35, 0.35, (gh, gw))
    f1 = rng.uniform(-0.12, 0.12, (gh * 4, gw * 4))
    f2 = rng.uniform(-0.12, 0.12, (gh * 4, gw * 4))
    return (_up(g1, w, h) + _up(f1, w, h)) * lat.dx, (_up(g2, w, h) + _up(f2, w, h)) * lat.dx


def height_pixels(lat: Lattice, h: np.ndarray, w: int, hh: int) -> np.ndarray:
    """Altura bilineal por píxel (con la columna de la costura repetida para envolver)."""
    g = h.reshape(lat.rows, lat.cols).astype(np.float32)
    g = np.concatenate([g, g[:, :1]], axis=1)
    extra = int(round(w / lat.cols))
    big = np.asarray(Image.fromarray(g, "F").resize((w + extra, hh), Image.BILINEAR), np.float32)
    off = int(round(w / lat.cols / 2))
    return np.ascontiguousarray(big[:, off:off + w])


def nearest_cells(lat: Lattice, w: int, h: int, *, cell_class: np.ndarray, pix_class: np.ndarray,
                  warp: tuple[np.ndarray, np.ndarray] | None, cancelled: CancelCheck = None,
                  progress=None) -> np.ndarray:
    out = np.empty((h, w), np.int32)
    px = np.arange(w, dtype=np.float32) + 0.5
    P = lat.pts.astype(np.float32)
    bands = list(range(0, h, BAND))
    for bi, y0 in enumerate(bands):
        raise_if_cancelled(cancelled)
        y1 = min(h, y0 + BAND)
        yy = (np.arange(y0, y1, dtype=np.float32) + 0.5)[:, None] * np.ones((1, w), np.float32)
        xx = np.broadcast_to(px, (y1 - y0, w)).copy()
        if warp is not None:
            xx += warp[0][y0:y1]
            yy += warp[1][y0:y1]
            if lat.wrap_x:
                xx %= w
            np.clip(yy, 0, h - 1e-3, out=yy)
        rr0 = np.floor(yy / lat.dy).astype(np.int32)
        best = np.full(xx.shape, np.inf, np.float32)
        bid = np.zeros(xx.shape, np.int32)
        best_any = np.full(xx.shape, np.inf, np.float32)
        bid_any = np.zeros(xx.shape, np.int32)
        pcls = pix_class[y0:y1]
        for dr in (-1, 0, 1):
            rr = rr0 + dr
            okr = (rr >= 0) & (rr < lat.rows)
            rrc = np.clip(rr, 0, lat.rows - 1)
            cc0 = np.floor((xx - lat.row_shift[rrc].astype(np.float32)) / np.float32(lat.dx)).astype(np.int32)
            for dc in (-1, 0, 1):
                cc = cc0 + dc
                if lat.wrap_x:
                    cc %= lat.cols
                    ok = okr
                else:
                    ok = okr & (cc >= 0) & (cc < lat.cols)
                    cc = np.clip(cc, 0, lat.cols - 1)
                cid = rrc * lat.cols + cc
                ddx = np.abs(P[cid, 0] - xx)
                if lat.wrap_x:
                    ddx = np.minimum(ddx, np.float32(w) - ddx)
                ddy = P[cid, 1] - yy
                d = ddx * ddx + ddy * ddy
                d[~ok] = np.inf
                better_any = d < best_any
                best_any[better_any] = d[better_any]
                bid_any[better_any] = cid[better_any]
                d = np.where(cell_class[cid] == pcls, d, np.inf)
                better = d < best
                best[better] = d[better]
                bid[better] = cid[better]
        miss = ~np.isfinite(best)
        bid[miss] = bid_any[miss]
        out[y0:y1] = bid
        if progress:
            progress(bi + 1, len(bands))
    return out


def raster(lat: Lattice, h: np.ndarray, land: np.ndarray, *, scale: int, rng: np.random.Generator,
           cancelled: CancelCheck = None, progress=None) -> tuple[np.ndarray, np.ndarray]:
    """``(cell_of_pixel, h_px)`` a la escala pedida (W/scale × H/scale)."""
    lat_s = lat.scaled(scale)
    w, hh = int(round(lat.W / scale)), int(round(lat.H / scale))
    warp = warp_field(lat_s, w, hh, rng)
    hp = height_pixels(lat, h, w, hh)
    cells = nearest_cells(lat_s, w, hh, cell_class=land, pix_class=hp >= SEA_LEVEL, warp=warp, cancelled=cancelled,
                          progress=progress)
    return cells, hp


# --- terreno ----------------------------------------------------------------------------------------------


def pixel_categories(cell_r: np.ndarray, category: np.ndarray, hp: np.ndarray, pix_land: np.ndarray, *,
                     hills: float, mountain: float) -> np.ndarray:
    pcat = category[cell_r].astype(np.int8)
    pcat[pix_land & (pcat == 0)] = CAT_INDEX["plains"]
    pcat[~pix_land] = 0
    hcls = np.where(hp >= mountain, CAT_INDEX["mountain"], np.where(hp >= hills, CAT_INDEX["hills"], -1))
    return np.where(pix_land & (hcls >= 0) & (pcat != CAT_INDEX["arctic"]), hcls, pcat).astype(np.int8)


def terrain_pixels(pcat: np.ndarray, ids: np.ndarray, state_of_id: np.ndarray, idx_by_cat: dict,
                   rng: np.random.Generator, pix_land: np.ndarray) -> np.ndarray:
    """Un índice por (estado, categoría), elegido entre los índices usados por la instalación con su frecuencia."""
    nst = int(state_of_id.max()) + 2 if state_of_id.size else 2
    lut = np.full((nst, len(CATS)), 254, np.uint8)
    fallback = idx_by_cat.get("plains") or next(iter(idx_by_cat.values()), [(0, 1.0)])
    for k, c in enumerate(CATS):
        if k == 0:
            continue
        opts = idx_by_cat.get(c) or fallback
        ii = np.array([i for i, _ in opts])
        ww = np.array([w for _, w in opts], dtype=np.float64)
        ww = ww / ww.sum()
        lut[:, k] = ii[rng.choice(ii.size, size=nst, p=ww)]
    st_px = state_of_id[ids] + 1
    terr = lut[np.clip(st_px, 0, nst - 1), pcat]
    terr[~pix_land] = 254
    return terr


# --- ríos -------------------------------------------------------------------------------------------------


def draw_rivers(riv: np.ndarray, paths: list) -> dict:
    """``riv`` (H, W) uint8 con 254 en agua y 255 en tierra. ``paths``: (xs, ys, anchos) por tramo, troncos
    primero. 0 en el primer píxel; se detiene antes del agua (desembocadura) o al tocar otro río (1 en su último
    píxel). Polilínea en escalera 4-conexa entre extremos enteros."""
    H, W = riv.shape
    stats = {"paths": 0, "sources": 0, "confluences": 0, "mouths": 0, "dropped_short": 0}
    for xs, ys, wd in paths:
        px, py, pw = [], [], []
        lx = ly = None
        for k in range(len(xs) - 1):
            x0, y0, x1, y1 = xs[k], ys[k], xs[k + 1], ys[k + 1]
            dx = x1 - x0
            if dx > W / 2:
                dx -= W
            if dx < -W / 2:
                dx += W
            ix0, iy0 = int(math.floor(x0)), int(math.floor(y0))
            idx_, idy = int(math.floor(x0 + dx)) - ix0, int(math.floor(y1)) - iy0
            n = abs(idx_) + abs(idy) + 1
            for t in range(n):
                fx = (ix0 + int(round(idx_ * t / max(n - 1, 1)))) % W
                fy = min(max(iy0 + int(round(idy * t / max(n - 1, 1))), 0), H - 1)
                if lx is not None and fx != lx and fy != ly:
                    px.append(fx)
                    py.append(ly)
                    pw.append(wd[k])
                if (fx, fy) != (lx, ly):
                    px.append(fx)
                    py.append(fy)
                    pw.append(wd[k])
                lx, ly = fx, fy
        seen = set()
        qx, qy, qw = [], [], []
        for a, b, c in zip(px, py, pw):
            if (a, b) in seen:
                break
            seen.add((a, b))
            qx.append(a)
            qy.append(b)
            qw.append(c)
        out = []
        end = None
        mine = set()
        for a, b, c in zip(qx, qy, qw):
            if riv[b, a] == 254:
                end = "mouth"
                break
            if riv[b, a] != 255:
                end = "conf"
                break
            touch = False
            for na, nb in (((a + 1) % W, b), ((a - 1) % W, b), (a, min(b + 1, H - 1)), (a, max(b - 1, 0))):
                if (na, nb) not in mine and riv[nb, na] not in (254, 255):
                    touch = True
            out.append((a, b, c))
            mine.add((a, b))
            if touch:
                end = "conf"
                break
        if len(out) < 3:
            stats["dropped_short"] += 1
            continue
        for a, b, c in out:
            riv[b, a] = c
        a, b, _ = out[0]
        riv[b, a] = 0
        stats["sources"] += 1
        if end == "conf":
            a, b, _ = out[-1]
            riv[b, a] = 1
            stats["confluences"] += 1
        elif end == "mouth":
            stats["mouths"] += 1
        stats["paths"] += 1
    return stats


def clean_isolated(riv: np.ndarray) -> int:
    r = riv < 254
    n4 = np.zeros(r.shape, np.int8)
    n4[:, 1:] += r[:, :-1]
    n4[:, :-1] += r[:, 1:]
    n4[:, 0] += r[:, -1]
    n4[:, -1] += r[:, 0]
    n4[1:] += r[:-1]
    n4[:-1] += r[1:]
    iso = r & (n4 == 0)
    riv[iso] = 255
    return int(iso.sum())


def river_pixels(lat: Lattice, ids_sea: np.ndarray, river: np.ndarray, recv: np.ndarray, flux: np.ndarray,
                 land: np.ndarray, *, scale: int, widths: list[int], width_share: list[float],
                 cancelled: CancelCheck = None) -> tuple[np.ndarray, dict]:
    """``rivers.bmp`` (índices) a partir de las celdas de río. ``ids_sea`` es la máscara de agua del ráster."""
    hh, w = ids_sea.shape
    riv = np.where(ids_sea, 254, 255).astype(np.uint8)
    n = river.size
    if not river.any() or not widths:
        return riv, {"paths": 0}
    ok = river & (recv >= 0) & river[np.maximum(recv, 0)]
    up = np.zeros(n, np.int64)
    np.add.at(up, recv[ok], 1)
    rc = np.flatnonzero(river)
    sources = rc[up[rc] == 0]
    share = np.array(width_share, dtype=np.float64)
    cum = np.cumsum(share / share.sum())[:-1]
    logs = np.array([math.log(max(float(f), 1e-9)) for f in flux[river].tolist()])
    lq = np.quantile(logs, cum) if cum.size else np.array([])
    paths = []
    pts_all = lat.pts / scale
    for s in sources.tolist():
        cells = [s]
        c = s
        while True:
            r = int(recv[c])
            if r < 0:
                break
            cells.append(r)
            if not land[r] or len(cells) > 4 * lat.cols:
                break
            c = r
        pts = pts_all[cells]
        if not land[cells[-1]] and len(cells) > 1:
            d = pts[-1] - pts[-2]
            d[0] = (d[0] + w / 2) % w - w / 2
            pts = np.vstack([pts, pts[-1] + d])
            cells = cells + [cells[-1]]
        wd = [widths[int(np.searchsorted(lq, math.log(max(float(flux[x]), 1e-9))))] for x in cells]
        mouth = max(float(flux[x]) for x in cells if land[x])
        paths.append((-mouth, s, pts[:, 0], pts[:, 1], wd))
    raise_if_cancelled(cancelled)
    paths.sort(key=lambda t: (t[0], t[1]))
    stats = draw_rivers(riv, [(p[2], p[3], p[4]) for p in paths])
    stats["isolated_removed"] = clean_isolated(riv)
    return riv, stats
