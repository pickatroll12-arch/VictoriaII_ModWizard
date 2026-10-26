# v10: POP size statistics vanilla 1836 vs generated
import re,glob,sys,numpy as np,collections
def stats(files):
    sizes=[]; prov=collections.Counter(); types=collections.Counter()
    for f in files:
        t=re.sub(r'#[^\n]*','',open(f,encoding='latin-1').read())
        for m in re.finditer(r'(\d+)\s*=\s*\{((?:[^{}]|\{[^{}]*\})*)\}',t):
            pid=int(m.group(1))
            for pm in re.finditer(r'(\w+)\s*=\s*\{[^{}]*size\s*=\s*(\d+)',m.group(2)):
                s=int(pm.group(2)); sizes.append(s); prov[pid]+=s; types[pm.group(1)]+=s
    a=np.array(sizes); p=np.array(list(prov.values()))
    tot=a.sum()
    return dict(pops=len(a),total=int(tot),median_pop=float(np.median(a)),p95_pop=float(np.percentile(a,95)),max_pop=int(a.max()),
                prov_median=float(np.median(p)),prov_max=int(p.max()),provs=len(p),
                type_share={k:round(v/tot,3) for k,v in types.most_common()})
print('vanilla 1836',stats(glob.glob('/home/user/corpus/vanilla/history/pops/1836.1.1/*.txt')))
print('generated',stats(glob.glob(sys.argv[1]+'/history/pops/1836.1.1/*.txt')))
