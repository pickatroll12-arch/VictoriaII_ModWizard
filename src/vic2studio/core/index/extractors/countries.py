"""Países: registro de TAG, archivos de país con sus partidos e historias de país (wizard §7, H11, H12, H19)."""

from __future__ import annotations

from ...clausewitz.nodes import Scalar
from ...vfs.rules import tag_key
from ..model import (
    KIND_COUNTRY_FILE,
    KIND_COUNTRY_FLAG,
    KIND_COUNTRY_HISTORY,
    KIND_CULTURE,
    KIND_DECISION,
    KIND_FILE,
    KIND_GLOBAL_FLAG,
    KIND_GOVERNMENT,
    KIND_GRAPHICAL_CULTURE,
    KIND_IDEOLOGY,
    KIND_INVENTION,
    KIND_ISSUE_OPTION,
    KIND_NATIONAL_VALUE,
    KIND_PARTY,
    KIND_PROVINCE,
    KIND_RELIGION,
    KIND_TAG,
    KIND_TECH_SCHOOL,
    KIND_TECHNOLOGY,
    extractor,
)
from ..parsing import as_number, document, is_date, loose_values
from ._support import Facts, path_name

PARTY_FIXED = frozenset({"name", "ideology", "start_date", "end_date"})


def country_file_name(text: str) -> str | None:
    """Nombre de símbolo de un archivo de país tal como lo escribe ``countries.txt`` (``countries/X.txt``)."""
    return path_name(text)


@extractor("common/countries.txt", version=1)
def tag_registry(rel, data, layer):
    """Cada ``TAG = "countries/X.txt"``; los que van tras ``dynamic_tags = yes`` son dominios dinámicos (H11)."""
    facts = Facts(rel, layer)
    dynamic = False
    for entry in document(data).entries:
        key = entry.key
        if key is None or entry.value.__class__ is not Scalar:
            continue
        name, value = key.text, entry.value.text
        if name.lower() == "dynamic_tags":
            dynamic = value.lower() == "yes"
            continue
        file = country_file_name(value)
        facts.define(KIND_TAG, name, entry.line, {"file": value, "dynamic": dynamic})
        if file is not None:
            facts.ref(KIND_COUNTRY_FILE, file, entry, "country_file")
    return facts.result()


@extractor("common/countries/*.txt", version=1)
def country_file(rel, data, layer):
    """El archivo de país (color, cultura gráfica) y sus partidos: ``"<archivo>:<nombre>"`` (H12)."""
    facts = Facts(rel, layer)
    doc = document(data)
    file = country_file_name("countries/" + rel.name) or rel.name.lower()
    color = None
    graphical = None
    parties: list[str] = []
    for entry in doc.entries:
        key = entry.key
        if key is None:
            continue
        name = key.text.lower()
        value = entry.value
        if name == "color" and value.__class__ is not Scalar:
            numbers = [as_number(v) for v in loose_values(value)]
            if len(numbers) == 3 and all(n is not None for n in numbers):
                color = [int(n) for n in numbers]
        elif name == "graphical_culture" and value.__class__ is Scalar:
            graphical = value.text
            facts.ref(KIND_GRAPHICAL_CULTURE, graphical, entry, "graphical_culture")
        elif name == "party" and value.__class__ is not Scalar:
            party = value.get_text("name")
            if not party:
                continue
            policies = {}
            for child in value.entries:
                if child.key is None or child.value.__class__ is not Scalar:
                    continue
                field_name = child.key.text
                if field_name in PARTY_FIXED:
                    continue
                policies[field_name] = child.value.text
                facts.ref(KIND_ISSUE_OPTION, child.value.text, child, field_name)
            ideology = value.get_text("ideology")
            if ideology:
                facts.ref(KIND_IDEOLOGY, ideology, value.find("ideology"), "ideology")
            parties.append(party)
            facts.define(KIND_PARTY, f"{file}:{party}", entry.line, {
                "country_file": file, "party": party, "ideology": ideology,
                "start": value.get_text("start_date"), "end": value.get_text("end_date"), "policies": policies})
    facts.define(KIND_COUNTRY_FILE, file, 1, {"path": str(rel), "color": color, "graphical_culture": graphical,
                                              "parties": parties})
    return facts.result()


# --- historia de país (H19) -------------------------------------------------------------------------

