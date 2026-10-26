"""m13: provincias donde la mayoría por índice y por categoría dan terreno distinto (casos para verificar en juego)."""
import json
from common import *
d = json.load(open(OUT + "/m03.json")); sea, _ = sea_ids()
tt = load(V + "/map/terrain.txt"); idx2type = {}
for k, v in tt.items():
    if isinstance(v, dict) and "type" in v:
        for c in (v["color"] if isinstance(v["color"], list) else [v["color"]]): idx2type[int(c)] = v["type"]
names = {r[0]: r[4] for r in read_definition()}
out = [(i, names[i], idx2type[d["maj"][i]], d["majcat"][str(i)]) for i in range(1, len(d["maj"]) - 1) if i not in sea and idx2type.get(d["maj"][i]) != d["majcat"][str(i)] and str(i) not in d["over"]]
print(len(out)); [print(*o) for o in out[:12]]
