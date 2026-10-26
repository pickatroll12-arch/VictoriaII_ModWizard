# Crawl FMG TS/JS imports from raw.githubusercontent.com (study only)
import re, os, sys, subprocess, posixpath
R="https://raw.githubusercontent.com/Azgaar/Fantasy-Map-Generator/master/"
OUT=sys.argv[1]
seeds=sys.argv[2:]
seen=set(); queue=list(seeds); missing=[]
def fetch(p):
    dst=os.path.join(OUT,p)
    if os.path.exists(dst): return open(dst,encoding='utf-8',errors='replace').read()
    r=subprocess.run(["curl","-sS","-f","-o",dst,"--create-dirs",R+p],capture_output=True)
    if r.returncode!=0:
        if os.path.exists(dst): os.remove(dst)
        return None
    return open(dst,encoding='utf-8',errors='replace').read()
imp=re.compile(r'''(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)|import\s+['"]([^'"]+)['"]''')
while queue:
    p=queue.pop()
    if p in seen: continue
    seen.add(p)
    txt=None
    cands=[p] if re.search(r"\.(js|json|mjs)$",p) else [p] if p.endswith(".ts") and not p.endswith("app.ts") else [p+".ts",p+".js",p+"/index.ts",p+"/index.js",p+".json"]
    got=None
    for c in cands:
        if c in seen and c!=p: pass
        txt=fetch(c)
        if txt is not None: got=c; break
    if got is None: missing.append(p); continue
    seen.add(got)
    if not got.endswith(('.ts','.js','.mjs')): continue
    for m in imp.finditer(txt):
        s=m.group(1) or m.group(2) or m.group(3)
        if s.startswith("@/"): t="src/"+s[2:]
        elif s.startswith("."): t=posixpath.normpath(posixpath.join(posixpath.dirname(got),s))
        else: continue
        if re.search(r'\.(css|svg|png|html|webp|jpg)(\?.*)?$',t): continue
        t=re.sub(r'\?.*$','',t)
        if t not in seen: queue.append(t)
print("fetched",len([s for s in seen]),"missing",len(missing))
print("\n".join(missing[:50]))
