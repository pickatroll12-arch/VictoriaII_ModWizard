"""Perfil de la instalación (wizard §18.3 y §18.13): lo que el taller aprende del juego en tiempo de ejecución.

``learn_install`` lee, sin escribir nada:
- las paletas de ``terrain.bmp`` y ``rivers.bmp``, las frecuencias de índices de ``terrain.bmp`` por categoría de
  ``terrain.txt`` (solo los índices con ≥ 0,5 % de su categoría), los anchos de ``rivers.bmp`` y sus cuotas;
- la paleta media de ``colormap.dds`` por categoría (también bajo el mar) y el color medio del agua;
- los TAG con su capital, cultura, religión y número de provincias; las fechas y la cultura y religión más
  frecuentes de ``history/pops``; continentes, climas, bienes y ``default.map``.

Los bitmaps y las texturas del mapa se leen de la capa del juego si existe (un mapa ya exportado por el taller no
debe enseñarle al taller sus propias frecuencias). Nada de esto se guarda en el mod ni en el repositorio. Sin
instalación (pruebas, o un juego sin mapa) hay un perfil sintético con la paleta procedural.

``PathSource`` es una lista ``rel → ruta`` que cruza al proceso trabajador; ``source_from_vfs`` la construye.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .textures import PROCEDURAL_PALETTE, PROCEDURAL_WATER
from .world import CATS, InstallProfile, TagInfo

MAP_FILES = ("map/terrain.txt", "map/terrain.bmp", "map/rivers.bmp", "map/terrain/colormap.dds",
             "map/terrain/colormap_water.dds", "map/default.map", "map/continent.txt", "map/climate.txt",
             "common/goods.txt", "common/countries.txt")
FOLDERS = ("history/countries", "history/provinces", "history/pops", "history/units")
MIN_INDEX_SHARE = 0.005
SYNTHETIC_WIDTHS = [2, 3, 4]
SYNTHETIC_WIDTH_SHARE = [0.6, 0.3, 0.1]


@dataclass
class PathSource:
    """Archivos de la instalación efectiva por ruta del juego (minúsculas de ``VPath.key`` → ruta en disco)."""

    files: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)      # clave → ruta del juego con su mayúscula

    def read(self, rel: str) -> bytes | None:
        path = self.files.get(rel.replace("\\", "/").lower())
        if path is None:
            return None
        try:
            return Path(path).read_bytes()
        except OSError:
            return None

    def list(self, folder: str, pattern: str = "*.txt") -> list[str]:
        prefix = folder.rstrip("/").lower() + "/"
        return sorted(self.names[k] for k in self.files
                      if k.startswith(prefix) and fnmatch.fnmatch(k.rsplit("/", 1)[-1], pattern.lower()))


def source_from_vfs(vfs) -> PathSource:
    from ..vfs.model import LayerKind

    src = PathSource()
    for rel in MAP_FILES:
        entry = vfs.entry(rel, LayerKind.GAME) if rel.startswith("map/") else None
        entry = entry or vfs.resolve(rel)
        if entry is not None:
            src.files[rel.lower()] = str(entry.path)
            src.names[rel.lower()] = rel
    for folder in FOLDERS:
        for entry in vfs.list(folder, "*.txt", recursive=True):
            key = str(entry.rel).lower()
            src.files[key] = str(entry.path)
            src.names[key] = str(entry.rel)
    return src


# --- lectura ----------------------------------------------------------------------------------------------

def _text(data: bytes | None) -> str:
    if not data:
        return ""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _strip_comments(text: str) -> str:
    return re.sub(r"#[^\r\n]*", "", text)


def _top_level_keys(text: str) -> list[str]:
    """Claves de primer nivel ``nombre = {`` de un archivo de Clausewitz (sin parser: rápido y tolerante)."""
    out = []
    depth = 0
    for m in re.finditer(r"([A-Za-z0-9_.\-]+)\s*=\s*\{|\{|\}", _strip_comments(text)):
        tok = m.group(0)
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth = max(0, depth - 1)
        else:
            if depth == 0:
                out.append(m.group(1))
            depth += 1
    return out


def _learn_terrain(src: PathSource) -> dict:
    from ..map.bmp import read_bmp
    from ..map.facts import terrain_types

    terrain_txt = src.read("map/terrain.txt")
    tbmp = src.read("map/terrain.bmp")
    rbmp = src.read("map/rivers.bmp")
    if not terrain_txt or not tbmp:
        return {}
    cat_of = {i: c for i, c in terrain_types(terrain_txt).items() if 0 <= i < 256}
    timg = read_bmp(tbmp)
    if timg.bits != 8 or timg.palette is None:
        return {}
    ter = timg.pixels
    cnt = np.bincount(ter.ravel(), minlength=256)
    idx_by_cat: dict[str, list] = {}
    for c in sorted(set(cat_of.values())):
        if c not in CATS or c == "ocean":
            continue
        ii = sorted(i for i, cc in cat_of.items() if cc == c and i < 254)
        tot = int(cnt[ii].sum()) if ii else 0
        if tot == 0:
            continue
        ok = [(i, cnt[i] / tot) for i in ii if cnt[i] / tot >= MIN_INDEX_SHARE]
        s = sum(w for _, w in ok)
        idx_by_cat[c] = [(int(i), float(w / s)) for i, w in ok]
    if "plains" not in idx_by_cat and idx_by_cat:
        idx_by_cat["plains"] = next(iter(idx_by_cat.values()))
    tpal = timg.palette[:, [2, 1, 0]].astype(np.uint8)
    widths, share, rpal = SYNTHETIC_WIDTHS, SYNTHETIC_WIDTH_SHARE, None
    if rbmp:
        rimg = read_bmp(rbmp)
        if rimg.bits == 8 and rimg.palette is not None:
            rcnt = np.bincount(rimg.pixels.ravel(), minlength=256)
            found = [i for i in range(2, 12) if rcnt[i] > 0]
            if found:
                widths = found
                tot = float(rcnt[found].sum())
                share = [float(rcnt[i] / tot) for i in found]
            rpal = rimg.palette[:, [2, 1, 0]].astype(np.uint8)
    out = {"cat_of": cat_of, "idx_by_cat": idx_by_cat, "widths": widths, "width_share": share,
           "terrain_palette": _pal_bytes(tpal), "rivers_palette": _pal_bytes(rpal if rpal is not None else tpal),
           "_ter": ter}
    return out


def _pal_bytes(pal: np.ndarray) -> bytes:
    full = np.zeros((256, 3), np.uint8)
    full[:min(256, len(pal))] = pal[:256]
    return full.tobytes()


def _learn_colormap(src: PathSource, ter: np.ndarray | None, cat_of: dict) -> tuple[np.ndarray, np.ndarray]:
    from ..gfx.dds import read_dds

    pal = PROCEDURAL_PALETTE.copy()
    water = PROCEDURAL_WATER.copy()
    cmd = src.read("map/terrain/colormap.dds")
    if cmd is None or ter is None:
        return pal, water
    try:
        cm = read_dds(cmd).rgba[..., :3].astype(np.float32)
    except Exception:       # noqa: BLE001 - un colormap ilegible deja la paleta procedural
        return pal, water
    h3, w3 = cm.shape[0], cm.shape[1] - 8
    sub = ter[1::3, 1::3][:h3, :w3]
    c2 = cm[:sub.shape[0], 4:4 + sub.shape[1]]
    lut = np.full(256, -1)
    for i, c in cat_of.items():
        lut[i] = CATS.index(c) if c in CATS else CATS.index("plains")
    lut[254] = 0
    sc = lut[sub]
    land_mask = sc > 0
    land_mean = c2[land_mask].mean(0) if land_mask.any() else pal[8]
    for k in range(len(CATS)):
        m = sc == k
        pal[k] = c2[m].mean(0) if m.sum() > 100 else land_mean
    wd = src.read("map/terrain/colormap_water.dds")
    if wd is not None:
        try:
            wat = read_dds(wd).rgba[..., :3].astype(np.float32)
            sea6 = (ter[2::6, 2::6] == 254)[:wat.shape[0], :wat.shape[1]]
            if sea6.any():
                water = wat[:sea6.shape[0], :sea6.shape[1]][sea6].mean(0)
        except Exception:   # noqa: BLE001
            pass
    return pal, water


def _learn_tags(src: PathSource) -> list[TagInfo]:
    owners: Counter = Counter()
    for rel in src.list("history/provinces"):
        m = re.search(r"^\s*owner\s*=\s*([A-Za-z0-9]{3})\b", _strip_comments(_text(src.read(rel))), re.M)
        if m:
            owners[m.group(1).upper()] += 1
    registered = set()
    reg = _strip_comments(_text(src.read("common/countries.txt")))
    for m in re.finditer(r"^\s*([A-Za-z0-9]{3})\s*=\s*\"", reg, re.M):
        registered.add(m.group(1).upper())
    tags: dict[str, TagInfo] = {}
    for rel in src.list("history/countries"):
        name = rel.rsplit("/", 1)[-1]
        m = re.match(r"([A-Za-z0-9]{3})\b", name)
        if not m:
            continue
        tag = m.group(1).upper()
        if tag in tags or tag == "REB" or (registered and tag not in registered):
            continue
        text = _strip_comments(_text(src.read(rel)))

        def first(key: str, text=text) -> str | None:
            mm = re.search(rf"^\s*{key}\s*=\s*\"?([A-Za-z0-9_]+)\"?", text, re.M)
            return mm.group(1) if mm else None

        cap = first("capital")
        tags[tag] = TagInfo(tag=tag, provinces=int(owners.get(tag, 0)),
                            capital=int(cap) if cap and cap.isdigit() else None,
                            culture=first("primary_culture"), religion=first("religion"),
                            civilized=(first("civilized") or "no").lower() == "yes", history_rel=rel)
    return sorted(tags.values(), key=lambda t: (-t.provinces, t.tag))


def _learn_pops(src: PathSource) -> tuple[list[str], str | None, str | None]:
    dates: set[str] = set()
    cultures: Counter = Counter()
    religions: Counter = Counter()
    rels = src.list("history/pops")
    for rel in rels:
        parts = rel.split("/")
        if len(parts) >= 4:
            dates.add(parts[2])
    first = min(dates, key=_date_key) if dates else None
    for rel in rels:
        if first is not None and rel.split("/")[2] != first:
            continue
        text = _strip_comments(_text(src.read(rel)))
        for m in re.finditer(r"culture\s*=\s*([A-Za-z0-9_]+)\s+religion\s*=\s*([A-Za-z0-9_]+)\s+size\s*=\s*(\d+)",
                             text):
            size = int(m.group(3))
            cultures[m.group(1)] += size
            religions[m.group(2)] += size
    top_c = max(sorted(cultures), key=lambda k: cultures[k]) if cultures else None
    top_r = max(sorted(religions), key=lambda k: religions[k]) if religions else None
    return sorted(dates, key=_date_key), top_c, top_r


def _date_key(d: str) -> tuple:
    try:
        return tuple(int(x) for x in d.split("."))
    except ValueError:
        return (9999,)


def _learn_goods(src: PathSource) -> list[str]:
    text = _strip_comments(_text(src.read("common/goods.txt")))
    out = []
    depth = 0
    for m in re.finditer(r"([A-Za-z0-9_]+)\s*=\s*\{|\{|\}", text):
        tok = m.group(0)
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth = max(0, depth - 1)
        else:
            if depth == 1:
                out.append(m.group(1))
            depth += 1
    return out


def _climate_info(text: str) -> tuple[list[str], str]:
    """Nombres de clima y el texto de sus bloques de modificadores (sin las listas de provincias)."""
    clean = re.sub(r"(?m)^\s*([A-Za-z0-9_]+)\s*=\s*\{[\s\d]*\}\s*$", "", text)
    names = []
    for key in _top_level_keys(clean):
        if key not in names:
            names.append(key)
    return names, clean.strip()


def synthetic_profile() -> InstallProfile:
    """Perfil sin instalación: índices propios por categoría y la paleta procedural (§18.5)."""
    idx_by_cat = {c: [(i, 1.0)] for i, c in enumerate(CATS) if c != "ocean"}
    cat_of = {i: c for i, c in enumerate(CATS) if c != "ocean"}
    pal = np.zeros((256, 3), np.uint8)
    pal[:len(CATS)] = PROCEDURAL_PALETTE.astype(np.uint8)
    pal[254] = (8, 31, 130)
    rpal = np.full((256, 3), 255, np.uint8)
    rpal[0] = (0, 255, 0)
    rpal[1] = (255, 0, 0)
    for k, w in enumerate(SYNTHETIC_WIDTHS):
        rpal[w] = (0, 200 - 40 * k, 255)
    rpal[254] = (122, 122, 122)
    return InstallProfile(cat_of=cat_of, idx_by_cat=idx_by_cat, widths=list(SYNTHETIC_WIDTHS),
                          width_share=list(SYNTHETIC_WIDTH_SHARE), terrain_palette=pal.tobytes(),
                          rivers_palette=rpal.tobytes(), cm_pal=PROCEDURAL_PALETTE.copy(),
                          water_mean=PROCEDURAL_WATER.copy(), synthetic=True)


def learn_install(src: PathSource) -> InstallProfile:
    terrain = _learn_terrain(src)
    if terrain:
        ter = terrain.pop("_ter")
        cm_pal, water = _learn_colormap(src, ter, terrain["cat_of"])
        profile = InstallProfile(cm_pal=cm_pal, water_mean=water, **terrain)
    else:
        profile = synthetic_profile()
    profile.tags = _learn_tags(src)
    dates, top_c, top_r = _learn_pops(src)
    profile.pop_dates = dates or ["1836.1.1"]
    if top_c:
        profile.top_culture = top_c
    if top_r:
        profile.top_religion = top_r
    profile.continent_text = _text(src.read("map/continent.txt"))
    profile.continents = _top_level_keys(profile.continent_text)
    names, blocks = _climate_info(_strip_comments(_text(src.read("map/climate.txt"))))
    profile.climates = names
    profile.climate_blocks = blocks
    profile.default_map = _text(src.read("map/default.map"))
    profile.goods = _learn_goods(src)
    h = hashlib.sha256()
    for key in sorted(src.files):
        h.update(key.encode())
    profile.source_digest = h.hexdigest()[:16]
    return profile
