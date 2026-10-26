# v04: are sea provinces listed in continent.txt / climate.txt / region.txt in vanilla?
import re,sys
V=sys.argv[1]
dm=open(V+'default.map',encoding='latin-1').read()
ss=set(int(x) for x in re.search(r'sea_starts\s*=\s*\{([^}]*)\}',dm).group(1).split())
mx=int(re.search(r'max_provinces\s*=\s*(\d+)',dm).group(1))
def nums(txt): return [int(x) for x in re.findall(r'\b\d+\b',re.sub(r'#.*','',txt))]
cont=open(V+'continent.txt',encoding='latin-1').read()
# continent blocks: provinces = { ... }
cp=[]
for m in re.finditer(r'provinces\s*=\s*\{([^}]*)\}',re.sub(r'#.*','',cont)): cp+=nums(m.group(1))
print('continent ids',len(cp),'sea in continent',len(set(cp)&ss))
cl=re.sub(r'#.*','',open(V+'climate.txt',encoding='latin-1').read())
clp=[]
for m in re.finditer(r'(\w+)\s*=\s*\{([^{}]*)\}',cl):
    n=nums(m.group(2))
    if n and all(x>=1 for x in n) and not re.search(r'[a-z]',m.group(2)): clp+=n
print('climate ids',len(clp),'sea in climate',len(set(clp)&ss))
rg=re.sub(r'#.*','',open(V+'region.txt',encoding='latin-1').read())
rp=nums(' '.join(m.group(1) for m in re.finditer(r'=\s*\{([^}]*)\}',rg)))
print('region ids',len(rp),'sea in region',len(set(rp)&ss))
print('max_provinces',mx,'sea_starts',len(ss))
