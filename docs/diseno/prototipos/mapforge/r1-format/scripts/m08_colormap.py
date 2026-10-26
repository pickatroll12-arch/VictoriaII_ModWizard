"""m08: colormap*.dds: orientación respecto a provinces.bmp, columnas de relleno, relación con la máscara de mar."""
import struct
from common import *
def read_dds_rgba(p):
    b = open(p, "rb").read()
    h, w = struct.unpack_from("<II", b, 12)
    pfflags, = struct.unpack_from("<I", b, 80); bits, = struct.unpack_from("<I", b, 88)
    assert pfflags & 0x40, "comprimido"
    bpp = bits // 8
    a = np.frombuffer(b, np.uint8, w * h * bpp, 128).reshape(h, w, bpp)
    return a[..., [2, 1, 0]]  # BGR(A) -> RGB
ids = province_ids(); H, W = ids.shape
sea, maxp = sea_ids(); is_sea = np.zeros(maxp + 1, bool); is_sea[list(sea)] = True
seam = is_sea[ids].astype(float)
for name, f in [("colormap", 3), ("colormap_political", 3), ("colormap_water", 6)]:
    c = read_dds_rgba(V + f"/map/terrain/{name}.dds").astype(float)
    h, w, _ = c.shape
    ds = seam[: (H // f) * f, : (W // f) * f].reshape(H // f, f, W // f, f).mean((1, 3))
    lum = c[..., :3].mean(2)
    print(f"== {name} {w}x{h}: ds {ds.shape}")
    for flip in (False, True):
        for off in (0, w - ds.shape[1]):
            if off < 0: continue
            L = lum[:, off: off + ds.shape[1]][: ds.shape[0]]
            D = ds[::-1] if flip else ds
            r = np.corrcoef(L.ravel(), D.ravel())[0, 1]
            print(f"   flipV={flip} xoff={off}: corr(lum, mar) = {r:+.3f}")
    extra = c[:, ds.shape[1]:, :3]
    if extra.size:
        print("   columnas extra", extra.shape[1], ": media", extra.mean((0, 1)).round(1), " ¿iguales a las primeras columnas?", np.abs(extra - c[:, :extra.shape[1], :3]).mean().round(2), " ¿a las anteriores?", np.abs(extra - c[:, ds.shape[1]-extra.shape[1]:ds.shape[1], :3]).mean().round(2))
    if c.shape[2] == 4: print("   alfa: min/med/max", c[..., 3].min(), np.median(c[..., 3]), c[..., 3].max())
