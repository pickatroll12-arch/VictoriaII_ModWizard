# v13: overlap between FMG bundled name bases (MIT) and vanilla PROV/state localisation names
import re,glob,sys,collections
src=open(sys.argv[1],encoding='utf-8').read()
bases=re.findall(r'\bb:\s*"([^"]*)"',src)
names=set()
for b in bases: names.update(n.strip() for n in b.split(',') if n.strip())
print('bases',len(bases),'names',len(names))
van=set()
for f in glob.glob('/home/user/corpus/vanilla/localisation/*.csv'):
    for l in open(f,encoding='cp1252',errors='replace'):
        p=l.split(';')
        if len(p)>1 and re.match(r'PROV\d+$',p[0]): van.add(p[1].strip())
ov=sorted(names&van)
print('vanilla PROV names',len(van),'overlap with FMG bases',len(ov),ov[:25])
