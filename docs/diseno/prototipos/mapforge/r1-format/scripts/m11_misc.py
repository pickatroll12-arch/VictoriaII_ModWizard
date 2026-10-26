"""m11: bordes del mapa, colores de definition.csv, ids contiguos, sea_starts, colores sin id."""
import collections
from common import *
ids = province_ids(); H, W = ids.shape
sea, maxp = sea_ids(); N = maxp - 1
for name, col in [("x=0", ids[:, 0]), ("x=W-1", ids[:, -1]), ("y=0", ids[0]), ("y=H-1", ids[-1])]:
    u = set(np.unique(col).tolist()); print(f"borde {name}: ids {len(u)}, de mar {len(u & sea)}, de tierra {sorted(u - sea - {0})[:10]}")
seam = set(zip(ids[:, -1].tolist(), ids[:, 0].tolist())); seam = {p for p in seam if p[0] != p[1]}
print("pares distintos a través de la costura x=W-1|x=0:", len(seam))
defs = read_definition()
idl = [r[0] for r in defs]
print("definition: filas con id", len(idl), " min", min(idl), " max", max(idl), " huecos", sorted(set(range(1, max(idl) + 1)) - set(idl))[:10], " repetidos", [k for k, c in collections.Counter(idl).items() if c > 1])
cols = [(r[1], r[2], r[3]) for r in defs]
print("  colores (0,0,0):", (0, 0, 0) in cols, " (255,255,255):", (255, 255, 255) in cols, " repetidos:", len(cols) - len(set(cols)))
print("  max_provinces - max id:", maxp - max(idl), "; sea_starts ⊂ ids:", sea <= set(idl))
# distancia mínima entre colores de definición (canal)
c = np.array(cols, int); d = []
srt = c[np.lexsort(c.T[::-1])]
print("  canal R/G/B valores distintos:", [len(set(c[:, i])) for i in range(3)])
rgb = np.asarray(Image.open(V + "/map/provinces.bmp").convert("RGB"))
m = ids == 0
u, n = np.unique(rgb[m].reshape(-1, 3), axis=0, return_counts=True)
print("colores sin id:", len(u), " mayores:", [(tuple(map(int, a)), int(b)) for a, b in sorted(zip(u.tolist(), n.tolist()), key=lambda x: -x[1])[:5]])
# vecinos de esos píxeles: ¿mar o tierra?
nb = collections.Counter()
ys, xs = np.nonzero(m)
for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
    yy = np.clip(ys + dy, 0, H - 1); xx = (xs + dx) % W
    v = ids[yy, xx]; v = v[v > 0]
    nb.update("mar" if int(x) in sea else "tierra" for x in v)
print("  vecinos de píxeles sin id:", dict(nb))
