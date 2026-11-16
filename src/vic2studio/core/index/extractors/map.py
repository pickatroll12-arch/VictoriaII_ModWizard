"""Mapa: provincias (``definition.csv`` + ``default.map``), regiones, continentes, climas, terrenos e historias de
provincia (wizard §7, H4–H7, H9)."""

from __future__ import annotations

from ...clausewitz.nodes import Scalar
from ...encoding import decode_bytes
from ...vfs.rules import leading_int_key
from ..model import (
    KIND_BUILDING,
    KIND_CLIMATE,
    KIND_CONTINENT,
    KIND_FILE,
    KIND_GOODS,
    KIND_IDEOLOGY,
    KIND_PROVINCE,
    KIND_PROVINCE_FLAG,
    KIND_PROVINCE_HISTORY,
    KIND_REGION,
    KIND_SEA_REGION,
    KIND_TAG,
    KIND_TERRAIN,
    ROLE_SEA_STARTS,
    extractor,
)
from ..parsing import as_int, document, is_date, leading_int, loose_values
from ._support import Facts, path_name


@extractor("map/definition.csv", version=1)
def definition(rel, data, layer):
    """``province;red;green;blue;nombre;x``: una provincia por fila con id (los ids se leen al estilo ``atoi``,
    H4: ``223.``); la cabecera y las filas sin id no definen nada."""
    facts = Facts(rel, layer)
    text = decode_bytes(data).text
    for number, line in enumerate(text.split("\n"), start=1):
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split(";")
        province = leading_int(fields[0])
        if province is None:
            continue
        color = [leading_int(f) if f.strip() else None for f in fields[1:4]]
        facts.define(KIND_PROVINCE, str(province), number, {
            "color": color if len(color) == 3 and None not in color else None,
            "name": fields[4] if len(fields) > 4 else ""})
    return facts.result()


# Claves de default.map que nombran archivos de map/ (H5).
MAP_FILE_KEYS = ("definitions", "provinces", "positions", "terrain", "rivers", "terrain_definition",
                 "tree_definition", "continent", "adjacencies", "region", "region_sea", "province_flag_sprite")


@extractor("map/default.map", version=1)
def default_map(rel, data, layer):
    """``sea_starts`` son referencias a provincias con rol ``sea_starts`` (el índice las separa en tierra y mar);
    los archivos que nombra, referencias ``file``."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None:
            continue
        key = entry.key.text.lower()
        if key == "sea_starts" and entry.value.__class__ is not Scalar:
            for child in entry.value.entries:
                if child.key is None and child.value.__class__ is Scalar and as_int(child.value.text) is not None:
                    facts.ref(KIND_PROVINCE, str(int(child.value.text)), child, ROLE_SEA_STARTS)
        elif key in MAP_FILE_KEYS and entry.value.__class__ is Scalar:
            target = path_name(entry.value.text, "map")
            if target is not None:
                facts.ref(KIND_FILE, target, entry, f"map_{key}")
    return facts.result()


def _province_list(block) -> list[int]:
    return [int(v) for v in loose_values(block) if as_int(v) is not None]


def _groups(rel, data, layer, kind: str):
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        facts.define(kind, entry.key.text, entry.line, {"provinces": _province_list(entry.value)})
    return facts.result()


@extractor("map/region.txt", version=1)
def regions(rel, data, layer):
    """549 estados en vanilla (``PRU_549 = { 549 550 551 552 681 }``, H6)."""
    return _groups(rel, data, layer, KIND_REGION)


@extractor("map/region_sea.txt", version=1)
def sea_regions(rel, data, layer):
    return _groups(rel, data, layer, KIND_SEA_REGION)


@extractor("map/continent.txt", version=1)
def continents(rel, data, layer):
    """``europe = { provinces = { … } <modificadores> }`` (H7)."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        found = entry.value.find("provinces")
        provinces = [] if found is None or found.value.__class__ is Scalar else _province_list(found.value)
        facts.define(KIND_CONTINENT, entry.key.text, entry.line, {"provinces": provinces})
    return facts.result()


