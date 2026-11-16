"""Familia «countries»: registro de TAG, archivos de país, partidos, historias y referencias rotas (wizard §11).

Todo sale del índice (sin volver a analizar archivos) y de ``GameRules``:

- registro: ``tag_not_registered`` (un TAG con historia o usado en las historias de
  provincia, guerras, diplomacia o culturas que no está en ``countries.txt``;
  arreglo ``register_tag``), ``flag_tag_not_registered`` (info: un TAG sin registrar
  del que solo hay banderas, que el juego no usa), ``tag_after_dynamic_tags``,
  ``tag_invalid``, ``tag_taken``,
  ``country_file_missing``, ``country_history_missing`` y
  ``country_history_duplicate``;
- partidos (H12): ``ruling_party_not_of_country``, ``ruling_party_ideology_not_allowed``
  (a la fecha de inicio o de trabajo) y ``party_unknown_policy``;
- gobiernos (H16): ``government_missing_in_rebel_map``,
  ``government_election_without_duration`` y ``government_flagtype_unknown`` (un
  ``flagType`` sin ninguna bandera ``gfx/flags/<TAG>_<flagType>.tga``, §14.11);
- iteración 6: ``ruling_party_inactive``, ``capital_not_owned``, ``flag_missing``, ``flag_format``,
  ``country_colors_missing`` (info) y ``map_color_duplicate`` (info);
- historia: ``upper_house_sum`` y ``duplicate_field`` (campos de valor único
  repetidos en el mismo bloque: los 50 ``civilized`` de D01–D50, H13);
- referencias rotas por tipo, ``*_unknown`` (cultura, religión, gobierno, valor
  nacional, tecnología, invención, reforma, bien, edificio, tipo de POP, CB,
  unidad, escuela, ideología, cultura gráfica, terreno, provincia y decisión) y
  ``oob_file_missing``. Los TAG, eventos y textos tienen sus propios códigos.
"""

from __future__ import annotations

from ...clausewitz import Severity
from ...clausewitz.nodes import ClausewitzDate, Scalar
from ...index import model as m
from ...index.extractors._support import path_name
from ...rules.ids import DYNAMIC_TAG_RE, FLAGS_FOLDER, RESERVED_TAGS, TAG_RE, flag_tag, tag_problem
from ...vfs.paths import VPath
from ...vfs.rules import tag_key
from ..registry import make_problem, rule

E, W, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
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


def suggest_party(own: dict, allowed, today: tuple[int, int, int]) -> str | None:
    """El primer partido del archivo del país (en su orden) activo en ``today`` y con una ideología que admite el
    gobierno (``allowed``; None: cualquiera). Es lo que propone el arreglo ``set_ruling_party``."""
    for name, party in own.items():
        ideology = party.attrs.get("ideology")
        if allowed is not None and ideology not in allowed:
            continue
        start = _date_tuple(party.attrs.get("start")) or (0, 0, 0)
        end = _date_tuple(party.attrs.get("end")) or (99999, 0, 0)
        if start <= today < end:
            return name
    return None


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


def unregistered_tags(index) -> tuple[dict[str, tuple], dict[str, list]]:
    """``(usados, solo_banderas)`` de los TAG sin registrar. ``usados``: TAG → ``(rel, línea, columna)`` de su primer
    uso, la historia de país o, si no, una referencia (provincias, guerras, diplomacia, ``union``/``primary`` de las
    culturas). ``solo_banderas``: TAG → sus ``gfx/flags/<TAG>*.tga``, los que no tienen ningún uso."""
    registered = set(index.names(m.KIND_TAG))
    used: dict[str, tuple] = {}
    for symbol in index.symbols(m.KIND_COUNTRY_HISTORY):
        if symbol.name not in registered:
            used.setdefault(symbol.name, (symbol.rel, symbol.line, None))
    for ref in index.refs(m.KIND_TAG):
        if ref.role in TAG_USE_ROLES and ref.name not in registered and ref.name not in used:
            used[ref.name] = (ref.rel, ref.line, ref.column)
    flags: dict[str, list] = {}
    for image in index.symbols(m.KIND_IMAGE):
        tag = flag_tag(image.name)
        if tag is not None and tag not in registered and tag not in used and tag not in RESERVED_TAGS:
            flags.setdefault(tag, []).append(image)
    return used, flags


