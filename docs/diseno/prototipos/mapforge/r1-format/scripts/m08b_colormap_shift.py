"""m08b: desplazamiento horizontal óptimo (0..8) de colormap y colormap_political respecto a la máscara de mar."""
from m08_colormap import read_dds_rgba  # noqa (re-ejecuta m08: aceptable)
from common import *
ids = province_ids(); H, W = ids.shape
sea, maxp = sea_ids(); is_sea = np.zeros(maxp + 1, bool); is_sea[list(sea)] = True
ds = is_sea[ids].astype(float).reshape(H // 3, 3, W // 3, 3).mean((1, 3))
for name in ("colormap", "colormap_political"):
    c = read_dds_rgba(V + f"/map/terrain/{name}.dds").astype(float)
    for ch, lab in [(0, "R"), (1, "G"), (2, "B")]:
        rs = [np.corrcoef(c[:, o:o + ds.shape[1], ch].ravel(), ds.ravel())[0, 1] for o in range(9)]
        print(name, lab, " ".join(f"{o}:{r:+.3f}" for o, r in enumerate(rs)))
    sea_px = c[:, 8:, :3][ds > 0.99]; land_px = c[:, 8:, :3][ds < 0.01]
    print(name, "media RGB mar", sea_px.mean(0).round(1), "tierra", land_px.mean(0).round(1))