@extractor("map/climate.txt", version=1)
def climates(rel, data, layer):
    """Claves emparejadas (H7): la 1.ª aparición trae los modificadores y la 2.ª la lista de provincias."""
    facts = Facts(rel, layer)
    found: dict[str, tuple[int | None, list[int]]] = {}
    order: list[str] = []
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        name = entry.key.text
        provinces = _province_list(entry.value)
        if name not in found:
            order.append(name)
            found[name] = (entry.line, provinces)
        elif provinces:
            found[name] = (found[name][0], found[name][1] + provinces)
    for name in order:
        line, provinces = found[name]
        facts.define(KIND_CLIMATE, name, line, {"provinces": provinces})
    return facts.result()


@extractor("map/terrain.txt", version=1)
def terrains(rel, data, layer):
    """Los terrenos son las categorías de ``categories = { … }``."""
    facts = Facts(rel, layer)
    categories = document(data).find("categories")
    if categories is not None and categories.value.__class__ is not Scalar:
        for child in categories.value.entries:
            if child.key is not None and child.value.__class__ is not Scalar:
                water = child.value.get_text("is_water")
                facts.define(KIND_TERRAIN, child.key.text, child.line,
                             {"is_water": water is not None and water.lower() == "yes"})
    return facts.result()


# Historia de provincia: clave → (tipo, rol).
PROVINCE_REFS = {
    "owner": (KIND_TAG, "owner"),
    "controller": (KIND_TAG, "controller"),
    "add_core": (KIND_TAG, "add_core"),
    "remove_core": (KIND_TAG, "remove_core"),
    "trade_goods": (KIND_GOODS, "trade_goods"),
    "terrain": (KIND_TERRAIN, "terrain"),
}
PROVINCE_KEPT = ("owner", "controller", "trade_goods", "life_rating", "colonial", "colony", "terrain", "railroad",
                 "fort", "naval_base")
# Claves que se repiten y se guardan como lista, en su orden (los núcleos: ProvinceFacts los acumula por fecha).
PROVINCE_LISTED = ("add_core", "remove_core")


def _province_block(facts: Facts, block, fields: dict) -> None:
    for entry in block.entries:
        if entry.key is None:
            continue
        lowered = entry.key.text.lower()
        value = entry.value
        if value.__class__ is not Scalar:
            if lowered == "state_building":
                building = value.get_text("building")
                if building:
                    facts.ref(KIND_BUILDING, building, value.find("building"), "state_building")
            elif lowered == "party_loyalty":
                ideology = value.get_text("ideology")
                if ideology:
                    facts.ref(KIND_IDEOLOGY, ideology, value.find("ideology"), "party_loyalty")
            continue
        if lowered in PROVINCE_KEPT:
            fields[lowered] = value.text
        elif lowered in PROVINCE_LISTED:
            fields.setdefault(lowered, []).append(value.text)
        if lowered in PROVINCE_REFS:
            kind, role = PROVINCE_REFS[lowered]
            facts.ref(kind, value.text, entry, role)
        elif lowered == "set_province_flag":
            facts.define(KIND_PROVINCE_FLAG, value.text, entry.line)


@extractor("history/provinces/**/*.txt", version=2)
def province_history(rel, data, layer):
    """Una historia por archivo; el id es el entero inicial del nombre (H9: ``3246  JanMayen.txt``)."""
    facts = Facts(rel, layer)
    doc = document(data)
    fields: dict = {}
    _province_block(facts, doc, fields)
    dated = []
    for entry in doc.entries:
        if entry.key is not None and entry.value.__class__ is not Scalar and is_date(entry.key.text):
            block_fields: dict = {}
            _province_block(facts, entry.value, block_fields)
            dated.append([entry.key.text, entry.line, block_fields])
    province = leading_int_key(rel)
    if province is not None:
        facts.define(KIND_PROVINCE_HISTORY, province, 1, {"fields": fields, "dated": dated})
        facts.ref(KIND_PROVINCE, province, 1, "history")
    return facts.result()
