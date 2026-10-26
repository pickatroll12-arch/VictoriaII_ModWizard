# v16: orientation of colormap.dds / colormap_water.dds vs land mask from terrain.bmp (as Pillow loads both)
import numpy as np,sys
from PIL import Image
for d in ['/home/user/corpus/vanilla/map/',sys.argv[1]]:
    t=np.asarray(Image.open(d+'terrain.bmp')); sea=(t==254).astype(np.float32)
    H,W=sea.shape
    for n,(w,h) in [('terrain/colormap_water.dds',(W//6,H//6)),('terrain/colormap.dds',(W//3,H//3))]:
        c=np.asarray(Image.open(d+n).convert('RGB')).astype(np.float32)
        if n.endswith('colormap.dds'): c=c[:, 4:4+W//3]
        b=c[...,2]-c[...,0]  # blueness
        s=np.asarray(Image.fromarray(sea).resize((c.shape[1],c.shape[0]),Image.BILINEAR))
        r0=np.corrcoef(b.ravel(),s.ravel())[0,1]; r1=np.corrcoef(b.ravel(),s[::-1].ravel())[0,1]
        print(d[-24:],n,'corr as-is %.3f flipped %.3f'%(r0,r1))
