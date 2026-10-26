# v09: np.unique timing on vanilla province colors: default vs explicit sort-based (numpy 1.x behaviour)
import numpy as np,time,inspect
from PIL import Image
im=np.asarray(Image.open('/home/user/corpus/vanilla/map/provinces.bmp').convert('RGB'))
key=((im[...,0].astype(np.uint32)<<16)|(im[...,1].astype(np.uint32)<<8)|im[...,2]).ravel()
print(np.__version__, 'sorted' in inspect.signature(np.unique).parameters)
for rep in range(2):
    t=time.perf_counter(); u=np.unique(key); a=time.perf_counter()-t
    t=time.perf_counter(); s=np.sort(key); u2=s[np.r_[True,s[1:]!=s[:-1]]]; b=time.perf_counter()-t
    t=time.perf_counter(); c=np.bincount(key,minlength=1<<24); u3=np.flatnonzero(c); d=time.perf_counter()-t
    print('np.unique %.2f s | sort-based (numpy<2.3 path) %.2f s | bincount 2^24 %.2f s'%(a,b,d), len(u),len(u2),len(u3))
for rep in range(2):
    t=time.perf_counter(); lut=np.zeros(1<<24,np.uint16); lut[u]=np.arange(1,len(u)+1); ids=lut[key]; e=time.perf_counter()-t
    t=time.perf_counter(); ids2=np.searchsorted(u,key).astype(np.uint16)+1; f=time.perf_counter()-t
    print('dense LUT build+gather %.2f s | searchsorted %.2f s'%(e,f), bool((ids==ids2).all()))
