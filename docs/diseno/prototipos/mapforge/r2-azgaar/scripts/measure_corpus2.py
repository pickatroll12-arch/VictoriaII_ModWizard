"""Regiones, continentes, climas, POPs y adyacencias de vanilla por regex (el parser del repo está en obras)."""
import re, glob, collections, numpy as np
V="/home/user/corpus/vanilla/"
def strip(t): return re.sub(r"#[^\r\n]*","",t)
reg = strip(open(V+"map/region.txt",encoding="cp1252").read())
sizes=[len(m.group(2).split()) for m in re.finditer(r"(\w+)\s*=\s*\{([^}]*)\}",reg)]
s=np.array(sizes); print("region.txt states",len(s),"provs/state pctl5/25/50/75/95",np.percentile(s,[5,25,50,75,95]).tolist(),"mean",round(s.mean(),2),"max",s.max())
rs = strip(open(V+"map/region_sea.txt",encoding="cp1252").read())
ss=[len(m.group(2).split()) for m in re.finditer(r"(\w+)\s*=\s*\{([^}]*)\}",rs)]
print("region_sea.txt",len(ss),"empty",sum(1 for x in ss if x==0),"provs",sum(ss))
cl = strip(open(V+"map/climate.txt",encoding="cp1252").read())
keys=re.findall(r"^(\w+)\s*=\s*\{",cl,re.M); print("climate keys",collections.Counter(keys))
co = strip(open(V+"map/continent.txt",encoding="cp1252").read()); print("continents",re.findall(r"^(\w+)\s*=",co,re.M))
# adjacencies
adj=[l for l in open(V+"map/adjacencies.csv",encoding="cp1252").read().splitlines() if l and l[0].isdigit()]
print("adjacencies rows",len(adj),"types",collections.Counter(l.split(";")[2] for l in adj))
print("adjacency sample", adj[:2])
# POPs 1836
tot=collections.Counter(); per=collections.defaultdict(int); types=collections.Counter(); blocks=0
for f in glob.glob(V+"history/pops/1836.1.1/*.txt"):
    t=strip(open(f,encoding="cp1252",errors="replace").read())
    for m in re.finditer(r"(\d+)\s*=\s*\{((?:[^{}]|\{[^{}]*\})*)\}",t):
        pid=int(m.group(1))
        for pm in re.finditer(r"(\w+)\s*=\s*\{([^{}]*)\}",m.group(2)):
            sz=re.search(r"size\s*=\s*(\d+)",pm.group(2)); 
            if sz: per[pid]+=int(sz.group(1)); types[pm.group(1)]+=int(sz.group(1)); blocks+=1
p=np.array(list(per.values())); print("POP 1836: provinces",len(p),"pop blocks",blocks,"total size",p.sum(),"per prov pctl5/50/95",np.percentile(p,[5,50,95]).astype(int).tolist())
print("by type", types.most_common())
# province history fields
lr=collections.Counter(); tg=collections.Counter(); n=0
for f in glob.glob(V+"history/provinces/*/*.txt"):
    t=strip(open(f,encoding="cp1252",errors="replace").read()); n+=1
    m=re.search(r"^life_rating\s*=\s*(\d+)",t,re.M); lr[int(m.group(1)) if m else None]+=1
    m=re.search(r"^trade_goods\s*=\s*(\w+)",t,re.M); tg[m.group(1) if m else None]+=1
print("prov history files",n,"life_rating",sorted(lr.items(),key=lambda x:(x[0] is None, x[0] or 0))[:20])
print("trade_goods",tg.most_common(25))
# cultures / religions counts
cu=strip(open(V+"common/cultures.txt",encoding="cp1252").read())
re_=strip(open(V+"common/religion.txt",encoding="cp1252").read())
print("religion groups/religions:",re.findall(r"^(\w+)\s*=\s*\{",re_,re.M))
