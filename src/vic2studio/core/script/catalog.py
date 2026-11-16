"""Catálogo de guion: qué claves existen, dónde valen, qué valor llevan y cómo se leen (wizard §12.1).

Los datos son propios y viven en ``data/{triggers,effects,scopes}.json``: **solo** nombres de claves del
lenguaje de guion, tipos y frases ES/EN escritas para el Studio. Ningún texto, evento ni fragmento de los
archivos del juego (REGLAS §6). ``tools/catalog_census.py`` propone claves, recuentos y tipos a partir del
juego instalado del usuario; el JSON se depura a mano.

Formato de cada archivo (UTF-8 sin BOM): ``{"format": 1, "entries": [<entrada>, …]}``. Una entrada es un
objeto con estas claves (``ENTRY_KEYS``; ``entry_problems`` las comprueba):

- ``name`` **o** ``family``: una clave fija (``"year"``) o una familia de claves dinámicas (``"tech"``).
  Una familia lleva ``key_kind`` (el tipo de símbolo del índice cuyas definiciones son sus claves:
  ``"technology"``, ``"goods"``, ``"pop_type"``…) y/o ``pattern`` (una expresión regular que reconoce la
  clave sin índice: los TAG y los ids de provincia).
- ``role``: ``condition``, ``effect``, ``logic`` (``AND``/``OR``/``NOT`` y ``limit``), ``scope`` (cambia de
  ámbito a un único destino: ``capital_scope``, ``owner``, ``FRA = { }``) o ``iterator`` (cambia de ámbito y
  recorre varios: ``any_owned_province``, ``random_state``).
- ``kinds``: en qué bloques vale (``["condition"]``, ``["effect"]`` o los dos). Si falta, sale del papel
  (``condition`` y ``effect``); es obligatoria en ``logic``, ``scope`` e ``iterator``.
- ``scopes``: ámbitos en los que la clave vale (``["country"]``, ``["any"]``…). Obligatoria.
- ``value``: tipo del valor suelto, con la misma forma que ``core.schema.types.from_spec``
  (``{"type": "ref", "kind": "tag"}``). ``block``: campos de un bloque con estructura
  (``{"who": {"type": "ref", "kind": "tag"}, "value": {"type": "int"}}``; cada campo admite además
  ``"required": false``). Una clave puede llevar los dos (``country_event = 5`` y
  ``country_event = { id = 5 days = 3 }``). Solo en ``condition`` y ``effect``, que exigen al menos uno.
- ``scope_change``: ámbito de lo que contiene el bloque. Obligatoria en ``scope`` e ``iterator`` y prohibida
  en los demás. ``"any"``: no se sabe (``THIS``, ``FROM``).
- ``body``: tipo de guion de lo que contiene un grupo ``logic`` cuando no es el de fuera
  (``limit`` → ``"condition"`` dentro de efectos).
- ``category``: una de ``CATEGORIES`` (el buscador del constructor agrupa por ella). Obligatoria en
  ``condition`` y ``effect``.
- ``label``: ``{"es": …, "en": …}``, obligatoria. ``phrase``, ``negated`` y ``help``: opcionales, con la
  misma forma. Las plantillas admiten ``{value}``, los nombres de los campos de ``block`` y, en una
  familia, ``{key}`` (el nombre localizado de la clave); ES y EN usan los mismos huecos. ``negated`` es la
  frase dentro de un ``NOT`` o con el valor ``no``.

Dos entradas pueden compartir ``name`` si difieren en ``kinds`` o en ``scopes`` (``prestige`` es condición
y efecto; ``owner`` es condición de provincia con valor y cambio de ámbito con bloque).

Hechos de vanilla que fijan el diseño (censo de la iteración 7, eventos y decisiones): 277 palabras
distintas en condiciones y 232 en efectos, sin contar mayúsculas; las 80 y las 82 más usadas, junto con
los grupos lógicos, los TAG y los ids de provincia, cubren el 95 % de los usos (criterio 2). Familias con
usos: grupos de reformas (554), tecnologías (469), tipos de POP como ámbito de efectos (330), ideologías
(119), opciones de reforma (107), bienes (100), ids de provincia (119), TAG (89) y regiones como ámbito de
estado (33).
"""

