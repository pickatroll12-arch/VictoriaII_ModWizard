"""Guion: eventos, decisiones, marcas definidas por uso y las referencias a eventos y textos (wizard §7, H21)."""

from __future__ import annotations

import re

from ...clausewitz.nodes import Scalar
from ..model import (
    KIND_COUNTRY_FLAG,
    KIND_DECISION,
    KIND_EVENT,
    KIND_GLOBAL_FLAG,
    KIND_LOC_KEY,
    KIND_PROVINCE_FLAG,
    extractor,
)
from ..parsing import as_int, document, walk
from ._support import Facts

EVENT_KEYS = frozenset({"country_event", "province_event"})
FLAG_KINDS = {"set_country_flag": KIND_COUNTRY_FLAG, "set_global_flag": KIND_GLOBAL_FLAG,
              "set_province_flag": KIND_PROVINCE_FLAG}
# Un texto que es una clave de localización (sin espacios); un título en prosa no lo es.
LOC_KEY_RE = re.compile(r"[^\s;]+")


def _script_refs(facts: Facts, block) -> None:
    """Dentro de un evento o una decisión: ``country_event = 123`` o ``{ id = 123 }`` y las marcas puestas."""
    for entry, _ in walk(block):
        if entry.key is None:
            continue
        lowered = entry.key.text.lower()
        value = entry.value
        if lowered in EVENT_KEYS:
            if value.__class__ is Scalar:
                event = as_int(value.text)
                found = entry
            else:
                found = value.find("id")
                event = None if found is None or found.value.__class__ is not Scalar else as_int(found.value.text)
            if event is not None:
                facts.ref(KIND_EVENT, str(event), found, lowered)
        elif lowered in FLAG_KINDS and value.__class__ is Scalar:
            facts.define(FLAG_KINDS[lowered], value.text, entry.line)


def _loc_ref(facts: Facts, entry, role: str) -> str | None:
    if entry is None or entry.value.__class__ is not Scalar:
        return None
    text = entry.value.text
    if LOC_KEY_RE.fullmatch(text) is None:
        return None
    facts.ref(KIND_LOC_KEY, text, entry, role)
    return text


@extractor("events/*.txt", version=1)
def events(rel, data, layer):
    """``country_event``/``province_event`` de primer nivel con su ``id``; las referencias de sus efectos."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        kind = entry.key.text.lower()
        if kind not in EVENT_KEYS:
            continue
        block = entry.value
        found = block.find("id")
        event = None if found is None or found.value.__class__ is not Scalar else as_int(found.value.text)
        title = _loc_ref(facts, block.find("title"), "title")
        desc = _loc_ref(facts, block.find("desc"), "desc")
        options = []
        for option in block.find_all("option"):
            if option.value.__class__ is not Scalar:
                name = _loc_ref(facts, option.value.find("name"), "option")
                options.append(name)
        # Las referencias a otros eventos (y las marcas) se buscan en todo el bloque, salvo el propio id.
        for child in block.entries:
            if child.value.__class__ is not Scalar:
                _script_refs(facts, child.value)
        if event is not None:
            triggered = block.get_text("is_triggered_only")
            facts.define(KIND_EVENT, str(event), entry.line, {
                "type": kind, "title": title, "desc": desc, "picture": block.get_text("picture"),
                "options": options, "triggered_only": triggered is not None and triggered.lower() == "yes"})
    return facts.result()


@extractor("decisions/*.txt", version=1)
def decisions(rel, data, layer):
    """Las decisiones de ``political_decisions = { … }`` (H21); los textos son ``<id>_title`` y ``<id>_desc``."""
    facts = Facts(rel, layer)
    for group in document(data).entries:
        if group.key is None or group.value.__class__ is Scalar:
            continue
        category = group.key.text
        for entry in group.value.entries:
            if entry.key is None or entry.value.__class__ is Scalar:
                continue
            name = entry.key.text
            block = entry.value
            picture = block.get_text("picture")
            facts.define(KIND_DECISION, name, entry.line, {"category": category, "picture": picture})
            facts.ref(KIND_LOC_KEY, f"{name}_title", entry, "decision_title")
            facts.ref(KIND_LOC_KEY, f"{name}_desc", entry, "decision_desc")
            _script_refs(facts, block)
    return facts.result()
