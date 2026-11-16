"""Países nuevos: la especificación del asistente, su plan de cambios y su creación (wizard §14.2). Contrato y
implementación de la iteración 6.

``NewCountrySpec`` es lo que el asistente «Nuevo país» reúne en sus 8 pasos. ``plan_new_country`` enseña lo que
hará (archivo · acción · diff) **sin dejar nada cambiado**: ejecuta la creación en una transacción que se revierte
y compara los bytes de antes y de después. ``create_new_country`` hace lo mismo de verdad, en **una sola
transacción** (``undo.new_country``): un Ctrl+Z lo deshace entero (criterio 1). Como plan y creación usan el
mismo código, el plan es exactamente lo que se aplicará.

Archivos que toca (y solo esos):

- ``common/countries.txt``: una línea ``TAG = "countries/<Archivo>.txt"`` justo antes de ``dynamic_tags`` y de
  los comentarios que lo preceden (H11); sin ``dynamic_tags``, al final.
- ``common/countries/<Archivo>.txt`` (nuevo): ``color``, ``graphical_culture``, los partidos y ``unit_names``.
- ``history/countries/<TAG> - <Archivo>.txt`` (nuevo): capital, culturas, religión, gobierno, partido
  gobernante, cámara alta, reformas, tecnologías y demás.
- ``common/country_colors.txt`` (si hay colores de uniforme): un bloque al final.
- ``history/units/<TAG>_oob.txt`` (si hay ejércitos o flotas) y ``oob = "<TAG>_oob.txt"`` en la historia.
- ``gfx/flags/<TAG>{,_communist,_fascist,_monarchy,_republic}.tga`` (las que traiga ``flags``).
- ``history/provinces/...`` de las provincias que pasan a ser suyas (dueño, controlador y, si se pide, núcleo,
  en la fecha de inicio), con la fachada de provincia.
- ``localisation/00_<P>_countries.csv``: ``TAG``, ``TAG_ADJ`` y el nombre de cada partido.

Ninguna función escribe en disco: todo queda en el ``Workspace`` hasta que el usuario guarda.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..encoding import GAME_ENCODING
from ..rules.names import country_file_name
from ..vfs.paths import VPath
from .tags import check_tag, taken_tags

if TYPE_CHECKING:
    from ..project import Project
    from ..validate.model import ChangePlan

UNDO_NEW_COUNTRY = "undo.new_country"
COUNTRIES_REL = VPath.of("common/countries.txt")
COUNTRY_COLORS_REL = VPath.of("common/country_colors.txt")
LOC_AREA = "countries"
DEFAULT_PARTY_START = "1830.1.1"            # las fechas más habituales en vanilla (§14.2)
DEFAULT_PARTY_END = "2000.1.1"
POLICY_GROUPS = ("economic_policy", "trade_policy", "religious_policy", "citizenship_policy", "war_policy")
# Política preferida de cada ideología para la plantilla de partidos (se usa la primera que exista en el juego; si
# ninguna existe, la primera opción del grupo).
IDEOLOGY_POLICIES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "conservative": {"economic_policy": ("interventionism",), "trade_policy": ("protectionism",),
                     "religious_policy": ("moralism",), "citizenship_policy": ("limited_citizenship",),
                     "war_policy": ("pro_military",)},
    "liberal": {"economic_policy": ("laissez_faire",), "trade_policy": ("free_trade",),
                "religious_policy": ("pluralism",), "citizenship_policy": ("limited_citizenship",),
                "war_policy": ("anti_military",)},
    "reactionary": {"economic_policy": ("state_capitalism",), "trade_policy": ("protectionism",),
                    "religious_policy": ("moralism",), "citizenship_policy": ("residency",),
                    "war_policy": ("jingoism",)},
    "socialist": {"economic_policy": ("state_capitalism",), "trade_policy": ("protectionism",),
                  "religious_policy": ("secularized",), "citizenship_policy": ("full_citizenship",),
                  "war_policy": ("anti_military",)},
    "communist": {"economic_policy": ("planned_economy",), "trade_policy": ("protectionism",),
                  "religious_policy": ("pro_atheism",), "citizenship_policy": ("full_citizenship",),
                  "war_policy": ("pro_military",)},
    "fascist": {"economic_policy": ("state_capitalism",), "trade_policy": ("protectionism",),
                "religious_policy": ("moralism",), "citizenship_policy": ("residency",),
                "war_policy": ("jingoism",)},
    "anarcho_liberal": {"economic_policy": ("laissez_faire",), "trade_policy": ("free_trade",),
                        "religious_policy": ("pro_atheism",), "citizenship_policy": ("full_citizenship",),
                        "war_policy": ("pacifism",)},
}


@dataclass(frozen=True)
class DomainContext:
    """Lo que las funciones de este módulo y de ``core.domain.war`` necesitan de un proyecto abierto: el
    ``Workspace`` y la VFS, el índice, la localización (``LocSync``), ``Entities``, las reglas del juego y los
    ajustes (el prefijo). La sesión de la interfaz lo arma con lo suyo; un ``Project`` con esos atributos también
    vale (las pruebas se los ponen)."""

    ws: object
    vfs: object
    index: object
    loc: object
    entities: object
    rules: object
    settings: object = None


class CountryError(ValueError):
    """El país no se puede crear tal como está; no se cambió nada. ``code``: ``tag`` (con ``detail`` = motivo de
    ``check_tag``), ``file_exists`` (ya hay un archivo con ese nombre), ``no_name``, ``bad_party`` (el partido
    gobernante no es de los suyos), ``province`` (una provincia de mar o que no existe) o ``capital`` (la capital
    no está entre sus provincias, si tiene alguna)."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class PartySpec:
    name: str
    ideology: str
    start_date: str = DEFAULT_PARTY_START
    end_date: str = DEFAULT_PARTY_END
    policies: Mapping[str, str] = field(default_factory=dict)
    texts: Mapping[str, str] = field(default_factory=dict)     # idioma → nombre visible


