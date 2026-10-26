"""Mide el corpus vanilla para la correspondencia FMG -> Victoria II (solo lectura)."""
import sys, re, collections, time
import numpy as np
from PIL import Image
sys.path.insert(0, "/home/user/VictoriaII_ModWizard/src")
from vic2studio.core.clausewitz import parse_file
V = "/home/user/corpus/vanilla/"
t0=time.time()
img = np.asarray(Image.open(V+"map/provinces.bmp").convert("RGB"))
H, W, _ = img.shape
key = (img[...,0].astype(np.uint32)<<16)|(img[...,1].astype(np.uint32)<<8)|img[...,2]
# definition
rows = {}
for line in open(V+"map/definition.csv", encoding="cp1252").read().splitlines()[1:]:
    p = line.split(";")
    try: pid=int(p[0]); r=int(p[1]); g=int(p[2]); b=int(re.match(r"\d+",p[3]).group())
    except Exception: continue
    rows[(r<<16)|(g<<8)|b]=pid
lut_keys = np.array(sorted(rows)); lut_ids=np.array([rows[k] for k in lut_keys])
flat = key.ravel()
u, inv, cnt = np.unique(flat, return_inverse=True, return_counts=True)
pos = np.searchsorted(lut_keys, u); pos[pos>=len(lut_keys)]=0
uid = np.where(lut_keys[pos]==u, lut_ids[pos], 0)
ids = uid[inv].reshape(H,W)
area = np.bincount(ids.ravel(), minlength=3300)
dm = open(V+"map/default.map", encoding="cp1252").read()
sea = set(int(x) for x in re.search(r"sea_starts\s*=\s*\{([^}]*)\}", dm).group(1).split())
land_ids = [i for i in range(1,3249) if i not in sea and area[i]>0]
sea_ids = [i for i in sea if area[i]>0]
la = area[land_ids]; sa = area[sea_ids]
print(f"size {W}x{H}; land provinces {len(land_ids)} sea {len(sea_ids)}")
q=lambda a: np.percentile(a,[5,25,50,75,95]).astype(int).tolist()
print("land area px: total", la.sum(), f"({la.sum()/(W*H):.1%})", "pctl5/25/50/75/95", q(la), "mean", int(la.mean()))
print("sea  area px: total", sa.sum(), f"({sa.sum()/(W*H):.1%})", "pctl", q(sa), "mean", int(sa.mean()))
print("unassigned px", int(area[0]))
# terrain.bmp
tb = Image.open(V+"map/terrain.bmp"); print("terrain.bmp mode", tb.mode, tb.size)
tr = np.asarray(tb); tc = np.bincount(tr.ravel(), minlength=256)
print("terrain idx used:", int((tc>0).sum()), "top", sorted([(int(c),i) for i,c in enumerate(tc) if c], reverse=True)[:8])
# terrain of sea pixels
seamask = np.isin(ids, np.array(sorted(sea)))
print("terrain idx on sea pixels:", collections.Counter(tr[seamask].tolist()).most_common(4))
rb = Image.open(V+"map/rivers.bmp"); rr=np.asarray(rb); rc=np.bincount(rr.ravel(), minlength=256)
print("rivers.bmp mode", rb.mode, rb.size, "idx counts", {i:int(c) for i,c in enumerate(rc) if c})
pal = rb.getpalette()[:3*16]; print("rivers palette 0..15", [tuple(pal[i:i+3]) for i in range(0,48,3)])
with open(V+"map/rivers.bmp","rb") as f: hdr=f.read(54); import struct; print("rivers.bmp bfOffBits", struct.unpack("<I",hdr[10:14])[0])
with open(V+"map/terrain.bmp","rb") as f: hdr=f.read(54); print("terrain.bmp bfOffBits", struct.unpack("<I",hdr[10:14])[0])
# river pixels per land province
print("river pixels (idx<=11):", int((rr<=11).sum()))
# regions
reg = parse_file(V+"map/region.txt")
print(type(reg))
