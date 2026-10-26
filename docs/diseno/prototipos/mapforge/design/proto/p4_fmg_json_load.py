"""p4: coste de leer un «Export to JSON → Full» de FMG del tamaño típico (sintético con la forma de
export-json.ts getFullDataJson: pack.cells[] {i,v,c,p,g,h,area,f,t,haven,harbor,fl,r,conf,biome,s,pop,culture,
burg,routes,state,religion,province}, pack.vertices[] {p,v,c}, grid.cells[] {v,c,b,f,t,h,temp,prec}).
Mide tamaño, json.load y conversión a arrays numpy. Uso: python3 -I p4_fmg_json_load.py NCELLS OUT.json"""
import json, sys, time, random, resource
import numpy as np
n = int(sys.argv[1]); out = sys.argv[2]
rnd = random.Random(1)
cells = [{"i": i, "v": [rnd.randrange(2 * n) for _ in range(6)], "c": [rnd.randrange(n) for _ in range(6)],
          "p": [round(rnd.uniform(0, 1920), 2), round(rnd.uniform(0, 1080), 2)], "g": rnd.randrange(n), "h": rnd.randrange(100),
          "area": rnd.randrange(400), "f": 1, "t": rnd.randrange(-3, 4), "haven": 0, "harbor": 0, "fl": rnd.randrange(500),
          "r": 0, "conf": 0, "biome": rnd.randrange(13), "s": rnd.randrange(100), "pop": round(rnd.uniform(0, 30), 3),
          "culture": rnd.randrange(12), "burg": 0, "routes": {}, "state": rnd.randrange(18), "religion": rnd.randrange(8),
          "province": rnd.randrange(80)} for i in range(n)]
verts = [{"p": [round(rnd.uniform(0, 1920), 2), round(rnd.uniform(0, 1080), 2)], "v": [rnd.randrange(2 * n) for _ in range(3)],
          "c": [rnd.randrange(n) for _ in range(3)]} for _ in range(2 * n)]
grid = [{"v": [rnd.randrange(2 * n) for _ in range(6)], "c": [rnd.randrange(n) for _ in range(6)], "b": 0, "f": 1, "t": 1,
         "h": rnd.randrange(100), "temp": rnd.randrange(-20, 30), "prec": rnd.randrange(100)} for _ in range(n)]
doc = {"info": {"version": "1.156.0", "width": 1920, "height": 1080, "seed": "1"}, "pack": {"cells": cells, "vertices": verts},
       "grid": {"cells": grid}}
json.dump(doc, open(out, "w"), separators=(",", ":"))
del doc, cells, verts, grid
import os
sz = os.path.getsize(out)
t = time.perf_counter(); d = json.load(open(out)); t1 = time.perf_counter() - t
t = time.perf_counter()
pc = d["pack"]["cells"]
h = np.fromiter((c["h"] for c in pc), np.uint8, len(pc)); st = np.fromiter((c["state"] for c in pc), np.int32, len(pc))
pv = np.array([c["v"] for c in pc], dtype=object)
vp = np.array([v["p"] for v in d["pack"]["vertices"]], np.float64)
t2 = time.perf_counter() - t
print(json.dumps({"cells": n, "file_MB": round(sz / 2**20, 1), "json_load_s": round(t1, 2), "to_numpy_s": round(t2, 2),
                  "ru_maxrss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}))
os.remove(out)
