"""Economía, técnica y ejército: bienes, edificios, tecnologías, invenciones, unidades y modificadores (wizard §7)."""

from __future__ import annotations

from ...clausewitz.nodes import Scalar
from ..model import (
    KIND_BUILDING,
    KIND_GOODS,
    KIND_GRAPHICAL_CULTURE,
    KIND_INVENTION,
    KIND_MODIFIER,
    KIND_TECH_FOLDER,
    KIND_TECH_SCHOOL,
    KIND_TECHNOLOGY,
    KIND_TRAIT,
    KIND_UNIT_TYPE,
    extractor,
)
from ..parsing import as_int, as_number, document, loose_values, walk
from ._support import Facts


def _top_blocks(data: bytes):
    for entry in document(data).entries:
        if entry.key is not None and entry.value.__class__ is not Scalar:
            yield entry.key.text, entry.value, entry


@extractor("common/goods.txt", version=1)
def goods(rel, data, layer):
    """Categorías (``military_goods``) con los bienes como bloques hijos."""
    facts = Facts(rel, layer)
    for category, block, _ in _top_blocks(data):
        for child in block.entries:
            if child.key is None or child.value.__class__ is Scalar:
                continue
            color = child.value.find("color")
            numbers = [] if color is None or color.value.__class__ is Scalar else loose_values(color.value)
            facts.define(KIND_GOODS, child.key.text, child.line, {
                "category": category, "cost": as_number(child.value.get_text("cost")),
                "color": [as_int(n) for n in numbers] if len(numbers) == 3 else None})
    return facts.result()


@extractor("common/buildings.txt", version=1)
def buildings(rel, data, layer):
    facts = Facts(rel, layer)
    for name, block, entry in _top_blocks(data):
        facts.define(KIND_BUILDING, name, entry.line, {
            "type": block.get_text("type"), "max_level": as_int(block.get_text("max_level"))})
    return facts.result()


@extractor("common/technology.txt", version=1)
def technology_setup(rel, data, layer):
    """``folders = { army_tech = { áreas } }`` y ``schools = { … }``."""
    facts = Facts(rel, layer)
    for name, block, entry in _top_blocks(data):
        lowered = name.lower()
        if lowered == "folders":
            for child in block.entries:
                if child.key is not None and child.value.__class__ is not Scalar:
                    facts.define(KIND_TECH_FOLDER, child.key.text, child.line, {"areas": loose_values(child.value)})
        elif lowered == "schools":
            for child in block.entries:
                if child.key is not None and child.value.__class__ is not Scalar:
                    facts.define(KIND_TECH_SCHOOL, child.key.text, child.line)
    return facts.result()


def _activations(facts: Facts, block) -> list[str]:
    units = []
    for entry, _ in walk(block):
        if entry.key is None or entry.value.__class__ is not Scalar:
            continue
        lowered = entry.key.text.lower()
        if lowered == "activate_unit":
            units.append(entry.value.text)
            facts.ref(KIND_UNIT_TYPE, entry.value.text, entry, "activate_unit")
        elif lowered == "activate_building":
            facts.ref(KIND_BUILDING, entry.value.text, entry, "activate_building")
    return units


@extractor("technologies/*.txt", version=1)
def technologies(rel, data, layer):
    """Cada bloque de primer nivel es una tecnología; la carpeta es el nombre del archivo (``army_tech``)."""
    facts = Facts(rel, layer)
    folder = rel.name.rsplit(".", 1)[0]
    for name, block, entry in _top_blocks(data):
        units = _activations(facts, block)
        facts.define(KIND_TECHNOLOGY, name, entry.line, {
            "folder": folder, "area": block.get_text("area"), "year": as_int(block.get_text("year")),
            "activate_unit": units})
    return facts.result()


@extractor("inventions/*.txt", version=1)
def inventions(rel, data, layer):
    facts = Facts(rel, layer)
    folder = rel.name.rsplit(".", 1)[0]
    for name, block, entry in _top_blocks(data):
        units = _activations(facts, block)
        facts.define(KIND_INVENTION, name, entry.line, {"folder": folder, "activate_unit": units})
    return facts.result()


@extractor("units/*.txt", version=1)
def units(rel, data, layer):
    """Un tipo de unidad por bloque (normalmente uno por archivo), ``type = land | naval`` (H18)."""
    facts = Facts(rel, layer)
    for name, block, entry in _top_blocks(data):
        active = block.get_text("active")
        facts.define(KIND_UNIT_TYPE, name, entry.line, {
            "type": block.get_text("type"), "active": None if active is None else active.lower() == "yes",
            "sprite": block.get_text("sprite")})
    return facts.result()


@extractor("common/graphicalculturetype.txt", version=1)
def graphical_cultures(rel, data, layer):
    """Lista de valores sueltos (``RussianGC BritishGC … Generic``)."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None and entry.value.__class__ is Scalar:
            facts.define(KIND_GRAPHICAL_CULTURE, entry.value.text, entry.line)
        elif entry.key is not None:
            facts.define(KIND_GRAPHICAL_CULTURE, entry.key.text, entry.line)
    return facts.result()


@extractor("common/traits.txt", version=1)
def traits(rel, data, layer):
    """``personality = { … }`` y ``background = { … }`` con los rasgos como bloques hijos."""
    facts = Facts(rel, layer)
    for category, block, _ in _top_blocks(data):
        for child in block.entries:
            if child.key is not None and child.value.__class__ is not Scalar:
                facts.define(KIND_TRAIT, child.key.text, child.line, {"category": category})
    return facts.result()


@extractor("common/*_modifiers.txt", version=1)
def modifiers(rel, data, layer):
    """``event_modifiers.txt``, ``static_modifiers.txt`` y ``triggered_modifiers.txt``: un bloque por modificador."""
    facts = Facts(rel, layer)
    source = rel.name.rsplit(".", 1)[0]
    for name, _, entry in _top_blocks(data):
        facts.define(KIND_MODIFIER, name, entry.line, {"source": source})
    return facts.result()
