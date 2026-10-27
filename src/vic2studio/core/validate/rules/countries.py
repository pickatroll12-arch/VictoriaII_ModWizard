"""Familia «countries»: registro de TAG, archivos de país, partidos, historias y referencias rotas (wizard §11).

Todo sale del índice (sin volver a analizar archivos) y de ``GameRules``:

- registro: ``tag_not_registered`` (un TAG con historia o usado en las historias de
  provincia, guerras o diplomacia que no está en ``countries.txt``; arreglo
  ``register_tag``), ``tag_after_dynamic_tags``, ``tag_invalid``, ``tag_taken``,
  ``country_file_missing``, ``country_history_missing`` y
  ``country_history_duplicate``;
- partidos (H12): ``ruling_party_not_of_country``, ``ruling_party_ideology_not_allowed``
  (a la fecha de inicio o de trabajo) y ``party_unknown_policy``;
- gobiernos (H16): ``government_missing_in_rebel_map`` y
  ``government_election_without_duration``;
- historia: ``upper_house_sum`` y ``duplicate_field`` (campos de valor único
  repetidos en el mismo bloque: los 50 ``civilized`` de D01–D50, H13);
- referencias rotas por tipo, ``*_unknown`` (cultura, religión, gobierno, valor
  nacional, tecnología, invención, reforma, bien, edificio, tipo de POP, CB,
  unidad, escuela, ideología, cultura gráfica, terreno, provincia y decisión) y
  ``oob_file_missing``. Los TAG, eventos y textos tienen sus propios códigos.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...clausewitz.nodes import ClausewitzDate
from ...index import model as m
from ...index.extractors._support import path_name
from ...rules.ids import DYNAMIC_TAG_RE, RESERVED_TAGS, flag_tag, tag_problem
from ...vfs.paths import VPath
from ...vfs.rules import tag_key
from ..registry import make_problem, rule

E, W = Severity.ERROR, Severity.WARNING
REGISTRY_REL = VPath.of("common/countries.txt")

# Roles de las referencias a un TAG que cuentan como «se usa» para ``tag_not_registered`` (``union`` y ``primary``:
# el país de unión de un grupo de culturas y el de una cultura, en ``common/cultures.txt``).
TAG_USE_ROLES = frozenset({"owner", "controller", "add_core", "remove_core", "add_attacker", "add_defender",
                           "rem_attacker", "rem_defender", "actor", "receiver", "country", "alliance_first",
                           "alliance_second", "vassal_first", "vassal_second", "substate_first", "substate_second",
                           "union_first", "union_second", "union", "primary"})

# Tipo referenciado → (código, tipos que lo definen).
UNKNOWN = {
    m.KIND_CULTURE: ("culture_unknown", (m.KIND_CULTURE,)),
    m.KIND_RELIGION: ("religion_unknown", (m.KIND_RELIGION,)),
    m.KIND_GOVERNMENT: ("government_unknown", (m.KIND_GOVERNMENT,)),
    m.KIND_NATIONAL_VALUE: ("nationalvalue_unknown", (m.KIND_NATIONAL_VALUE,)),
    m.KIND_TECHNOLOGY: ("technology_unknown", (m.KIND_TECHNOLOGY, m.KIND_INVENTION)),
    m.KIND_INVENTION: ("invention_unknown", (m.KIND_INVENTION, m.KIND_TECHNOLOGY)),
    m.KIND_GOODS: ("goods_unknown", (m.KIND_GOODS,)),
    m.KIND_BUILDING: ("building_unknown", (m.KIND_BUILDING,)),
    m.KIND_POP_TYPE: ("pop_type_unknown", (m.KIND_POP_TYPE,)),
    m.KIND_CB: ("cb_unknown", (m.KIND_CB,)),
    m.KIND_UNIT_TYPE: ("unit_unknown", (m.KIND_UNIT_TYPE,)),
    m.KIND_TECH_SCHOOL: ("tech_school_unknown", (m.KIND_TECH_SCHOOL,)),
    m.KIND_IDEOLOGY: ("ideology_unknown", (m.KIND_IDEOLOGY,)),
    m.KIND_GRAPHICAL_CULTURE: ("graphical_culture_unknown", (m.KIND_GRAPHICAL_CULTURE,)),
    m.KIND_TERRAIN: ("terrain_unknown", (m.KIND_TERRAIN,)),
    m.KIND_PROVINCE: ("province_unknown", (m.KIND_PROVINCE, m.KIND_SEA_PROVINCE)),
    m.KIND_DECISION: ("decision_unknown", (m.KIND_DECISION,)),
}
# Referencias que se comprueban en otra regla (o que no son usos que el juego necesite resueltos).
SKIP_ROLES = {m.KIND_CB: {"peace_order"}, m.KIND_PROVINCE: {m.ROLE_SEA_STARTS, "history"}}


# --- utilidades -------------------------------------------------------------------------------------


def _date(text) -> ClausewitzDate | None:
    try:
        return ClausewitzDate.parse(str(text))
    except ValueError:
        return None


def history_at(symbol, date: ClausewitzDate) -> dict:
    """Campos de una historia de país a ``date``: la raíz y los bloques fechados hasta esa fecha, en orden."""
    fields = dict(symbol.attrs.get("fields") or {})
    dated = []
    for item in symbol.attrs.get("dated") or ():
        when = _date(item[0])
        if when is not None and when <= date:
            dated.append((when, item[1] or 0, item[2]))
    for _, _, block in sorted(dated, key=lambda t: (t[0], t[1])):
        fields.update(block)
    return fields


def parties_by_file(index) -> dict[str, dict[str, object]]:
    """Archivo de país (``countries/x.txt``) → nombre de partido → símbolo (H12: los nombres se repiten)."""
    found: dict[str, dict[str, object]] = {}
    for symbol in index.symbols(m.KIND_PARTY):
        file = symbol.attrs.get("country_file")
        party = symbol.attrs.get("party")
        if isinstance(file, str) and isinstance(party, str):
            found.setdefault(file, {}).setdefault(party, symbol)
    return found


def country_file_of(index, tag: str) -> str | None:
    file = index.attrs(m.KIND_TAG, tag, "file")
    return path_name(file) if isinstance(file, str) else None


def loaded_filter(index):
    """Función ``rel → bool``: si el juego carga ese archivo. Los archivos de país (``REFERENCED``) solo si un TAG
    registrado los nombra, y las historias de país solo si su TAG está registrado; lo demás, siempre. Las
    referencias de lo que no se carga no se validan (las de SIL saldrán al registrarlo)."""
    registered = set(index.names(m.KIND_TAG))
    files = {country_file_of(index, tag) for tag in registered}

    def loaded(rel: VPath) -> bool:
        key = rel.key
        if key.startswith("COMMON/COUNTRIES/"):
            return path_name("countries/" + rel.name) in files
        if key.startswith("HISTORY/COUNTRIES/"):
            return tag_key(rel) in registered
        return True

    return loaded


def first_ref(index, rel: VPath, role: str, name: str | None = None):
    for ref in index.refs_from(rel):
        if ref.role == role and (name is None or ref.name == name):
            return ref
    return None


# --- registro de TAG ----------------------------------------------------------------------------------


@rule("tag_not_registered", E, fixes=("register_tag",))
def tags_not_registered(ctx):
    """Un problema por TAG sin registrar, en su primer uso: la historia de país; si no, una referencia (provincias,
    guerras, diplomacia, ``union``/``primary`` de las culturas); si no, su bandera ``gfx/flags/<TAG>*.tga``."""
    index = ctx.index
    registered = set(index.names(m.KIND_TAG))
    first: dict[str, tuple] = {}
    for symbol in index.symbols(m.KIND_COUNTRY_HISTORY):
        if symbol.name not in registered:
            first.setdefault(symbol.name, (0, symbol.rel, symbol.line, None))
    for ref in index.refs(m.KIND_TAG):
        if ref.role in TAG_USE_ROLES and ref.name not in registered and ref.name not in first:
            first[ref.name] = (1, ref.rel, ref.line, ref.column)
    for image in index.symbols(m.KIND_IMAGE):
        tag = flag_tag(image.name)
        if tag is not None and tag not in registered and tag not in first and tag not in RESERVED_TAGS:
            first[tag] = (2, image.rel, None, None)
    return [make_problem("tag_not_registered", rel, line, column, entity=(m.KIND_TAG, tag), tag=tag)
            for tag, (_, rel, line, column) in sorted(first.items())]


@rule("tag_after_dynamic_tags", E)
@rule("tag_invalid", E)
@rule("tag_taken", E)
def tag_registry(ctx):
    index = ctx.index
    problems = []
    for tag in index.names(m.KIND_TAG):
        definitions = index.effective(m.KIND_TAG, tag)
        symbol = definitions[0]
        entity = (m.KIND_TAG, tag)
        if symbol.attrs.get("dynamic") and DYNAMIC_TAG_RE.fullmatch(tag) is None:
            problems.append(make_problem("tag_after_dynamic_tags", symbol.rel, symbol.line, entity=entity, tag=tag))
        if tag not in RESERVED_TAGS and tag_problem(tag) is not None:
            problems.append(make_problem("tag_invalid", symbol.rel, symbol.line, entity=entity, tag=tag))
        for other in definitions[1:]:
            problems.append(make_problem("tag_taken", other.rel, other.line, entity=entity, tag=tag,
                                         first_line=symbol.line))
    return problems


@rule("country_file_missing", E)
@rule("country_history_missing", W)
@rule("country_history_duplicate", E)
def country_files(ctx):
    index = ctx.index
    problems = []
    for symbol in index.symbols(m.KIND_TAG):
        tag = symbol.name
        entity = (m.KIND_TAG, tag)
        file = country_file_of(index, tag)
        if file is None or not index.exists(m.KIND_COUNTRY_FILE, file):
            problems.append(make_problem("country_file_missing", symbol.rel, symbol.line, entity=entity, tag=tag,
                                         file=str(symbol.attrs.get("file", ""))))
        if not index.exists(m.KIND_COUNTRY_HISTORY, tag):
            problems.append(make_problem("country_history_missing", symbol.rel, symbol.line, entity=entity, tag=tag))
    for tag in index.names(m.KIND_COUNTRY_HISTORY):
        definitions = index.effective(m.KIND_COUNTRY_HISTORY, tag)
        for other in definitions[1:]:
            problems.append(make_problem("country_history_duplicate", other.rel, other.line, entity=(m.KIND_TAG, tag),
                                         tag=tag, other=str(definitions[0].rel)))
    return problems


# --- partidos y gobiernos ---------------------------------------------------------------------------


@rule("ruling_party_not_of_country", E)
@rule("ruling_party_ideology_not_allowed", W)
def ruling_parties(ctx):
    index = ctx.index
    rules = ctx.rules
    parties = parties_by_file(index)
    registered = set(index.names(m.KIND_TAG))
    date = ctx.start_date
    problems = []
    for history in index.symbols(m.KIND_COUNTRY_HISTORY):
        tag = history.name
        if tag not in registered:
            continue
        file = country_file_of(index, tag)
        if file is None or not index.exists(m.KIND_COUNTRY_FILE, file):
            continue
        own = parties.get(file, {})
        entity = (m.KIND_TAG, tag)
        for ref in index.refs_from(history.rel):
            if ref.kind == m.KIND_PARTY and ref.role == "ruling_party" and ref.name not in own:
                problems.append(make_problem("ruling_party_not_of_country", ref.rel, ref.line, ref.column,
                                             entity=entity, field=("ruling_party",), tag=tag, party=ref.name))
        fields = history_at(history, date)
        party_name, government = fields.get("ruling_party"), fields.get("government")
        party = own.get(party_name) if party_name else None
        allowed = rules.government_ideologies.get(government) if government else None
        ideology = party.attrs.get("ideology") if party is not None else None
        if allowed is not None and ideology and ideology not in allowed:
            ref = first_ref(index, history.rel, "ruling_party", party_name)
            problems.append(make_problem(
                "ruling_party_ideology_not_allowed", history.rel, ref.line if ref else history.line,
                ref.column if ref else None, entity=entity, field=("ruling_party",), tag=tag, party=party_name,
                ideology=ideology, government=government))
    return problems


@rule("party_unknown_policy", W)
def party_policies(ctx):
    index = ctx.index
    policies = ctx.rules.party_policies
    if not policies:
        return []
    problems = []
    loaded = loaded_filter(index)
    for party in index.symbols(m.KIND_PARTY):
        if not loaded(party.rel):
            continue
        for policy, value in (party.attrs.get("policies") or {}).items():
            if policy in policies and value in policies[policy]:
                continue
            ref = next((r for r in index.refs_from(party.rel) if r.role == policy and r.name == value
                        and (r.line or 0) >= (party.line or 0)), None)
            problems.append(make_problem(
                "party_unknown_policy", party.rel, ref.line if ref else party.line, ref.column if ref else None,
                entity=(m.KIND_PARTY, party.name), field=(policy,), party=party.attrs.get("party", party.name),
                policy=policy, value=value))
    return problems


@rule("government_missing_in_rebel_map", E)
@rule("government_election_without_duration", W)
def governments(ctx):
    index = ctx.index
    problems = []
    names = index.names(m.KIND_GOVERNMENT)
    for symbol in index.symbols(m.KIND_GOVERNMENT):
        if symbol.attrs.get("election") and not symbol.attrs.get("duration"):
            problems.append(make_problem("government_election_without_duration", symbol.rel, symbol.line,
                                         entity=(m.KIND_GOVERNMENT, symbol.name), government=symbol.name))
    for rebel in index.symbols(m.KIND_REBEL_TYPE):
        mapping = rebel.attrs.get("government")
        if not isinstance(mapping, dict):
            continue
        for government in names:
            if government not in mapping:
                problems.append(make_problem("government_missing_in_rebel_map", rebel.rel, rebel.line,
                                             entity=(m.KIND_GOVERNMENT, government), government=government,
                                             rebel=rebel.name))
    return problems


# --- historia ----------------------------------------------------------------------------------------


@rule("upper_house_sum", W)
@rule("duplicate_field", W)
def country_history_fields(ctx):
    problems = []
    loaded = loaded_filter(ctx.index)
    for history in ctx.index.symbols(m.KIND_COUNTRY_HISTORY):
        if not loaded(history.rel):
            continue
        entity = (m.KIND_TAG, history.name)
        for line, total in history.attrs.get("upper_house") or ():
            if abs(float(total) - 100.0) > 0.01:
                problems.append(make_problem("upper_house_sum", history.rel, line, entity=entity,
                                             field=("upper_house",), tag=history.name, total=total))
        for field_name, line, first_line in history.attrs.get("duplicates") or ():
            problems.append(make_problem("duplicate_field", history.rel, line, entity=entity, field=(field_name,),
                                         tag=history.name, name=field_name, first_line=first_line))
    return problems


# --- referencias rotas por tipo ---------------------------------------------------------------------


def _register_unknown(fn):
    for code, _ in UNKNOWN.values():
        fn = rule(code, E)(fn)
    fn = rule("reform_unknown", E)(fn)
    return rule("oob_file_missing", W)(fn)


@_register_unknown
def unknown_references(ctx):
    index = ctx.index
    problems = []
    loaded = loaded_filter(index)
    for kind, (code, defined_by) in UNKNOWN.items():
        skip = SKIP_ROLES.get(kind, ())
        known: dict[str, bool] = {}
        for ref in index.refs(kind):
            if ref.role in skip or not loaded(ref.rel):
                continue
            found = known.get(ref.name)
            if found is None:
                found = known[ref.name] = any(index.exists(k, ref.name) for k in defined_by)
            if not found:
                problems.append(make_problem(code, ref.rel, ref.line, ref.column, entity=(kind, ref.name),
                                             field=(ref.role,), name=ref.name))
    problems.extend(_unknown_reforms(ctx, loaded))
    for ref in index.refs(m.KIND_FILE):
        if ref.role == "oob" and loaded(ref.rel) and ctx.layer_of(VPath.of(ref.name)) is None:
            problems.append(make_problem("oob_file_missing", ref.rel, ref.line, ref.column,
                                         entity=(m.KIND_FILE, ref.name), field=("oob",), file=ref.name))
    return problems


def _unknown_reforms(ctx, loaded) -> list:
    """Reformas de las historias de país: ``<grupo> = <opción>`` con un grupo o una opción que no existen."""
    index = ctx.index
    groups = {g.name: set(g.attrs.get("options") or ()) for g in index.symbols(m.KIND_ISSUE_GROUP)}
    problems = []
    for ref in index.refs(m.KIND_ISSUE_OPTION):
        if not ref.rel.key.startswith("HISTORY/COUNTRIES/") or not loaded(ref.rel):
            continue                 # las políticas de los partidos son de ``party_unknown_policy``
        options = groups.get(ref.role)
        if options is None or ref.name not in options:
            problems.append(make_problem("reform_unknown", ref.rel, ref.line, ref.column,
                                         entity=(m.KIND_ISSUE_OPTION, ref.name), field=(ref.role,),
                                         group=ref.role, name=ref.name))
    return problems
