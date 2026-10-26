"""p7: pipeline v2 tras la verificación adversarial.

Cambios frente a p1 (cada uno responde a un problema de la revisión):
  M1/M11  Etapa de celdas en coordenadas FINALES, una sola vez y para cualquier escala: la rejilla (N, semilla) es
          fija; la vista previa solo cambia la escala del ráster. Estados, continentes, climas, países, culturas,
          POPs, RGO y life rating se calculan sobre las PROVINCIAS PROVISIONALES (grafo de celdas) ANTES del ráster;
          tras `fix`/`ids` el paso `reconcile` hereda los atributos (provincia nueva ← su padre) y retira las vacías.
  M2      Sin ufuncs trascendentes (arctan2, power, hypot) en decisiones: centroides sin trigonometría (la costura es
          frontera), pesos suit^0,75 = sqrt(suit·sqrt(suit)), distancias con sqrt, totales con math.fsum.
  M3      La costura x=0/W-1 es frontera obligatoria de provincias y estados (y fix sin envoltura).
  M4      terrain.bmp: un índice por (estado, categoría), elegido entre los índices que la instalación usa (≥ 0,5 %).
  M5      rivers.bmp con 0/1, 4-conexo, anchos usados por la instalación, densidad por parámetro.
  M6      Puntos secundarios de positions por dirección unitaria.
  M8      definition.csv sin comentario; adjacencies.csv con la cabecera de vanilla en la línea 1.
  m1      DDS con la cabecera de vanilla y mips hasta 1×1; colormap_no_shadow en DXT3.
  m3      POPs con tabla de presencia (sin POPs urbanas en provincias sin dueño).
  m7      colormap con la paleta aprendida de la instalación (también bajo el mar).
  m8      Nombres de archivo transliterados a ASCII.
Uso: python3 -I p7_pipeline_v2.py W H N SEED OUT --install VANILLA [--scale S] [--write] [--river-q Q]
"""
from __future__ import annotations

import hashlib, heapq, io, json, math, os, resource, struct, sys, time, zlib
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "r2-azgaar", "proto"))
sys.path.insert(0, HERE)
import forge as F  # noqa: E402
import mf_lib as L  # noqa: E402

W, H, N, SEED = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
OUT = sys.argv[5]
A = sys.argv
S = int(A[A.index("--scale") + 1]) if "--scale" in A else 1
INSTALL = A[A.index("--install") + 1]
RIVER_Q = float(A[A.index("--river-q") + 1]) if "--river-q" in A else 0.80
WRITE = "--write" in A
os.makedirs(OUT, exist_ok=True)
T: dict[str, float] = {}
R: dict[str, object] = {"W": W, "H": H, "N": N, "seed": SEED, "scale": S}
HASH: dict[str, str] = {}


class phase:
    def __init__(self, name): self.name = name
    def __enter__(self): self.t = time.perf_counter()
    def __exit__(self, *a): T[self.name] = round(time.perf_counter() - self.t, 3)


def rng_for(step):
    return np.random.default_rng([SEED, zlib.crc32(step.encode())])


def sha(a):
    return hashlib.sha256(a if isinstance(a, (bytes, bytearray)) else np.ascontiguousarray(a).tobytes()).hexdigest()[:16]


def grow_vec(n, edges, members, seeds, step_cost, pts, Wd):
    """grow_regions_vec sin hypot (sqrt es IEEE exacta)."""
    e = edges[members[edges[:, 0]] & members[edges[:, 1]]]
    u = np.concatenate([e[:, 0], e[:, 1]]); v = np.concatenate([e[:, 1], e[:, 0]])
    ddx = np.abs(pts[u, 0] - pts[v, 0]); ddx = np.minimum(ddx, Wd - ddx)
    ddy = pts[u, 1] - pts[v, 1]
    w = np.sqrt(ddx * ddx + ddy * ddy) * (step_cost[u] + step_cost[v]) * 0.5
    dist = np.full(n, np.inf); owner = np.full(n, -1, np.int64)
    dist[seeds] = 0; owner[seeds] = np.arange(seeds.size)
    active = np.zeros(n, bool); active[seeds] = True
    while True:
        sel = active[u]
        if not sel.any():
            break
        uu, vv, nd = u[sel], v[sel], dist[u[sel]] + w[sel]
        best = np.full(n, np.inf); np.minimum.at(best, vv, nd)
        imp = best < dist
        if not imp.any():
            break
        win = imp[vv] & (nd == best[vv])
        dist[imp] = best[imp]
        # desempate determinista: el menor id de semilla entre los ganadores
        cand_owner = np.full(n, np.iinfo(np.int64).max); np.minimum.at(cand_owner, vv[win], owner[uu[win]])
        owner[imp] = cand_owner[imp]
        active = imp
    return owner


def group(n, members, k_total, weight, step_cost, pts, edges, comp, rng, lloyd=2):
    idx = np.nonzero(members)[0]
    ucomp, inv = np.unique(comp[idx], return_inverse=True)
    wsum = np.bincount(inv, weights=weight[idx])
    tot = math.fsum(wsum.tolist())
    quota = np.maximum(1, np.round(k_total * wsum / tot)).astype(int)
    seeds = []
    for ci in range(ucomp.size):
        cand = idx[inv == ci]
        q = min(quota[ci], cand.size)
        p = weight[cand] / math.fsum(weight[cand].tolist())
        p = p / p.sum()
        seeds.extend(rng.choice(cand, size=q, replace=False, p=p).tolist())
    seeds = np.array(seeds)
    for it in range(lloyd + 1):
        owner = grow_vec(n, edges, members, seeds, step_cost, pts, W)
        if it == lloyd:
            break
        o = owner[idx]
        cw = np.bincount(o, weights=weight[idx], minlength=seeds.size)
        cx = np.bincount(o, weights=pts[idx, 0] * weight[idx], minlength=seeds.size) / np.maximum(cw, 1e-12)
        cy = np.bincount(o, weights=pts[idx, 1] * weight[idx], minlength=seeds.size) / np.maximum(cw, 1e-12)
        d2 = (pts[idx, 0] - cx[o]) ** 2 + (pts[idx, 1] - cy[o]) ** 2
        order = np.lexsort((idx, d2, o))
        first = np.ones(order.size, bool); first[1:] = o[order][1:] != o[order][:-1]
        seeds = idx[order[first]]
    return owner


