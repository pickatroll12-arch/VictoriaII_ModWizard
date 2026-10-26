# v07: fraction of secondary position points coinciding with unit (generated vs vanilla)
import sys,collections,math
sys.path.insert(0,sys.path[0]); import cw
for path in sys.argv[1:]:
    P=cw.read(path); same=collections.Counter(); tot=collections.Counter(); keys=collections.Counter()
    for k,v in P:
        d=dict((kk,vv) for kk,vv in v if kk)
        if 'unit' not in d: continue
        u=dict(d['unit']); ux,uy=float(u['x']),float(u['y'])
        sec=[(kk,vv) for kk,vv in v if kk in('building_construction','military_construction','factory','city')]
        if 'building_position' in d: sec+= [(kk,vv) for kk,vv in d['building_position'] if kk!='naval_base']
        for kk,vv in sec:
            p=dict(vv); dist=math.hypot(float(p['x'])-ux,float(p['y'])-uy)
            tot[kk]+=1; same[kk]+= dist<1.0
        for kk,_ in v: keys[kk]+=1
    print(path[-60:]); print(' keys',dict(keys))
    print(' frac within 1px of unit',{k:round(same[k]/tot[k],3) for k in tot})
