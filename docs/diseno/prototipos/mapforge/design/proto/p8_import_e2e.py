"""p8: importación de extremo a extremo (m6). Entrada: solo provinces.bmp + terrain.bmp + rivers.bmp de la
instalación (como si fueran bitmaps pintados a mano, sin definition.csv ni textos). Reconstruye todo lo que falta:
ids (tierra primero), tierra/mar por el 254 de terrain.bmp, fragmentos (aviso), vecinos, posiciones, estrechos,
estados, continentes, climas, texturas (pseudorrelieve), textos de map/ e historias y POPs mínimas; codifica todo
en memoria. Uso: python3 -I p8_import_e2e.py VANILLA"""
import io, json, math, os, resource, sys, time
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "r2-azgaar", "proto")); sys.path.insert(0, HERE)
import forge as F  # noqa: E402
import mf_lib as L  # noqa: E402

V = sys.argv[1]
T, R = {}, {}


class phase:
    def __init__(self, k): self.k = k
    def __enter__(self): self.t = time.perf_counter()
    def __exit__(self, *a): T[self.k] = round(time.perf_counter() - self.t, 3)


with phase("00_learn_install_cached"):
    LI = L.learn_install(V)          # en la aplicación: una vez por instalación, cacheado en <cache_dir>
t_all = time.perf_counter()
with phase("01_read_bmps"):
    a = np.asarray(Image.open(V + "/map/provinces.bmp").convert("RGB"))
    terr = np.asarray(Image.open(V + "/map/terrain.bmp")); riv = np.asarray(Image.open(V + "/map/rivers.bmp"))
    H, W = terr.shape
with phase("02_census_unique_plus_lut"):
    packed = (a[..., 0].astype(np.uint32) << 16) | (a[..., 1].astype(np.uint32) << 8) | a[..., 2]
    del a
    ucol = np.unique(packed)
    lut = np.zeros(1 << 24, np.uint16); lut[ucol] = np.arange(1, ucol.size + 1, dtype=np.uint16)
    ids0 = lut[packed]; del lut
with phase("03_land_sea_compact"):
    n0 = ucol.size
    area0 = np.bincount(ids0.ravel(), minlength=n0 + 1)
    wat0 = np.bincount(ids0.ravel(), weights=(terr == 254).ravel(), minlength=n0 + 1)
    sea0 = wat0 > area0 / 2; sea0[0] = False
    ambiguous = int(((wat0 / np.maximum(area0, 1) > 0.3) & (wat0 / np.maximum(area0, 1) < 0.7)).sum())
    order = np.concatenate([np.flatnonzero(~sea0[1:]) + 1, np.flatnonzero(sea0[1:]) + 1])
    remap = np.zeros(n0 + 1, np.uint16); remap[order] = np.arange(1, n0 + 1)
    ids = remap[ids0]; del ids0
    NP = n0; NL = int((~sea0[1:]).sum())
    is_sea = np.zeros(NP + 1, bool); is_sea[NL + 1:] = True
with phase("04_fragments_info"):
    nfrag = F.raster_fragments(ids, True)
R["fragmented_provinces"] = int((nfrag[1:] > 1).sum())
with phase("05_neighbors"):
    pe = F.raster_edges(ids.astype(np.int32), True); pe = pe[pe[:, 0] > 0]
deg = np.bincount(pe.ravel(), minlength=NP + 1)
with phase("06_positions"):
    P = L.positions(ids, is_sea, NP)
with phase("07_straits"):
    st_ = L.suggest_straits(ids, is_sea, pe, 8)
with phase("08_states_continents_climates"):
    ll = pe[(~is_sea[pe[:, 0]]) & (~is_sea[pe[:, 1]])]
    pts = np.column_stack([P["cx"], P["cy"]])
    landm = ~is_sea; landm[0] = False
    comp = F.components(NP + 1, ll, landm)
    ip, ix = F.to_csr(ll, NP + 1)
    state = F.group_cells(NP + 1, ip, ix, landm, round(NL / 4.92), np.ones(NP + 1), np.ones(NP + 1), pts, W, True,
                          np.random.default_rng(0), 1, comp, "vec", ll)
    cat_lut = np.array([L.CATS.index(LI["cat_of"].get(i, "plains")) if LI["cat_of"].get(i, "plains") in L.CATS else 0 for i in range(256)])
    cat_lut[254] = 0
    kc = np.bincount(ids.ravel().astype(np.int64) * 12 + cat_lut[terr].ravel(), minlength=(NP + 1) * 12).reshape(NP + 1, 12)
    dom = kc[:, 1:].argmax(1) + 1
    lat = -60 + P["cy"] / H * 135
    clim = np.select([np.abs(lat) > 60, np.abs(lat) > 45, dom == L.CATS.index("desert")], [3, 2, 1], 0)