LI = L.learn_install(INSTALL) if INSTALL else None
# ============================================================ ETAPA DE CELDAS (coordenadas finales, cualquier escala)
with phase("01_lattice"):
    lat = F.make_lattice(W, H, N, "hex", 0.3, True, SEED)
    nbr = F.implicit_neighbors(lat, "hex6")
    edges = F.edges_from_padded(nbr)
    seam_e = np.abs(lat.pts[edges[:, 0], 0] - lat.pts[edges[:, 1], 0]) > W / 2
    edges_ns = edges[~seam_e]                                        # la costura es frontera (M3)
n = lat.n
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
with phase("02_relief"):
    hm = F.Heightmap(lat, nbr, rng_for("heightmap"))
    hm.run_template(TEMPLATE)
    q = np.quantile(hm.h, 1 - 0.34)
    h = np.clip(hm.h + (F.SEA_LEVEL - q) - 0.5, 0, 100)
land = h >= F.SEA_LEVEL
with phase("03_features"):
    comp_w = F.components(n, edges, ~land)
    big = np.bincount(comp_w[~land]).argmax()
    is_ocean = comp_w == big
    lake = (~land) & ~is_ocean
    lsize = np.bincount(np.where(lake, comp_w, 0), minlength=n)
    small = lake & (lsize[np.maximum(comp_w, 0)] < 4)
    h[small] = F.SEA_LEVEL; land = h >= F.SEA_LEVEL
    lake = (~land) & ~is_ocean
with phase("04_climate_hydro_biomes"):
    temp = F.temperature(lat, h); prec = F.precipitation(lat, h, temp)
    filled = F.priority_flood(h, nbr, is_ocean | lake)
    recv, flux = F.flow(filled, nbr, prec / 10, is_ocean | lake)
    thr = np.quantile(flux[land], RIVER_Q)
    river = land & (flux >= thr)
    CATS = L.CATS; CI = {c: i for i, c in enumerate(CATS)}
    moist = prec.copy()
    nb = np.where(nbr >= 0, moist[np.maximum(nbr, 0)], np.nan)
    moist = np.nanmean(np.column_stack([moist, nb]), axis=1) + 4 * river
    cat = np.full(n, CI["plains"], np.int8)
    cat[temp < -4] = CI["arctic"]
    m = (temp >= -4) & (temp < 5); cat[m] = np.where(moist[m] > 25, CI["forest"], CI["steppe"])
    m = (temp >= 5) & (temp < 18); cat[m] = np.select([moist[m] > 45, moist[m] > 25, moist[m] > 10], [CI["forest"], CI["woods"], CI["plains"]], CI["steppe"])
    m = temp >= 18; cat[m] = np.select([moist[m] > 50, moist[m] > 15, moist[m] > 8], [CI["jungle"], CI["plains"], CI["steppe"]], CI["desert"])
    cat[land & (h < 24) & (moist > 40)] = CI["marsh"]
    cat[land & (h >= 44)] = CI["hills"]; cat[land & (h >= 67)] = CI["mountain"]
    suit = np.clip((temp + 5) / 30, 0.05, 1) * np.clip(1 - (h - 20) / 80, 0.1, 1) * (1 + 2 * river)
    suit[cat == CI["desert"]] *= 0.2; suit[cat == CI["arctic"]] *= 0.1
    cat[land & (suit > np.quantile(suit[land], 0.8)) & np.isin(cat, [CI["plains"], CI["woods"]])] = CI["farmlands"]
    cat[~land] = CI["ocean"]

with phase("05_provinces_cells"):
    comp_l = F.components(n, edges_ns, land); comp_s = F.components(n, edges_ns, ~land)
    step = 1 + 1.5 * (h >= 67) + 0.5 * river
    wl = np.sqrt(suit * np.sqrt(suit))                              # suit^0,75 sin power (M2)
    own_l = group(n, land, 2700, wl, step, lat.pts, edges_ns, comp_l, rng_for("prov_land"))
    own_s = group(n, ~land, 545, np.ones(n), np.ones(n), lat.pts, edges_ns, comp_s, rng_for("prov_sea"))
    nl0 = int(own_l[land].max()) + 1
    prov0 = np.where(land, own_l, own_s + nl0).astype(np.int64)     # provincias provisionales 0..P0-1
    P0 = int(prov0.max()) + 1
    sea0 = np.zeros(P0, bool); sea0[nl0:] = True
    ccount = np.bincount(prov0, minlength=P0)
    pcx = np.bincount(prov0, weights=lat.pts[:, 0], minlength=P0) / ccount
    pcy = np.bincount(prov0, weights=lat.pts[:, 1], minlength=P0) / ccount
    pa, pb = prov0[edges[:, 0]], prov0[edges[:, 1]]
    dm = pa != pb
    pp = np.unique(np.sort(np.column_stack([pa[dm], pb[dm]]), 1), axis=0)
    pseam = np.abs(pcx[pp[:, 0]] - pcx[pp[:, 1]]) > W / 2
