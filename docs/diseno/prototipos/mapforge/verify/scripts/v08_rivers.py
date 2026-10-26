# v08: river raster stats (4-neighbour degree, endpoints next to water, markers)
import sys,numpy as np
from PIL import Image
for f in sys.argv[1:]:
    r=np.asarray(Image.open(f)); rv=r<254; water=r==254
    p=np.pad(rv,1); pw=np.pad(water,1)
    n4=p[:-2,1:-1].astype(int)+p[2:,1:-1]+p[1:-1,:-2]+p[1:-1,2:]
    w4=pw[:-2,1:-1].astype(int)+pw[2:,1:-1]+pw[1:-1,:-2]+pw[1:-1,2:]
    deg=n4[rv]; ends=rv&(n4<=1)
    print(f[-50:],'px',int(rv.sum()),'deg dist',{k:round(float((deg==k).mean()),3) for k in range(5)})
    print('  endpoints',int(ends.sum()),'endpoints touching water',int((ends&(w4>0)).sum()),'idx0',int((r==0).sum()),'idx1',int((r==1).sum()),'deg>=3 px',int((rv&(n4>=3)).sum()))
