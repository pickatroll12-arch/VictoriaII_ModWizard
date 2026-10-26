"""Precisión/recobrado de la vecindad implícita frente a la del ráster según el jitter."""
import sys, os, time, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge as F
W,H=5616,2160
for kind,mode in (("hex","hex6"),("square","square8"),("square","square4")):
    for j in (0.9,0.6,0.3,0.0):
        lat=F.make_lattice(W,H,30000,kind,j,True,7)
        e_imp=F.edges_from_padded(F.implicit_neighbors(lat,mode))
        t=time.perf_counter(); ras=F.rasterize(lat,W,H,reach=1); e=F.raster_edges(ras,True); dt=time.perf_counter()-t
        a=set(map(tuple,e_imp.tolist())); b=set(map(tuple,e.tolist())); tp=len(a&b)
        print(f"{kind:6} {mode:7} jitter={j}: precision={tp/len(a):.4f} recall={tp/len(b):.4f} (raster+edges {dt:.1f}s)")
