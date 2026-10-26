# v01: orientation of provinces.bmp as Pillow returns it vs positions.txt y
import sys, numpy as np
from PIL import Image
V='/home/user/corpus/vanilla/map/'
im=np.asarray(Image.open(V+'provinces.bmp').convert('RGB'))
H,W,_=im.shape
key=(im[...,0].astype(np.uint32)<<16)|(im[...,1].astype(np.uint32)<<8)|im[...,2]
for pid,rgb in [(549,(131,177,168)),(2101,(204,196,215))]:
    k=(rgb[0]<<16)|(rgb[1]<<8)|rgb[2]
    ys,xs=np.nonzero(key==k)
    print(pid,'pillow row mean',ys.mean(),'col',xs.mean(),'H',H)
# top row and bottom row water fraction using definition colors? just print unique counts
print('row0 uniq',len(np.unique(key[0])),'last row uniq',len(np.unique(key[-1])))
Image.fromarray(im[::8,::8]).save(sys.argv[1])