with phase("09_textures_pseudorelief"):
    W3, H3 = W // 3, H // 3
    sc = cat_lut[terr[1::3, 1::3][:H3, :W3]]
    ph = np.select([sc == L.CATS.index("mountain"), sc == L.CATS.index("hills"), sc == 0], [75, 50, 10], 30).astype(np.float32)
    im = Image.fromarray(ph, "F")
    for _ in range(3):
        im = im.resize((W3 // 2, H3 // 2), Image.BILINEAR).resize((W3, H3), Image.BILINEAR)
    ph = np.asarray(im)
    gy, gx = np.gradient(ph)
    col = LI["cm_pal"][sc] * np.clip(1 + 0.04 * (gx - gy), 0.7, 1.25)[..., None]
    cm = np.clip(col, 0, 255).astype(np.uint8)
    cm = np.concatenate([cm[:, -4:], cm, cm[:, :4]], axis=1)
    a255 = lambda x: np.dstack([x, np.full(x.shape[:2], 255, np.uint8)])
    out = {"colormap.dds": L.dds_a8r8g8b8(a255(cm)), "colormap_political.dds": L.dds_a8r8g8b8(a255(cm))}
    wat = np.broadcast_to(LI["water_mean"].astype(np.uint8), (H // 6, W // 6, 3)).copy()
    out["colormap_water.dds"] = L.dds_a8r8g8b8(a255(wat), mips=True)
    out["colormap_no_shadow.dds"] = L.dds_dxt3(np.clip(LI["cm_pal"][sc], 0, 255).astype(np.uint8)[: H3 // 4 * 4, : W3 // 4 * 4])
    out["minimap.dds"] = L.dds_a8r8g8b8(a255(np.asarray(Image.fromarray(cm).resize((266, 102), Image.BOX))))
with phase("10_texts"):
    CR = "\r\n"
    out["definition.csv"] = ("province;red;green;blue;x;x" + CR + "".join(f"{i};{c >> 16};{(c >> 8) & 255};{c & 255};x;x{CR}" for i, c in zip(range(1, NP + 1), ucol[order - 1].tolist()))).encode("cp1252")
    out["default.map"] = (f"max_provinces = {NP + 1}{CR}sea_starts = {{ " + " ".join(map(str, range(NL + 1, NP + 1))) + f" }}{CR}").encode()
    pos = []
    for p in range(1, NP + 1):
        Lp = [f"{p} = {{", f"\tunit = {{ x = {P['ux'][p]}.000 y = {P['uy'][p]}.000 }}", f"\ttext_scale = {P['text_scale'][p]:.2f}"]
        if p <= NL:
            for k, (px, py) in P["extra"].items():
                Lp.append(f"\t{k} = {{ x = {px[p]}.000 y = {py[p]}.000 }}")
            if P["nbx"][p] >= 0:
                Lp.append(f"\tbuilding_position = {{ naval_base = {{ x = {P['nbx'][p]}.000 y = {P['nby'][p]}.000 }} }}")
        pos.append(CR.join(Lp) + CR + "}" + CR)
    out["positions.txt"] = "".join(pos).encode()
    out["region.txt"] = "".join(f"S_{s} = {{ " + " ".join(map(str, (np.flatnonzero(state[1:NL + 1] == s) + 1).tolist())) + f" }}{CR}" for s in np.unique(state[1:NL + 1]).tolist()).encode()
    out["adjacencies.csv"] = ("#From;To;Type;Through;Data;Comment" + CR + "".join(f"{x};{y};sea;{z};0;{CR}" for x, y, z, _ in st_.tolist())).encode()
    for p in range(1, NL + 1):
        out[f"history/provinces/x/{p} - P{p}.txt"] = f"trade_goods = grain{CR}life_rating = 35{CR}".encode()
    out["pops"] = "".join(f"{p} = {{ farmers = {{ culture = c religion = r size = 1000 }} }}{CR}" for p in range(1, NL + 1)).encode()
R["total_without_learn_s"] = round(time.perf_counter() - t_all, 2)
R.update(provinces=NP, land=NL, sea=NP - NL, ambiguous_land_sea=ambiguous, isolated=int((deg[1:] == 0).sum()), straits=len(st_),
         states=int(np.unique(state[1:NL + 1]).size), unit_inside=float((ids[P["uy"][1:], P["ux"][1:]] == np.arange(1, NP + 1)).mean()),
         phases=T, rss_MiB=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1), files=len(out))
print(json.dumps(R, indent=1))