from __future__ import annotations

import json
import re
import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from ..schema.fields import Field
from ..schema.types import ValueType, from_spec
from .scopes import Scope, ScriptKind, accepts

CATALOG_FORMAT = 1
DATA_FILES = ("triggers.json", "effects.json", "scopes.json")
LANGUAGES = ("es", "en")

# Categorías del buscador (wizard §14.7) más las de los grupos lógicos, los ámbitos y el resto.
CATEGORIES = ("country", "province", "time", "technology", "politics", "economy", "diplomacy", "population",
              "flags", "military", "events", "logic", "scope", "other")

ENTRY_KEYS = frozenset({"name", "family", "key_kind", "pattern", "role", "kinds", "scopes", "value", "block",
                        "body", "scope_change", "category", "label", "phrase", "negated", "help"})
_TEXT_KEYS = ("label", "phrase", "negated", "help")


class Role(Enum):
    """Papel de una clave: lo que decide cómo se ve en el constructor y en la frase."""

    CONDITION = "condition"
    EFFECT = "effect"
    LOGIC = "logic"
    SCOPE = "scope"
    ITERATOR = "iterator"


_SCRIPT_ROLES = (Role.LOGIC, Role.SCOPE, Role.ITERATOR)      # su bloque contiene más guion
_DEFAULT_KINDS = {Role.CONDITION: frozenset({ScriptKind.TRIGGER}), Role.EFFECT: frozenset({ScriptKind.EFFECT})}
_EMPTY: Mapping[str, str] = MappingProxyType({})


class CatalogError(ValueError):
    """Una entrada del catálogo no cumple el formato. ``.problems`` son las frases de ``entry_problems``."""

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


class SymbolSource(Protocol):
    """Lo que el catálogo necesita del índice para resolver las familias: lo cumple ``SymbolIndex``."""

    def exists(self, kind: str, name: str, *, ignore_case: bool = False) -> bool: ...

    def names(self, kind: str) -> list[str]: ...


@dataclass(frozen=True)
class ScriptKeyDef:
    """Una clave del catálogo, o una familia de claves dinámicas (``family``).

    ``name`` es la clave tal como se escribe al añadirla (``year``, ``AND``) o el nombre de la familia
    (``tech``). ``value``: tipo del valor suelto. ``block``: campos del bloque con estructura
    (``relation = { who value }``). ``scope_change``: ámbito de los hijos (``SCOPE``/``ITERATOR``). ``body``:
    tipo de guion de los hijos cuando cambia (``limit``). Los textos no cuentan al comparar ni en el hash.
    """

    name: str
    role: Role
    kinds: frozenset[ScriptKind]
    scopes: frozenset[Scope]
    value: ValueType | None = None
    block: tuple[Field, ...] | None = None
    scope_change: Scope | None = None
    body: ScriptKind | None = None
    category: str = "other"
    family: bool = False
    key_kind: str | None = None
    pattern: str | None = None
    label: Mapping[str, str] = field(default=_EMPTY, compare=False)
    phrase: Mapping[str, str] = field(default=_EMPTY, compare=False)
    negated: Mapping[str, str] = field(default=_EMPTY, compare=False)
    help: Mapping[str, str] = field(default=_EMPTY, compare=False)

    @property
    def has_script_body(self) -> bool:
        """True si su bloque contiene más guion (grupos lógicos, ámbitos e iteradores)."""
        return self.role in _SCRIPT_ROLES

    def accepts(self, scope: Scope) -> bool:
        """True si la clave vale en ``scope`` (``scopes.accepts``)."""
        return accepts(self.scopes, scope)

    def child_scope(self, scope: Scope) -> Scope:
        """Ámbito de los hijos de un nodo con esta definición que está en ``scope``."""
        return scope if self.scope_change is None else self.scope_change

    def child_kind(self, kind: ScriptKind) -> ScriptKind:
        """Tipo de guion de los hijos de un nodo con esta definición dentro de un bloque ``kind``."""
        return kind if self.body is None else self.body

    def matches(self, key: str) -> bool:
        """Solo familias con ``pattern``: True si ``key`` tiene la forma de sus claves (sin índice)."""
        return self.pattern is not None and re.fullmatch(self.pattern, key) is not None


