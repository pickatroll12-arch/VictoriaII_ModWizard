# v11: POP types present in vanilla unowned land provinces (1836) and craftsmen/capitalists presence
import re,glob,os,collections
owned=set(); land=set()
for f in glob.glob('/home/user/corpus/vanilla/history/provinces/**/*.txt',recursive=True):
    m=re.match(r'\s*(\d+)',os.path.basename(f))
    if not m: continue
    pid=int(m.group(1)); land.add(pid)
    t=re.sub(r'#[^\n]*','',open(f,encoding='latin-1').read())
    t=re.split(r'\n\s*\d{4}\.\d+\.\d+\s*=',t)[0]
    if re.search(r'^\s*owner\s*=',t,re.M): owned.add(pid)
types_un=collections.Counter(); types_own_prov=collections.Counter(); nprov=collections.Counter()
for f in glob.glob('/home/user/corpus/vanilla/history/pops/1836.1.1/*.txt'):
    t=re.sub(r'#[^\n]*','',open(f,encoding='latin-1').read())
    for m in re.finditer(r'(\d+)\s*=\s*\{((?:[^{}]|\{[^{}]*\})*)\}',t):
        pid=int(m.group(1)); ts=set(re.findall(r'(\w+)\s*=\s*\{',m.group(2)))
        grp='unowned' if pid not in owned else 'owned'; nprov[grp]+=1
        for x in ts: types_un[(grp,x)]+=1
print('land files',len(land),'owned',len(owned))
for g in ('owned','unowned'):
    print(g,nprov[g],{k[1]:v for k,v in sorted(types_un.items(),key=lambda kv:-kv[1]) if k[0]==g})
