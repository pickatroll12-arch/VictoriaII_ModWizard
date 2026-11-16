"""Catálogo y árbol de guion falsos para las pruebas de la interfaz de la iteración 7 (wizard §20).

La cadena B construye ``ui/script/**`` contra estos falsos antes de la integración; siguen las firmas del
contrato (``tests/test_contract_it7.py`` lo comprueba método a método) y, cuando el núcleo esté, se cambian por
los reales con ``catalog_class()`` y ``tree_class()``, que eligen solos:

- ``FAKE_ENTRIES``: 20 entradas con el formato de ``core/script/data/*.json`` (``entry_problems`` las da por
  válidas). Tres grupos lógicos y ``limit``, seis condiciones, cuatro efectos, tres ámbitos (uno iterador) y
  tres familias: TAG y provincia por patrón y tecnología por símbolo del índice. Todo inventado: solo nombres
  de claves, tipos y frases propias.
- ``FakeCatalog``: la API pública de ``ScriptCatalog`` con búsquedas lineales.
- ``FakeScriptTree`` y ``FakeScriptNode``: la API de ``ScriptTree`` y ``ScriptNode`` sobre el CST real, así que
  las ediciones conservan el resto del texto de verdad.

Límites de los falsos (lo que solo da el núcleo real): ``issues`` solo avisa de claves desconocidas y de
ámbitos incorrectos (no comprueba valores ni referencias); ``summary`` y ``fake_phrase_lines`` rellenan la
plantilla del catálogo sin localizar nombres ni conjugar; ``source()`` de la raíz une sus entradas con saltos
de línea; ``add_child`` exige el valor de una clave desconocida; no se valida un ``STRUCT`` más allá de sus
campos.

Lo que el catálogo falso **no** conoce a propósito, para que haya nodos crudos en el minijuego
(``_minigame.SCRIPT_GAME_FILES``): ``set_country_flag``, ``has_country_flag``, ``government`` como efecto y
``mg_made_up_check``. ``musket_drill`` solo se reconoce con símbolos (familia ``tech``).
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import types
from collections.abc import Callable, Iterable, Iterator, Mapping
from types import SimpleNamespace

from vic2studio.core.clausewitz import Block, Entry, Scalar, Severity, parse, to_source
from vic2studio.core.index.model import fold
from vic2studio.core.schema.fields import Field
from vic2studio.core.script import catalog as real_catalog
from vic2studio.core.script import tree as real_tree
from vic2studio.core.script.catalog import CATEGORIES, Role, ScriptKeyDef, SymbolSource, definition_from_entry
from vic2studio.core.script.phrases import PhraseLine
from vic2studio.core.script.scopes import LOGIC_KEYS, Scope, ScriptKind
from vic2studio.core.script.tree import SCOPE_MISMATCH, SCRIPT_UNKNOWN_KEY, NodeForm, ScriptSyntaxError
from vic2studio.core.validate.model import Problem

_BOTH = ["condition", "effect"]
_TAG = {"type": "ref", "kind": "tag"}

FAKE_ENTRIES: tuple[dict, ...] = (
    {"name": "AND", "role": "logic", "kinds": _BOTH, "scopes": ["any"],
     "label": {"es": "Todas se cumplen", "en": "All of these"}},
    {"name": "OR", "role": "logic", "kinds": _BOTH, "scopes": ["any"],
     "label": {"es": "Alguna se cumple", "en": "Any of these"}},
    {"name": "NOT", "role": "logic", "kinds": _BOTH, "scopes": ["any"],
     "label": {"es": "Ninguna se cumple", "en": "None of these"}},
    {"name": "limit", "role": "logic", "kinds": ["effect"], "scopes": ["any"], "body": "condition",
     "label": {"es": "Solo donde…", "en": "Only where…"}},
    {"name": "tag", "role": "condition", "scopes": ["country"], "value": _TAG, "category": "country",
     "label": {"es": "Es el país", "en": "Is the country"},
     "phrase": {"es": "el país es {value}", "en": "the country is {value}"},
     "negated": {"es": "el país no es {value}", "en": "the country is not {value}"}},
    {"name": "year", "role": "condition", "scopes": ["any"], "value": {"type": "int"}, "category": "time",
     "label": {"es": "Año", "en": "Year"},
     "phrase": {"es": "es {value} o después", "en": "it is {value} or later"},
     "negated": {"es": "es antes de {value}", "en": "it is before {value}"},
     "help": {"es": "Se cumple desde el 1 de enero de ese año.", "en": "True from January 1st of that year."}},
    {"name": "government", "role": "condition", "scopes": ["country"],
     "value": {"type": "ref", "kind": "government"}, "category": "politics",
     "label": {"es": "Forma de gobierno", "en": "Government type"},
     "phrase": {"es": "su gobierno es {value}", "en": "its government is {value}"}},
    {"name": "prestige", "role": "condition", "scopes": ["country"], "value": {"type": "float"},
     "category": "country", "label": {"es": "Prestigio mínimo", "en": "Prestige at least"},
     "phrase": {"es": "tiene {value} de prestigio o más", "en": "it has {value} prestige or more"}},
    {"name": "is_greater_power", "role": "condition", "scopes": ["country"], "value": {"type": "bool"},
     "category": "diplomacy", "label": {"es": "Es gran potencia", "en": "Is a great power"},
     "phrase": {"es": "es una gran potencia", "en": "it is a great power"},
     "negated": {"es": "no es una gran potencia", "en": "it is not a great power"}},
    {"name": "owned_by", "role": "condition", "scopes": ["province"], "value": _TAG, "category": "province",
     "label": {"es": "Pertenece a", "en": "Owned by"},
     "phrase": {"es": "la provincia es de {value}", "en": "the province belongs to {value}"}},
    {"name": "relation", "role": "effect", "scopes": ["country"], "category": "diplomacy",
     "block": {"who": _TAG, "value": {"type": "int"}},
     "label": {"es": "Cambiar relaciones", "en": "Change relations"},
     "phrase": {"es": "las relaciones con {who} cambian en {value}", "en": "relations with {who} change by {value}"}},
    {"name": "prestige", "role": "effect", "scopes": ["country"], "value": {"type": "float"}, "category": "country",
     "label": {"es": "Dar prestigio", "en": "Give prestige"},
     "phrase": {"es": "gana {value} de prestigio", "en": "gains {value} prestige"}},
    {"name": "country_event", "role": "effect", "scopes": ["country"], "category": "events",
     "value": {"type": "int"}, "block": {"id": {"type": "int"}, "days": {"type": "int", "required": False}},
     "label": {"es": "Lanzar evento de país", "en": "Fire country event"},
     "phrase": {"es": "ocurre el evento {value}", "en": "event {value} happens"}},
    {"name": "add_core", "role": "effect", "scopes": ["province"], "value": _TAG, "category": "province",
     "label": {"es": "Añadir reclamación", "en": "Add core"},
     "phrase": {"es": "{value} reclama la provincia", "en": "{value} gets a core on the province"}},
    {"name": "capital_scope", "role": "scope", "kinds": _BOTH, "scopes": ["country"], "scope_change": "province",
     "label": {"es": "En la capital", "en": "In the capital"}},
    {"name": "any_owned", "role": "iterator", "kinds": ["effect"], "scopes": ["country"],
     "scope_change": "province", "label": {"es": "En cada provincia propia", "en": "In every owned province"}},
    {"name": "owner", "role": "scope", "kinds": _BOTH, "scopes": ["province"], "scope_change": "country",
     "label": {"es": "El dueño", "en": "The owner"}},
    {"family": "tag_scope", "pattern": "[A-Z][A-Z0-9]{2}", "role": "scope", "kinds": _BOTH, "scopes": ["any"],
     "scope_change": "country", "label": {"es": "El país {key}", "en": "The country {key}"}},
    {"family": "province_scope", "pattern": "[0-9]+", "role": "scope", "kinds": _BOTH, "scopes": ["any"],
     "scope_change": "province", "label": {"es": "La provincia {key}", "en": "Province {key}"}},
    {"family": "tech", "key_kind": "technology", "role": "condition", "scopes": ["country"],
     "value": {"type": "int"}, "category": "technology",
     "label": {"es": "Tecnología {key}", "en": "Technology {key}"},
     "phrase": {"es": "ha investigado {key}", "en": "it has researched {key}"}},
)

# Bloques de muestra (inventados) para las pruebas que no necesitan el minijuego.
SAMPLE_TRIGGER = ("OR = {\n\ttag = AAA\n\ttag = BBB\n}\nyear = 1842 # desde ese año\n"
                  "NOT = { year = 1845 }\nmg_made_up_check = 3\n")
SAMPLE_EFFECT = ("prestige = 5\nany_owned = {\n\tlimit = { owned_by = AAA }\n\tadd_core = BBB\n}\n"
                 "BBB = { relation = { who = AAA value = 50 } }\ncountry_event = { id = 2003 days = 3 }\n")


class FakeSymbols:
    """``SymbolSource`` mínimo: ``FakeSymbols(technology=["musket_drill"])``."""

    def __init__(self, **names: Iterable[str]) -> None:
        self._names = {kind: sorted(values) for kind, values in names.items()}

    def exists(self, kind: str, name: str, *, ignore_case: bool = False) -> bool:
        names = self._names.get(kind, [])
        return name in names or (ignore_case and name.lower() in {n.lower() for n in names})

    def names(self, kind: str) -> list[str]:
        return list(self._names.get(kind, []))


def fake_definitions() -> tuple[ScriptKeyDef, ...]:
    return tuple(definition_from_entry(entry) for entry in FAKE_ENTRIES)


def _fits(definition: ScriptKeyDef, block: bool | None) -> bool:
    if block is None:
        return True
    if block:
        return definition.has_script_body or definition.block is not None
    return definition.value is not None


class FakeCatalog:
    """La API de ``ScriptCatalog`` sobre una lista. ``load()`` da las 20 entradas de ``FAKE_ENTRIES``."""

    def __init__(self, definitions: Iterable[ScriptKeyDef] = (), *, symbols: SymbolSource | None = None) -> None:
        self._definitions = tuple(definitions)
        self.symbols = symbols

    @classmethod
    def load(cls) -> FakeCatalog:
        return cls(fake_definitions())

    @classmethod
    def from_entries(cls, entries: Iterable[Mapping]) -> FakeCatalog:
        return cls(definition_from_entry(entry) for entry in entries)

    def with_symbols(self, symbols: SymbolSource | None) -> FakeCatalog:
        return type(self)(self._definitions, symbols=symbols)

    def definitions(self, name: str | None = None) -> tuple[ScriptKeyDef, ...]:
        if name is None:
            return self._definitions
        return tuple(d for d in self._definitions if d.name.lower() == name.lower())

    def _candidates(self, name: str, kind: ScriptKind) -> list[ScriptKeyDef]:
        usable = [d for d in self._definitions if kind in d.kinds]
        found = [d for d in usable if not d.family and d.name.lower() == name.lower()]
        found += [d for d in usable if d.family and d.matches(name)]
        if self.symbols is not None:
            found += [d for d in usable if d.family and d.key_kind is not None
                      and self.symbols.exists(d.key_kind, name)]
        return found

    def lookup(self, name: str, kind: ScriptKind, scope: Scope | None = None, *,
               block: bool | None = None) -> ScriptKeyDef | None:
        candidates = self._candidates(name, ScriptKind(kind))
        if not candidates:
            return None
        # max() devuelve la primera de las mejores: la que vale en el ámbito y, entre esas, la que encaja.
        return max(candidates, key=lambda d: (scope is None or d.accepts(scope), _fits(d, block)))

    def suggestions(self, kind: ScriptKind, scope: Scope, text: str = "", lang: str = "es", *,
                    roles: Iterable[Role] | None = None, limit: int | None = None) -> list[ScriptKeyDef]:
        wanted = None if roles is None else frozenset(roles)
        needle = fold(text)
        found = []
        for definition in self._definitions:
            if kind not in definition.kinds or not definition.accepts(scope):
                continue
            if wanted is not None and definition.role not in wanted:
                continue
            name, label = fold(definition.name), fold(definition.label.get(lang, ""))
            if needle and needle not in name and needle not in label:
                continue
            starts = name.startswith(needle) or label.startswith(needle)
            found.append(((not starts, CATEGORIES.index(definition.category), label), definition))
        found.sort(key=lambda pair: pair[0])
        return [definition for _, definition in found][:limit]

    def categories(self, kind: ScriptKind, scope: Scope) -> list[str]:
        present = {definition.category for definition in self.suggestions(kind, scope)}
        return [category for category in CATEGORIES if category in present]

    def family_keys(self, definition: ScriptKeyDef, text: str = "", *, limit: int | None = None) -> list[str]:
        if self.symbols is None or definition.key_kind is None:
            return []
        needle = fold(text)
        return sorted(name for name in self.symbols.names(definition.key_kind) if needle in fold(name))[:limit]


class FakeScriptNode:
    """La API de ``ScriptNode`` sobre una ``Entry`` real (ver los límites en el docstring del módulo)."""

    def __init__(self, tree: FakeScriptTree, entry: Entry | None, parent: FakeScriptNode | None) -> None:
        self.tree = tree
        self.entry = entry
        self.parent = parent
        self.definition: ScriptKeyDef | None = None
        self.kind = tree.kind
        self.scope = tree.scope
        self.children: list[FakeScriptNode] = []

    # --- lectura ------------------------------------------------------------------------------------

    @property
    def key(self) -> str:
        return "" if self.entry is None or self.entry.key is None else self.entry.key.text

    @property
    def raw(self) -> bool:
        return self.entry is not None and self.definition is None

    @property
    def form(self) -> NodeForm:
        if self.entry is None:
            return NodeForm.GROUP
        definition, is_block = self.definition, isinstance(self.entry.value, Block)
        if definition is None:
            return NodeForm.RAW
        if definition.has_script_body:
            if not is_block:
                return NodeForm.RAW
            return NodeForm.GROUP if definition.role is Role.LOGIC else NodeForm.SCOPE
        if is_block:
            return NodeForm.STRUCT if definition.block is not None else NodeForm.RAW
        return NodeForm.VALUE if definition.value is not None else NodeForm.RAW

    @property
    def logic(self) -> str | None:
        if self.entry is None:
            return "AND"
        if self.form is NodeForm.GROUP and self.key.upper() in LOGIC_KEYS:
            return self.key.upper()
        return None

    @property
    def inner_kind(self) -> ScriptKind:
        return self.kind if self.definition is None else self.definition.child_kind(self.kind)

    @property
    def inner_scope(self) -> Scope:
        if self.entry is None:
            return self.scope
        if self.definition is None:
            return Scope.ANY if isinstance(self.entry.value, Block) else self.scope
        return self.definition.child_scope(self.scope)

    @property
    def path(self) -> tuple[int, ...]:
        if self.parent is None:
            return ()
        return (*self.parent.path, self.parent.children.index(self))

    @property
    def value(self) -> object:
        form = self.form
        if form is NodeForm.VALUE:
            try:
                return self.definition.value.read(self.entry.value)
            except ValueError:
                return self.entry.value.text
        if form is NodeForm.STRUCT:
            return {field.key: field.type.read(self.entry.value.get(field.key))
                    for field in self.definition.block if self.entry.value.has(field.key)}
        if form is NodeForm.RAW and isinstance(self.entry.value, Scalar):
            return self.entry.value.text
        return None

    def source(self) -> str:
        if self.entry is None:
            return "\n".join(to_source(child.entry) for child in self.children)
        return to_source(self.entry)

    # --- edición ------------------------------------------------------------------------------------

    def _block(self) -> Block:
        if self.form not in (NodeForm.GROUP, NodeForm.SCOPE):
            raise ValueError(f"«{self.key}» no admite hijos")
        return self.tree.block if self.entry is None else self.entry.value

    def _own(self) -> Entry:
        if self.entry is None:
            raise ValueError("la raíz no se puede quitar, mover ni envolver")
        return self.entry

    def _field(self, key: str) -> Field:
        for field in self.definition.block:
            if field.key == key:
                return field
        raise ValueError(f"«{self.key}» no tiene el campo «{key}»")

    def set_value(self, value: object) -> None:
        form, entry = self.form, self.entry
        if form is NodeForm.VALUE:
            written = self.definition.value.write(value, entry.value)
        elif form is NodeForm.STRUCT:
            if not isinstance(value, Mapping):
                raise ValueError("se esperaba un dict con los campos que cambian")
            written = [(key, None if item is None else self._field(key).type.write(item, entry.value.get(key)))
                       for key, item in value.items()]
            if any(item is None and self._field(key).required for key, item in written):
                raise ValueError("no se puede quitar un campo obligatorio")
        elif form is NodeForm.RAW and isinstance(entry.value, Scalar) and isinstance(value, str):
            written = value
        else:
            raise ValueError(f"«{self.key}» no lleva un valor editable")
        self.tree._touch()
        if form is NodeForm.STRUCT:
            for key, item in written:
                if item is None:
                    entry.value.remove(key)
                else:
                    entry.value.set(key, item)
        else:
            entry.value = written
        self.tree._changed()

    def _initial(self, definition: ScriptKeyDef | None, value: object) -> object:
        ctx = SimpleNamespace(index=self.tree.catalog.symbols)
        if definition is None:
            if not isinstance(value, str):
                raise ValueError("una clave no catalogada necesita su valor como texto")
            return value
        if definition.has_script_body:
            return Block()
        if isinstance(value, Mapping) or (value is None and definition.value is None):
            given = dict(value or {})
            pairs = [(field.key, field.type.write(given.get(field.key, field.type.example(ctx)), None))
                     for field in definition.block if field.required or field.key in given]
            return Block.from_pairs(pairs)
        return definition.value.write(definition.value.example(ctx) if value is None else value, None)

    def add_child(self, name: str, value: object = None, *, index: int | None = None) -> FakeScriptNode:
        block = self._block()
        wants_block = None if value is None else isinstance(value, Mapping)
        definition = self.tree.catalog.lookup(name, self.inner_kind, self.inner_scope, block=wants_block)
        initial = self._initial(definition, value)
        self.tree._touch()
        position = len(self.children) if index is None else index
        anchor = self.children[position].entry if position < len(self.children) else None
        entry = block.append(name, initial) if anchor is None else block.insert_before(anchor, name, initial)
        self.tree._changed()
        return self.tree.node_of(entry)

    def wrap(self, op: str = "OR") -> FakeScriptNode:
        entry, block = self._own(), self.parent._block()
        if op not in LOGIC_KEYS:
            raise ValueError(f"grupo desconocido: {op}")
        self.tree._touch()
        group = block.insert_before(entry, op, Block())
        block.move(entry, to=group.value)
        self.tree._changed()
        return self.tree.node_of(group)

    def unwrap(self) -> None:
        entry = self._own()
        if self.logic is None:
            raise ValueError(f"«{self.key}» no es un grupo lógico")
        block = self.parent._block()
        self.tree._touch()
        position = block.entries.index(entry)
        for offset, child in enumerate(list(entry.value.entries)):
            entry.value.move(child, position + offset, to=block)
        block.remove_entry(entry)
        self.tree._changed()

    def remove(self) -> None:
        entry, block = self._own(), self.parent._block()
        self.tree._touch()
        block.remove_entry(entry)
        self.tree._changed()

    def move(self, index: int, *, to: FakeScriptNode | None = None) -> None:
        entry, target = self._own(), self.parent if to is None else to
        probe = target
        while probe is not None:
            if probe is self:
                raise ValueError("un nodo no se mueve dentro de sí mismo")
            probe = probe.parent
        source, block = self.parent._block(), target._block()
        siblings = [child.entry for child in target.children if child is not self]
        self.tree._touch()
        source.remove_entry(entry)
        position = block.entries.index(siblings[index]) if index < len(siblings) else len(block.entries)
        block.insert_entry(position, entry)
        self.tree._changed()

    def replace_source(self, text: str) -> list[FakeScriptNode]:
        result = parse(text)
        errors = [d for d in result.diagnostics if d.severity is Severity.ERROR]
        if errors:
            raise ScriptSyntaxError(errors)
        new = [entry.clone() for entry in result.document.entries]
        self.tree._touch()
        if self.entry is None:
            for child in self.children:
                self.tree.block.remove_entry(child.entry)
            for entry in new:
                self.tree.block.insert_entry(len(self.tree.block.entries), entry)
        else:
            block = self.parent._block()
            position = block.remove_entry(self.entry)
            for offset, entry in enumerate(new):
                block.insert_entry(position + offset, entry)
        self.tree._changed()
        return [self.tree.node_of(entry) for entry in new]

    # --- problemas y frases -------------------------------------------------------------------------

    def issues(self, ctx=None) -> list[Problem]:
        if self.entry is None:
            return []
        if self.definition is None:
            return [Problem(SCRIPT_UNKNOWN_KEY, Severity.INFO, None, self.entry.line, self.entry.column,
                            args={"key": self.key})]
        if not self.definition.accepts(self.scope):
            return [Problem(SCOPE_MISMATCH, Severity.WARNING, None, self.entry.line, self.entry.column,
                            args={"key": self.key, "scope": str(self.scope)})]
        return []

    def summary(self, lang: str, index=None, loc=None) -> str:
        if self.entry is None or self.form in (NodeForm.GROUP, NodeForm.SCOPE):
            head = "" if self.entry is None else self._label(lang) + ": "
            return head + "; ".join(child.summary(lang, index, loc) for child in self.children)
        if self.form is NodeForm.RAW:
            return to_source(self.entry).strip()
        template = self.definition.phrase.get(lang) or self._label(lang) + " {value}"
        holes = self.value if isinstance(self.value, Mapping) else {"value": self.value}
        try:
            return template.format(key=self.key, **holes)
        except KeyError:
            return self._label(lang)

    def _label(self, lang: str) -> str:
        if self.definition is None:
            return self.key
        return self.definition.label[lang].format(key=self.key)


class FakeScriptTree:
    """La API de ``ScriptTree`` sobre un ``Block`` real, con un nodo por entrada (se conservan entre
    ediciones: los nodos de las entradas que siguen en el árbol son los mismos objetos)."""

    def __init__(self, block: Block, kind: ScriptKind, scope: Scope, catalog, *,
                 skip: Iterable[str] = (), touch: Callable[[], None] | None = None) -> None:
        self.block = block
        self.kind = ScriptKind(kind)
        self.scope = Scope(scope)
        self.catalog = catalog
        self.version = 0
        self._skip = frozenset(key.lower() for key in skip)
        self._touch_callback = touch
        self._nodes: dict[int, FakeScriptNode] = {}
        self.root = FakeScriptNode(self, None, None)
        self._sync(self.root)

    def _touch(self) -> None:
        if self._touch_callback is None:
            raise RuntimeError("árbol de solo lectura: no se construyó con «touch»")
        self._touch_callback()

    def _changed(self) -> None:
        self._sync(self.root)
        self.version += 1

    def _sync(self, node: FakeScriptNode) -> None:
        """Recalcula los hijos de ``node`` (y los de debajo), reutilizando el nodo de cada entrada."""
        children = []
        if node.form in (NodeForm.GROUP, NodeForm.SCOPE):
            block = self.block if node.entry is None else node.entry.value
            for entry in block.entries:
                key = "" if entry.key is None else entry.key.text
                if node.entry is None and key.lower() in self._skip:
                    continue
                child = self._nodes.get(id(entry))
                if child is None:
                    child = self._nodes[id(entry)] = FakeScriptNode(self, entry, node)
                child.parent, child.kind, child.scope = node, node.inner_kind, node.inner_scope
                child.definition = self.catalog.lookup(key, child.kind, child.scope,
                                                       block=isinstance(entry.value, Block))
                children.append(child)
        node.children = children
        for child in children:
            self._sync(child)
        if node.entry is None:
            alive = {id(n.entry) for n in self.walk()}
            self._nodes = {key: n for key, n in self._nodes.items() if key in alive}

    def walk(self) -> Iterator[FakeScriptNode]:
        pending = list(reversed(self.root.children))
        while pending:
            node = pending.pop()
            yield node
            pending.extend(reversed(node.children))

    def node_at(self, path: Iterable[int]) -> FakeScriptNode | None:
        node = self.root
        for position in path:
            if not 0 <= position < len(node.children):
                return None
            node = node.children[position]
        return node

    def node_of(self, entry: Entry) -> FakeScriptNode | None:
        return self._nodes.get(id(entry))

    def issues(self, ctx=None) -> list[Problem]:
        return [problem for node in self.walk() for problem in node.issues(ctx)]

    def raw_count(self) -> int:
        return sum(1 for node in self.walk() if node.raw)


def fake_check_source(text: str) -> list:
    """Como ``tree.check_source``: los errores de sintaxis de ``text``."""
    return [d for d in parse(text).diagnostics if d.severity is Severity.ERROR]


def fake_phrase_lines(tree, lang: str) -> list[PhraseLine]:
    """Como ``phrases.phrase_lines`` sin localizar: una línea por nodo con ``summary`` o su etiqueta."""
    lines = []
    for node in tree.walk():
        grouped = node.form in (NodeForm.GROUP, NodeForm.SCOPE)
        text = node._label(lang) if grouped else node.summary(lang)
        lines.append(PhraseLine(len(node.path) - 1, text, node.path, raw=node.raw))
    return lines


def implemented(obj) -> bool:
    """True si ``obj`` (función, método, propiedad o clase del contrato) ya tiene lógica: su cuerpo no acaba
    en un ``raise NotImplementedError`` incondicional. Una clase lo está cuando lo están todas las funciones
    y propiedades que define ella. Para ``@unittest.skipUnless(implemented(ScriptCatalog), "…")`` hasta la
    integración. Mira el código fuente: lo que no lo tiene (C, Qt) cuenta como implementado."""
    if isinstance(obj, property):
        return implemented(obj.fget)
    if isinstance(obj, (classmethod, staticmethod)):
        return implemented(obj.__func__)
    if isinstance(obj, type):
        members = [member for member in vars(obj).values()
                   if isinstance(member, (property, classmethod, staticmethod, types.FunctionType))]
        return all(implemented(member) for member in members)
    function = getattr(obj, "__func__", obj)
    if not isinstance(function, types.FunctionType):
        return True
    return not _is_stub(function.__code__, function)


_STUBS: dict = {}


def _is_stub(code, function) -> bool:
    if code not in _STUBS:
        _STUBS[code] = "NotImplementedError" in code.co_names and _ends_raising(function)
    return _STUBS[code]


def _ends_raising(function) -> bool:
    """True si la última sentencia del cuerpo es ``raise NotImplementedError`` (con o sin argumentos)."""
    try:
        module = ast.parse(textwrap.dedent(inspect.getsource(function)))
    except (OSError, TypeError, SyntaxError):
        return False
    last = module.body[0].body[-1]
    if not isinstance(last, ast.Raise) or last.exc is None:
        return False
    raised = last.exc.func if isinstance(last.exc, ast.Call) else last.exc
    return isinstance(raised, ast.Name) and raised.id == "NotImplementedError"


def catalog_class():
    """``ScriptCatalog`` si ya está implementado; si no, ``FakeCatalog``."""
    return real_catalog.ScriptCatalog if implemented(real_catalog.ScriptCatalog) else FakeCatalog


def tree_class():
    """``ScriptTree`` si ya está implementado; si no, ``FakeScriptTree``."""
    return real_tree.ScriptTree if implemented(real_tree.ScriptTree) and implemented(real_tree.ScriptNode) \
        else FakeScriptTree


def fixture_catalog(symbols: SymbolSource | None = None):
    """El catálogo de 20 entradas con la clase que toque (``catalog_class``)."""
    return catalog_class().from_entries(FAKE_ENTRIES).with_symbols(symbols)


def script_block(text: str) -> Block:
    """El ``Document`` de un bloque de muestra: sirve de bloque raíz de un árbol."""
    result = parse(text)
    assert not result.diagnostics, [str(d) for d in result.diagnostics]
    return result.document


def sample_tree(text: str = SAMPLE_TRIGGER, kind: ScriptKind = ScriptKind.TRIGGER, scope: Scope = Scope.COUNTRY,
                *, symbols: SymbolSource | None = None, touch: Callable[[], None] | None = lambda: None):
    """Un árbol editable (``touch`` no hace nada) sobre un bloque de muestra, con ``tree_class``."""
    return tree_class()(script_block(text), kind, scope, fixture_catalog(symbols), touch=touch)

