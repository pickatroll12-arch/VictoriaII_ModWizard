# v02: terrain.bmp index usage vanilla vs generated; rivers index usage
import numpy as np, sys
from PIL import Image
V='/home/user/corpus/vanilla/map/'
G=sys.argv[1]
for name in ['terrain.bmp','rivers.bmp']:
    a=np.asarray(Image.open(V+name)); b=np.asarray(Image.open(G+name))
    ua,ca=np.unique(a,return_counts=True); ub,cb=np.unique(b,return_counts=True)
    print(name,'vanilla used',len(ua),'gen used',len(ub))
    print(' gen indices not used by vanilla:',sorted(set(ub)-set(ua)))
    print(' vanilla unused among 0..63:',sorted(set(range(64))-set(ua)))
    print(' gen idx counts', dict(zip(ub.tolist(),cb.tolist())) if name=='rivers.bmp' else '')
    pa=Image.open(V+name).getpalette()[:768]; pb=Image.open(G+name).getpalette()[:768]
    print(' palette equal',pa==pb)