@dataclass(frozen=True)
class RegimentSpec:
    name: str
    type: str
    home: int


@dataclass(frozen=True)
class ArmySpec:
    """Un ejército (``naval=False``) o una flota (``naval=True``) del OOB inicial."""

    name: str
    location: int
    units: tuple[RegimentSpec, ...] = ()
    naval: bool = False


@dataclass(frozen=True)
class NewCountrySpec:
    tag: str
    name: Mapping[str, str]                          # idioma → nombre («en» decide el archivo si no hay file_name)
    adjective: Mapping[str, str] = field(default_factory=dict)
    file_name: str | None = None                     # sin «.txt»
    color: tuple[int, int, int] = (128, 128, 128)
    graphical_culture: str = "EuropeanGC"
    uniform_colors: tuple[tuple[int, int, int], ...] = ()     # 3 colores o ninguno
    flags: Mapping[str, bytes] = field(default_factory=dict)  # sufijo → TGA (core.gfx.flags.make_flag_set)
    primary_culture: str | None = None
    cultures: tuple[str, ...] = ()
    religion: str | None = None
    parties: tuple[PartySpec, ...] = ()
    government: str | None = None
    ruling_party: str | None = None
    reforms: Mapping[str, str] = field(default_factory=dict)  # grupo → opción
    upper_house: Mapping[str, float] = field(default_factory=dict)
    plurality: float | None = None
    literacy: float | None = None
    non_state_culture_literacy: float | None = None
    prestige: float | None = None
    nationalvalue: str | None = None
    civilized: bool = True
    school: str | None = None
    technologies: tuple[str, ...] = ()
    inventions: tuple[str, ...] = ()
    capital: int | None = None
    provinces: tuple[int, ...] = ()
    cores: bool = True
    armies: tuple[ArmySpec, ...] = ()

    def display_name(self, lang: str = "en") -> str:
        return self.name.get(lang) or self.name.get("en") or next(iter(self.name.values()), "") or self.tag

    def base_name(self) -> str:
        """El nombre del archivo de país sin extensión (``file_name`` o el nombre en inglés, limpio)."""
        raw = self.file_name or self.name.get("en") or self.display_name()
        return country_file_name(raw)[:-4]


# --- lo que se puede ofrecer en el asistente --------------------------------------------------------------


def party_template(tag: str, index, ideologies: Iterable[str] | None = None) -> tuple[PartySpec, ...]:
    """Un partido por ideología (``<TAG>_<ideología>``), con las fechas más habituales y una política por grupo."""
    from ..index import model as m

    names = list(ideologies) if ideologies is not None else (index.names(m.KIND_IDEOLOGY) if index else [])
    groups = {}
    if index is not None:
        for group in POLICY_GROUPS:
            symbol = index.get(m.KIND_ISSUE_GROUP, group)
            if symbol is not None:
                groups[group] = list(symbol.attrs.get("options") or ())
    parties = []
    for ideology in names:
        wanted = IDEOLOGY_POLICIES.get(ideology, {})
        policies = {}
        for group, options in groups.items():
            if not options:
                continue
            choice = next((o for o in wanted.get(group, ()) if o in options), options[0])
            policies[group] = choice
        parties.append(PartySpec(f"{tag}_{ideology}", ideology, policies=policies))
    return tuple(parties)


