"""m05: positions.txt: claves, proporción por tierra/mar, coherencia con el ráster."""
import collections, json, time
from common import *
t = time.time(); pos = load(V + "/map/positions.txt"); print(f"parse {time.time()-t:.2f}s, entradas {len(pos)}")
ids = province_ids(); H, W = ids.shape
sea, maxp = sea_ids(); N = maxp - 1
m02 = json.load(open(OUT + "/m02.json")); coastal = set(m02["coastal"])
land = [i for i in range(1, N + 1) if i not in sea]
keys = collections.Counter(); sub = collections.Counter(); types = {}
dup = [k for k, v in pos.items() if isinstance(v, list)]
print("provincias repetidas en positions:", dup[:10], len(dup))
def blk(v): return v[0] if isinstance(v, list) else v
for k, v in pos.items():
    pid = int(k); v = blk(v); grp = "sea" if pid in sea else "land"
    for kk, vv in v.items():
        keys[(grp, kk)] += 1
        types.setdefault(kk, type(vv).__name__ + (":" + ",".join(sorted(vv.keys())) if isinstance(vv, dict) else (":%d" % len(vv) if isinstance(vv, list) else "")))
        if kk == "building_position" and isinstance(vv, dict):
            for b in vv: sub[(grp, b)] += 1
present = set(int(k) for k in pos)
print("ids presentes:", len(present), " de tierra:", len(present & set(land)), "/", len(land), " de mar:", len(present & sea), "/", len(sea))
print("faltan de tierra:", sorted(set(land) - present)[:20], " de mar:", len(sea - present))
print("ids en positions que no existen:", sorted(present - set(range(1, N + 1)))[:10])
for (g, k), c in sorted(keys.items()):
    tot = len(present & (sea if g == "sea" else set(land)))
    print(f"  {g:4s} {k:24s} {c:5d} ({100*c/tot:5.1f}%)  {types[k]}")
for (g, k), c in sorted(sub.items()):
    print(f"  {g:4s} building_position.{k:12s} {c}")
# naval_base solo en costeras?
nb = [int(k) for k, v in pos.items() if "naval_base" in blk(v)]
print("naval_base: total", len(nb), " en costeras", sum(1 for p in nb if p in coastal), " costeras sin naval_base", len(coastal - set(nb)))
# ¿cae unit dentro de su provincia? (y del juego = fila del array Pillow, H1)
inside = collections.Counter(); dist = []
for k, v in pos.items():
    pid = int(k); v = blk(v)
    for key in ("unit", "text_position", "building_construction", "military_construction", "factory"):
        if key in v and isinstance(v[key], dict):
            x, y = float(v[key]["x"]), float(v[key]["y"])
            xi, yi = int(round(x)) % W, int(round(y))
            if 0 <= yi < H:
                inside[(key, ids[yi, xi] == pid)] += 1
    if "naval_base" in v:
        x, y = float(v["naval_base"]["x"]), float(v["naval_base"]["y"]); xi, yi = int(round(x)) % W, int(round(y))
        if 0 <= yi < H: inside[("naval_base", ids[yi, xi] == pid)] += 1
for kk in sorted(set(k for k, _ in inside)):
    print(f"  {kk}: dentro {inside[(kk, True)]} fuera {inside[(kk, False)]}")
# rangos de text_scale y text_rotation
for key in ("text_scale", "text_rotation", "spawn_railway_track"):
    vals = [blk(v)[key] for v in pos.values() if key in blk(v)]
    nums = [float(x) for x in vals if not isinstance(x, (list, dict))]
    if nums: print(f"  {key}: n={len(vals)} min {min(nums):.3f} med {np.median(nums):.3f} max {max(nums):.3f}")
    else: print(f"  {key}: n={len(vals)} ej {vals[:2]}")