def _text_problems(entry: Mapping, key: str, allowed: frozenset[str]) -> list[str]:
    texts = entry[key]
    if not isinstance(texts, Mapping) or set(texts) != set(LANGUAGES) \
            or not all(isinstance(texts[lang], str) and texts[lang].strip() for lang in LANGUAGES):
        return [f"{key}: se espera un texto no vacío en cada idioma de {LANGUAGES}"]
    try:
        holes = [{name for _, name, _, _ in string.Formatter().parse(texts[lang]) if name is not None}
                 for lang in LANGUAGES]
    except ValueError as exc:
        return [f"{key}: plantilla mal formada ({exc})"]
    problems = []
    if holes[0] != holes[1]:
        problems.append(f"{key}: los huecos no coinciden entre idiomas ({sorted(holes[0])} y {sorted(holes[1])})")
    unknown = sorted((holes[0] | holes[1]) - allowed)
    if unknown and key != "help":
        problems.append(f"{key}: huecos desconocidos {unknown}")
    return problems


def _enum_list(entry: Mapping, key: str, enum: type[Enum]) -> tuple[list, list[str]]:
    raw = entry.get(key)
    if not isinstance(raw, list) or not raw:
        return [], [f"{key}: se espera una lista no vacía"]
    try:
        return [enum(item) for item in raw], []
    except ValueError:
        return [], [f"{key}: valores desconocidos en {raw!r}"]


def _block_fields(block: Mapping) -> tuple[Field, ...]:
    """Campos de ``block``; ``ValueError`` si un tipo no es válido."""
    fields = []
    for key, spec in block.items():
        if not isinstance(key, str) or not key or not isinstance(spec, Mapping):
            raise ValueError(f"campo de bloque inválido: {key!r}")
        spec = dict(spec)
        required = spec.pop("required", True)
        if not isinstance(required, bool):
            raise ValueError(f"{key}: «required» debe ser true o false")
        fields.append(Field(key, from_spec(spec), required=required))
    return tuple(fields)


