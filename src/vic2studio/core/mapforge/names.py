# Port of Azgaar's Fantasy Map Generator src/modules/names-generator.ts (calculateChain, getBase) (MIT,
# © Max Haniyeu)
"""Nombres (wizard §18.5): cadena de Markov de pseudosílabas de FMG.

Fuentes de la iteración 9a: ``syllables`` (una lista propia de sílabas, inventada) y ``custom`` (nombres pegados por
el usuario). Se descartan los duplicados por tipo y lo que no cabe en cp1252. ``ascii_name`` translitera para los
nombres de archivo (NFKD, solo ``[A-Za-z0-9 _-]``): el nombre acentuado queda solo en la localización.
"""

from __future__ import annotations

import random
import re
import unicodedata

VOWELS = set("aeiouyàáâãäåæèéêëìíîïòóôõöøùúûüýÿ")
# Sílabas propias (inventadas) con las que se entrena la cadena de ``syllables``.
SYLLABLES = ("ka", "lo", "ver", "an", "dra", "mi", "sul", "te", "ron", "ba", "el", "is", "or", "ven", "ga", "thi",
             "mar", "du", "sen", "ul", "ri", "na", "tor", "es", "al", "be", "co", "lan", "vi", "sa", "dor", "en")
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _seed_names(rnd: random.Random, count: int = 400) -> list[str]:
    return ["".join(rnd.choice(SYLLABLES) for _ in range(rnd.randint(2, 3))) for _ in range(count)]


def calculate_chain(names: list[str]) -> dict[str, list[str]]:
    chain: dict[str, list[str]] = {}
    for n in names:
        name = n.strip().lower()
        if not name:
            continue
        basic = all(32 <= ord(ch) < 127 for ch in name)
        i = -1
        while i < len(name):
            prev = name[i] if i >= 0 else ""
            syl = ""
            v = False
            c = i + 1
            while c < len(name) and len(syl) < 5:
                that = name[c]
                nxt = name[c + 1] if c + 1 < len(name) else ""
                syl += that
                if syl in (" ", "-") or not nxt or nxt in " -":
                    break
                if that in VOWELS:
                    v = True
                if that == "y" and nxt == "e":
                    c += 1
                    continue
                if basic and (that + nxt) in ("oo", "ee", "ae", "ch"):
                    c += 1
                    continue
                if (that in VOWELS) == bool(nxt):
                    break
                if v and c + 2 < len(name) and name[c + 2] in VOWELS:
                    break
                c += 1
            chain.setdefault(prev, []).append(syl)
            i += len(syl) or 1
    return chain


class MarkovNames:
    """Generador de nombres determinista para una semilla."""

    def __init__(self, seed: int, source: str = "syllables", custom: tuple[str, ...] = ()):
        self.rnd = random.Random(seed)
        base = [c for c in custom if c.strip()] if source == "custom" and custom else _seed_names(self.rnd)
        self.chain = calculate_chain(base)
        self.used: dict[str, set[str]] = {}

    def _raw(self, mn: int = 4, mx: int = 11) -> str:
        chain = self.chain
        v = chain.get("", ["a"])
        cur = self.rnd.choice(v)
        w = ""
        for _ in range(20):
            if cur == "":
                if len(w) < mn:
                    cur = ""
                    w = ""
                    v = chain.get("", ["a"])
                else:
                    break
            else:
                if len(w) + len(cur) > mx:
                    if len(w) < mn:
                        w += cur
                    break
                v = chain.get(cur[-1], chain.get("", ["a"]))
            w += cur
            cur = self.rnd.choice(v)
        w = w.rstrip("'- ")
        out = ""
        for k, ch in enumerate(w):
            if k + 1 < len(w) and ch == w[k + 1]:
                continue
            out += ch.upper() if not out or out[-1] in " -" else ch
        return out

    def name(self, kind: str = "province") -> str:
        used = self.used.setdefault(kind, set())
        for attempt in range(60):
            n = self._raw()
            if len(n) < 3 or not cp1252_ok(n) or n.lower() in WINDOWS_RESERVED:
                continue
            if n in used and attempt < 50:
                continue
            if n in used:
                n = f"{n} {len(used)}"
            used.add(n)
            return n
        n = f"Terra {len(used) + 1}"
        used.add(n)
        return n


def cp1252_ok(text: str) -> bool:
    try:
        text.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def ascii_name(s: str) -> str:
    t = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^A-Za-z0-9 _-]", "", t).strip()
    return t or "x"


def key_name(s: str) -> str:
    """Clave de script (estados, continentes): ASCII en minúsculas con guiones bajos."""
    return re.sub(r"[^a-z0-9_]", "", ascii_name(s).lower().replace(" ", "_").replace("-", "_")) or "x"
