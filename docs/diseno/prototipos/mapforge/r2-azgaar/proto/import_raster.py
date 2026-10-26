"""Importación: rasterizar puntos arbitrarios (pack de FMG: no uniformes) por cubos, y comparar
con el relleno de polígonos de Pillow. Mapa FMG típico 1920x1080 escalado a 5616x2160."""
import sys, os, time, numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge as F
W,H=5616,2160

def rasterize_points(P, W, H, cell, band=64):
    """Vecino más cercano para puntos arbitrarios: cubos de lado `cell`, 3x3 cubos por píxel,
    ocupación rellenada a K. Exacto si cada cubo de 3x3 contiene el vecino (se comprueba con 5x5)."""
    bx = np.minimum((P[:,0]//cell).astype(int), int(np.ceil(W/cell))-1); by = np.minimum((P[:,1]//cell).astype(int), int(np.ceil(H/cell))-1)
    nbx, nby = int(np.ceil(W/cell)), int(np.ceil(H/cell))
    b = by*nbx+bx; order=np.argsort(b, kind="stable"); cnt=np.bincount(b, minlength=nbx*nby)
    K=int(cnt.max()); start=np.concatenate([[0],np.cumsum(cnt)[:-1]])
    pad=np.full((nbx*nby,K),-1,np.int64); rank=np.arange(b.size)-start[b[order]]
    pad[b[order],rank]=order
    out=np.empty((H,W),np.int32); Pf=P.astype(np.float32)
    xs=np.arange(W,dtype=np.float32)+.5
    for y0 in range(0,H,band):
        y1=min(H,y0+band); yy=(np.arange(y0,y1,dtype=np.float32)+.5)[:,None]; xx=xs[None,:]
        cbx=(xx//cell).astype(int); cby=(yy//cell).astype(int)
        best=np.full((y1-y0,W),np.inf,np.float32); bid=np.zeros((y1-y0,W),np.int32)
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                qx=np.clip(cbx+dx,0,nbx-1); qy=np.clip(cby+dy,0,nby-1); q=(qy*nbx+qx)
                for k in range(K):
                    cid=pad[q,k]; ok=cid>=0; c=np.maximum(cid,0)
                    d=(Pf[c,0]-xx)**2+(Pf[c,1]-yy)**2; d[~ok]=np.inf
                    m=d<best; best[m]=d[m]; bid[m]=c[m]
        out[y0:y1]=bid
    return out, K

for N in (10000, 60000):
    lat=F.make_lattice(W,H,N,"hex",0.9,False,3)
    P=lat.pts.copy()
    # pack de FMG: se densifica una franja ("costa") con puntos medios y se quitan puntos ("océano profundo")
    rng=np.random.default_rng(1)
    coast=(np.abs(P[:,1]-H/2)<H*0.08)
    extra=P[coast]+rng.normal(0,lat.dx*0.35,(coast.sum(),2))
    keep=~((P[:,1]<H*0.15))
    Pk=np.concatenate([P[keep],np.clip(extra,0,[W-1,H-1])])
    t=time.perf_counter(); ras,K=rasterize_points(Pk,W,H,cell=lat.dx); dt=time.perf_counter()-t
    print(f"N={N} pack-like points={len(Pk)} bucket occupancy K={K}: bucket NN raster {dt:.2f}s")
    # polígonos: hexágono regular alrededor de cada punto (≈ coste de pack.cells.v + vertices.p)
    r=lat.dx/np.sqrt(3); ang=np.deg2rad(np.arange(30,390,60))
    polys=[list(zip((x+r*np.cos(ang)).tolist(),(y+r*np.sin(ang)).tolist())) for x,y in P]
    im=Image.new("I",(W,H),0); d=ImageDraw.Draw(im)
    t=time.perf_counter()
    for i,pg in enumerate(polys): d.polygon(pg, fill=i+1)
    dt=time.perf_counter()-t
    print(f"N={N}: Pillow ImageDraw.polygon (modo I) {len(polys)} polígonos {dt:.2f}s")
