"""Población y cultura: culturas, religiones, tipos de POP y bloques de POPs (wizard §7, H10, H18)."""

from __future__ import annotations

from ...clausewitz.nodes import Scalar
from ..model import (
    KIND_CULTURE,
    KIND_CULTURE_GROUP,
    KIND_GRAPHICAL_CULTURE,
    KIND_POP_BLOCK,
    KIND_POP_TYPE,
    KIND_PROVINCE,
    KIND_RELIGION,
    KIND_RELIGION_GROUP,
    KIND_TAG,
    extractor,
)
from ..parsing import as_int, as_number, document, is_date, loose_values
from ._support import Facts

# Claves de un grupo de culturas que no son culturas (H18).
CULTURE_GROUP_FIELDS = frozenset({"leader", "unit", "union", "is_overseas"})


def _color(block) -> list | None:
    found = block.find("color")
    if found is None or found.value.__class__ is Scalar:
        return None
    numbers = [as_number(v) for v in loose_values(found.value)]
    if len(numbers) != 3 or any(n is None for n in numbers):
        return None
    return [n if isinstance(n, float) and not n.is_integer() else int(n) for n in numbers]


@extractor("common/cultures.txt", version=1)
def cultures(rel, data, layer):
    """34 grupos que contienen 226 culturas como bloques hijos sin clave fija (H18)."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        group = entry.key.text
        members = []
        attrs: dict = {}
        for child in entry.value.entries:
            if child.key is None:
                continue
            name = child.key.text
            if name.lower() in CULTURE_GROUP_FIELDS:
                if child.value.__class__ is Scalar:
                    attrs[name.lower()] = child.value.text
                    if name.lower() == "unit":
                        facts.ref(KIND_GRAPHICAL_CULTURE, child.value.text, child, "unit")
                    elif name.lower() == "union":
                        facts.ref(KIND_TAG, child.value.text, child, "union")
                continue
            if child.value.__class__ is Scalar:
                continue
            members.append(name)
            culture_attrs = {"group": group, "color": _color(child.value)}
            primary = child.value.get_text("primary")
            if primary:
                culture_attrs["primary"] = primary
                facts.ref(KIND_TAG, primary, child.value.find("primary"), "primary")
            facts.define(KIND_CULTURE, name, child.line, culture_attrs)
        attrs["cultures"] = members
        facts.define(KIND_CULTURE_GROUP, group, entry.line, attrs)
    return facts.result()


@extractor("common/religion.txt", version=1)
def religions(rel, data, layer):
    """Grupos con religiones como bloques hijos; el color va en 0–1."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        group = entry.key.text
        members = []
        for child in entry.value.entries:
            if child.key is None or child.value.__class__ is Scalar:
                continue
            members.append(child.key.text)
            facts.define(KIND_RELIGION, child.key.text, child.line,
                         {"group": group, "color": _color(child.value), "icon": as_int(child.value.get_text("icon"))})
        facts.define(KIND_RELIGION_GROUP, group, entry.line, {"religions": members})
    return facts.result()


@extractor("poptypes/*.txt", version=1)
def pop_types(rel, data, layer):
    """El nombre del archivo es el tipo de POP (``poptypes/aristocrats.txt``)."""
    facts = Facts(rel, layer)
    name = rel.name.rsplit(".", 1)[0]
    doc = document(data)
    facts.define(KIND_POP_TYPE, name, 1, {"sprite": as_int(doc.get_text("sprite")), "strata": doc.get_text("strata")})
    return facts.result()


@extractor("history/pops/**/*.txt", version=1)
def pops(rel, data, layer):
    """``<provincia> = { <tipo> = { culture religion size } }``: una referencia por nombre distinto y archivo
    (la primera línea), para que la caché no crezca con cada POP; y un bloque (fecha, provincia) por aparición
    (H10: la provincia 2482 aparece dos veces en el mismo archivo)."""
    facts = Facts(rel, layer)
    date = rel.parts[2] if len(rel.parts) > 3 and is_date(rel.parts[2]) else ""
    seen: set[tuple[str, str]] = set()

    def once(kind: str, name: str, entry, role: str) -> None:
        if (kind, name) not in seen:
            seen.add((kind, name))
            facts.ref(kind, name, entry, role)

    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        province = as_int(entry.key.text)
        if province is None:
            continue
        facts.define(KIND_POP_BLOCK, f"{date}:{province}", entry.line)
        once(KIND_PROVINCE, str(province), entry, "pops")
        for pop in entry.value.entries:
            if pop.key is None or pop.value.__class__ is Scalar:
                continue
            once(KIND_POP_TYPE, pop.key.text, pop, "pop_type")
            for field in pop.value.entries:
                if field.key is None or field.value.__class__ is not Scalar:
                    continue
                lowered = field.key.text.lower()
                if lowered == "culture":
                    once(KIND_CULTURE, field.value.text, field, "pop_culture")
                elif lowered == "religion":
                    once(KIND_RELIGION, field.value.text, field, "pop_religion")
    return facts.result()