# provincias provisionales que cruzan la costura (debe ser 0)
xs_cells = lat.pts[:, 0]
R["prov0_cross_seam"] = int(np.sum(np.bincount(prov0, weights=(xs_cells < W / 4)) * np.bincount(prov0, weights=(xs_cells > 3 * W / 4)) > 0))
HASH["cells_prov0"] = sha(prov0)

with phase("06_states_continents_climates_on_prov0"):
    pts0 = np.column_stack([pcx, pcy])
    ll = pp[(~sea0[pp[:, 0]]) & (~sea0[pp[:, 1]])]
    ll_ns = ll[np.abs(pcx[ll[:, 0]] - pcx[ll[:, 1]]) <= W / 2]
    landp = ~sea0
    compP = F.components(P0, ll_ns, landp)
    csize = np.bincount(compP[landp], minlength=P0)
    bigc = landp & (csize[compP] >= 3)
    st = group(P0, bigc, round(nl0 / 4.92), np.ones(P0), np.ones(P0), pts0, ll_ns, compP, rng_for("states"), lloyd=1)
    # islas de < 3 provincias → estado de la provincia más cercana de otra masa (vanilla: 65 estados no conexos)
    smallp = np.flatnonzero(landp & ~bigc); bigp = np.flatnonzero(bigc)
    for p in smallp.tolist():
        dx = np.abs(pcx[bigp] - pcx[p]); dx = np.minimum(dx, W - dx)
        q_ = bigp[np.argmin(dx * dx + (pcy[bigp] - pcy[p]) ** 2)]
        st[p] = st[q_]
    st[sea0] = -1
    # continentes: k-medias sin trigonometría; cada masa entera a su continente mayoritario
    k_cont = 6; rc = rng_for("continents"); lp_ = np.flatnonzero(landp)
    cent = pts0[rc.choice(lp_, k_cont, replace=False)].copy()
    for _ in range(12):
        dxk = np.abs(pts0[lp_, None, 0] - cent[None, :, 0]); dxk = np.minimum(dxk, W - dxk)
        lab = np.argmin(dxk ** 2 + (pts0[lp_, None, 1] - cent[None, :, 1]) ** 2, axis=1)
        for k in range(k_cont):
            if (lab == k).any():
                cent[k] = pts0[lp_[lab == k]].mean(0)
    massc = F.components(P0, ll, landp)[lp_]
    um, inv_ = np.unique(massc * k_cont + lab, return_inverse=True)
    cnt_ = np.bincount(inv_)
    mm_, kk_ = np.divmod(um, k_cont)
    o = np.lexsort((kk_, -cnt_, mm_)); f2 = np.ones(o.size, bool); f2[1:] = mm_[o][1:] != mm_[o][:-1]
    mass_cont = dict(zip(mm_[o][f2].tolist(), kk_[o][f2].tolist()))
    msize = np.bincount(massc)
    cont = np.full(P0, -1); cont[lp_] = np.where(msize[massc] > 0.25 * nl0, lab, [mass_cont[x] for x in massc.tolist()])
    ctemp = np.bincount(prov0, weights=temp, minlength=P0) / ccount
    csuit = np.bincount(prov0, weights=suit, minlength=P0) / ccount
    clim = np.where(sea0, -1, np.select([ctemp < -2, ctemp < 6, csuit < 0.25], [3, 2, 1], 0))
    # categoría dominante por provincia provisional (para RGO y costes)
    kc = np.bincount(prov0 * len(CATS) + cat, minlength=P0 * len(CATS)).reshape(P0, len(CATS))
    kc[:, 0] = np.where(sea0, kc[:, 0], 0)
    dom0 = kc.argmax(1)

