"""Port mínimo de FMG Names.calculateChain/getBase (cadena de Markov de pseudo-sílabas)."""
import random, re, time
VOW = set("aeiouyàáâãäåæèéêëìíîïòóôõöøùúûüýÿ")
def is_vowel(c): return c in VOW
def calculate_chain(names):
    chain = {}
    for n in names:
        name = n.strip().lower(); basic = all(32 <= ord(ch) < 127 for ch in name)
        i = -1
        while i < len(name):
            prev = name[i] if i >= 0 else ""
            syl = ""; v = False; c = i + 1
            while c < len(name) and len(syl) < 5:
                that = name[c]; nxt = name[c + 1] if c + 1 < len(name) else ""
                syl += that
                if syl in (" ", "-") or not nxt or nxt in " -": break
                if is_vowel(that): v = True
                if that == "y" and nxt == "e": c += 1; continue
                if basic and (that + nxt) in ("oo", "ee", "ae", "ch"): c += 1; continue
                if is_vowel(that) == bool(nxt): break        # rareza original de FMG
                if v and c + 2 < len(name) and is_vowel(name[c + 2]): break
                c += 1
            chain.setdefault(prev, []).append(syl)
            i += len(syl) or 1
    return chain
def get_name(chain, rnd, mn=5, mx=12, dupl=""):
    v = chain[""]; cur = rnd.choice(v); w = ""
    for _ in range(20):
        if cur == "":
            if len(w) < mn: cur = ""; w = ""; v = chain[""]
            else: break
        else:
            if len(w) + len(cur) > mx:
                if len(w) < mn: w += cur
                break
            v = chain.get(cur[-1], chain[""])
        w += cur; cur = rnd.choice(v)
    w = w.rstrip("'- ")
    out = ""
    for k, ch in enumerate(w):
        if k + 1 < len(w) and ch == w[k + 1] and ch not in dupl: continue
        out += ch.upper() if not out or out[-1] in " -" else ch
    return out
if __name__ == "__main__":
    import sys
    t = re.sub(r"#[^\r\n]*", "", open(sys.argv[1], encoding="cp1252").read())
    names = " ".join(re.findall(r"last_names\s*=\s*\{([^}]*)\}", t)).replace('"', "").split()
    t0 = time.perf_counter(); ch = calculate_chain(names); t1 = time.perf_counter()
    rnd = random.Random(1); out = [get_name(ch, rnd) for _ in range(3000)]; t2 = time.perf_counter()
    print(f"chain from {len(names)} names: {t1-t0:.3f}s; 3000 names: {t2-t1:.3f}s; unique {len(set(out))}")
