# v14: provinces whose pixels touch both x=0 and x=W-1 in the same row (cross the wrap seam)
import sys,numpy as np
from PIL import Image
for f in sys.argv[1:]:
    im=np.asarray(Image.open(f).convert('RGB')).astype(np.int64)
    k=(im[...,0]<<16)|(im[...,1]<<8)|im[...,2]
    same=k[:,0]==k[:,-1]
    cross=np.unique(k[same,0])
    # are they connected only through the seam? check if left part and right part are separate when wrap disabled: approx via column extents
    print(f[-60:],'rows with same id at both edges',int(same.sum()),'provinces crossing seam',len(cross))
