"""m12: las 6 anulaciones terrain= de history/provinces frente a la mayoría por índice y por categoría."""
import json
from common import *
d = json.load(open(OUT + "/m03.json")); ids = province_ids(); ter, _ = palette_image(V + "/map/terrain.bmp")
tt = load(V + "/map/terrain.txt")
idx2type = {}
for k, v in tt.items():
    if isinstance(v, dict) and "type" in v:
        for c in (v["color"] if isinstance(v["color"], list) else [v["color"]]): idx2type[int(c)] = v["type"]
for pid, val in d["over"].items():
    pid = int(pid); h = np.bincount(ter[ids == pid], minlength=256)
    top = [(int(i), idx2type[int(i)], int(h[i])) for i in np.argsort(-h)[:4] if h[i]]
    print(pid, "override", val, " mayoría-categoría", d["majcat"][str(pid)], " índices", top)