with phase("07_world_on_prov0"):
    # vecinos para la expansión: grafo de provincias + cruces cortos por una celda de mar
    adj = [[] for _ in range(P0)]
    for a, b in ll.tolist():
        adj[a].append(b); adj[b].append(a)
    sea_c = np.flatnonzero(~land)
    nbp = np.where(nbr[sea_c] >= 0, prov0[np.maximum(nbr[sea_c], 0)], -1)
    nbp = np.where((nbr[sea_c] >= 0) & land[np.maximum(nbr[sea_c], 0)], nbp, -1)
    cross = set()
    for i in range(6):
        for j in range(i + 1, 6):
            a_, b_ = nbp[:, i], nbp[:, j]
            mm = (a_ >= 0) & (b_ >= 0) & (a_ != b_)
            for a, b in np.column_stack([np.minimum(a_[mm], b_[mm]), np.maximum(a_[mm], b_[mm])]).tolist():
                cross.add((a, b))
    for a, b in sorted(cross):
        adj[a].append(b); adj[b].append(a)
    tcost = {CI["mountain"]: 4.0, CI["hills"]: 2.0, CI["marsh"]: 2.0, CI["desert"]: 3.0, CI["arctic"]: 5.0, CI["jungle"]: 2.5}
    pcost = np.array([tcost.get(int(c), 1.0) for c in dom0])
    landl = landp.tolist()

    def expand(n_centers, rng, mindist, limit_frac=1.0):
        jit = 1.0 + rng.random(P0) * 0.2
        order = np.argsort(-(csuit[lp_] * rng.uniform(0.6, 1.0, lp_.size)), kind="stable")
        order = lp_[order]
        centers = []; cxl, cyl = pcx.tolist(), pcy.tolist()
        while len(centers) < n_centers and mindist > 1:
            for p in order.tolist():
                if p in centers:
                    continue
                if all(min(abs(cxl[p] - cxl[q]), W - abs(cxl[p] - cxl[q])) ** 2 + (cyl[p] - cyl[q]) ** 2 > mindist ** 2 for q in centers):
                    centers.append(p)
                if len(centers) == n_centers:
                    break
            mindist /= 1.2
        owner = np.full(P0, -1, np.int64); dist_ = np.full(P0, np.inf)
        hq = [(0.0, k, p) for k, p in enumerate(centers)]
        for _, k, p in hq:
            dist_[p] = 0; owner[p] = k
        heapq.heapify(hq)
        budget = limit_frac * nl0; taken = len(centers)
        while hq:
            dd_, k, p = heapq.heappop(hq)
            if dd_ > dist_[p]:
                continue
            for q_ in adj[p]:
                if not landl[q_]:
                    continue
                nd = dd_ + pcost[q_] * jit[q_]
                if nd < dist_[q_] and (owner[q_] >= 0 or taken < budget):
                    if owner[q_] < 0:
                        taken += 1
                    dist_[q_] = nd; owner[q_] = k
                    heapq.heappush(hq, (nd, k, q_))
        return np.array(centers), owner
    caps, country = expand(60, rng_for("countries"), W / 40, 0.85)
    cul_c, culture = expand(24, rng_for("cultures"), W / 18)
    culture[landp & (culture < 0)] = 0
    gk = 8; cc_ = pts0[cul_c]
    grp = np.argmin(((cc_[:, None, :] - cc_[None, rng_for("cgroups").choice(len(cul_c), gk, replace=False), :]) ** 2).sum(-1), axis=1)
    religion = grp[culture] % 4
    goods_by_cat = {"plains": ["grain", "cattle", "wool"], "farmlands": ["grain", "fruit", "cotton"], "forest": ["timber", "fur"],
                    "woods": ["timber", "cattle"], "hills": ["coal", "iron", "wool"], "mountain": ["iron", "coal", "precious_metal"],
                    "steppe": ["cattle", "wool"], "jungle": ["tropical_wood", "rubber", "coffee"], "marsh": ["rice", "fish"],
                    "desert": ["sulphur", "cattle"], "arctic": ["fur", "fish"]}
    rg = rng_for("rgo")
    goods0 = [None] * P0
    for p in lp_.tolist():
        goods0[p] = str(rg.choice(goods_by_cat.get(CATS[int(dom0[p])], ["grain"])))
    target = np.repeat([10, 15, 20, 25, 30, 35, 40, 45, 50], [2, 3, 6, 10, 14, 45, 12, 5, 3])
    rk = np.argsort(np.argsort(csuit[lp_], kind="stable"), kind="stable") / max(lp_.size - 1, 1)
    lr0 = np.zeros(P0, int); lr0[lp_] = target[np.minimum((rk * target.size).astype(int), target.size - 1)]
    civilized = rng_for("civ").random(len(caps)) < 0.5
HASH["world_prov0"] = sha(np.concatenate([st, cont, clim, country, culture, religion, lr0]).astype(np.int64))

# ============================================================ ETAPA DE RÁSTER (a la escala pedida)
Ws, Hs = W // S, H // S
with phase("08_raster"):
    lat_s = F.Lattice(lat.kind, Ws, Hs, lat.cols, lat.rows, lat.dx / S, lat.dy / S, lat.row_shift / S, lat.pts / S, True)
    rw = rng_for("warp")
    gw, gh = lat.cols // 2, lat.rows // 2
    g1 = rw.uniform(-0.35, 0.35, (gh, gw)).astype(np.float32); g2 = rw.uniform(-0.35, 0.35, (gh, gw)).astype(np.float32)
    gf1 = rw.uniform(-0.12, 0.12, (gh * 4, gw * 4)).astype(np.float32); gf2 = rw.uniform(-0.12, 0.12, (gh * 4, gw * 4)).astype(np.float32)
    up = lambda g: np.asarray(Image.fromarray(g, "F").resize((Ws, Hs), Image.BILINEAR), np.float32)
    warp = ((up(g1) + up(gf1)) * lat_s.dx, (up(g2) + up(gf2)) * lat_s.dx)
    g = h.reshape(lat.rows, lat.cols).astype(np.float32); g = np.concatenate([g, g[:, :1]], axis=1)
    bigh = np.asarray(Image.fromarray(g, "F").resize((Ws + int(round(Ws / lat.cols)), Hs), Image.BILINEAR))
    off = int(round(Ws / lat.cols / 2)); hp = bigh[:, off:off + Ws]
    pix_land = hp >= F.SEA_LEVEL
    cell_r = F.rasterize(lat_s, Ws, Hs, cell_class=land, pix_class=pix_land, reach=1, warp=warp)
    del warp, bigh
with phase("09_fix_noseam"):
    pid0 = prov0[cell_r] + 1                                         # 1..P0
    is_sea_p = np.concatenate([[False], sea0])
    pid, merged, flipped, created, is_sea_p2 = F.fix_fragments2(pid0, is_sea_p, False)   # sin envoltura: la costura parte (M3)
    # padre de cada provincia creada: el id provisional mayoritario de sus píxeles
    parent = np.arange(is_sea_p2.size); parent[:P0 + 1] = np.arange(P0 + 1)
    if created:
        newm = pid > P0
        k_ = pid[newm].astype(np.int64) * (P0 + 1) + pid0[newm]
        uk, uc = np.unique(k_, return_counts=True); a_, b_ = np.divmod(uk, P0 + 1)
        o = np.lexsort((b_, -uc, a_)); f = np.ones(o.size, bool); f[1:] = a_[o][1:] != a_[o][:-1]
        parent[a_[o][f]] = b_[o][f]
    del pid0