# Campo → (tipo referenciado, rol). Los demás escalares son tecnologías (número), invenciones (yes/no) y
# reformas (palabra: grupo = opción), como en vanilla y VSM (wizard H19).
HISTORY_REFS = {
    "capital": (KIND_PROVINCE, "capital"),
    "primary_culture": (KIND_CULTURE, "primary_culture"),
    "culture": (KIND_CULTURE, "culture"),
    "add_accepted_culture": (KIND_CULTURE, "culture"),
    "religion": (KIND_RELIGION, "religion"),
    "government": (KIND_GOVERNMENT, "government"),
    "nationalvalue": (KIND_NATIONAL_VALUE, "nationalvalue"),
    "ruling_party": (KIND_PARTY, "ruling_party"),
    "schools": (KIND_TECH_SCHOOL, "school"),
    "school": (KIND_TECH_SCHOOL, "school"),
    "decision": (KIND_DECISION, "decision"),
}
# Campos sin referencia (números, sí/no, fechas, bloques).
HISTORY_PLAIN = frozenset({
    "plurality", "literacy", "non_state_culture_literacy", "civilized", "prestige", "consciousness",
    "nonstate_consciousness", "colonial_points", "is_releasable_vassal", "last_election", "badboy", "money",
    "leadership", "research_points", "war_exhaustion", "diplomatic_points", "upper_house", "foreign_investment",
    "govt_flag", "remove_accepted_culture", "clr_country_flag", "clr_global_flag",
})
# Campos de valor único: repetirlos en el mismo bloque es ``duplicate_field`` (los 50 ``civilized`` de D01–D50).
HISTORY_SINGLE = frozenset({
    "capital", "primary_culture", "religion", "government", "plurality", "nationalvalue", "literacy",
    "non_state_culture_literacy", "civilized", "prestige", "ruling_party", "consciousness", "nonstate_consciousness",
    "is_releasable_vassal", "last_election",
})
# Campos que guarda el símbolo para las reglas (a la fecha de inicio o a la de trabajo).
HISTORY_KEPT = ("capital", "primary_culture", "religion", "government", "nationalvalue", "ruling_party",
                "civilized", "plurality", "literacy")


def _history_block(facts: Facts, block, fields: dict, duplicates: list, upper: list) -> None:
    seen: dict[str, int] = {}
    for entry in block.entries:
        key = entry.key
        if key is None:
            continue
        name = key.text
        lowered = name.lower()
        value = entry.value
        if value.__class__ is not Scalar:
            if lowered == "upper_house":
                total = 0.0
                for child in value.entries:
                    number = as_number(child.value.text) if child.value.__class__ is Scalar else None
                    if number is not None:
                        total += number
                    if child.key is not None:
                        facts.ref(KIND_IDEOLOGY, child.key.text, child, "upper_house")
                upper.append([entry.line, round(total, 4)])
            continue
        text = value.text
        if lowered in HISTORY_SINGLE:
            if lowered in seen:
                duplicates.append([lowered, entry.line, seen[lowered]])
            else:
                seen[lowered] = entry.line
        if lowered in HISTORY_KEPT:
            fields[lowered] = text
        if lowered in HISTORY_REFS:
            kind, role = HISTORY_REFS[lowered]
            facts.ref(kind, text, entry, role)
        elif lowered == "oob":
            target = path_name(text, "history/units")
            if target is not None:
                facts.ref(KIND_FILE, target, entry, "oob")
        elif lowered == "set_country_flag":
            facts.define(KIND_COUNTRY_FLAG, text, entry.line)
        elif lowered == "set_global_flag":
            facts.define(KIND_GLOBAL_FLAG, text, entry.line)
        elif lowered in HISTORY_PLAIN:
            continue
        elif as_number(text) is not None:
            facts.ref(KIND_TECHNOLOGY, name, entry, "technology")
        elif text.lower() in ("yes", "no"):
            facts.ref(KIND_INVENTION, name, entry, "invention")
        else:
            facts.ref(KIND_ISSUE_OPTION, text, entry, name)


@extractor("history/countries/*.txt", version=1)
def country_history(rel, data, layer):
    """Historia de un TAG (``<TAG> - <Nombre>.txt``): campos, bloques fechados y todas sus referencias."""
    facts = Facts(rel, layer)
    doc = document(data)
    fields: dict = {}
    duplicates: list = []
    upper: list = []
    _history_block(facts, doc, fields, duplicates, upper)
    dated = []
    for entry in doc.entries:
        key = entry.key
        if key is not None and entry.value.__class__ is not Scalar and is_date(key.text):
            block_fields: dict = {}
            _history_block(facts, entry.value, block_fields, duplicates, upper)
            dated.append([key.text, entry.line, block_fields])
    tag = tag_key(rel)
    if tag is not None:
        facts.define(KIND_COUNTRY_HISTORY, tag, 1, {"fields": fields, "dated": dated, "duplicates": duplicates,
                                                    "upper_house": upper})
    return facts.result()
