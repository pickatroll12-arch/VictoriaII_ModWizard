"""Utilidades comunes de medida (solo lectura del corpus)."""
import os, sys, re, glob, struct
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, *[".."] * 6, "src"))  # src/ del repositorio
from vic2studio.core.clausewitz import parse_file, simplify  # noqa
V = os.environ.get("VIC2_VANILLA", "/home/user/corpus/vanilla")
OUT = os.path.join(HERE, "..", "out"); os.makedirs(OUT, exist_ok=True)
Image.MAX_IMAGE_PIXELS = None

def load(path):
    return simplify(parse_file(path).document)

def read_definition(path=V + "/map/definition.csv"):
    rows = []
    for ln in open(path, encoding="cp1252"):
        p = ln.rstrip("\r\n").split(";")
        if not p[0].strip().isdigit():
            continue
        def num(s):
            m = re.match(r"\s*(\d+)", s); return int(m.group(1)) if m else None
        rows.append((int(p[0]), num(p[1]), num(p[2]), num(p[3]), p[4] if len(p) > 4 else ""))
    return rows

def province_ids(cache=True):
    f = os.path.join(OUT, "ids.npy")
    if cache and os.path.exists(f):
        return np.load(f)
    rgb = np.asarray(Image.open(V + "/map/provinces.bmp").convert("RGB"))
    key = (rgb[..., 0].astype(np.uint32) << 16) | (rgb[..., 1].astype(np.uint32) << 8) | rgb[..., 2]
    lut = np.zeros(1 << 24, np.uint16)
    for pid, r, g, b, _ in read_definition():
        lut[(r << 16) | (g << 8) | b] = pid
    ids = lut[key]
    np.save(f, ids)
    return ids

def palette_image(path):
    im = Image.open(path)
    assert im.mode == "P", im.mode
    return np.asarray(im), np.array(im.getpalette()[:768], np.uint8).reshape(-1, 3)

def history_province_files():
    out = {}
    for p in glob.glob(V + "/history/provinces/**/*.txt", recursive=True):
        m = re.match(r"\s*(\d+)", os.path.basename(p))
        if m:
            out.setdefault(int(m.group(1)), []).append(p)
    return out

def sea_ids():
    d = load(V + "/map/default.map")
    return set(int(x) for x in d["sea_starts"]), int(d["max_provinces"])