R["fix_merged_flipped_created"] = [merged, flipped, created]
with phase("10_ids_reconcile"):
    cnt = np.bincount(pid.ravel(), minlength=is_sea_p2.size)
    present = np.flatnonzero(cnt[1:] > 0) + 1
    land_ids = present[~is_sea_p2[present]]; sea_ids = present[is_sea_p2[present]]
    remap = np.zeros(is_sea_p2.size, np.int32)
    remap[land_ids] = np.arange(1, land_ids.size + 1); remap[sea_ids] = np.arange(land_ids.size + 1, present.size + 1)
    ids = remap[pid].astype(np.uint16); del pid
    NL, NP = int(land_ids.size), int(present.size)
    is_sea = np.zeros(NP + 1, bool); is_sea[NL + 1:] = True
    par = np.full(NP + 1, -1, np.int64); par[remap[present]] = parent[present] - 1           # provisional 0-based
    # reconcile: atributos heredados del padre; capitales y estados que se quedan sin provincia
    vanished = np.setdiff1d(np.arange(P0), par[1:]); vanished_land = vanished[~sea0[vanished]]
    state = np.full(NP + 1, -1); state[1:NL + 1] = st[par[1:NL + 1]]
    owner = np.full(NP + 1, -1); owner[1:NL + 1] = country[par[1:NL + 1]]
    cul = np.full(NP + 1, -1); cul[1:NL + 1] = culture[par[1:NL + 1]]
    rel = np.full(NP + 1, -1); rel[1:NL + 1] = religion[par[1:NL + 1]]
    contF = np.full(NP + 1, -1); contF[1:NL + 1] = cont[par[1:NL + 1]]
    climF = np.full(NP + 1, -1); climF[1:NL + 1] = clim[par[1:NL + 1]]
    lrF = np.zeros(NP + 1, int); lrF[1:NL + 1] = lr0[par[1:NL + 1]]
    goodsF = [None] + [goods0[p] for p in par[1:NL + 1].tolist()] + [None] * (NP - NL)
    dup = np.bincount(par[1:NL + 1], minlength=P0)                    # >1: hijos creados
    areaF = np.bincount(ids.ravel(), minlength=NP + 1)
    capF = []
    reassigned = 0
    for k, c in enumerate(caps.tolist()):
        kids = np.flatnonzero(par[1:NL + 1] == c) + 1
        if kids.size:
            capF.append(int(kids[np.argmax(areaF[kids])]))
        else:                                                        # capital desaparecida: mayor provincia del país
            mine = np.flatnonzero(owner[1:NL + 1] == k) + 1
            capF.append(int(mine[np.argmax(areaF[mine])]) if mine.size else -1); reassigned += 1
R.update(land_provinces=NL, sea_provinces=NP - NL, vanished_prov0=int(vanished.size), vanished_land=int(vanished_land.size),
         created_children=int((dup > 1).sum()), capitals_reassigned=reassigned,
         land_without_state=int((state[1:NL + 1] < 0).sum()), land_without_continent=int((contF[1:NL + 1] < 0).sum()),
         land_without_climate=int((climF[1:NL + 1] < 0).sum()), land_without_culture=int((cul[1:NL + 1] < 0).sum()),
         states=int(np.unique(state[1:NL + 1]).size), countries_with_land=int(np.unique(owner[owner >= 0]).size))
seam_rows = int((ids[:, 0] == ids[:, -1]).sum())
R["seam_rows_same_id"] = seam_rows
R["seam_provinces"] = int(np.intersect1d(ids[:, 0], ids[:, -1]).size)
HASH["ids"] = sha(ids)

with phase("11_neighbors"):
    pe = F.raster_edges(ids.astype(np.int32), True); pe = pe[pe[:, 0] > 0]
deg = np.bincount(pe.ravel(), minlength=NP + 1)
R["isolated"] = int((deg[1:] == 0).sum())
R["seam_neighbor_pairs"] = int(np.unique(np.sort(np.column_stack([ids[:, 0], ids[:, -1]]), 1)[ids[:, 0] != ids[:, -1]], axis=0).shape[0])
coastal = np.zeros(NP + 1, bool); ls = pe[(~is_sea[pe[:, 0]]) & is_sea[pe[:, 1]]]; coastal[ls[:, 0]] = True

with phase("12_positions"):
    P = L.positions(ids, is_sea, NP)
ux, uy = P["ux"], P["uy"]
R["unit_inside"] = float((ids[uy[1:], ux[1:]] == np.arange(1, NP + 1)).mean())
sec = {}
for k, (px, py) in P["extra"].items():
    d = np.hypot(np.minimum(np.abs(px - ux), Ws - np.abs(px - ux)), py - uy)[1:NL + 1]
    sec[k] = {"inside": float((ids[py[1:NL + 1], px[1:NL + 1]] == np.arange(1, NL + 1)).mean()),
              "lt2px": round(float((d < 2).mean()), 4), "median_px": float(np.median(d))}
R["secondary_points"] = sec
R["naval_base_coastal"] = float((P["nbx"][coastal] >= 0).mean())