def renamed_party(name: str, source: str, tag: str) -> str:
    """``PRU_conservative`` → ``SOM_conservative``; un nombre sin el prefijo del origen gana el del TAG nuevo."""
    if name.upper().startswith(source.upper() + "_"):
        return f"{tag}_{name[len(source) + 1:]}"
    return f"{tag}_{name}"


def copy_parties(project: Project, source: str, tag: str) -> tuple[PartySpec, ...]:
    """Los partidos del país ``source`` con el prefijo de ``tag`` («Copiar partidos de PRU»), con sus textos."""
    from ..index import model as m
    from ..validate.rules.countries import country_file_of

    index = project.index
    file = country_file_of(index, source)
    if file is None:
        return ()
    parties = []
    for symbol in index.symbols(m.KIND_PARTY):
        attrs = symbol.attrs
        if attrs.get("country_file") != file:
            continue
        original = attrs.get("party") or ""
        texts = {}
        loc = getattr(project, "loc", None)
        for lang in ("en", "es"):
            text = loc.text(original, lang) if loc is not None else None
            if text:
                texts[lang] = text
        parties.append(PartySpec(renamed_party(original, source, tag), attrs.get("ideology") or "",
                                 attrs.get("start") or DEFAULT_PARTY_START, attrs.get("end") or DEFAULT_PARTY_END,
                                 dict(attrs.get("policies") or {}), texts))
    return tuple(parties)


def country_profile(project: Project, tag: str) -> dict:
    """Lo que «basar en…» copia de un país: color, cultura gráfica y los campos de su historia a la fecha de
    inicio (cultura, religión, gobierno, valor nacional, alfabetización, pluralidad, prestigio, civilizado y
    tecnologías)."""
    from ..index import model as m
    from ..validate.rules.countries import country_file_of

    index = project.index
    profile: dict = {}
    file = country_file_of(index, tag)
    symbol = index.get(m.KIND_COUNTRY_FILE, file) if file else None
    if symbol is not None:
        if symbol.attrs.get("color"):
            profile["color"] = tuple(symbol.attrs["color"])
        if symbol.attrs.get("graphical_culture"):
            profile["graphical_culture"] = symbol.attrs["graphical_culture"]
    history = index.get(m.KIND_COUNTRY_HISTORY, tag)
    if history is not None:
        fields = dict(history.attrs.get("fields") or {})
        for key in ("primary_culture", "religion", "government", "nationalvalue"):
            if fields.get(key):
                profile[key] = fields[key]
        for key in ("literacy", "plurality"):
            try:
                profile[key] = float(fields[key])
            except (KeyError, TypeError, ValueError):
                pass
        if "civilized" in fields:
            profile["civilized"] = str(fields["civilized"]).lower() == "yes"
        techs = [ref.name for ref in index.refs_from(history.rel) if ref.kind == m.KIND_TECHNOLOGY]
        profile["technologies"] = tuple(dict.fromkeys(techs))
        cultures = [ref.name for ref in index.refs_from(history.rel)
                    if ref.kind == m.KIND_CULTURE and ref.role == "culture"]
        profile["cultures"] = tuple(dict.fromkeys(cultures))
    return profile


# --- validación de la especificación ---------------------------------------------------------------------


def _exists(project: Project, rel: VPath) -> bool:
    handle = project.ws.peek(rel)
    if handle is not None:
        return not handle.deleted
    return project.vfs.resolve(rel) is not None


def history_rel(spec: NewCountrySpec) -> VPath:
    return VPath.of(f"history/countries/{spec.tag} - {spec.base_name()}.txt")


def country_rel(spec: NewCountrySpec) -> VPath:
    return VPath.of(f"common/countries/{spec.base_name()}.txt")


def oob_rel(spec: NewCountrySpec) -> VPath:
    return VPath.of(f"history/units/{spec.tag}_oob.txt")


def flag_rel(tag: str, suffix: str) -> VPath:
    return VPath.of(f"gfx/flags/{tag}{suffix}.tga")


def check_spec(project: Project, spec: NewCountrySpec) -> None:
    """``CountryError`` con el primer motivo por el que ``spec`` no se puede crear; nada si se puede."""
    from ..index import model as m

    result = check_tag(spec.tag, taken_tags(project.index))
    if not result.ok:
        raise CountryError("tag", result.reason or "")
    if not spec.display_name().strip() or spec.display_name() == spec.tag and not spec.name:
        raise CountryError("no_name")
    for rel in (country_rel(spec), history_rel(spec)):
        if _exists(project, rel):
            raise CountryError("file_exists", str(rel))
    names = {party.name for party in spec.parties}
    if spec.ruling_party and spec.ruling_party not in names:
        raise CountryError("bad_party", spec.ruling_party)
    index = project.index
    for pid in spec.provinces:
        if not index.exists(m.KIND_PROVINCE, str(pid)):
            raise CountryError("province", str(pid))
    if spec.provinces and spec.capital is not None and spec.capital not in spec.provinces:
        raise CountryError("capital", str(spec.capital))


