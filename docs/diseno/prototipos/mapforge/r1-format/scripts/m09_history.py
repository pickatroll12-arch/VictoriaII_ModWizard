"""m09: history/provinces, history/pops y history/countries: estructura y campos."""
import collections, glob, os, re, time
from common import *
sea, maxp = sea_ids(); N = maxp - 1; land = set(range(1, N + 1)) - sea
hp = history_province_files()
subdirs = collections.Counter(os.path.relpath(os.path.dirname(f[0]), V + "/history/provinces") for f in hp.values())
print("history/provinces: ids con archivo", len(hp), " subcarpetas", len(subdirs), " profundidad máx", max(s.count("/") + 1 for s in subdirs), " ej", list(subdirs.items())[:6])
print("  de mar con archivo:", len(set(hp) & sea), " de tierra sin archivo:", len(land - set(hp)))
names = [os.path.basename(f) for fs in hp.values() for f in fs]
print("  patrón nombre '<id> - <Nombre>.txt':", sum(1 for n in names if re.match(r"^\d+ - .+\.txt$", n)), "/", len(names), " otros ej:", [n for n in names if not re.match(r"^\d+ - .+\.txt$", n)][:5])
keys = collections.Counter(); dated = collections.Counter(); vals = collections.defaultdict(collections.Counter)
for pid, fs in hp.items():
    d = load(fs[0])
    for k, v in d.items():
        if re.match(r"^\d+\.\d+\.\d+$", k): dated[k] += 1; continue
        keys[k] += 1
        if k in ("trade_goods", "colonial", "is_slave", "life_rating", "railroad", "fort", "naval_base", "terrain", "colony"):
            vals[k][str(v) if not isinstance(v, list) else "list"] += 1
print("  claves raíz (n archivos de", len(hp), "):", dict(keys.most_common()))
print("  bloques fechados:", dict(dated.most_common(8)))
for k in ("colonial", "is_slave", "railroad", "fort", "naval_base", "colony"):
    print("   ", k, dict(vals[k]))
print("   trade_goods distintos:", len(vals["trade_goods"]), " life_rating min/max", min(int(x) for x in vals["life_rating"]), max(int(x) for x in vals["life_rating"]))
own = sum(1 for pid, fs in hp.items() if "owner" in load(fs[0]))
print("  con owner:", own, " sin owner (sin colonizar):", len(hp) - own)
# POPs
t = time.time()
dates = sorted(os.listdir(V + "/history/pops"))
for dt in dates:
    files = glob.glob(V + f"/history/pops/{dt}/*.txt")
    prov = collections.Counter(); types = collections.Counter(); pk = collections.Counter(); sizes = []
    for f in files:
        d = load(f)
        for k, v in d.items():
            blocks = v if isinstance(v, list) else [v]
            prov[int(k)] += len(blocks)
            for b in blocks:
                for pt, pv in b.items():
                    for pp in (pv if isinstance(pv, list) else [pv]):
                        types[pt] += 1; sizes.append(int(pp.get("size", 0))); pk.update(pp.keys())
    p = set(prov)
    print(f"pops {dt}: archivos {len(files)} provincias {len(p)} (tierra sin POPs {len(land - p)}, mar con POPs {len(p & sea)}) POPs {sum(types.values())} tamaño med {int(np.median(sizes))} total {sum(sizes)}")
    print("   tipos:", dict(types.most_common()), " claves POP:", dict(pk))
    nop = sorted(land - p)
    if nop:
        owners = collections.Counter("owner" in load(hp[i][0]) for i in nop if i in hp)
        print("   tierra sin POPs: con owner?", dict(owners))
print(f"  ({time.time()-t:.1f}s)")
# history/countries
hc = glob.glob(V + "/history/countries/*.txt")
ck = collections.Counter()
for f in hc:
    d = load(f)
    ck.update(k for k in d if not re.match(r"^\d+\.\d+\.\d+$", k))
fixed = {k: c for k, c in ck.items() if c >= 20}
print("history/countries:", len(hc), " claves raíz con >=20 archivos:", fixed)
