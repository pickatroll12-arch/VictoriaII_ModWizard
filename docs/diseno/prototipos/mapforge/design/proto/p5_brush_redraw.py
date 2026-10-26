"""p5: latencia del pincel de relieve en la vista previa: tocar alturas de celdas (radio r) y repintar la
vista 1404×540 por LUT celda→color sobre el ráster de celdas precalculado (sin volver a rasterizar).
Uso: python3 -I p5_brush_redraw.py"""
import os, sys, time, json
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "r2-azgaar", "proto"))
import forge as F
W, H, N = 1404, 540, 60000
lat = F.make_lattice(W, H, N, "hex", 0.3, True, 7)
t = time.perf_counter(); cr = F.rasterize(lat, W, H, reach=1); t_r = time.perf_counter() - t
h = np.random.default_rng(1).uniform(0, 100, lat.n).astype(np.float32)
ramp = np.zeros((101, 4), np.uint8); ramp[:, 3] = 255
ramp[:20, 2] = np.linspace(80, 200, 20); ramp[20:, 1] = np.linspace(160, 60, 81); ramp[20:, 0] = np.linspace(60, 200, 81)
ts = []
for k in range(50):
    t = time.perf_counter()
    cx, cy = np.random.default_rng(k).uniform(0, W), np.random.default_rng(k + 1).uniform(0, H)
    d = np.hypot(lat.pts[:, 0] - cx, lat.pts[:, 1] - cy)
    h = np.clip(h + 5 * np.clip(1 - d / 40, 0, 1), 0, 100)       # pincel «subir»
    img = ramp[h.astype(np.uint8)][cr]                            # (H, W, 4) listo para QImage
    ts.append(time.perf_counter() - t)
print(json.dumps({"raster_cells_preview_once_s": round(t_r, 3), "brush_plus_redraw_ms_median": round(1000 * float(np.median(ts)), 1),
                  "p95_ms": round(1000 * float(np.percentile(ts, 95)), 1)}))
