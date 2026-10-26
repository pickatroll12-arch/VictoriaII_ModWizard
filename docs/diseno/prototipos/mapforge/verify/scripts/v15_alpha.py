# v15: alpha channel content of vanilla vs generated colormaps
import numpy as np,sys
from PIL import Image
for d in ['/home/user/corpus/vanilla/map/terrain/',sys.argv[1]]:
    for n in ['colormap.dds','colormap_water.dds','colormap_political.dds']:
        a=np.asarray(Image.open(d+n).convert('RGBA'))[...,3]
        u=np.unique(a)
        print(d[-28:],n,'alpha unique',len(u),'min',a.min(),'max',a.max(),'mean %.1f'%a.mean())
