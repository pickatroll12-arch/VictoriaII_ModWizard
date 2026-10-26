"""m06: climate/continent/region/region_sea y adjacencies.csv frente al ráster."""
import json, collections, re
from common import *
sea, maxp = sea_ids(); N = maxp - 1
land = set(range(1, N + 1)) - sea
nb = {int(k): set(v) for k, v in json.load(open(OUT + "/m02.json"))["neighbors"].items()}
def ints(x):
    if isinstance(x, list): return [int(v) for v in x]
    if isinstance(x, (int, float)): return [int(x)]
    return []
# climate (claves pareadas)
cl = load(V + "/map/climate.txt"); cmem = collections.defaultdict(list)
for k, v in cl.items():
    lst = v if isinstance(v, list) else [v]
    mods = [b for b in lst if isinstance(b, dict)]; provs = [b for b in lst if isinstance(b, list)]
    print(f"climate {k}: bloques mod {len(mods)} listas {len(provs)} claves mod {sorted(mods[0].keys()) if mods else None}")
    for p in provs:
        for i in ints(p): cmem[i].append(k)
print("  provincias con clima:", len(cmem), " tierra sin clima:", len(land - set(cmem)), " mar con clima:", len(set(cmem) & sea), " en >1 clima:", sum(1 for v in cmem.values() if len(v) > 1))
co = load(V + "/map/continent.txt"); comem = collections.defaultdict(list)
for k, v in co.items():
    print(f"continent {k}: claves {sorted(v.keys())} provincias {len(ints(v.get('provinces')))}")
    for i in ints(v.get("provinces")): comem[i].append(k)
print("  tierra sin continente:", len(land - set(comem)), " mar en continente:", len(set(comem) & sea), " en >1:", sum(1 for v in comem.values() if len(v) > 1), " repetidas dentro:", sum(len(v) for v in comem.values()) - len(comem))
rg = load(V + "/map/region.txt"); rmem = collections.defaultdict(list); sizes = []
for k, v in rg.items():
    l = ints(v); sizes.append(len(l))
    for i in l: rmem[i].append(k)
print(f"region.txt: {len(rg)} estados; tamaño min/med/max {min(sizes)}/{int(np.median(sizes))}/{max(sizes)}; vacíos {sizes.count(0)}")
print("  tierra sin estado:", len(land - set(rmem)), " mar en estado:", len(set(rmem) & sea), " en >1:", sum(1 for v in rmem.values() if len(v) > 1))
# conexidad de cada estado por vecinos de tierra (sin adyacencias de estrecho)
disc = 0; ex = []
for k, v in rg.items():
    l = set(ints(v))
    if not l: continue
    st = [next(iter(l))]; seen = set(st)
    while st:
        p = st.pop()
        for q in nb[p]:
            if q in l and q not in seen: seen.add(q); st.append(q)
    if seen != l: disc += 1; ex.append(k)
print("  estados no conexos por tierra:", disc, ex[:8])
names = list(rg.keys()); pat = collections.Counter(re.sub(r"_\d+$", "_<id>", n) == n for n in names)
print("  nombres TAG_<id>:", sum(1 for n in names if re.match(r"^[A-Z]{3}_\d+$", n)), " ¿el número es una provincia del estado?", sum(1 for n in names if re.match(r"^[A-Z]{3}_(\d+)$", n) and int(n.split('_')[1]) in ints(rg[n])))
rs = load(V + "/map/region_sea.txt"); print("region_sea:", {k: ints(v) for k, v in rs.items()})
# adyacencias
rows = []
for ln in open(V + "/map/adjacencies.csv", encoding="cp1252"):
    s = ln.strip()
    if not s or s.startswith("#"): continue
    rows.append(s.split(";"))
print("adjacencies: filas activas", len(rows), " columnas", collections.Counter(len(r) for r in rows), " tipos", collections.Counter(r[2] for r in rows))
bad = collections.Counter()
for r in rows:
    a, b, t, th, d = int(r[0]), int(r[1]), r[2], int(r[3]), int(r[4])
    if t == "sea":
        bad["sea: ambos tierra"] += a in land and b in land
        bad["sea: ya vecinos en ráster"] += b in nb[a]
        bad["sea: through es mar"] += th in sea
        bad["sea: through toca A y B"] += th in nb[a] and th in nb[b]
        bad["sea: data=0"] += d == 0
    elif t == "impassable":
        bad["imp: vecinos en ráster"] += b in nb[a]; bad["imp: through=0"] += th == 0
        bad["imp: ambos tierra"] += a in land and b in land
    elif t == "canal":
        bad["canal: A,B mar"] += a in sea and b in sea; bad["canal: through tierra"] += th in land
        bad["canal: through toca A y B"] += th in nb[a] and th in nb[b]
        bad["canal: A,B vecinos ráster"] += b in nb[a]
print("  comprobaciones:", dict(bad))
dup = collections.Counter((min(int(r[0]), int(r[1])), max(int(r[0]), int(r[1])), r[2]) for r in rows)
print("  pares repetidos:", [k for k, c in dup.items() if c > 1])
