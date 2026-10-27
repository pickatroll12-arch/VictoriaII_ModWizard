"""Guerra e historia: casus belli, bookmarks, guerras y diplomacia de inicio (wizard §7, H17, H20)."""

from __future__ import annotations

from ...clausewitz.nodes import Scalar
from ..model import KIND_BOOKMARK, KIND_CB, KIND_PROVINCE, KIND_TAG, KIND_WAR, extractor
from ..parsing import as_int, document, is_date
from ._support import Facts

ROLE_PEACE_ORDER = "peace_order"


@extractor("common/cb_types.txt", version=1)
def cb_types(rel, data, layer):
    """``peace_order = { … }`` (referencias, H17: incluye ``annex``, que no es un CB) y los CB que siguen."""
    facts = Facts(rel, layer)
    doc = document(data)
    order: list[str] = []
    for entry in doc.entries:
        if entry.key is not None and entry.key.text.lower() == "peace_order" and entry.value.__class__ is not Scalar:
            for child in entry.value.entries:
                if child.key is None and child.value.__class__ is Scalar:
                    order.append(child.value.text)
                    facts.ref(KIND_CB, child.value.text, child, ROLE_PEACE_ORDER)
    in_order = set(order)
    for entry in doc.entries:
        if entry.key is None or entry.value.__class__ is Scalar or entry.key.text.lower() == "peace_order":
            continue
        block = entry.value
        facts.define(KIND_CB, entry.key.text, entry.line, {
            "in_peace_order": entry.key.text in in_order, "sprite_index": as_int(block.get_text("sprite_index")),
            "war_name": block.get_text("war_name"), "months": as_int(block.get_text("months"))})
    return facts.result()


@extractor("common/bookmarks.txt", version=1)
def bookmarks(rel, data, layer):
    """``bookmark = { name desc date cameraX cameraY }``: el nombre del símbolo es su ``name`` (``GC_NAME``)."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.key.text.lower() != "bookmark" or entry.value.__class__ is Scalar:
            continue
        block = entry.value
        date = block.get_text("date")
        name = block.get_text("name") or date or f"bookmark_{entry.line}"
        facts.define(KIND_BOOKMARK, name, entry.line, {"date": date, "desc": block.get_text("desc")})
    return facts.result()


WAR_TAG_KEYS = frozenset({"add_attacker", "add_defender", "rem_attacker", "rem_defender"})
WAR_GOAL_TAG_KEYS = frozenset({"actor", "receiver", "country"})


@extractor("history/wars/*.txt", version=1)
def wars(rel, data, layer):
    """Una guerra por archivo; su nombre es ``name`` si lo hay (``ACW.txt`` lo tiene comentado) o el del archivo."""
    facts = Facts(rel, layer)
    doc = document(data)
    name = doc.get_text("name") or rel.name.rsplit(".", 1)[0]
    dates = []
    for entry in doc.entries:
        if entry.key is None or entry.value.__class__ is Scalar or not is_date(entry.key.text):
            continue
        dates.append(entry.key.text)
        for child in entry.value.entries:
            if child.key is None:
                continue
            lowered = child.key.text.lower()
            if lowered in WAR_TAG_KEYS and child.value.__class__ is Scalar:
                facts.ref(KIND_TAG, child.value.text, child, lowered)
            elif lowered == "war_goal" and child.value.__class__ is not Scalar:
                for goal in child.value.entries:
                    if goal.key is None or goal.value.__class__ is not Scalar:
                        continue
                    field = goal.key.text.lower()
                    if field == "casus_belli":
                        facts.ref(KIND_CB, goal.value.text, goal, "casus_belli")
                    elif field in WAR_GOAL_TAG_KEYS:
                        facts.ref(KIND_TAG, goal.value.text, goal, field)
                    elif field == "state_province_id":
                        facts.ref(KIND_PROVINCE, goal.value.text, goal, "state_province_id")
    facts.define(KIND_WAR, name, 1, {"dates": dates})
    return facts.result()


@extractor("history/diplomacy/*.txt", version=1)
def diplomacy(rel, data, layer):
    """``alliance``/``vassal``/``substate``/``union`` = { first second start_date end_date } (H20)."""
    facts = Facts(rel, layer)
    for entry in document(data).entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        relation = entry.key.text.lower()
        for child in entry.value.entries:
            if child.key is not None and child.key.text.lower() in ("first", "second") \
                    and child.value.__class__ is Scalar:
                facts.ref(KIND_TAG, child.value.text, child, f"{relation}_{child.key.text.lower()}")
    return facts.result()