@rule("tag_not_registered", E, fixes=("register_tag",))
def tags_not_registered(ctx):
    """Un problema por TAG sin registrar que algo usa, en su primer uso (``unregistered_tags``)."""
    used, _ = unregistered_tags(ctx.index)
    return [make_problem("tag_not_registered", rel, line, column, entity=(m.KIND_TAG, tag), tag=tag)
            for tag, (rel, line, column) in sorted(used.items())]


@rule("flag_tag_not_registered", INFO)
def flags_without_country(ctx):
    """Un aviso informativo por TAG sin registrar del que solo hay banderas: el juego no las usa, pero no rompen
    nada (el error sería registrarlo sin archivo de país, ver ``fixes.country_file_for``). En VSM, las 5 de CSR."""
    _, flags = unregistered_tags(ctx.index)
    problems = []
    for tag, images in sorted(flags.items()):
        first = min(images, key=lambda image: image.rel.key)
        problems.append(make_problem("flag_tag_not_registered", first.rel, None, entity=(m.KIND_TAG, tag), tag=tag,
                                     flags=len(images)))
    return problems


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
@rule("ruling_party_ideology_not_allowed", W, fixes=("set_ruling_party",))
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
            today = (date.year, date.month, date.day)
            problems.append(make_problem(
                "ruling_party_ideology_not_allowed", history.rel, ref.line if ref else history.line,
                ref.column if ref else None, entity=entity, field=("ruling_party",), tag=tag, party=party_name,
                ideology=ideology, government=government, suggestion=suggest_party(own, allowed, today) or ""))
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


def flag_types(index) -> set[str] | None:
    """Los ``<tipo>`` de las banderas ``gfx/flags/<TAG>_<tipo>.tga`` de la vista, en minúsculas (las rutas de las
    imágenes van así en el índice y Windows no las distingue); None si no hay ninguna bandera de país."""
    found: set[str] = set()
    any_flag = False
    for name in index.names(m.KIND_IMAGE):
        if not name.startswith(FLAGS_FOLDER) or not name.endswith(".tga"):
            continue
        stem = name[len(FLAGS_FOLDER):-len(".tga")]
        if "/" in stem or TAG_RE.fullmatch(stem[:3].upper()) is None:
            continue
        any_flag = True
        if len(stem) > 4 and stem[3] == "_":
            found.add(stem[4:])
    return found if any_flag else None


def _flag_type_entry(ctx, symbol):
    """La entrada ``flagType`` del gobierno ``symbol`` en su archivo, para dar su línea (el índice solo trae la del
    bloque); None si no se encuentra."""
    parsed = ctx.parse(symbol.rel)
    if parsed is None:
        return None
    for entry in parsed.document.entries:
        if entry.key is not None and entry.key.text == symbol.name and entry.value.__class__ is not Scalar:
            return entry.value.find("flagType", ignore_case=True)
    return None


@rule("government_flagtype_unknown", W)
def government_flag_types(ctx):
    """Vanilla: 7 de sus 8 gobiernos llevan ``flagType`` y los 4 tipos (communist, fascist, monarchy y republic)
    tienen bandera en 271 países cada uno. Qué enseña el juego si un país con ese gobierno no tiene la suya es
    [verificar en juego]; aquí solo se avisa cuando no la tiene **ninguno**: el tipo no existe como bandera. Sin
    banderas de país en la vista, la regla calla."""
    index = ctx.index
    known = flag_types(index)
    if known is None:
        return []
    problems = []
    for symbol in index.symbols(m.KIND_GOVERNMENT):
        flag_type = symbol.attrs.get("flag_type")
        if not isinstance(flag_type, str) or not flag_type.strip() or flag_type.strip().lower() in known:
            continue
        entry = _flag_type_entry(ctx, symbol)
        line, column = (symbol.line, None) if entry is None else (entry.line, entry.column)
        problems.append(make_problem("government_flagtype_unknown", symbol.rel, line, column,
                                     entity=(m.KIND_GOVERNMENT, symbol.name), field=("flagType",),
                                     government=symbol.name, flag_type=flag_type.strip()))
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


