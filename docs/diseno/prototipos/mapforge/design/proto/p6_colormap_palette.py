"""p6: paleta del colormap «aprendida» de la instalación del usuario en tiempo de ejecución:
color medio y dispersión de colormap.dds por categoría de terreno (terrain.bmp submuestreado a W/3 con el
desplazamiento de 4 px medido en r1). Nada se guarda en el repositorio. Uso: python3 -I p6_colormap_palette.py VANILLA"""
import json, re, sys, time
import numpy as np
from PIL import Image
V = sys.argv[1]
t = time.perf_counter()
cm = np.asarray(Image.open(V + "/map/terrain/colormap.dds").convert("RGB")).astype(np.float32)   # 720×1880
ter = np.asarray(Image.open(V + "/map/terrain.bmp"))
cat_of = {}
for m in re.finditer(r"text_(\d+)\s*=\s*\{\s*type\s*=\s*(\w+)", open(V + "/map/terrain.txt", encoding="cp1252").read()):
    cat_of[int(m.group(1))] = m.group(2)
cats = sorted(set(cat_of.values()))
lut = np.full(256, -1); 
for i, c in cat_of.items(): lut[i] = cats.index(c)
sub = lut[ter[1::3, 1::3]][:720, :1872]
c2 = cm[:, 4:4 + 1872]
out = {}
for k, c in enumerate(cats):
    m = sub == k
    if m.sum() < 100: continue
    px = c2[m]
    out[c] = {"px": int(m.sum()), "mean": px.mean(0).round(0).tolist(), "std": px.std(0).round(1).tolist()}
print(json.dumps({"per_category": out, "seconds": round(time.perf_counter() - t, 2)}, indent=0))
