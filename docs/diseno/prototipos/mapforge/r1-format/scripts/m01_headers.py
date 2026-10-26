"""m01: cabeceras de BMP, DDS y TGA de map/ y map/terrain (solo lectura)."""
import struct, sys, os, glob
V = sys.argv[1] if len(sys.argv) > 1 else "/home/user/corpus/vanilla"
def bmp(p):
    b = open(p, "rb").read(1078)
    off, = struct.unpack_from("<I", b, 10); hs, w, h, planes, bpp, comp, isz, xppm, yppm, clr, imp = struct.unpack_from("<IiiHHIIiiII", b, 14)
    return f"BMP hdr={hs} {w}x{h} (h>0 => bottom-up={h>0}) bpp={bpp} comp={comp} dataoff={off} clrUsed={clr} size={os.path.getsize(p)}"
DDPF = {4: "FOURCC", 0x40: "RGB", 0x41: "RGBA", 0x1: "ALPHAPIXELS", 0x20000: "LUMINANCE", 0x2:"ALPHA"}
def dds(p):
    b = open(p, "rb").read(128)
    assert b[:4] == b"DDS "
    size, flags, h, w, pitch, depth, mips = struct.unpack_from("<7I", b, 4)
    pf = struct.unpack_from("<2I4s5I", b, 76)
    pfflags, fourcc, bits, rm, gm, bm, am = pf[1], pf[2], pf[3], pf[4], pf[5], pf[6], pf[7]
    caps = struct.unpack_from("<4I", b, 108)
    fmt = fourcc.decode('latin1') if pfflags & 4 else f"RGB{bits} masks R={rm:08x} G={gm:08x} B={bm:08x} A={am:08x}"
    return f"DDS {w}x{h} mips={mips} pfflags={pfflags:#x} fmt={fmt} caps={caps[0]:#x},{caps[1]:#x} size={os.path.getsize(p)}"
def tga(p):
    b = open(p, "rb").read(18)
    idl, cmt, it, cmo, cml, cmd, xo, yo, w, h, bpp, desc = struct.unpack("<BBBHHBHHHHBB", b)
    return f"TGA {w}x{h} type={it} ({'RLE' if it>=9 else 'raw'}) bpp={bpp} origin={'top' if desc & 0x20 else 'bottom'}-left alphabits={desc&15} cmap={cmt} size={os.path.getsize(p)}"
for p in sorted(glob.glob(V + "/map/*.bmp") + glob.glob(V + "/map/terrain/*") + glob.glob(V + "/map/terrain/trees/*")):
    if os.path.isdir(p): continue
    ext = p.rsplit(".", 1)[-1].lower()
    f = {"bmp": bmp, "dds": dds, "tga": tga}.get(ext)
    print(p.replace(V + "/", ""), "|", f(p) if f else "?")