# --- iteración 6: partido activo, capital, banderas y colores --------------------------------------------------


def _date_tuple(text) -> tuple | None:
    when = _date(text) if text else None
    return None if when is None else (when.year, when.month, when.day)


@rule("ruling_party_inactive", W, fixes=("set_ruling_party",))
def ruling_party_inactive(ctx):
    """El partido gobernante a la fecha de inicio (o de trabajo) no está activo ese día: su ``start_date`` es
    posterior o su ``end_date`` no es posterior. Vanilla: 11 países (heredados)."""
    index = ctx.index
    parties = parties_by_file(index)
    date = ctx.start_date
    today = (date.year, date.month, date.day)
    problems = []
    for history in index.symbols(m.KIND_COUNTRY_HISTORY):
        tag = history.name
        file = country_file_of(index, tag)
        name = history_at(history, date).get("ruling_party")
        party = parties.get(file, {}).get(name) if file and name else None
        if party is None:
            continue
        start = _date_tuple(party.attrs.get("start")) or (0, 0, 0)
        end = _date_tuple(party.attrs.get("end")) or (99999, 0, 0)
        if start <= today < end:
            continue
        ref = first_ref(index, history.rel, "ruling_party", name)
        government = history_at(history, date).get("government")
        allowed = ctx.rules.government_ideologies.get(government) if government else None
        problems.append(make_problem("ruling_party_inactive", history.rel, ref.line if ref else history.line,
                                     ref.column if ref else None, entity=(m.KIND_TAG, tag), field=("ruling_party",),
                                     tag=tag, party=name, start=party.attrs.get("start") or "",
                                     end=party.attrs.get("end") or "", date=str(date),
                                     suggestion=suggest_party(parties.get(file, {}), allowed, today) or ""))
    return problems


def province_owners(index, date: ClausewitzDate) -> dict[str, str]:
    """Id de provincia → dueño a ``date`` (de los símbolos ``province_history`` del índice)."""
    owners = {}
    for symbol in index.symbols(m.KIND_PROVINCE_HISTORY):
        fields = history_at(symbol, date)
        owner = fields.get("owner")
        if owner:
            owners[symbol.name] = str(owner).upper()
    return owners


@rule("capital_not_owned", W)
def capital_not_owned(ctx):
    """Un país que tiene provincias a la fecha de inicio pero cuya capital es de otro. Los que no tienen tierra
    (liberables, formables) no cuentan: en vanilla 90 de 220 capitales están en provincias ajenas por eso, y solo 3
    de los 131 países con tierra (heredados)."""
    index = ctx.index
    date = ctx.start_date
    owners = province_owners(index, date)
    landed = set(owners.values())
    problems = []
    for history in index.symbols(m.KIND_COUNTRY_HISTORY):
        tag = history.name.upper()
        if tag not in landed:
            continue
        capital = history_at(history, date).get("capital")
        if not capital or owners.get(str(capital)) == tag:
            continue
        ref = first_ref(index, history.rel, "capital", str(capital))
        problems.append(make_problem("capital_not_owned", history.rel, ref.line if ref else history.line,
                                     ref.column if ref else None, entity=(m.KIND_TAG, tag), field=("capital",),
                                     tag=tag, province=str(capital), owner=owners.get(str(capital)) or "—"))
    return problems


TGA_TYPES = frozenset({2, 10})            # color verdadero sin comprimir y con RLE (vanilla usa los dos)
TGA_DEPTHS = frozenset({24, 32})