def entry_problems(entry: object) -> list[str]:
    """Lo que incumple ``entry`` del formato de ``data/*.json`` (ver el docstring del módulo); vacía si
    es válida. Es el esquema de validación de las entradas: lo usan ``ScriptCatalog.load``, la prueba de los
    datos y el catálogo falso de las pruebas."""
    if not isinstance(entry, Mapping):
        return ["la entrada no es un objeto"]
    problems = [f"clave desconocida: {key}" for key in sorted(set(entry) - ENTRY_KEYS, key=str)]
    named = [key for key in ("name", "family") if key in entry]
    if len(named) != 1 or not isinstance(entry[named[0]], str) or not entry[named[0]]:
        problems.append("se espera «name» o «family» (uno solo, no vacío)")
    is_family = named == ["family"]
    if is_family and not ("key_kind" in entry or "pattern" in entry):
        problems.append("una familia necesita «key_kind» o «pattern»")
    if not is_family and ("key_kind" in entry or "pattern" in entry):
        problems.append("«key_kind» y «pattern» solo valen en una familia")
    if "key_kind" in entry and (not isinstance(entry["key_kind"], str) or not entry["key_kind"]):
        problems.append("key_kind: se espera un tipo de símbolo del índice")
    if "pattern" in entry:
        try:
            re.compile(entry["pattern"])
        except (re.error, TypeError):
            problems.append("pattern: expresión regular inválida")
    try:
        role = Role(entry.get("role"))
    except ValueError:
        return problems + ["role: se espera uno de " + ", ".join(r.value for r in Role)]
    script_role = role in _SCRIPT_ROLES
    if "kinds" in entry or script_role:
        problems += _enum_list(entry, "kinds", ScriptKind)[1]
    problems += _enum_list(entry, "scopes", Scope)[1]
    if script_role != ("scope_change" in entry) and role is not Role.LOGIC:
        problems.append("scope_change: obligatoria en scope e iterator y prohibida en los demás papeles")
    if "scope_change" in entry:
        if role is Role.LOGIC:
            problems.append("scope_change: un grupo lógico no cambia de ámbito")
        try:
            Scope(entry["scope_change"])
        except ValueError:
            problems.append(f"scope_change: ámbito desconocido {entry['scope_change']!r}")
    if "body" in entry:
        if role is not Role.LOGIC:
            problems.append("body: solo vale en un grupo lógico")
        try:
            ScriptKind(entry["body"])
        except ValueError:
            problems.append(f"body: tipo de guion desconocido {entry['body']!r}")
    holes = {"value"} | ({"key"} if is_family else set())
    if script_role:
        if "value" in entry or "block" in entry:
            problems.append("value/block: un grupo, un ámbito o un iterador contienen guion, no un valor")
    else:
        if "value" not in entry and "block" not in entry:
            problems.append("una condición o un efecto necesitan «value» o «block»")
        if entry.get("category") not in CATEGORIES:
            problems.append("category: se espera una de " + ", ".join(CATEGORIES))
        if "value" in entry:
            try:
                from_spec(entry["value"])
            except ValueError as exc:
                problems.append(f"value: {exc}")
        if "block" in entry:
            block = entry["block"]
            if not isinstance(block, Mapping) or not block:
                problems.append("block: se espera un objeto no vacío de campos")
            else:
                try:
                    _block_fields(block)
                except ValueError as exc:
                    problems.append(f"block: {exc}")
                holes |= {key for key in block if isinstance(key, str)}
    if "category" in entry and entry["category"] not in CATEGORIES and script_role:
        problems.append("category: se espera una de " + ", ".join(CATEGORIES))
    if "label" not in entry:
        problems.append("label: obligatoria en ES y EN")
    for key in _TEXT_KEYS:
        if key in entry:
            problems += _text_problems(entry, key, frozenset(holes))
    return problems


def definition_from_entry(entry: Mapping) -> ScriptKeyDef:
    """``ScriptKeyDef`` de una entrada válida; ``CatalogError`` con sus problemas si no lo es."""
    problems = entry_problems(entry)
    if problems:
        raise CatalogError(problems)
    role = Role(entry["role"])
    is_family = "family" in entry
    kinds = frozenset(ScriptKind(k) for k in entry["kinds"]) if "kinds" in entry else _DEFAULT_KINDS[role]
    category = entry.get("category") or ("logic" if role is Role.LOGIC else "scope")
    return ScriptKeyDef(
        name=entry["family"] if is_family else entry["name"],
        role=role,
        kinds=kinds,
        scopes=frozenset(Scope(s) for s in entry["scopes"]),
        value=from_spec(entry["value"]) if "value" in entry else None,
        block=_block_fields(entry["block"]) if "block" in entry else None,
        scope_change=Scope(entry["scope_change"]) if "scope_change" in entry else None,
        body=ScriptKind(entry["body"]) if "body" in entry else None,
        category=category,
        family=is_family,
        key_kind=entry.get("key_kind"),
        pattern=entry.get("pattern"),
        **{key: MappingProxyType(dict(entry[key])) for key in _TEXT_KEYS if key in entry},
    )


