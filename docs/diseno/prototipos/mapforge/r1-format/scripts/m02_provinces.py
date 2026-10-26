"""m02: provinces.bmp + definition.csv: orientación, envoltura, vecinos, islas, fragmentos."""
import time, json
from common import *
t = time.time(); ids = province_ids(cache=False); print("ids raster", ids.shape, f"{time.time()-t:.1f}s")
H, W = ids.shape
sea, maxp = sea_ids()
defs = read_definition(); N = max(r[0] for r in defs)
cnt = np.bincount(ids.ravel(), minlength=N + 1)
print("pixels unmapped (id 0):", int(cnt[0]))
print("min/median/max px land:", *[int(f(cnt[[i for i in range(1, N+1) if i not in sea]])) for f in (np.min, np.median, np.max)])
print("min/median/max px sea:", *[int(f(cnt[sorted(sea)])) for f in (np.min, np.median, np.max)])
# orientación: fila media (array Pillow, fila 0 = arriba del archivo visto) de provincias conocidas
ys = np.arange(H)[:, None]
for pid, name in [(549, "Berlin"), (300, "London"), (2101, "?"), (1, "Sitka")]:
    m = ids == pid
    print("orient", pid, name, [r[4] for r in defs if r[0] == pid], "mean row", round(float(np.nonzero(m)[0].mean()), 1))
# envoltura horizontal: misma provincia a ambos lados
same = ids[:, 0] == ids[:, -1]
print("wrap: filas con id igual en x=0 y x=W-1:", int(same.sum()), "/", H, "; ids distintos en columna 0:", len(np.unique(ids[:, 0])))
# vecinos (4-conexión + envoltura)
def pairs(a, b):
    m = a != b
    p = np.stack([a[m], b[m]], 1).astype(np.int64); p.sort(1)
    return np.unique(p[:, 0] * 65536 + p[:, 1])
pr = np.unique(np.concatenate([pairs(ids[:, :-1], ids[:, 1:]), pairs(ids[:-1], ids[1:]), pairs(ids[:, -1], ids[:, 0])]))
pr8 = np.unique(np.concatenate([pr, pairs(ids[:-1, :-1], ids[1:, 1:]), pairs(ids[:-1, 1:], ids[1:, :-1])]))
print("pares de vecinos 4-con:", len(pr), " 8-con:", len(pr8), " solo diagonales:", len(np.setdiff1d(pr8, pr)))
nb = {i: set() for i in range(N + 1)}
for v in pr:
    a, b = divmod(int(v), 65536); nb[a].add(b); nb[b].add(a)
land = [i for i in range(1, N + 1) if i not in sea]
no_land_nb = [i for i in land if not any(j not in sea and j != 0 for j in nb[i])]
coastal = [i for i in land if any(j in sea for j in nb[i])]
islands_no_sea = [i for i in no_land_nb if not any(j in sea for j in nb[i])]
sea_no_sea_nb = [i for i in sorted(sea) if not any(j in sea for j in nb[i])]
sea_no_land = [i for i in sorted(sea) if not any(j not in sea and j != 0 for j in nb[i])]
print("tierra:", len(land), "costeras:", len(coastal), "sin vecino de tierra (islas de 1 prov):", len(no_land_nb), "aisladas sin mar:", islands_no_sea)
print("mar:", len(sea), "mar sin vecino mar:", sea_no_sea_nb, "mar sin costa:", len(sea_no_land))
print("vecinos por provincia: min/med/max", min(len(nb[i]) for i in range(1, N+1)), int(np.median([len(nb[i]) for i in range(1, N+1)])), max(len(nb[i]) for i in range(1, N+1)))
print("provincias que tocan píxeles sin id:", len(nb[0]))
# fragmentos por provincia: componentes 4-conexas por run-length + propagación
t = time.time()
start = np.ones((H, W), bool); start[:, 1:] = ids[:, 1:] != ids[:, :-1]
run = np.cumsum(start.ravel()).reshape(H, W) - 1
nr = int(run.max()) + 1
run_id = ids.ravel()[np.flatnonzero(start.ravel())]
eq = ids[:-1] == ids[1:]
a = run[:-1][eq]; b = run[1:][eq]
e = np.unique(a.astype(np.int64) * nr + b); a, b = e // nr, e % nr
wr = ids[:, 0] == ids[:, -1]
a = np.concatenate([a, run[:, 0][wr]]); b = np.concatenate([b, run[:, -1][wr]])
lab = np.arange(nr)
while True:
    m = np.minimum(lab[a], lab[b]); old = lab.copy()
    np.minimum.at(lab, a, m); np.minimum.at(lab, b, m)
    lab = lab[lab]; lab = lab[lab]
    if np.array_equal(lab, old): break
roots = np.unique(lab)
comp_per_id = np.bincount(run_id[roots], minlength=N + 1)
frag = [(i, int(comp_per_id[i])) for i in range(1, N + 1) if comp_per_id[i] > 1]
print(f"componentes: {len(roots)} runs={nr} ({time.time()-t:.1f}s); provincias con >1 componente: {len(frag)} (tierra {sum(1 for i,_ in frag if i not in sea)}, mar {sum(1 for i,_ in frag if i in sea)}); max {max(frag, key=lambda x: x[1]) if frag else None}")
json.dump({"neighbors": {i: sorted(nb[i]) for i in range(N + 1)}, "cnt": cnt.tolist(), "frag": frag, "coastal": coastal}, open(OUT + "/m02.json", "w"))
