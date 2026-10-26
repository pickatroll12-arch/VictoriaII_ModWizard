# v03: compare DDS headers vanilla vs generated
import struct,sys,os
def hdr(f):
    b=open(f,'rb').read(128)
    v=struct.unpack('<4s7I44x8I5I',b[:128])
    # magic,size,flags,h,w,pitch,depth,mips, pf: size,flags,fourcc,rgbbits,rmask,gmask,bmask,amask, caps1..4,res
    magic,size,flags,h,w,pitch,depth,mips=v[:8]
    pfsize,pfflags,fourcc,bits,rm,gm,bm,am=v[8:16]
    caps=v[16:18]
    return dict(flags=hex(flags),w=w,h=h,pitch=pitch,mips=mips,pfflags=hex(pfflags),fourcc=struct.pack('<I',fourcc),bits=bits,masks=(hex(rm),hex(gm),hex(bm),hex(am)),caps=tuple(hex(c) for c in caps),filesize=os.path.getsize(f))
for d in ['/home/user/corpus/vanilla/map/terrain/', sys.argv[1]]:
    for n in ['colormap.dds','colormap_political.dds','colormap_no_shadow.dds','colormap_water.dds']:
        print(d[-30:],n,hdr(d+n))
print('minimap van',hdr('/home/user/corpus/vanilla/gfx/interface/minimap.dds'))
print('minimap gen',hdr(sys.argv[1]+'../../gfx/interface/minimap.dds'))
