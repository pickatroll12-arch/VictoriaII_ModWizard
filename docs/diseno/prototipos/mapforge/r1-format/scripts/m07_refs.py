"""m07: referencias a ids de provincia, estados, continentes y climas fuera de map/, por carpeta."""
import re, collections, os, glob
from common import *
sea, maxp = sea_ids(); N = maxp - 1
KEYS = r"owns|controls|province_id|capital|location|home|state_province_id|is_core_province|province_control|has_province_modifier_x|add_province_modifier_x"
kv = re.compile(r"(?<![\w.])(" + KEYS + r")\s*=\s*\"?(\d+)\"?(?![\d.])")
scope = re.compile(r"(?<![\w.\"])(\d{1,5})\s*=\s*\{")
comment = re.compile(r"#[^\r\n]*")
regions = set(load(V + "/map/region.txt").keys())
conts = set(load(V + "/map/continent.txt").keys())
clims = set(load(V + "/map/climate.txt").keys())
word = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
tot = collections.defaultdict(collections.Counter)
regkeys = collections.Counter(); contkeys = collections.Counter()
for p in glob.glob(V + "/**/*", recursive=True):
    if not p.endswith((".txt", ".lua", ".gui", ".gfx")) or "/map/" in p: continue
    rel = os.path.relpath(p, V).split(os.sep)
    folder = "/".join(rel[:2]) if rel[0] in ("history", "common") and len(rel) > 2 else rel[0]
    if rel[0] == "common" and len(rel) == 2: folder = "common/" + rel[1]
    t = comment.sub("", open(p, encoding="cp1252", errors="replace").read())
    for k, v in kv.findall(t):
        if 1 <= int(v) <= N: tot[folder][k] += 1
    for v in scope.findall(t):
        if 1 <= int(v) <= N: tot[folder]["<id> = {"] += 1
    if rel[:2] == ["history", "pops"]:
        tot[folder]["(claves raíz = provincia)"] += 0
    for w in word.findall(t):
        if w in regions: regkeys[(folder, w)] += 1
        if w in conts: contkeys[(folder, w)] += 1
        if w in clims: tot[folder]["climate:" + w] += 1
hp = glob.glob(V + "/history/provinces/**/*.txt", recursive=True)
tot["history/provinces"]["(archivo por id)"] = len(hp)
for folder in sorted(tot):
    print(f"{folder:28s}", dict(tot[folder]))
rc = collections.Counter(f for f, _ in regkeys.elements())
print("regiones (estados) citadas fuera de map/:", dict(rc), "ejemplos", list(regkeys.items())[:6])
cc = collections.Counter(); [cc.__setitem__(f, cc[f] + c) for (f, w), c in contkeys.items()]
print("continentes citados fuera de map/:", dict(cc), sorted(set(w for _, w in contkeys))[:10])
