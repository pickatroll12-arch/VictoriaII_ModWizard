# v06: independent validation of a generated mod's map/ (prototype output)
import sys,re,os,collections,numpy as np,time
sys.path.insert(0,sys.path[0]); import cw
from PIL import Image
M=sys.argv[1].rstrip('/')+'/'
t=time.perf_counter()
im=np.asarray(Image.open(M+'map/provinces.bmp').convert('RGB'))
H,W,_=im.shape
key=(im[...,0].astype(np.int64)<<16)|(im[...,1].astype(np.int64)<<8)|im[...,2]
rows=[l.split(';') for l in open(M+'map/definition.csv',encoding='latin-1').read().splitlines() if not l.startswith('#') and not l.startswith('province') if l.strip() and not l.startswith('#')]
d={int(r[0]):(int(r[1])<<16)|(int(r[2])<<8)|int(r[3]) for r in rows}
lut={v:k for k,v in d.items()}
assert len(lut)==len(d),'dup colors'
uk,inv=np.unique(key.ravel(),return_inverse=True)
missing=[k for k in uk if k not in lut]
print('colors',len(uk),'defs',len(d),'colors w/o id',len(missing))
idmap=np.array([lut.get(k,0) for k in uk]); ids=idmap[inv].reshape(H,W)
present=set(np.unique(ids).tolist()); print('ids without px',len(set(d)-present))
dm=open(M+'map/default.map',encoding='latin-1').read()
print('default.map keys',re.findall(r'^\s*(\w+)\s*=',dm,re.M))
ss=sorted(int(x) for x in re.search(r'sea_starts\s*=\s*\{([^}]*)\}',dm).group(1).split())
mx=int(re.search(r'max_provinces\s*=\s*(\d+)',dm).group(1))
N=max(d); L=min(ss)-1
print('N',N,'max_provinces',mx,'sea contiguous L+1..N',ss==list(range(L+1,N+1)))
is_sea=np.zeros(N+1,bool); is_sea[ss]=True
# water mask consistency
ter=np.asarray(Image.open(M+'map/terrain.bmp')); riv=np.asarray(Image.open(M+'map/rivers.bmp'))
sea_px=is_sea[ids]
print('terrain 254 vs sea mismatch',int(((ter==254)!=sea_px).sum()),'rivers 254 vs sea mismatch',int(((riv==254)!=sea_px).sum()))
# rivers on land only: river px = riv<254
rv=riv<254
print('river px',int(rv.sum()),'river px on sea',int((rv&sea_px).sum()))
# 4-conn check: river px with only diagonal neighbors
p=np.pad(rv,1)
n4=p[:-2,1:-1].astype(int)+p[2:,1:-1]+p[1:-1,:-2]+p[1:-1,2:]
nd=p[:-2,:-2].astype(int)+p[:-2,2:]+p[2:,:-2]+p[2:,2:]
print('river px with 0 4-neighbours but diagonal ones',int((rv&(n4==0)&(nd>0)).sum()),'isolated',int((rv&(n4==0)&(nd==0)).sum()))
# width monotonic not checked here; sources
print('river idx0',int((riv==0).sum()),'idx1',int((riv==1).sum()))
# connectivity of provinces (4-conn, wrap x)
from collections import deque
# label components per id via union-find on runs is heavy; use simple: count components using scipy-free BFS over downsampled? do exact with run-length union-find
def components(ids):
    parent={}
    def find(a):
        while parent[a]!=a:
            parent[a]=parent[parent[a]]; a=parent[a]
        return a
    def union(a,b):
        ra,rb=find(a),find(b)
        if ra!=rb: parent[rb]=ra
    prev=None; nrun=0; runid_of=[]
    runs_prev=[]
    for y in range(H):
        r=ids[y]; ch=np.flatnonzero(np.diff(r))+1; st=np.r_[0,ch]; en=np.r_[ch,W]
        runs=[]
        for s,e in zip(st,en):
            rid=nrun; nrun+=1; parent[rid]=rid; runs.append((s,e,r[s],rid))
        # wrap: first and last run same id
        if len(runs)>1 and runs[0][2]==runs[-1][2]: union(runs[0][3],runs[-1][3])
        # vertical
        i=j=0
        while i<len(runs) and j<len(runs_prev):
            s,e,v,a=runs[i]; s2,e2,v2,b=runs_prev[j]
            if s<e2 and s2<e and v==v2: union(a,b)
            if e<e2: i+=1
            else: j+=1
        runs_prev=runs; runid_of.append(runs)
    comp=collections.defaultdict(set)
    for runs in runid_of:
        for s,e,v,a in runs: comp[v].add(find(a))
    return {k:len(v) for k,v in comp.items()}
c=components(ids)
print('split provinces',sum(1 for v in c.values() if v>1))
# positions
P=cw.read(M+'map/positions.txt')
def pt(v): dd=dict(v); return float(dd['x']),float(dd['y'])
bad=collections.Counter(); tot=collections.Counter(); nb_bad=0; nb_tot=0; blocks=set()
for k,v in P:
    pid=int(k); blocks.add(pid)
    for kk,vv in v:
        if kk in('unit','text_position'):
            x,y=pt(vv); tot[kk]+=1
            if ids[int(y)%H,int(x)%W]!=pid: bad[kk]+=1
        if kk=='building_position':
            for bk,bv in vv:
                x,y=pt(bv); tot[bk]+=1
                if bk=='naval_base':
                    xi,yi=int(x),int(y)
                    if not is_sea[ids[yi,xi]]: bad['naval_not_sea']+=1
                    nbh=[ids[(yi+dy)%H,(xi+dx)%W] for dx,dy in((1,0),(-1,0),(0,1),(0,-1))]
                    if pid not in nbh: bad['naval_not_adjacent']+=1
                elif ids[int(y),int(x)]!=pid: bad[bk]+=1
print('positions blocks',len(blocks),'of',N,'tot',dict(tot),'bad',dict(bad))
# adjacencies
for l in open(M+'map/adjacencies.csv',encoding='latin-1').read().splitlines():
    if l.startswith('#') or not l.strip(): continue
    f,to,ty,th,da=l.split(';')[:5]; f,to,th=int(f),int(to),int(th)
    print('adj',f,to,ty,th,'through sea',is_sea[th],'from/to land',not is_sea[f],not is_sea[to])
print('elapsed',round(time.perf_counter()-t,1))
