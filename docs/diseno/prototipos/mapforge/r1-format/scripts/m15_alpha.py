"""m15: canal alfa de las texturas RGB32 proporcionales al mapa."""
import struct
from common import *
for n in ("colormap", "colormap_political", "colormap_water"):
    b = open(V + f"/map/terrain/{n}.dds", "rb").read(); h, w = struct.unpack_from("<II", b, 12)
    a = np.frombuffer(b, np.uint8, w * h * 4, 128).reshape(h, w, 4)[..., 3]
    print(n, "alfa min/med/max", int(a.min()), int(np.median(a)), int(a.max()), " valores distintos", len(np.unique(a)))
