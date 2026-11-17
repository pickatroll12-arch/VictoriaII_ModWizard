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


# Letras sin descomposición Unicode que tienen una equivalente clara en cp1252.
_FOLD = {"Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "Ħ": "H", "ħ": "h", "ı": "i", "Ŀ": "L", "ŀ": "l", "Ŧ": "T",
         "ŧ": "t", "Ŋ": "N", "ŋ": "n", "ĸ": "k", "Ə": "E", "ə": "e", "Ɛ": "E", "ɛ": "e", "ſ": "s"}


def cp1252_text(text: str) -> str:
    """``text`` con solo caracteres que el juego sabe escribir (cp1252): las letras que no caben pierden el acento
    que no existe ('Ő' → 'O', 'Ŝ' → 'S', 'ș' → 's') o se cambian por la más parecida ('Ł' → 'L'); lo demás
    (otras escrituras, emojis) se quita. Lo que ya cabe no cambia."""
    out = []
    for ch in unicodedata.normalize("NFC", str(text)):
        if cp1252_ok(ch):
            out.append(ch)
            continue
        if ch in _FOLD:
            out.append(_FOLD[ch])
            continue
        if unicodedata.category(ch).startswith("L"):
            base = "".join(c for c in unicodedata.normalize("NFKD", ch)
                           if unicodedata.category(c).startswith("L") and cp1252_ok(c))
            out.append(base)
        elif unicodedata.category(ch).startswith("Z"):
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def loc_text(text) -> str:
    """``text`` listo para una celda de la localización del juego: todo lo que ``csvloc.check_text`` y la
    codificación del juego (cp1252) admiten. Es ``cp1252_text`` con los caracteres de control (saltos de línea,
    tabulaciones, NUL…) como espacios y cada ';' cambiado por ',': el CSV del juego no tiene escapes y un ';' o un
    salto partirían la fila (``LocSync`` los rechaza y la transacción entera se deshace). Puede quedar vacío;
    ``None`` da ''."""
    if text is None:
        return ""
    spaced = "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in str(text))
    return cp1252_text(spaced).replace(";", ",")


def cp1252_name(text, fallback: str | None = None) -> str | None:
    """Un nombre que el juego sabe escribir en su localización (``loc_text``) o, si no le queda ninguna letra (un
    nombre solo en otra escritura, como '東京', un emoji o solo cifras), ``fallback`` limpiado igual; ``None`` si
    tampoco. Nunca da un nombre vacío. Es para los nombres que vienen de fuera (JSON de Azgaar) y los de países y
    culturas, que llevan gentilicio ('12' daría «12ian»): antes llegaban tal cual y la exportación fallaba al escribir
    sus textos (letras sin cp1252, o un ';' como el de 'Alta;Baja'). Lo puesto a mano en la tabla de nombres va
    por ``loc_name``, que respeta lo que quede."""
    for candidate in (text, fallback):
        clean = loc_text(candidate)
        if any(ch.isalpha() for ch in clean):
            return clean
    return None


def loc_name(text, fallback: str | None = None) -> str | None:
    """Un nombre de provincia o de estado para la localización: lo que quede de ``text`` tras ``loc_text`` (aunque
    sean cifras o signos: lo ha escrito alguien a mano, como '12' o '...'), o ``fallback`` limpiado igual si no
    queda nada ('大阪', 'Москва', un emoji); ``None`` si tampoco."""
    for candidate in (text, fallback):
        clean = loc_text(candidate)
        if clean:
            return clean
    return None


def ascii_name(s: str) -> str:
    t = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^A-Za-z0-9 _-]", "", t).strip()
    return t or "x"


def key_name(s: str) -> str:
    """Clave de script (estados, continentes): ASCII en minúsculas con guiones bajos."""
    return re.sub(r"[^a-z0-9_]", "", ascii_name(s).lower().replace(" ", "_").replace("-", "_")) or "x"
