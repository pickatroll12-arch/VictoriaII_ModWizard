"""m10: países (registro, archivo, banderas), culturas, religiones y localización ligada al mapa."""
import collections, glob, os, re, struct
from common import *
sea, maxp = sea_ids(); N = maxp - 1; land = set(range(1, N + 1)) - sea
reg = {}
for ln in open(V + "/common/countries.txt", encoding="cp1252"):
    m = re.match(r'\s*([A-Z][A-Z0-9]{2})\s*=\s*"([^"]+)"', ln)
    if m: reg[m.group(1)] = m.group(2)
dyn = sum(1 for t in reg if re.match(r"D\d\d", t))
print("countries.txt: TAG", len(reg), " dinámicos D01..", dyn)
ck = collections.Counter(); party_n = []
for t, f in reg.items():
    p = V + "/common/" + f
    if not os.path.exists(p): ck["(falta archivo)"] += 1; continue
    d = load(p); ck.update(d.keys())
    pa = d.get("party", []); party_n.append(len(pa) if isinstance(pa, list) else 1)
print("  claves de common/countries/*.txt:", dict(ck), " partidos por país min/med/max", min(party_n), int(np.median(party_n)), max(party_n))
gov = load(V + "/common/governments.txt")
ft = collections.Counter(v.get("flagType", "(ninguno)") for v in gov.values())
print("governments.txt flagType:", dict(ft))
flags = {os.path.basename(p)[:-4] for p in glob.glob(V + "/gfx/flags/*.tga")}
suf = collections.Counter()
for t in reg:
    for s in ("", "_communist", "_fascist", "_monarchy", "_republic"):
        suf[s or "(base)"] += (t + s) in flags
print("banderas para los TAG registrados por sufijo:", dict(suf), " de", len(reg))
hc = {os.path.basename(p)[:3] for p in glob.glob(V + "/history/countries/*.txt")}
print("TAG con historia:", len(hc), " registrados sin historia:", sorted(set(reg) - hc)[:12], "...", len(set(reg) - hc))
# culturas y religiones
cu = load(V + "/common/cultures.txt"); gk = collections.Counter(); ck2 = collections.Counter(); ncul = 0
for g, gv in cu.items():
    for k, v in gv.items():
        if isinstance(v, dict) and ("first_names" in v or "color" in v):
            ncul += 1; ck2.update(v.keys())
        else: gk[k] += 1
print("cultures.txt: grupos", len(cu), " culturas", ncul, " claves grupo:", dict(gk), " claves cultura:", dict(ck2))
re_ = load(V + "/common/religion.txt"); rk = collections.Counter(); nrel = 0
for g, gv in re_.items():
    for k, v in gv.items():
        if isinstance(v, dict): nrel += 1; rk.update(v.keys())
print("religion.txt: grupos", len(re_), " religiones", nrel, " claves:", dict(rk))
# localización
loc = {}
for p in sorted(glob.glob(V + "/localisation/*.csv")):
    for ln in open(p, encoding="cp1252", errors="replace"):
        k = ln.split(";", 1)[0].strip()
        if k and not k.startswith("#") and k not in loc: loc[k] = os.path.basename(p)
prov = {k for k in loc if re.match(r"^PROV\d+$", k)}
print("loc PROV<id>:", len(prov), " de tierra", sum(1 for k in prov if int(k[4:]) in land), "/", len(land), " de mar", sum(1 for k in prov if int(k[4:]) in sea), "/", len(sea), " archivos:", dict(collections.Counter(loc[k] for k in prov)))
regs = set(load(V + "/map/region.txt")); print("loc estados (clave = nombre de región):", sum(1 for r in regs if r in loc), "/", len(regs))
for s in ("europe", "asia", "mild_climate", "harsh_climate", "plains", "mountain", "coastal_desert", "black_sea_region"):
    print("   loc", s, s in loc)
tags = [t for t in reg]
print("loc TAG:", sum(t in loc for t in tags), " TAG_ADJ:", sum(t + "_ADJ" in loc for t in tags), " de", len(tags))
govs = list(gov.keys())
print("loc TAG_<gobierno>:", {g: sum(f"{t}_{g}" in loc for t in tags) for g in govs})
print("loc TAG_<gobierno>_ADJ:", {g: sum(f"{t}_{g}_ADJ" in loc for t in tags) for g in govs})
cultures = [k for g, gv in cu.items() for k, v in gv.items() if isinstance(v, dict) and ("first_names" in v or "color" in v)]
print("loc culturas:", sum(c in loc for c in cultures), "/", len(cultures), " grupos:", sum(g in loc for g in cu), "/", len(cu))
rels = [k for g, gv in re_.items() for k, v in gv.items() if isinstance(v, dict)]
print("loc religiones:", sum(r in loc for r in rels), "/", len(rels))
