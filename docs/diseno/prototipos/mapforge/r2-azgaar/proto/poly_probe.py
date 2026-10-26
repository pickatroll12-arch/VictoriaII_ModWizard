"""Polígonos de Voronoi implícitos (hex, jitter 0,3) + relleno Pillow frente al vecino más cercano."""
import sys, os, time, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge as F
W,H=5616,2160
for N in (10000,30000,60000):
  for rep in (1,2):
    lat=F.make_lattice(W,H,N,"hex",0.3,True,7)
    t=time.perf_counter(); polys=F.hex_voronoi_polygons(lat); t1=time.perf_counter()-t
    t=time.perf_counter(); ras=F.draw_polygons(polys,W,H,True); t2=time.perf_counter()-t
    nn=F.rasterize(lat,W,H,reach=1)
    mism=int((ras!=nn).sum()); gaps=int((ras<0).sum())
    rng=np.random.default_rng(3)
    nz=(F.value_noise(W,H,int(lat.dx*2),1.0,rng)+F.value_noise(W,H,max(1,int(lat.dx/2)),0.35,rng),
        F.value_noise(W,H,int(lat.dx*2),1.0,rng)+F.value_noise(W,H,max(1,int(lat.dx/2)),0.35,rng))
    t=time.perf_counter(); rw=F.draw_polygons(polys,W,H,True,subdiv=4,noise=nz,amp=0.3*lat.dx); t3=time.perf_counter()-t
    gw=int((rw<0).sum())
    e1=F.raster_edges(np.where(rw<0,0,rw),True)
    frag=F.raster_fragments(np.where(rw<0,-1,rw)+1,True)
    print(f"N={N} rep{rep}: polygons {t1:.2f}s draw {t2:.2f}s mismatch_vs_NN={mism}px ({mism/(W*H):.4%}) gaps={gaps}; warped subdiv4 draw {t3:.2f}s gaps={gw} fragmented_cells={(frag[1:]>1).sum()}")
