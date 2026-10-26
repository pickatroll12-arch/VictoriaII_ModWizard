"""m04: ríos: máscara de agua frente a terrain.bmp, recorrido desde nacimientos, desembocaduras."""
import collections, itertools
from common import *
ids = province_ids(); H, W = ids.shape
sea, maxp = sea_ids(); N = maxp - 1
ter, _ = palette_image(V + "/map/terrain.bmp"); riv, _ = palette_image(V + "/map/rivers.bmp")
is_sea = np.zeros(N + 2, bool); is_sea[list(sea)] = True; sm = is_sea[ids]
print("rivers==254 vs terrain==254: iguales", int(((riv == 254) == (ter == 254)).sum()), "de", H * W,
      "; riv254&!ter254", int(((riv == 254) & (ter != 254)).sum()), "ter254&!riv254", int(((ter == 254) & (riv != 254)).sum()))
print("rivers==254 vs mar de provinces: riv254&tierra", int(((riv == 254) & ~sm).sum()), " mar&!riv254", int((sm & (riv != 254)).sum()))
rv = riv < 254
D4 = [(0, 1), (0, -1), (1, 0), (-1, 0)]
def nbrs(y, x):
    for dy, dx in D4:
        yy, xx = y + dy, (x + dx) % W
        if 0 <= yy < H: yield yy, xx
# recorridos desde cada nacimiento (idx 0) siguiendo píxeles de río 4-conexos no visitados
seen = np.zeros((H, W), bool)
ends = collections.Counter(); seqs = []; monot = collections.Counter(); lens = []
for y0, x0 in zip(*np.nonzero(riv == 0)):
    if seen[y0, x0]: continue
    path = [(y0, x0)]; seen[y0, x0] = True; y, x = y0, x0
    while True:
        nx = [(yy, xx) for yy, xx in nbrs(y, x) if rv[yy, xx] and not seen[yy, xx]]
        if not nx: break
        y, x = nx[0]; seen[y, x] = True; path.append((y, x))
        if riv[y, x] == 1: break
    last = path[-1]
    # ¿qué hay junto al final?
    near_sea = any(sm[yy, xx] for yy, xx in nbrs(*last))
    if riv[last] == 1: kind = "confluencia(1)"
    elif near_sea: kind = "mar"
    elif len(path) > 1 and any(rv[yy, xx] and seen[yy, xx] and (yy, xx) != path[-2] for yy, xx in nbrs(*last)): kind = "otro_rio"
    else: kind = "seco"
    ends[kind] += 1
    s = [int(riv[p]) for p in path[1:] if riv[p] >= 2]
    lens.append(len(path))
    if s:
        d = np.diff(s); monot["no_decrece" if (d >= 0).all() else ("no_crece" if (d <= 0).all() else "mixto")] += 1
import itertools
print("nacimientos recorridos:", sum(ends.values()), "final:", dict(ends))
print("monotonía del ancho a lo largo del tramo (desde el nacimiento):", dict(monot))
print("longitud de tramo px: min/med/max", min(lens), int(np.median(lens)), max(lens))
print("píxeles de río no alcanzados desde un nacimiento:", int((rv & ~seen).sum()))
# ejemplos de secuencia comprimida
cnt = 0
for y0, x0 in zip(*np.nonzero(riv == 0)):
    if cnt >= 4: break
    path = [(y0, x0)]; vis = {(y0, x0)}; y, x = y0, x0
    while True:
        nx = [(yy, xx) for yy, xx in nbrs(y, x) if rv[yy, xx] and (yy, xx) not in vis]
        if not nx or riv[y, x] == 1 and len(path) > 1: break
        y, x = nx[0]; vis.add((y, x)); path.append((y, x))
    if len(path) > 30:
        print("  tramo", (int(x0), int(y0)), [k for k, _ in itertools.groupby(int(riv[p]) for p in path)], "fin cerca de mar:", any(sm[yy, xx] for yy, xx in nbrs(*path[-1])))
        cnt += 1
