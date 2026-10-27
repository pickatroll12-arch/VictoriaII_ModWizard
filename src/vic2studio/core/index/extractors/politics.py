"""Política: gobiernos, ideologías, asuntos y reformas, valores nacionales y rebeldes (wizard §7, H16)."""

from __future__ import annotations

from ...clausewitz.nodes import Scalar
from ..model import (
    KIND_GOVERNMENT,
    KIND_IDEOLOGY,
    KIND_ISSUE_GROUP,
    KIND_ISSUE_OPTION,
    KIND_NATIONAL_VALUE,
    KIND_REBEL_TYPE,
    extractor,
)
from ..parsing import document
from ._support import Facts

# Claves de un gobierno que no son ideologías (``<ideología> = yes``, H16).
GOVERNMENT_FIELDS = frozenset({"election", "duration", "appoint_ruling_party", "flagtype"})


@extractor("common/governments.txt", version=1)
def governments(rel, data, layer):
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        key = entry.key
        if key is None or entry.value.__class__ is Scalar:
            continue
        block = entry.value
        ideologies = []
        attrs: dict = {}
        for child in block.entries:
            if child.key is None or child.value.__class__ is not Scalar:
                continue
            name, text = child.key.text, child.value.text
            lowered = name.lower()
            if lowered == "election":
                attrs["election"] = text.lower() == "yes"
            elif lowered == "duration":
                attrs["duration"] = text
            elif lowered == "appoint_ruling_party":
                attrs["appoint_ruling_party"] = text.lower() == "yes"
            elif lowered == "flagtype":
                attrs["flag_type"] = text
            elif text.lower() == "yes":
                ideologies.append(name)
                facts.ref(KIND_IDEOLOGY, name, child, "government_ideology")
        attrs["ideologies"] = ideologies
        facts.define(KIND_GOVERNMENT, key.text, entry.line, attrs)
    return facts.result()


@extractor("common/ideologies.txt", version=1)
def ideologies(rel, data, layer):
    """Grupos (``fascist_group``) con sus ideologías como bloques hijos."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        group = entry.key.text
        for child in entry.value.entries:
            if child.key is not None and child.value.__class__ is not Scalar:
                facts.define(KIND_IDEOLOGY, child.key.text, child.line, {"group": group})
    return facts.result()


@extractor("common/issues.txt", version=1)
def issues(rel, data, layer):
    """Categorías (``party_issues``, ``political_reforms``…) → grupos → opciones (bloques hijos)."""
    facts = Facts(rel, layer)
    for category_entry in document(data).entries:
        if category_entry.key is None or category_entry.value.__class__ is Scalar:
            continue
        category = category_entry.key.text
        for group_entry in category_entry.value.entries:
            if group_entry.key is None or group_entry.value.__class__ is Scalar:
                continue
            group = group_entry.key.text
            options = []
            for option in group_entry.value.entries:
                if option.key is not None and option.value.__class__ is not Scalar:
                    options.append(option.key.text)
                    facts.define(KIND_ISSUE_OPTION, option.key.text, option.line,
                                 {"group": group, "category": category})
            facts.define(KIND_ISSUE_GROUP, group, group_entry.line, {"category": category, "options": options})
    return facts.result()


@extractor("common/nationalvalues.txt", version=1)
def national_values(rel, data, layer):
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is not None and entry.value.__class__ is not Scalar:
            facts.define(KIND_NATIONAL_VALUE, entry.key.text, entry.line)
    return facts.result()


@extractor("common/rebel_types.txt", version=1)
def rebel_types(rel, data, layer):
    """Tipos de rebelde con su tabla ``government = { <gobierno> = <gobierno destino> }`` (H16)."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        table = entry.value.find("government")
        mapping = None
        if table is not None and table.value.__class__ is not Scalar:
            mapping = {}
            for child in table.value.entries:
                if child.key is not None and child.value.__class__ is Scalar:
                    mapping[child.key.text] = child.value.text
                    facts.ref(KIND_GOVERNMENT, child.key.text, child, "rebel_government")
                    facts.ref(KIND_GOVERNMENT, child.value.text, child, "rebel_government_target")
        facts.define(KIND_REBEL_TYPE, entry.key.text, entry.line, {"government": mapping})
    return facts.result()
