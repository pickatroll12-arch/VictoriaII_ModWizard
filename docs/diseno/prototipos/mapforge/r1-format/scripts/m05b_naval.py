"""m05b: building_position.naval_base frente a costeras; dónde cae (tierra propia, mar)."""
import json, collections
from common import *
pos = load(V + "/map/positions.txt"); ids = province_ids(); H, W = ids.shape
sea, maxp = sea_ids(); coastal = set(json.load(open(OUT + "/m02.json"))["coastal"])
nbp = {int(k): v["building_position"]["naval_base"] for k, v in pos.items() if isinstance(v.get("building_position"), dict) and "naval_base" in v["building_position"]}
print("con building_position.naval_base:", len(nbp), " de ellas costeras:", len(set(nbp) & coastal), " costeras sin ella:", len(coastal - set(nbp)))
where = collections.Counter()
for pid, p in nbp.items():
    x, y = int(round(float(p["x"]))) % W, int(round(float(p["y"])))
    q = int(ids[y, x]); where["propia" if q == pid else ("mar" if q in sea else "otra_tierra")] += 1
print("naval_base cae en:", dict(where))
print("ejemplo building_rotation:", [v["building_rotation"] for v in pos.values() if "building_rotation" in v][:3])
print("ejemplo railroad_visibility:", [v["railroad_visibility"] for v in pos.values() if "railroad_visibility" in v][:2])
print("ejemplo building_nudge:", [v["building_nudge"] for v in pos.values() if "building_nudge" in v][:2])
print("ejemplo town/city:", [ (k, v.get("town"), v.get("city")) for k, v in pos.items() if "town" in v][:2])
