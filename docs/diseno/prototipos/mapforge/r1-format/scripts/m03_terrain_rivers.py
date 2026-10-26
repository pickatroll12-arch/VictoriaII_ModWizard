"""m03: terrain.bmp/rivers.bmp: paleta, índices, mayoría por provincia, anulaciones de historia, ríos."""
import json, collections, time
from common import *
ids = province_ids(); H, W = ids.shape
sea, maxp = sea_ids(); N = maxp - 1
t = time.time()
ter, tpal = palette_image(V + "/map/terrain.bmp")
riv, rpal = palette_image(V + "/map/rivers.bmp")
print("read 8-bit", f"{time.time()-t:.2f}s", ter.shape, riv.shape)
for name, arr, pal in [("terrain", ter, tpal), ("rivers", riv, rpal)]:
    h = np.bincount(arr.ravel(), minlength=256)
    used = np.flatnonzero(h)
    print(f"== {name}: índices usados {len(used)}: {used.tolist()}")
    print("   píxeles por índice:", {int(i): int(h[i]) for i in used})
    print("   colores de paleta usados:", {int(i): tuple(int(c) for c in pal[i]) for i in used})
    gray = all(pal[i][0] == pal[i][1] == pal[i][2] for i in range(256))
    print("   paleta gris?", gray, " entradas distintas:", len({tuple(p) for p in pal}))
tt = load(V + "/map/terrain.txt")
idx2type = {}
for k, v in tt.items():
    if isinstance(v, dict) and "type" in v:
        cols = v["color"] if isinstance(v["color"], list) else [v["color"]]
        for c in cols: idx2type.setdefault(int(c), []).append((k, v["type"], v.get("has_texture", True), v.get("priority")))
print("terrain.txt: índices definidos:", len(idx2type), "repetidos:", {i: t for i, t in idx2type.items() if len(t) > 1})
print("  sin definir y usados:", [int(i) for i in np.flatnonzero(np.bincount(ter.ravel(), minlength=256)) if int(i) not in idx2type])
print("  categorías:", list(tt["categories"].keys()), " water:", [k for k, v in tt["categories"].items() if v.get("is_water")])
# índice de mar y relación con provincias de mar
is_sea = np.zeros(N + 2, bool); is_sea[list(sea)] = True
sm = is_sea[ids]
print("terrain idx en píxeles de mar:", dict(collections.Counter(ter[sm].tolist()).most_common(6)))
print("terrain idx 254 en píxeles de tierra:", int(((ter == 254) & ~sm & (ids > 0)).sum()), " píxeles de tierra totales", int((~sm & (ids > 0)).sum()))
# mayoría por provincia
code = ids.astype(np.int64).ravel() * 256 + ter.ravel()
bc = np.bincount(code, minlength=(N + 2) * 256).reshape(-1, 256)
maj = bc.argmax(1)
share = bc.max(1) / np.maximum(bc.sum(1), 1)
land = [i for i in range(1, N + 1) if i not in sea]
maj_type = {i: idx2type.get(int(maj[i]), [(None, "?")])[0][1] for i in range(1, N + 1)}
print("tierra con mayoría 254:", [i for i in land if maj[i] == 254][:20], " mar con mayoría != 254:", [i for i in sea if maj[i] != 254][:20])
print("cuota de la mayoría (tierra): min %.2f mediana %.2f; provincias con cuota <0.5: %d" % (share[land].min(), np.median(share[land]), int((share[land] < .5).sum())))
# mayoría por categoría (sumando índices de la misma categoría)
cats = list(tt["categories"].keys())
catbc = np.zeros((N + 2, len(cats)))
for i, lst in idx2type.items(): catbc[:, cats.index(lst[0][1])] += bc[:, i]
majcat = {i: cats[int(catbc[i].argmax())] for i in range(1, N + 1)}
print("mayoría por índice != mayoría por categoría (tierra):", sum(1 for i in land if maj_type[i] != majcat[i]))
# anulaciones en history/provinces
hp = history_province_files()
over = {}
for pid, files in hp.items():
    for f in files:
        d = load(f)
        if "terrain" in d: over[pid] = d["terrain"]
print("historias con terrain =:", len(over), " valores:", dict(collections.Counter(over.values())))
print("  anulación == categoría mayoritaria:", sum(1 for p, v in over.items() if majcat.get(p) == v), "/", len(over))
print("  provincias de tierra por categoría mayoritaria:", dict(collections.Counter(majcat[i] for i in land)))
eff = {i: over.get(i, majcat[i]) for i in land}
print("  tras anulación:", dict(collections.Counter(eff.values())))
# ríos
rm = (riv < 254)
print("ríos: píxeles <254:", int(rm.sum()), " sobre mar:", int((rm & sm).sum()), " sobre id 0:", int((rm & (ids == 0)).sum()))
print("ríos idx 254/255: en mar 254->", int(((riv == 254) & sm).sum()), "255->", int(((riv == 255) & sm).sum()), "; en tierra 254->", int(((riv == 254) & ~sm).sum()), "255->", int(((riv == 255) & ~sm).sum()))
# vecindario de índices 0 (nacimiento) y 1 (confluencia)
def nb8(mask):
    m = np.zeros_like(mask)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx: m |= np.roll(np.roll(mask, dy, 0), dx, 1)
    return m
river_any = riv < 254
for code_ in (0, 1):
    ys, xs = np.nonzero(riv == code_)
    n = []
    for y, x in zip(ys, xs):
        win = river_any[max(0, y-1):y+2, max(0, x-1):x+2]
        n.append(int(win.sum()) - 1)
    print(f"ríos idx {code_}: {len(ys)} px; nº vecinos-río (8-con) histograma", dict(collections.Counter(n)))
# ¿tocan el mar los ríos? píxeles de río con vecino de mar
touch = river_any & nb8(sm)
print("píxeles de río adyacentes a mar:", int(touch.sum()), " índices:", dict(collections.Counter(riv[touch].tolist())))
# grosor: ¿los ríos son líneas de 1 px? píxeles con >2 vecinos-río 4-con
n4 = sum(np.roll(river_any, s, a) for s in (1, -1) for a in (0, 1)).astype(int)
print("píxeles de río por nº de vecinos-río 4-con:", dict(collections.Counter(n4[river_any].tolist())))
nb8c = sum(np.roll(np.roll(river_any, dy, 0), dx, 1) for dy in (-1,0,1) for dx in (-1,0,1) if dy or dx).astype(int)
print("píxeles de río por nº de vecinos-río 8-con:", dict(collections.Counter(nb8c[river_any].tolist())))
# provincias con río
pr = np.bincount(ids[river_any], minlength=N + 2)
print("provincias de tierra con algún píxel de río:", int(sum(1 for i in land if pr[i] > 0)))
# anchura por tramo (idx) y orientación: ¿crece el índice hacia la desembocadura? muestra
json.dump({"maj": maj.tolist(), "majcat": majcat, "over": over}, open(OUT + "/m03.json", "w"))
