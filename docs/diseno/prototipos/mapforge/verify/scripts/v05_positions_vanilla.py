# v05: vanilla positions.txt key statistics for sea provinces, text_rotation range
import sys,re,collections,math
sys.path.insert(0,sys.path[0]); import cw
V='/home/user/corpus/vanilla/map/'
dm=open(V+'default.map',encoding='latin-1').read()
ss=set(int(x) for x in re.search(r'sea_starts\s*=\s*\{([^}]*)\}',dm).group(1).split())
P=cw.read(V+'positions.txt')
seakeys=collections.Counter(); rots=[]
for k,v in P:
    pid=int(k)
    if pid in ss:
        for kk,_ in v: seakeys[kk]+=1
    for kk,vv in v:
        if kk=='text_rotation': rots.append(float(vv))
print('sea blocks keys',dict(seakeys))
print('text_rotation n',len(rots),'min',min(rots),'max',max(rots),'neg',sum(r<0 for r in rots),'>2pi',sum(r>=2*math.pi for r in rots))
