# v18: per land province, does the majority terrain.bmp index belong to the majority category? (generated or vanilla)
import sys,re,numpy as np
from PIL import Image
M=sys.argv[1].rstrip('/')+'/'
tt=open('/home/user/corpus/vanilla/map/terrain.txt',encoding='cp1252').read()
cat_of=np.full(256,-1); names={}
for m in re.finditer(r'text_(\d+)\s*=\s*\{\s*type\s*=\s*(\w+)',tt):
    c=names.setdefault(m.group(2),len(names)); cat_of[int(m.group(1))]=c
cat_of[64:254]=names.setdefault('plains',len(names)); cat_of[255]=names['plains']; cat_of[254]=names.setdefault('ocean',len(names))
im=np.asarray(Image.open(M+'provinces.bmp').convert('RGB')).astype(np.int64)
key=(im[...,0]<<16)|(im[...,1]<<8)|im[...,2]
u,inv=np.unique(key.ravel(),return_inverse=True)
t=np.asarray(Image.open(M+'terrain.bmp')).ravel().astype(np.int64)
P=len(u)
bi=np.bincount(inv*256+t,minlength=P*256).reshape(P,256)
nc=len(names); bc=np.zeros((P,nc),np.int64)
for i in range(256):
    if cat_of[i]>=0: bc[:,cat_of[i]]+=bi[:,i]
land=bi[:,254]<bi.sum(1)/2
maj_idx=bi.argmax(1); maj_cat=bc.argmax(1)
mis=(cat_of[maj_idx]!=maj_cat)&land
print(M,'land provinces',int(land.sum()),'majority-index category != majority category',int(mis.sum()))
