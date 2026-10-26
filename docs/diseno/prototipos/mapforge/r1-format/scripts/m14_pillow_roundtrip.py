"""m14: ¿Pillow reescribe los BMP de vanilla byte a byte? (escribe en out/, no toca el corpus)"""
import io, time, hashlib
from common import *
for name in ("terrain.bmp", "rivers.bmp", "provinces.bmp"):
    src = open(V + "/map/" + name, "rb").read()
    t = time.time(); im = Image.open(io.BytesIO(src)); im.load(); t1 = time.time() - t
    buf = io.BytesIO(); t = time.time(); im.save(buf, "BMP"); t2 = time.time() - t
    out = buf.getvalue()
    diff = sum(1 for a, b in zip(src, out) if a != b) if len(src) == len(out) else None
    print(f"{name}: lee {t1:.2f}s escribe {t2:.2f}s; tamaño {len(src)} -> {len(out)}; bytes distintos {diff}; cabecera distinta en {[i for i in range(min(54, len(out))) if src[i] != out[i]]}")
import struct
for name, off in (("terrain.bmp", 1078), ("provinces.bmp", 54)):
    src = open(V + "/map/" + name, "rb").read(); buf = io.BytesIO(); Image.open(V + "/map/" + name).save(buf, "BMP"); out = buf.getvalue()
    print(name, "datos+paleta idénticos:", src[54:len(out)] == out[54:], " cola extra:", src[len(out):], " hdr src", struct.unpack_from("<IiiHHIIiiII", src, 14), " hdr pillow", struct.unpack_from("<IiiHHIIiiII", out, 14))