with phase("13_straits"):
    straits = L.suggest_straits(ids, is_sea, pe, D=max(2, 8 // S))
R["straits"] = int(len(straits))

with phase("14_terrain_px"):
    pcat = cat[cell_r]
    pcat[~pix_land] = 0
    pix_land_f = ~is_sea[ids]
    pcat[pix_land_f & (pcat == 0)] = CI["plains"]
    pcat[~pix_land_f] = 0
    hcls = np.where(hp >= 67, CI["mountain"], np.where(hp >= 44, CI["hills"], -1))
    pcat = np.where(pix_land_f & (hcls >= 0) & (pcat != CI["arctic"]), hcls, pcat).astype(np.int8)
    terr = L.terrain_index_by_state_category(pcat, ids, state, LI["idx_by_cat"], rng_for("tindex"))
    terr[~pix_land_f] = 254
    # propiedad: índice mayoritario ∈ categoría mayoritaria (por provincia de tierra)
    kt = np.bincount(ids.ravel().astype(np.int64) * 256 + terr.ravel(), minlength=(NP + 1) * 256).reshape(NP + 1, 256)
    kcat = np.bincount(ids.ravel().astype(np.int64) * len(CATS) + pcat.ravel(), minlength=(NP + 1) * len(CATS)).reshape(NP + 1, len(CATS))
    maj_idx = kt.argmax(1); maj_cat = kcat.argmax(1)
    cat_of_idx = np.array([CATS.index(LI["cat_of"].get(i, "plains")) if LI["cat_of"].get(i, "plains") in CATS else -1 for i in range(256)])
    R["terrain_majority_mismatch"] = int((cat_of_idx[maj_idx[1:NL + 1]] != maj_cat[1:NL + 1]).sum())
    used = np.unique(terr[pix_land_f])
    R["terrain_indices_used"] = used.tolist()
    R["terrain_land_px_254_or_ge64"] = int(((terr >= 64) & pix_land_f).sum())
    share = kcat.max(1) / np.maximum(kcat.sum(1), 1)
    R["terrain_dominant_share_p5_p50"] = np.percentile(share[1:NL + 1], [5, 50]).round(3).tolist()
    domF = maj_cat
HASH["terrain"] = sha(terr)

with phase("15_rivers_px"):
    riv = np.where(is_sea[ids], 254, 255).astype(np.uint8)
    widths = LI["widths"]                                            # p. ej. [2, 4, 6, 7, 10, 11] en vanilla
    rc_ = np.flatnonzero(river)
    up_ = np.zeros(n, np.int64); ok_ = river & (recv >= 0) & river[np.maximum(recv, 0)]
    np.add.at(up_, recv[ok_], 1)
    # tronco principal aguas arriba de cada celda: el afluente de mayor caudal
    mainup = np.full(n, -1, np.int64)
    src_ = np.flatnonzero(ok_)
    o = np.lexsort((src_, -flux[src_], recv[src_])); f = np.ones(o.size, bool); f[1:] = recv[src_][o][1:] != recv[src_][o][:-1]
    mainup[recv[src_][o][f]] = src_[o][f]
    sources = rc_[up_[rc_] == 0]
    # umbrales de ancho: la cuota de píxeles de cada ancho en la instalación (vanilla: 2 domina, 10–11 raros)
    wshare = np.array(LI["width_share"]); cum = np.cumsum(wshare)[:-1]
    lq = np.quantile(np.log(flux[river]), cum) if river.any() else []
    paths = []
    why = {}
    for s_ in sources.tolist():
        cells = [s_]; c = s_
        while True:
            r_ = int(recv[c])
            if r_ < 0:
                why["recv<0"] = why.get("recv<0", 0) + 1
                break
            k_ = "water" if not land[r_] else None
            if k_ is None and mainup[r_] != c:
                why["junction"] = why.get("junction", 0) + 1     # se sigue hasta el agua; el dibujo para al tocar
            if k_:
                why[k_] = why.get(k_, 0) + 1
            cells.append(r_)
            if not land[r_] or len(cells) > 4 * lat.cols:
                break
            c = r_
        pts = lat.pts[cells] / S
        if not land[cells[-1]] and len(cells) > 1:                  # desembocadura: prolongar hasta el agua real
            d_ = pts[-1] - pts[-2]
            d_[0] = (d_[0] + Ws / 2) % Ws - Ws / 2
            pts = np.vstack([pts, pts[-1] + d_])
            cells = cells + [cells[-1]]
        # vértices desplazados hacia la geografía deformada: -warp aproximado no disponible aquí → sin desplazar
        wd = np.array([widths[int(np.searchsorted(lq, math.log(flux[c_])))] for c_ in cells])
        mouth_flux = max(flux[c_] for c_ in cells if land[c_])
        paths.append((-mouth_flux, s_, pts[:, 0], pts[:, 1], wd))
    paths.sort(key=lambda t: (t[0], t[1]))
    rstats = L.draw_rivers(riv, [(p[2], p[3], p[4]) for p in paths])
    rstats["isolated_removed"] = L.clean_isolated(riv)
    np.save(os.path.join(OUT, "river_last.npy"), np.array([(0 if e is None else {"mouth": 1, "conf": 2, "conf_hit": 3}[e], x, y, n_) for e, x, y, n_ in rstats.pop("_last")]))
    rrep = L.river_report(riv)
R["rivers"] = {**rstats, **rrep, "chain_end": why}
HASH["rivers"] = sha(riv)

with phase("16_textures"):
    W3, H3 = Ws // 3, Hs // 3
    sub_cat = pcat[1::3, 1::3][:H3, :W3]
    sub_h = np.asarray(Image.fromarray(hp, "F").resize((W3, H3), Image.BILINEAR))
    base = LI["cm_pal"]
    col = base[sub_cat]
    gy, gx = np.gradient(sub_h)
    shade = np.clip(1 + 0.04 * (gx - gy), 0.7, 1.25)[..., None]
    grain = np.asarray(Image.fromarray(rng_for("grain").uniform(-6, 6, (H3 // 8 + 1, W3 // 8 + 1)).astype(np.float32), "F").resize((W3, H3), Image.BILINEAR))[..., None]
    cm = np.clip(col * shade + grain, 0, 255).astype(np.uint8)
    landm = sub_cat > 0
    R["colormap_mean_land_sea_gen"] = [cm[landm].mean(0).round(0).tolist(), cm[~landm].mean(0).round(0).tolist()]
    R["colormap_mean_land_install"] = LI["cm_land_mean"].round(0).tolist()
    sh_ = np.bincount(sub_cat[landm].ravel(), minlength=len(CATS)) / landm.sum()
    R["colormap_expected_land_from_mix"] = (sh_ @ base).round(0).tolist()
    pad = 4
    cmp_ = np.concatenate([cm[:, -pad:], cm, cm[:, :pad]], axis=1)
    a255 = lambda x: np.dstack([x, np.full(x.shape[:2], 255, np.uint8)])
    b_colormap = L.dds_a8r8g8b8(a255(cmp_))
    W6, H6 = Ws // 6, Hs // 6
    hw = np.asarray(Image.fromarray(hp, "F").resize((W6, H6), Image.BILINEAR))
    depth = np.clip((F.SEA_LEVEL - hw) / F.SEA_LEVEL, 0, 1)[..., None]
    wm = LI["water_mean"]
    wat = np.clip(wm * (1.15 - 0.3 * depth), 0, 255)
    wat = np.where((hw >= F.SEA_LEVEL)[..., None], wm, wat).astype(np.uint8)
    b_water = L.dds_a8r8g8b8(a255(wat), mips=True)
    nos = np.clip(col + grain, 0, 255).astype(np.uint8)
    b_noshadow = L.dds_dxt3(nos[: H3 // 4 * 4, : W3 // 4 * 4])
    pol = np.where(sub_cat[..., None] == 0, 90, 200).astype(np.uint8).repeat(3, -1)
    pol = np.concatenate([pol[:, -pad:], pol, pol[:, :pad]], axis=1)
    b_political = L.dds_a8r8g8b8(a255(pol))
    mini = np.asarray(Image.fromarray(cm).resize((266, 102), Image.BOX))
    b_minimap = L.dds_a8r8g8b8(a255(mini))
chk = {}
for k, b in {"colormap": b_colormap, "colormap_water": b_water, "colormap_no_shadow": b_noshadow, "colormap_political": b_political, "minimap": b_minimap}.items():
    im = Image.open(io.BytesIO(b)); im.load()
    fl, hh, ww, lin, _, mips = struct.unpack("<6I", b[8:32])
    chk[k] = {"size": im.size, "mode": im.mode, "bytes": len(b), "flags": hex(fl), "linear": lin, "mips": mips}
nos_back = np.asarray(Image.open(io.BytesIO(b_noshadow)).convert("RGB")).astype(int)
chk["no_shadow_dxt3_mean_abs_err"] = round(float(np.abs(nos_back - nos[: nos_back.shape[0], : nos_back.shape[1]]).mean()), 2)
R["dds"] = chk

# ============================================================ textos
SYL = ["ka", "lo", "ver", "an", "dra", "mi", "sul", "te", "ron", "ba", "el", "is", "or", "ven", "ga", "thi", "mar", "du", "sen", "ul", "é", "ñu"]
import random as _random
CRLF = "\r\n"
files: dict[str, bytes] = {}
with phase("17_text_files"):
    rn = _random.Random(zlib.crc32(b"names") ^ SEED)
    mk = lambda: "".join(rn.choice(SYL) for _ in range(rn.randint(2, 3))).capitalize()
    pname = [None] + [mk() for _ in range(NP)]
    gen = "# Generado por Victoria II Mod Studio (Taller de mapas)" + CRLF
    lut_rgb = rng_for("colors").choice(2**24 - 2, size=NP, replace=False) + 1
    files["map/definition.csv"] = ("province;red;green;blue;x;x" + CRLF + "".join(
        f"{i};{c >> 16};{(c >> 8) & 255};{c & 255};{L.ascii_name(pname[i])};x{CRLF}" for i, c in zip(range(1, NP + 1), lut_rgb.tolist()))).encode("cp1252")
    files["map/adjacencies.csv"] = ("#From;To;Type;Through;Data;Comment" + CRLF + "".join(
        f"{a};{b};sea;{th};0;{L.ascii_name(pname[a])}-{L.ascii_name(pname[b])}{CRLF}" for a, b, th, _ in straits.tolist())).encode("cp1252")
    TAGS = []
    while len(TAGS) < len(caps):
        t = "".join(rn.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(3))
        if t not in TAGS and t not in ("REB", "CON", "PRN", "AUX", "NUL"):
            TAGS.append(t)
    # POPs con tabla de presencia (m3)
    MINE = {"coal", "iron", "sulphur", "precious_metal"}
    pw = areaF.astype(float) * np.maximum(csuit[np.maximum(par, 0)], 0.02); pw[0] = 0; pw[NL + 1:] = 0
    tot = math.fsum(pw.tolist())
    popsize = [int(round(x / tot * 250e6)) for x in pw.tolist()]
    capset = {c for k, c in enumerate(capF) if c > 0 and civilized[k]}
    pops = [gen]; urban_unowned = 0; craftsmen_provs = 0
    CUL = [mk().lower() for _ in range(len(cul_c))]; REL = ["catholic", "sunni", "mahayana", "animist"]
    for p in range(1, NL + 1):
        rural = "labourers" if goodsF[p] in MINE else "farmers"
        mix = {rural: 0.80, "artisans": 0.06, "clergymen": 0.02, "aristocrats": 0.015, "soldiers": 0.025}
        if owner[p] >= 0:
            mix.update({"bureaucrats": 0.006, "officers": 0.004})
        if p in capset:
            mix.update({"craftsmen": 0.03, "clerks": 0.006, "capitalists": 0.002}); craftsmen_provs += 1
        if owner[p] < 0 and set(mix) & {"craftsmen", "clerks", "capitalists", "bureaucrats", "officers"}:
            urban_unowned += 1
        c, r_ = CUL[cul[p]], REL[rel[p]]
        pops.append(f"{p} = {{{CRLF}" + "".join(f"\t{k} = {{ culture = {c} religion = {r_} size = {max(1, int(popsize[p] * v))} }}{CRLF}" for k, v in mix.items()) + f"}}{CRLF}")
    files["history/pops/1836.1.1/00_STU_mapforge.txt"] = "".join(pops).encode("cp1252")
    R["pops"] = {"urban_in_unowned": urban_unowned, "provinces_with_craftsmen": craftsmen_provs, "total": int(sum(popsize))}
    for p in range(1, NL + 1):
        body = gen
        if owner[p] >= 0:
            o_ = TAGS[owner[p]]; body += f"owner = {o_}{CRLF}controller = {o_}{CRLF}add_core = {o_}{CRLF}"
        body += f"trade_goods = {goodsF[p]}{CRLF}life_rating = {lrF[p]}{CRLF}"
        files[f"history/provinces/{['europe','asia','africa','north_america','south_america','oceania'][contF[p]]}/{p} - {L.ascii_name(pname[p])}.txt"] = body.encode("cp1252")
    nonascii = sum(1 for k in files if any(ord(ch) > 127 for ch in k))
    R["nonascii_filenames"] = nonascii
    reg = [gen]
    for s_ in np.unique(state[1:NL + 1]).tolist():
        mem = (np.flatnonzero(state[1:NL + 1] == s_) + 1).tolist()
        reg.append(f"STATE_{mem[0]} = {{ " + " ".join(map(str, mem)) + f" }}{CRLF}")
    files["map/region.txt"] = "".join(reg).encode("cp1252")
    pos = [gen]
    for p in range(1, NP + 1):
        Lp = [f"{p} = {{", f"\tunit = {{ x = {ux[p]}.000 y = {uy[p]}.000 }}", f"\ttext_position = {{ x = {ux[p]}.000 y = {uy[p]}.000 }}", f"\ttext_scale = {P['text_scale'][p]:.2f}"]
        if p <= NL:
            for k in ("building_construction", "military_construction", "factory"):
                Lp.append(f"\t{k} = {{ x = {P['extra'][k][0][p]}.000 y = {P['extra'][k][1][p]}.000 }}")
        Lp.append("}")
        pos.append(CRLF.join(Lp) + CRLF)
    files["map/positions.txt"] = "".join(pos).encode("cp1252")
R["definition_line1"] = files["map/definition.csv"].split(b"\r\n", 1)[0].decode()

with phase("18_bmp_encode"):
    lut = np.zeros((NP + 1, 3), np.uint8)
    lut[1:, 0] = lut_rgb >> 16; lut[1:, 1] = (lut_rgb >> 8) & 255; lut[1:, 2] = lut_rgb & 255
    bio = io.BytesIO(); Image.fromarray(lut[ids], "RGB").save(bio, "BMP"); files["map/provinces.bmp"] = bio.getvalue()
    for name, arr, pal in (("terrain", terr, LI["tpal"]), ("rivers", riv, LI["rpal"])):
        im = Image.fromarray(arr, "P"); im.putpalette(pal)
        bio = io.BytesIO(); im.save(bio, "BMP"); files[f"map/{name}.bmp"] = bio.getvalue()
    files["map/terrain/colormap.dds"] = b_colormap; files["map/terrain/colormap_water.dds"] = b_water
    files["map/terrain/colormap_no_shadow.dds"] = b_noshadow; files["map/terrain/colormap_political.dds"] = b_political
    files["gfx/interface/minimap.dds"] = b_minimap

if WRITE:
    root = os.path.join(OUT, "mod")
    for rel_, b in files.items():
        p_ = os.path.join(root, rel_); os.makedirs(os.path.dirname(p_), exist_ok=True)
        open(p_, "wb").write(b)
HASH["all_files"] = sha(b"".join(hashlib.sha256(files[k]).digest() for k in sorted(files)))
for k in ("map/region.txt", "map/positions.txt", "map/adjacencies.csv", "history/pops/1836.1.1/00_STU_mapforge.txt"):
    HASH[k] = sha(files[k])
np.save(os.path.join(OUT, "par.npy"), par); np.save(os.path.join(OUT, "state.npy"), state)
np.save(os.path.join(OUT, "prov0.npy"), prov0); np.save(os.path.join(OUT, "st0.npy"), st)
Image.fromarray(lut[ids][::-1][::max(1, Ws // 1404), ::max(1, Ws // 1404)]).save(os.path.join(OUT, "preview_north_up.png"))
Image.fromarray(np.asarray(Image.open(io.BytesIO(b_colormap)).convert("RGB"))[::-1]).save(os.path.join(OUT, "colormap_north_up.png"))
R["phases_s"] = T
R["total_s"] = round(sum(T.values()), 2)
R["ru_maxrss_MiB"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
R["hash"] = HASH
s = json.dumps(R, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
print(s)
open(os.path.join(OUT, "result.json"), "w").write(s)
