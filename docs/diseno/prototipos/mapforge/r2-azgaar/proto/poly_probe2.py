import sys, os, time, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge as F
W,H=5616,2160
for N in (30000,60000):
    lat=F.make_lattice(W,H,N,"hex",0.3,True,7)
    polys=F.hex_voronoi_polygons(lat)
    rng=np.random.default_rng(3)
    nz=(F.value_noise(W,H,int(lat.dx*2),1.0,rng)+F.value_noise(W,H,max(1,int(lat.dx/2)),0.35,rng),
        F.value_noise(W,H,int(lat.dx*2),1.0,rng)+F.value_noise(W,H,max(1,int(lat.dx/2)),0.35,rng))
    for name,kw in (("plain",{}),("warp_subdiv4",dict(subdiv=4,noise=nz,amp=0.3*lat.dx))):
        t=time.perf_counter(); r=F.draw_polygons(polys,W,H,True,**kw); r,passes=F.fill_gaps(r); dt=time.perf_counter()-t
        frag=F.raster_fragments(r+1,True)
        cnt=np.bincount(r.ravel(),minlength=lat.n)
        e=F.raster_edges(r,True); a=set(map(tuple,F.edges_from_padded(F.implicit_neighbors(lat,"hex6")).tolist())); b=set(map(tuple,e.tolist())); tp=len(a&b)
        print(f"N={N} {name}: draw+fill {dt:.2f}s (fill passes {passes}) fragmented cells={(frag[1:]>1).sum()} empty cells={(cnt==0).sum()} hex6 vs raster: P={tp/len(a):.4f} R={tp/len(b):.4f}")