def flag_header_problem(data: bytes | None) -> str | None:
    """Por qué el juego no podría leer esta bandera (``short``, ``type`` o ``depth``); None si se puede."""
    if data is None or len(data) < 18:
        return "short"
    if data[2] not in TGA_TYPES:
        return "type"
    if data[16] not in TGA_DEPTHS:
        return "depth"
    return None


def _head(ctx, rel: VPath, size: int = 18) -> bytes | None:
    if ctx.unsaved(rel):
        data = ctx.read(rel)
        return None if data is None else data[:size]
    entry = ctx.entry(rel)
    if entry is None:
        return None
    try:
        with open(entry.path, "rb") as handle:
            return handle.read(size)
    except OSError:
        return None


@rule("flag_missing", W)
@rule("flag_format", W)
def flags(ctx):
    """``flag_missing``: un país registrado (no dinámico) sin ``gfx/flags/<TAG>.tga`` (vanilla: ninguno).
    ``flag_format``: una bandera de país que no es un TGA de color verdadero de 24 o 32 bits (tipo 2 o 10): el
    juego la enseña en negro. Las medidas (93×64 en vanilla, también 64×64 en algunas) no se comprueban."""
    index = ctx.index
    images = {name for name in index.names(m.KIND_IMAGE)}
    problems = []
    for symbol in index.symbols(m.KIND_TAG):
        if symbol.attrs.get("dynamic") or symbol.name in RESERVED_TAGS:
            continue
        if f"{FLAGS_FOLDER}{symbol.name.lower()}.tga" not in images:
            problems.append(make_problem("flag_missing", symbol.rel, symbol.line, entity=(m.KIND_TAG, symbol.name),
                                         tag=symbol.name, file=f"gfx/flags/{symbol.name}.tga"))
    for name in sorted(images):
        tag = flag_tag(name)
        if tag is None:
            continue
        rel = next((s.rel for s in index.effective(m.KIND_IMAGE, name)), VPath.of(name))
        reason = flag_header_problem(_head(ctx, rel))
        if reason is not None:
            problems.append(make_problem("flag_format", rel, None, entity=(m.KIND_TAG, tag), tag=tag,
                                         file=str(rel), reason=reason))
    return problems


@rule("country_colors_missing", INFO)
def country_colors_missing(ctx):
    """Un país registrado (no dinámico) sin colores de uniforme en ``common/country_colors.txt``: el juego usa
    unos por defecto. Informativo (en vanilla los tienen 147 de 271)."""
    result = ctx.parse(VPath.of("common/country_colors.txt"))
    if result is None:
        return []
    listed = {entry.key.text.upper() for entry in result.document.entries if entry.key is not None}
    problems = []
    for symbol in ctx.index.symbols(m.KIND_TAG):
        if symbol.attrs.get("dynamic") or symbol.name.upper() in listed or symbol.name in RESERVED_TAGS:
            continue
        problems.append(make_problem("country_colors_missing", symbol.rel, symbol.line,
                                     entity=(m.KIND_TAG, symbol.name), tag=symbol.name))
    return problems


@rule("map_color_duplicate", INFO)
def map_color_duplicate(ctx):
    """Dos archivos de país con el mismo color de mapa: en el modo político no se distinguen (vanilla: 40 pares)."""
    index = ctx.index
    seen: dict[tuple, object] = {}
    problems = []
    for symbol in sorted(index.symbols(m.KIND_COUNTRY_FILE), key=lambda s: s.name):
        color = symbol.attrs.get("color")
        if not color:
            continue
        key = tuple(color)
        first = seen.setdefault(key, symbol)
        if first is symbol:
            continue
        problems.append(make_problem("map_color_duplicate", symbol.rel, 1, entity=(m.KIND_COUNTRY_FILE, symbol.name),
                                     field=("color",), file=symbol.name, other=first.name,
                                     color=" ".join(str(c) for c in key)))
    return problems
