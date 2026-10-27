"""Familia «provinces»: historias de provincia, ids, colores del BMP y regiones (wizard §11, H4–H6, H9).

- ``province_history_duplicate`` (error): dos historias con el mismo id (1396 y 1397
  en vanilla, H9; qué copia carga el juego es [verificar en juego]).
- ``province_id_invalid`` (error): una fila de ``definition.csv`` fuera de
  ``1 ≤ id < max_provinces``.
- ``bmp_color_unmapped`` (aviso): un color del BMP de provincias sin fila con id en
  ``definition.csv`` (27 en vanilla, H4). Lee el BMP con numpy, sin Pillow.
- Invariantes H6: ``land_province_without_region``, ``land_province_multiple_regions``,
  ``sea_in_region`` y ``land_province_without_continent`` (0 en vanilla).
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...index import model as m
from ...rules.ids import province_id_problem
from ...vfs.paths import InvalidPathError, VPath
from ..registry import make_problem, rule

E, W = Severity.ERROR, Severity.WARNING
DEFAULT_PROVINCES_BMP = "provinces.bmp"


@rule("province_history_duplicate", E)
def province_history_duplicates(ctx):
    index = ctx.index
    problems = []
    for name in index.names(m.KIND_PROVINCE_HISTORY):
        definitions = index.effective(m.KIND_PROVINCE_HISTORY, name)
        for other in definitions[1:]:
            problems.append(make_problem("province_history_duplicate", other.rel, other.line,
                                         entity=(m.KIND_PROVINCE, name), province=name, other=str(definitions[0].rel)))
    return problems


@rule("province_id_invalid", E)
def province_ids(ctx):
    max_provinces = getattr(ctx.rules, "max_provinces", 0)
    if not max_provinces:
        return []
    problems = []
    for kind in (m.KIND_PROVINCE, m.KIND_SEA_PROVINCE):
        for symbol in ctx.index.symbols(kind):
            if province_id_problem(int(symbol.name), max_provinces) is not None:
                problems.append(make_problem("province_id_invalid", symbol.rel, symbol.line,
                                             entity=(kind, symbol.name), province=symbol.name, max=max_provinces))
    return problems


def bmp_colors(data: bytes):
    """Colores distintos de un BMP de 24 bits y sus píxeles: ``(dict (r, g, b) → píxeles)``; None si no es un BMP
    de 24 bits sin comprimir (los de 8 bits con paleta llegan con el editor de mapa, iteración 5)."""
    import numpy as np

    if len(data) < 54 or data[:2] != b"BM":
        return None
    offset = int.from_bytes(data[10:14], "little")
    width = int.from_bytes(data[18:22], "little", signed=True)
    height = abs(int.from_bytes(data[22:26], "little", signed=True))
    bits = int.from_bytes(data[28:30], "little")
    compression = int.from_bytes(data[30:34], "little")
    if bits != 24 or compression != 0 or width <= 0 or height <= 0:
        return None
    stride = (width * 3 + 3) & ~3
    if offset + stride * height > len(data):
        return None
    rows = np.frombuffer(data, dtype=np.uint8, count=stride * height, offset=offset).reshape(height, stride)
    pixels = rows[:, :width * 3].reshape(-1, 3)
    packed = (pixels[:, 2].astype(np.uint32) << 16) | (pixels[:, 1].astype(np.uint32) << 8) | pixels[:, 0]
    counts = np.bincount(packed, minlength=1)
    present = np.nonzero(counts)[0]
    return {(int(v) >> 16, (int(v) >> 8) & 0xFF, int(v) & 0xFF): int(counts[v]) for v in present}


def provinces_bmp_rel(rules) -> VPath:
    """Ruta del BMP de provincias que nombra ``default.map`` (``GameRules.map_files``); la de vanilla si el nombre
    no es una ruta válida (``GameRules`` ya lo comprueba, pero unas reglas hechas a mano pueden traer cualquiera)."""
    name = getattr(rules, "map_files", {}).get("provinces", DEFAULT_PROVINCES_BMP)
    try:
        return VPath.of(f"map/{name}")
    except (InvalidPathError, TypeError):
        return VPath.of(f"map/{DEFAULT_PROVINCES_BMP}")


@rule("bmp_color_unmapped", W)
def unmapped_colors(ctx):
    rel = provinces_bmp_rel(ctx.rules)
    data = ctx.read(rel)
    if data is None:
        return []
    colors = bmp_colors(data)
    if colors is None:
        return []
    mapped = set()
    for kind in (m.KIND_PROVINCE, m.KIND_SEA_PROVINCE):
        for symbol in ctx.index.symbols(kind):
            color = symbol.attrs.get("color")
            if isinstance(color, list) and len(color) == 3:
                mapped.add(tuple(color))
    problems = []
    for color, pixels in sorted(colors.items()):
        if color not in mapped:
            problems.append(make_problem("bmp_color_unmapped", rel, color=" ".join(map(str, color)), pixels=pixels))
    return problems


@rule("land_province_without_region", E)
@rule("land_province_multiple_regions", E)
@rule("sea_in_region", E)
@rule("land_province_without_continent", E)
def region_invariants(ctx):
    index = ctx.index
    land = set(index.names(m.KIND_PROVINCE))
    sea = set(index.names(m.KIND_SEA_PROVINCE))
    if not land:
        return []
    problems = []
    regions: dict[str, list] = {}
    for region in index.symbols(m.KIND_REGION):
        for province in region.attrs.get("provinces") or ():
            name = str(province)
            regions.setdefault(name, []).append(region)
            if name in sea:
                problems.append(make_problem("sea_in_region", region.rel, region.line,
                                             entity=(m.KIND_SEA_PROVINCE, name), province=name, region=region.name))
    continents: dict[str, list] = {}
    for continent in index.symbols(m.KIND_CONTINENT):
        for province in continent.attrs.get("provinces") or ():
            continents.setdefault(str(province), []).append(continent)
    region_rel = next((s.rel for s in index.symbols(m.KIND_REGION)), VPath.of("map/region.txt"))
    continent_rel = next((s.rel for s in index.symbols(m.KIND_CONTINENT)), VPath.of("map/continent.txt"))
    has_regions = bool(index.names(m.KIND_REGION))
    has_continents = bool(index.names(m.KIND_CONTINENT))
    for name in sorted(land, key=int):
        found = regions.get(name, [])
        entity = (m.KIND_PROVINCE, name)
        if has_regions and not found:
            problems.append(make_problem("land_province_without_region", region_rel, entity=entity, province=name))
        elif len(found) > 1:
            problems.append(make_problem("land_province_multiple_regions", found[1].rel, found[1].line, entity=entity,
                                         province=name, regions=", ".join(r.name for r in found)))
        if has_continents and name not in continents:
            problems.append(make_problem("land_province_without_continent", continent_rel, entity=entity,
                                         province=name))
    return problems