class ScriptCatalog:
    """El catálogo cargado: búsqueda de una clave leída y sugerencias para el buscador.

    ``load()`` lee los tres JSON una sola vez (son inmutables y se comparten entre hilos). Las familias con
    ``key_kind`` necesitan saber qué símbolos existen: ``with_symbols(index)`` da una vista del mismo
    catálogo ligada a un índice. Sin símbolos solo se resuelven las familias con ``pattern`` (TAG e ids de
    provincia); el resto de claves dinámicas no se reconoce y el árbol las deja como nodos crudos.
    """

    def __init__(self, definitions: Iterable[ScriptKeyDef] = (), *, symbols: SymbolSource | None = None) -> None:
        self._definitions = tuple(definitions)
        self.symbols = symbols
        fixed: dict[str, list[ScriptKeyDef]] = {}
        by_name: dict[str, list[ScriptKeyDef]] = {}
        for definition in self._definitions:
            by_name.setdefault(definition.name.lower(), []).append(definition)
            if not definition.family:
                fixed.setdefault(definition.name.lower(), []).append(definition)
        self._fixed = fixed
        self._by_name = by_name
        self._families = tuple(d for d in self._definitions if d.family)

    @classmethod
    def load(cls) -> ScriptCatalog:
        """El catálogo de ``data/*.json`` (en caché). ``CatalogError`` si una entrada no cumple el formato
        o el archivo no declara ``CATALOG_FORMAT``."""
        global _LOADED
        if _LOADED is None:
            entries = []
            for name in DATA_FILES:
                path = DATA_DIR / name
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, Mapping) or data.get("format") != CATALOG_FORMAT \
                        or not isinstance(data.get("entries"), list):
                    raise CatalogError([f"{name}: se espera {{\"format\": {CATALOG_FORMAT}, \"entries\": [...]}}"])
                for position, entry in enumerate(data["entries"]):
                    problems = entry_problems(entry)
                    if problems:
                        raise CatalogError([f"{name}[{position}]: {problem}" for problem in problems])
                    entries.append(entry)
            _LOADED = cls.from_entries(entries)
        return _LOADED

    @classmethod
    def from_entries(cls, entries: Iterable[Mapping]) -> ScriptCatalog:
        """Un catálogo a partir de entradas ya leídas (pruebas, ``tools/catalog_census.py``)."""
        return cls(definition_from_entry(entry) for entry in entries)

    def with_symbols(self, symbols: SymbolSource | None) -> ScriptCatalog:
        """El mismo catálogo resolviendo las familias contra ``symbols`` (el ``SymbolIndex``). No copia las
        definiciones. ``None`` vuelve al catálogo sin símbolos."""
        view = object.__new__(type(self))
        view.__dict__.update(self.__dict__)
        view.symbols = symbols
        return view

    def definitions(self, name: str | None = None) -> tuple[ScriptKeyDef, ...]:
        """Todas las definiciones en el orden de los archivos; con ``name``, las de esa clave (sin distinguir
        mayúsculas; las familias se buscan por su nombre de familia)."""
        if name is None:
            return self._definitions
        return tuple(self._by_name.get(name.lower(), ()))

    def _family_matches(self, definition: ScriptKeyDef, name: str) -> bool:
        if definition.matches(name):
            return True
        if definition.key_kind is None or self.symbols is None:
            return False
        try:
            return bool(self.symbols.exists(definition.key_kind, name, ignore_case=True))
        except Exception:  # noqa: BLE001 - un índice a medias no debe romper el árbol
            return False

    def lookup(self, name: str, kind: ScriptKind, scope: Scope | None = None, *,
               block: bool | None = None) -> ScriptKeyDef | None:
        """La definición de la clave leída ``name`` dentro de un bloque ``kind``; None si el catálogo no la
        conoce (nodo crudo). No distingue mayúsculas (``and``, ``Prestige``).

        Primero las claves fijas y después las familias: por ``pattern`` y, con símbolos, por ``key_kind``.
        Entre varias candidatas gana la que vale en ``scope`` y cuya forma encaja con ``block`` (True: el
        valor leído es un bloque; False: un valor suelto; None: da igual). Si ninguna vale en ``scope``, se
        devuelve la primera igualmente: quien llama compara con ``definition.accepts(scope)`` y avisa con
        ``scope_mismatch``. ``scope=None`` no filtra por ámbito.
        """
        kind = ScriptKind(kind)
        candidates = [d for d in self._fixed.get(name.lower(), ()) if kind in d.kinds]
        if not candidates:
            candidates = [d for d in self._families if kind in d.kinds and self._family_matches(d, name)]
        if not candidates:
            return None
        best, best_score = None, None
        for definition in candidates:
            score = (scope is None or definition.accepts(scope), _fits(definition, block))
            if best_score is None or score > best_score:
                best, best_score = definition, score
        return best

    def suggestions(self, kind: ScriptKind, scope: Scope, text: str = "", lang: str = "es", *,
                    roles: Iterable[Role] | None = None, limit: int | None = None) -> list[ScriptKeyDef]:
        """Lo que se puede añadir a un bloque ``kind`` en ``scope``: las definiciones que valen ahí cuyo
        nombre o etiqueta en ``lang`` contienen ``text`` (sin acentos ni mayúsculas, ``index.model.fold``).

        Orden: las que empiezan por ``text``, después el resto; a igualdad, el orden de ``CATEGORIES`` y la
        etiqueta. Las familias salen una vez cada una (sus claves las da ``family_keys``). ``roles`` limita
        los papeles («+ Condición», «+ Ámbito»). ``text`` vacío las da todas.
        """
        from ..index.model import fold

        kind, wanted = ScriptKind(kind), None if roles is None else frozenset(roles)
        needle = fold(text or "")
        found = []
        for definition in self._definitions:
            if kind not in definition.kinds or not definition.accepts(scope):
                continue
            if wanted is not None and definition.role not in wanted:
                continue
            name = fold(definition.name)
            label = fold(definition.label.get(lang) or definition.label.get("en", "") or "")
            if needle and needle not in name and needle not in label:
                continue
            starts = bool(needle) and (name.startswith(needle) or label.startswith(needle))
            category = CATEGORIES.index(definition.category) if definition.category in CATEGORIES else len(CATEGORIES)
            found.append(((not starts, category, label, name), definition))
        found.sort(key=lambda pair: pair[0])
        result = [definition for _, definition in found]
        return result if limit is None else result[:limit]

    def categories(self, kind: ScriptKind, scope: Scope) -> list[str]:
        """Las categorías con alguna sugerencia para ``kind`` y ``scope``, en el orden de ``CATEGORIES``."""
        present = {definition.category for definition in self.suggestions(kind, scope)}
        return [category for category in CATEGORIES if category in present]

    def family_keys(self, definition: ScriptKeyDef, text: str = "", *, limit: int | None = None) -> list[str]:
        """Claves concretas de una familia con ``key_kind`` (los símbolos del índice que contienen ``text``),
        ordenadas. Sin símbolos, o en una familia solo con ``pattern``, lista vacía."""
        from ..index.model import fold

        if self.symbols is None or definition.key_kind is None:
            return []
        needle = fold(text or "")
        try:
            names = self.symbols.names(definition.key_kind)
        except Exception:  # noqa: BLE001
            return []
        result = sorted(name for name in names if needle in fold(name))
        return result if limit is None else result[:limit]


_LOADED: ScriptCatalog | None = None
DATA_DIR = Path(__file__).resolve().parent / "data"


def _fits(definition: ScriptKeyDef, block: bool | None) -> bool:
    """True si la forma del valor leído (bloque o suelto) encaja con la definición."""
    if block is None:
        return True
    if block:
        return definition.has_script_body or definition.block is not None
    return definition.value is not None