# --- texto de los archivos nuevos ------------------------------------------------------------------------


def _number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _rgb(color: Sequence[int]) -> str:
    return "{ " + " ".join(str(int(c)) for c in color) + " }"


def _encode(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode(GAME_ENCODING)


def country_file_text(spec: NewCountrySpec) -> bytes:
    lines = [f"color = {_rgb(spec.color)}", f"graphical_culture = {spec.graphical_culture}", ""]
    for party in spec.parties:
        lines += ["party = {", f'\tname = "{party.name}"', f"\tstart_date = {party.start_date}",
                  f"\tend_date = {party.end_date}", "", f"\tideology = {party.ideology}", ""]
        for group in POLICY_GROUPS:
            if group in party.policies:
                lines.append(f"\t{group} = {party.policies[group]}")
        for group, option in party.policies.items():
            if group not in POLICY_GROUPS:
                lines.append(f"\t{group} = {option}")
        lines += ["}", ""]
    lines += ["unit_names = {", "}"]
    return _encode(lines)


def history_text(spec: NewCountrySpec, *, with_oob: bool) -> bytes:
    lines = []
    if spec.capital is not None:
        lines.append(f"capital = {int(spec.capital)}")
    if spec.primary_culture:
        lines.append(f"primary_culture = {spec.primary_culture}")
    for culture in spec.cultures:
        lines.append(f"culture = {culture}")
    if spec.religion:
        lines.append(f"religion = {spec.religion}")
    if spec.government:
        lines.append(f"government = {spec.government}")
    if spec.plurality is not None:
        lines.append(f"plurality = {_number(spec.plurality)}")
    if spec.nationalvalue:
        lines.append(f"nationalvalue = {spec.nationalvalue}")
    if spec.literacy is not None:
        lines.append(f"literacy = {_number(spec.literacy)}")
    if spec.non_state_culture_literacy is not None:
        lines.append(f"non_state_culture_literacy = {_number(spec.non_state_culture_literacy)}")
    lines.append(f"civilized = {'yes' if spec.civilized else 'no'}")
    if spec.prestige is not None:
        lines.append(f"prestige = {_number(spec.prestige)}")
    if spec.ruling_party:
        lines.append(f"ruling_party = {spec.ruling_party}")
    if spec.upper_house:
        lines.append("upper_house = {")
        lines += [f"\t{ideology} = {_number(share)}" for ideology, share in spec.upper_house.items()]
        lines.append("}")
    if spec.reforms:
        lines.append("")
        lines += [f"{group} = {option}" for group, option in spec.reforms.items()]
    if spec.school:
        lines += ["", f"schools = {spec.school}"]
    if with_oob:
        lines += ["", f'oob = "{spec.tag}_oob.txt"']
    if spec.technologies:
        lines.append("")
        lines += [f"{tech} = 1" for tech in spec.technologies]
    if spec.inventions:
        lines.append("")
        lines += [f"{invention} = yes" for invention in spec.inventions]
    return _encode(lines)


def oob_text(spec: NewCountrySpec) -> bytes:
    lines = []
    for army in spec.armies:
        kind, unit = ("navy", "ship") if army.naval else ("army", "regiment")
        lines += [f"{kind} = {{", f'\tname = "{army.name}"', f"\tlocation = {int(army.location)}"]
        for regiment in army.units:
            lines += ["", f"\t{unit} = {{", f'\t\tname = "{regiment.name}"', f"\t\ttype = {regiment.type}"]
            if not army.naval:
                lines.append(f"\t\thome = {int(regiment.home)}")
            lines.append("\t}")
        lines += ["}", ""]
    return _encode(lines)


# --- creación --------------------------------------------------------------------------------------------


def _put_text(project: Project, rel: VPath, data: bytes) -> None:
    handle = project.ws.open(rel, create=True)
    project.ws.replace_text(handle, data)


def _put_bytes(project: Project, rel: VPath, data: bytes) -> None:
    from ..project.binary import put_bytes

    put_bytes(project.ws, rel, data)


def _registry_bytes(project: Project, spec: NewCountrySpec) -> bytes:
    from ..clausewitz.nodes import Scalar
    from ..validate.fixes import _parse, _render, current

    state = current(project, COUNTRIES_REL)
    if state.data is None:
        return _encode([f'{spec.tag} = "countries/{spec.base_name()}.txt"'])
    result = _parse(state.data)
    doc = result.document
    value = Scalar(f"countries/{spec.base_name()}.txt", True)
    anchor = next((e for e in doc.entries if e.key is not None and e.key.text.lower() == "dynamic_tags"), None)
    if anchor is not None:
        doc.insert_before(anchor, spec.tag, value)
    else:
        doc.append(spec.tag, value)
    return _render(result)


def _colors_bytes(project: Project, spec: NewCountrySpec) -> bytes:
    from ..validate.fixes import current

    state = current(project, COUNTRY_COLORS_REL)
    block = [f"{spec.tag} = {{"] + [f"\tcolor{n} = {_rgb(color)}" for n, color in
                                    enumerate(spec.uniform_colors[:3], start=1)] + ["}"]
    if state.data is None:
        return _encode(block)
    text = state.data.decode(state.encoding or GAME_ENCODING, errors="replace")
    newline = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith(("\n", "\r")):
        text += newline
    return (text + newline.join(block) + newline).encode(state.encoding or GAME_ENCODING)


def build_new_country(project: Project, spec: NewCountrySpec) -> None:
    """Hace todos los cambios de ``spec`` dentro de la transacción **abierta** de quien llama (I5)."""
    check_spec(project, spec)
    _put_text(project, COUNTRIES_REL, _registry_bytes(project, spec))
    _put_text(project, country_rel(spec), country_file_text(spec))
    with_oob = bool(spec.armies)
    _put_text(project, history_rel(spec), history_text(spec, with_oob=with_oob))
    if with_oob:
        _put_text(project, oob_rel(spec), oob_text(spec))
    if spec.uniform_colors:
        _put_text(project, COUNTRY_COLORS_REL, _colors_bytes(project, spec))
    for suffix, data in spec.flags.items():
        _put_bytes(project, flag_rel(spec.tag, suffix), data)
    texts = {spec.tag: dict(spec.name), f"{spec.tag}_ADJ": dict(spec.adjective or spec.name)}
    for party in spec.parties:
        texts.setdefault(party.name, dict(party.texts or {"en": party.name.split("_", 1)[-1].capitalize()}))
    if getattr(project, "loc", None) is not None:
        project.loc.ensure(texts, area=LOC_AREA)
    if spec.provinces:
        from .province import Provinces

        provinces = Provinces(project.entities, project.rules)
        date = None
        for pid in spec.provinces:
            provinces.set(pid, "owner", spec.tag, date)
            provinces.set(pid, "controller", spec.tag, date)
            if spec.cores:
                provinces.add_core(pid, spec.tag, date)


def create_new_country(project: Project, spec: NewCountrySpec) -> list[VPath]:
    """Crea el país en una transacción ``undo.new_country`` (un Ctrl+Z la deshace); devuelve los archivos tocados."""
    with project.ws.transaction(UNDO_NEW_COUNTRY, tag=spec.tag, name=spec.display_name()) as txn:
        build_new_country(project, spec)
        touched = list(txn.touched())
    _after_change(project)
    return touched


class _DryRun(Exception):
    pass


def _after_change(project: Project) -> None:
    loc = getattr(project, "loc", None)
    if loc is not None:
        loc.invalidate()


def dry_run(project: Project, key: str, build) -> ChangePlan:
    """``ChangePlan`` de lo que ``build()`` haría: lo ejecuta en una transacción que se revierte siempre."""
    from ..project.codecs import codec_for
    from ..validate.fixes import Edit, current, make_plan

    after: dict[str, tuple[VPath, bytes | None]] = {}
    try:
        with project.ws.transaction("undo.preview") as txn:
            build()
            for rel in txn.touched():
                handle = project.ws.peek(rel)
                if handle is None or handle.deleted:
                    after[rel.key] = (rel, None)
                else:
                    after[rel.key] = (handle.rel, codec_for(handle.kind).snapshot(handle.model))
            raise _DryRun
    except _DryRun:
        pass
    finally:
        _after_change(project)
    edits = [Edit(rel, current(project, rel), data) for rel, data in after.values()]
    edits.sort(key=lambda edit: str(edit.rel).lower())
    return make_plan(key, edits)


def plan_new_country(project: Project, spec: NewCountrySpec) -> ChangePlan:
    """Lo que ``create_new_country`` hará, sin cambiar nada (lanza ``CountryError`` si no se puede)."""
    check_spec(project, spec)
    return dry_run(project, "new_country", lambda: build_new_country(project, spec))
