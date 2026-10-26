"""Topología de rivers.bmp de vanilla: conectividad 4/8, bloques 2x2, fuentes y confluencias."""
import numpy as np
from PIL import Image
r=np.asarray(Image.open("/home/user/corpus/vanilla/map/rivers.bmp"))
R=(r<=11)
p=np.pad(R,1)
n4=p[:-2,1:-1].astype(int)+p[2:,1:-1]+p[1:-1,:-2]+p[1:-1,2:]
nd=p[:-2,:-2].astype(int)+p[:-2,2:]+p[2:,:-2]+p[2:,2:]
tot=R.sum()
print("river px",tot)
print("4-neighbour count distribution:",{k:int(((n4==k)&R).sum()) for k in range(5)})
print("px with 0 orthogonal river nbr but diagonal ones:",int(((n4==0)&(nd>0)&R).sum()))
b=R[:-1,:-1]&R[1:,:-1]&R[:-1,1:]&R[1:,1:]; print("2x2 full river blocks",int(b.sum()))
for v in (0,1):
    ys,xs=np.nonzero(r==v); print("idx",v,"count",len(ys),"with orth river nbrs:",np.bincount(n4[ys,xs],minlength=5).tolist())
# what lies under rivers in provinces? (land only?)
