"""Árbol de guion: una vista sobre el CST, sin copia (wizard §12.2).

``ScriptTree`` envuelve un ``Block`` de condiciones o de efectos y ``ScriptNode`` cada una de sus entradas.
Cada nodo apunta a su ``Entry``: editar el árbol **es** editar el CST, así que lo que no se toca se conserva
byte a byte (I3) y lo que el catálogo no conoce queda como nodo **crudo** (``raw``), que se ve, se mueve, se
borra y se edita como texto, pero nunca se pierde ni se regenera (I6).

Reglas que cumple toda mutación (``set_value``, ``add_child``, ``wrap``, ``unwrap``, ``remove``, ``move``,
``replace_source``):

- llama antes a ``touch`` (lo pone ``Record.script``: es ``ws.touch`` y exige una transacción abierta por
  quien llama, I5). Un documento de solo texto (D17) lanza ``ReadOnlyDocumentError`` sin cambiar nada;
- valida antes de tocar: un valor que no encaja lanza ``ValueError`` y el documento queda limpio;
- usa la API de edición del CST (``Block.insert``, ``move``, ``remove_entry``), nunca reescribe un bloque;
- deja el árbol coherente: los nodos afectados se actualizan en el sitio y ``version`` sube en uno.

Tras deshacer, rehacer o recargar, el CST es otro y los nodos antiguos ya no valen: la interfaz vuelve a
pedir el árbol (``Record.script``) y recupera la selección con ``ScriptNode.path`` y ``ScriptTree.node_at``.
Un CST vivo no cambia de hilo (I12): el árbol solo se usa en el hilo del ``Workspace``.

Criterio 1 de la iteración 7: sobre los 82 archivos de eventos y los 29 de decisiones de vanilla (1 064
eventos y 151 decisiones; todos cp1252, 80 con CRLF y 2 con LF, sin errores de sintaxis), construir el árbol
de cada bloque de guion y serializar da los mismos bytes, y ``set_value`` cambia solo la línea del nodo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from enum import Enum
from typing import TYPE_CHECKING

from .catalog import Role
from .scopes import LOGIC_KEYS, Scope, ScriptKind

if TYPE_CHECKING:
    from ..clausewitz.diagnostics import Diagnostic
    from ..clausewitz.nodes import Block, Entry
    from ..schema.validate import CheckContext
    from ..validate.model import Problem
    from .catalog import ScriptCatalog, ScriptKeyDef

# Códigos de problema que emite el árbol (textos en ``core/script/texts/script.<idioma>.json``).
SCRIPT_UNKNOWN_KEY = "script_unknown_key"      # info: clave no catalogada; se conserva como nodo crudo
SCOPE_MISMATCH = "scope_mismatch"              # aviso: la clave no vale en el ámbito donde está
SCRIPT_BAD_VALUE = "script_bad_value"          # aviso: el valor no encaja con el tipo del catálogo
SCRIPT_REF_MISSING = "script_ref_missing"      # aviso: el valor nombra un símbolo que no existe
ISSUE_CODES = (SCRIPT_UNKNOWN_KEY, SCOPE_MISMATCH, SCRIPT_BAD_VALUE, SCRIPT_REF_MISSING)


class NodeForm(Enum):
    """Cómo se edita un nodo: lo que decide el control de su fila en el constructor."""

    GROUP = "group"        # AND, OR, NOT y limit: un corchete con hijos
    SCOPE = "scope"        # ámbito o iterador: un corchete con hijos en otro ámbito
    VALUE = "value"        # clave = valor, con el control del tipo del catálogo
    STRUCT = "struct"      # clave = { campos }: relation = { who = FRA value = 100 }
    RAW = "raw"            # no catalogado: una línea de código


class ScriptSyntaxError(ValueError):
    """``replace_source`` con un texto que no es Clausewitz válido. ``.diagnostics`` son los errores del
    parser, con línea y columna relativas al texto. No se cambia nada."""

    def __init__(self, diagnostics: Iterable[Diagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__(f"{len(self.diagnostics)} error(es) de sintaxis")


def _is_block(value) -> bool:
    from ..clausewitz.nodes import Block

    return isinstance(value, Block)


class _Ctx:
    """Contexto mínimo para ``ValueType.example`` (solo usa ``index``)."""

    def __init__(self, index) -> None:
        self.index = index


class ScriptNode:
    """Vista sobre una ``Entry`` del CST. La raíz de un árbol no tiene entrada (``entry`` es None): es el
    AND implícito del bloque.

    ``definition``: su entrada del catálogo, o None si es crudo. ``kind`` y ``scope``: el tipo de bloque y
    el ámbito **en los que está** el nodo. ``inner_kind`` e ``inner_scope``: los de sus hijos (cambian con
    ``limit`` y con los ámbitos). ``children`` solo tiene nodos en ``GROUP`` y ``SCOPE`` (y en la raíz).
    """

    tree: ScriptTree
    entry: Entry | None
    parent: ScriptNode | None
    definition: ScriptKeyDef | None
    kind: ScriptKind
    scope: Scope
    children: list[ScriptNode]

    def __init__(self, tree: ScriptTree, entry: Entry | None, parent: ScriptNode | None) -> None:
        self.tree = tree
        self.entry = entry
        self.parent = parent
        self.definition = None
        self.kind = tree.kind
        self.scope = tree.scope
        self.children = []

    def __repr__(self) -> str:
        return f"ScriptNode({self.key or '<raíz>'!s}, {self.form.value}, path={self.path})"

    # --- lectura ------------------------------------------------------------------------------------

    @property
    def key(self) -> str:
        """La clave tal como está escrita (``NOT``, ``not``, ``FRA``); cadena vacía en la raíz y en un valor
        suelto sin clave."""
        return "" if self.entry is None or self.entry.key is None else self.entry.key.text

    @property
    def raw(self) -> bool:
        """True si la clave no está catalogada: se conserva y se edita como línea de código."""
        return self.entry is not None and self.form is NodeForm.RAW

    @property
    def form(self) -> NodeForm:
        """Cómo se edita (``NodeForm``). La raíz es ``GROUP``. Una clave catalogada cuyo valor leído no
        tiene la forma que declara el catálogo (un bloque donde va un valor) es ``RAW``."""
        if self.entry is None:
            return NodeForm.GROUP
        definition, is_block = self.definition, _is_block(self.entry.value)
        if definition is None or self.entry.key is None:
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
        """``"AND"``, ``"OR"`` o ``"NOT"`` (en mayúsculas, se escriba como se escriba) si es un grupo
        lógico; ``"AND"`` en la raíz; None en los demás (``limit`` incluido)."""
        if self.entry is None:
            return "AND"
        if self.form is NodeForm.GROUP and self.key.upper() in LOGIC_KEYS:
            return self.key.upper()
        return None

    @property
    def inner_kind(self) -> ScriptKind:
        """Tipo de guion de sus hijos (``ScriptKeyDef.child_kind``); el suyo si no tiene hijos."""
        return self.kind if self.definition is None else self.definition.child_kind(self.kind)

    @property
    def inner_scope(self) -> Scope:
        """Ámbito de sus hijos (``ScriptKeyDef.child_scope``). Dentro de un nodo crudo con bloque no se
        sabe: ``Scope.ANY``."""
        if self.entry is None:
            return self.scope
        if self.definition is None:
            return Scope.ANY if _is_block(self.entry.value) else self.scope
        return self.definition.child_scope(self.scope)

    @property
    def path(self) -> tuple[int, ...]:
        """Índices desde la raíz (vacío en la raíz): identifica el nodo entre dos versiones del árbol."""
        if self.parent is None:
            return ()
        return (*self.parent.path, self.parent.children.index(self))

    @property
    def value(self) -> object:
        """Valor tipado: ``VALUE`` → lo que da ``definition.value.read`` (el texto crudo si no encaja);
        ``STRUCT`` → ``dict`` de sus campos declarados; ``RAW`` con valor suelto → su texto; los demás,
        None."""
        form = self.form
        if form is NodeForm.VALUE:
            try:
                return self.definition.value.read(self.entry.value)
            except ValueError:
                return self.entry.value.text
        if form is NodeForm.STRUCT:
            result = {}
            for item in self.definition.block:
                if self.entry.value.has(item.key):
                    node = self.entry.value.get(item.key)
                    try:
                        result[item.key] = item.type.read(node)
                    except ValueError:
                        result[item.key] = getattr(node, "text", None)
            return result
        if form is NodeForm.RAW and self.entry is not None and not _is_block(self.entry.value):
            return self.entry.value.text
        return None

    def source(self) -> str:
        """El texto Clausewitz del nodo tal como está en el archivo (sin los comentarios de encima), para
        editarlo como código. En la raíz, el contenido del bloque."""
        from ..clausewitz import to_source

        if self.entry is None:
            return "\n".join(to_source(child.entry).strip() for child in self.children)
        return to_source(self.entry).strip()

    # --- edición ------------------------------------------------------------------------------------

    def _block(self) -> Block:
        if self.form not in (NodeForm.GROUP, NodeForm.SCOPE):
            raise ValueError(f"«{self.key}» no admite hijos")
        return self.tree.block if self.entry is None else self.entry.value

    def _own(self) -> Entry:
        if self.entry is None:
            raise ValueError("la raíz no se puede quitar, mover ni envolver")
        return self.entry

    def _field(self, key: str):
        for item in self.definition.block:
            if item.key == key:
                return item
        raise ValueError(f"«{self.key}» no tiene el campo «{key}»")

    def set_value(self, value: object) -> None:
        """Cambia el valor de un nodo ``VALUE`` (tipado: conserva comillas y decimales), ``STRUCT`` (un
        ``dict`` con los campos que cambian; None quita un campo opcional) o ``RAW`` con valor suelto (una
        cadena). Cambia solo su línea. ``ValueError`` si no encaja o el nodo no lleva valor."""
        from ..clausewitz.nodes import Scalar

        form, entry = self.form, self.entry
        if form is NodeForm.VALUE:
            written = self.definition.value.write(value, entry.value)
        elif form is NodeForm.STRUCT:
            if not isinstance(value, Mapping):
                raise ValueError("se esperaba un dict con los campos que cambian")
            written = []
            for key, item in value.items():
                spec = self._field(key)
                if item is None and spec.required:
                    raise ValueError(f"no se puede quitar el campo obligatorio «{key}»")
                written.append((key, None if item is None else spec.type.write(item, entry.value.get(key))))
        elif form is NodeForm.RAW and entry is not None and not _is_block(entry.value):
            if not isinstance(value, str) or not value.strip() or any(c in value for c in "{}=\n\r"):
                raise ValueError("el valor de una línea de código es un texto de una palabra")
            quoted = getattr(entry.value, "quoted", False) or any(c.isspace() for c in value)
            written = Scalar(value, quoted)
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
        from ..clausewitz.nodes import Block, Scalar

        ctx = _Ctx(self.tree.catalog.symbols)
        if definition is None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("una clave no catalogada necesita su valor como texto")
            if value.strip().startswith("{"):
                from ..clausewitz import parse

                parsed = parse("x = " + value)
                if any(d.severity.name == "ERROR" for d in parsed.diagnostics) or not parsed.document.entries:
                    raise ValueError("el bloque no es Clausewitz válido")
                return parsed.document.entries[0].value.clone()
            return Scalar(value.strip(), " " in value.strip())
        if definition.has_script_body:
            return Block()
        if isinstance(value, Mapping) or (value is None and definition.value is None):
            if definition.block is None:
                raise ValueError(f"«{definition.name}» no lleva un bloque de campos")
            given = dict(value or {})
            unknown = set(given) - {item.key for item in definition.block}
            if unknown:
                raise ValueError(f"campos desconocidos: {sorted(unknown)}")
            pairs = []
            for item in definition.block:
                if item.required or given.get(item.key) is not None:
                    raw = given.get(item.key)
                    pairs.append((item.key, item.type.write(item.type.example(ctx) if raw is None else raw, None)))
            return Block.from_pairs(pairs)
        if definition.value is None:
            raise ValueError(f"«{definition.name}» no lleva un valor suelto")
        return definition.value.write(definition.value.example(ctx) if value is None else value, None)

    def add_child(self, name: str, value: object = None, *, index: int | None = None) -> ScriptNode:
        """Añade ``name`` a un ``GROUP`` o ``SCOPE`` (o a la raíz), al final o en ``index``.

        ``value``: el valor inicial; None usa el ``example`` del tipo en un ``VALUE``, un bloque con los
        campos obligatorios en un ``STRUCT`` y un bloque vacío en los grupos y ámbitos. ``name`` puede ser
        una clave de familia (``FRA``, ``369``). Una clave que el catálogo no conoce se añade como nodo
        crudo con ``value`` (cadena). No se rechaza una clave que no vale en el ámbito: se añade y
        ``issues`` avisa. ``ValueError`` si este nodo no admite hijos o el valor no encaja.
        """
        block = self._block()
        if not isinstance(name, str) or not name.strip() or any(c.isspace() or c in "{}=#\"" for c in name):
            raise ValueError(f"clave inválida: {name!r}")
        wants_block = None if value is None else isinstance(value, Mapping)
        definition = self.tree.catalog.lookup(name, self.inner_kind, self.inner_scope, block=wants_block)
        initial = self._initial(definition, value)
        position = len(self.children) if index is None else max(0, min(index, len(self.children)))
        anchor = self.children[position].entry if position < len(self.children) else None
        self.tree._touch()
        if anchor is None:
            if self.entry is None and self.children:
                last = self.children[-1].entry
                entry = block.insert_after(last, name, initial)
            else:
                entry = block.append(name, initial)
        else:
            entry = block.insert_before(anchor, name, initial)
        self.tree._changed()
        return self.tree.node_of(entry)

    def wrap(self, op: str = "OR") -> ScriptNode:
        """Envuelve el nodo en un grupo ``AND``, ``OR`` o ``NOT`` nuevo, en la misma posición, y devuelve
        el grupo. La entrada envuelta se mueve entera, con sus comentarios. ``ValueError`` en la raíz o con
        otra ``op``."""
        from ..clausewitz.nodes import Block

        entry = self._own()
        if op not in LOGIC_KEYS:
            raise ValueError(f"grupo desconocido: {op}")
        block = self.parent._block()
        self.tree._touch()
        group = block.insert_before(entry, op, Block())
        block.move(entry, to=group.value)
        self.tree._changed()
        return self.tree.node_of(group)

    def unwrap(self) -> None:
        """Deshace un grupo lógico: sus hijos pasan a su sitio en el padre, en orden, y el grupo se quita.
        ``ValueError`` si no es ``AND``/``OR``/``NOT`` o es la raíz. Quitar un ``NOT`` o un ``OR`` cambia
        el significado: lo decide quien llama."""
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
        """Quita el nodo y todo lo que contiene (su línea o sus líneas enteras). ``ValueError`` en la raíz."""
        entry = self._own()
        block = self.parent._block()
        self.tree._touch()
        block.remove_entry(entry)
        self.tree._changed()

    def move(self, index: int, *, to: ScriptNode | None = None) -> None:
        """Mueve el nodo a ``index`` dentro de su padre, o de ``to`` (otro ``GROUP``/``SCOPE`` del mismo
        árbol que no sea él ni un descendiente suyo)."""
        entry = self._own()
        target = self.parent if to is None else to
        if target.tree is not self.tree:
            raise ValueError("el destino es de otro árbol")
        probe = target
        while probe is not None:
            if probe is self:
                raise ValueError("un nodo no se mueve dentro de sí mismo")
            probe = probe.parent
        source, block = self.parent._block(), target._block()
        siblings = [child.entry for child in target.children if child is not self]
        index = max(0, min(index, len(siblings)))
        self.tree._touch()
        if source is not block:
            source.move(entry, None, to=block)
        final = None
        if index < len(siblings):
            final = _final_index(block, entry, siblings[index])
        elif siblings:
            final = _after_index(block, entry, siblings[-1])
        if final is not None:
            block.move(entry, final)
        self.tree._changed()

    def replace_source(self, text: str) -> list[ScriptNode]:
        """Sustituye el nodo por lo que diga ``text`` (una o varias entradas Clausewitz) y devuelve los
        nodos nuevos. ``ScriptSyntaxError`` si el texto tiene errores de sintaxis o no cierra sus llaves;
        entonces no cambia nada. En la raíz sustituye el contenido del bloque."""
        from ..clausewitz import parse

        errors = check_source(text)
        if errors:
            raise ScriptSyntaxError(errors)
        new = [entry.clone() for entry in parse(text).document.entries]
        self.tree._touch()
        if self.entry is None:
            for child in list(self.children):
                self.tree.block.remove_entry(child.entry)
            anchor = self._first_skipped_tail()
            for entry in new:
                position = len(self.tree.block.entries) if anchor is None else self.tree.block.entries.index(anchor)
                self.tree.block.insert_entry(position, entry)
        else:
            block = self.parent._block()
            position = block.remove_entry(self.entry)
            for offset, entry in enumerate(new):
                block.insert_entry(position + offset, entry)
        self.tree._changed()
        return [node for node in (self.tree.node_of(entry) for entry in new) if node is not None]

    def _first_skipped_tail(self):
        """En la raíz, la primera entrada saltada (``skip``) que va detrás de todo el guion: el texto nuevo
        se inserta antes de ella para no mover lo que declara el esquema."""
        return None

    # --- problemas y frases -------------------------------------------------------------------------

    def issues(self, ctx: CheckContext | None = None) -> list[Problem]:
        """Problemas de este nodo, sin sus hijos (``ISSUE_CODES``). Sin ``ctx`` no se comprueban las
        referencias."""
        from ..clausewitz.diagnostics import Severity
        from ..validate.model import Problem

        if self.entry is None or self.entry.key is None:
            return []
        line, column = self.entry.line, self.entry.column

        def problem(code, severity, **args):
            return Problem(code, severity, None, line, column, args={"key": self.key, **args})

        if self.definition is None:
            return [problem(SCRIPT_UNKNOWN_KEY, Severity.INFO)]
        found = []
        if not self.definition.accepts(self.scope):
            found.append(problem(SCOPE_MISMATCH, Severity.WARNING, scope=str(self.scope)))
        form = self.form
        if form is NodeForm.RAW:
            found.append(problem(SCRIPT_BAD_VALUE, Severity.WARNING, value=_short(self.entry)))
            return found
        checks = []
        if form is NodeForm.VALUE:
            checks.append((self.definition.value, self.entry.value))
        elif form is NodeForm.STRUCT:
            for item in self.definition.block:
                if self.entry.value.has(item.key):
                    checks.append((item.type, self.entry.value.get(item.key)))
                elif item.required:
                    found.append(problem(SCRIPT_BAD_VALUE, Severity.WARNING, value=f"{item.key} = ?"))
        for value_type, node in checks:
            try:
                value_type.read(node)
            except ValueError:
                found.append(problem(SCRIPT_BAD_VALUE, Severity.WARNING, value=getattr(node, "text", "{…}")))
                continue
            if ctx is not None and getattr(ctx, "index", None) is not None:
                for issue in value_type.check(node, ctx):
                    if issue.code == "ref_missing":
                        found.append(problem(SCRIPT_REF_MISSING, Severity.WARNING,
                                             kind=issue.args.get("kind"), name=issue.args.get("name")))
        return found

    def summary(self, lang: str, index=None, loc=None) -> str:
        """Frase de una línea del nodo con sus hijos («El país posee Londres (300)»): es
        ``phrases.node_phrase``. ``index`` y ``loc`` dan los nombres localizados; sin ellos, los ids."""
        from .phrases import node_phrase

        return node_phrase(self, lang, index, loc)


def _final_index(block, entry, before) -> int:
    """Posición final de ``entry`` para quedar justo antes de ``before`` (los dos en ``block``)."""
    current = block.entries.index(entry)
    target = block.entries.index(before)
    return target - 1 if current < target else target


def _after_index(block, entry, after) -> int:
    current = block.entries.index(entry)
    target = block.entries.index(after)
    return target if current < target else target + 1


def _short(entry) -> str:
    from ..clausewitz import to_source

    text = " ".join(to_source(entry).split())
    return text if len(text) <= 60 else text[:57] + "…"


class ScriptTree:
    """El árbol de un bloque de guion.

    ``block``: el bloque del CST (``trigger = { … }`` → su valor). ``kind`` y ``scope``: los de la raíz.
    ``skip``: claves del bloque que no son guion porque las declara el esquema (``name`` y ``ai_chance`` en
    un ``option``, ``factor`` en un ``modifier``): no aparecen como nodos y no se tocan. ``touch``: se llama
    antes de cada mutación (ver el docstring del módulo); None en un árbol de solo lectura construido a
    mano, cuyas mutaciones lanzan ``RuntimeError``.
    """

    block: Block
    kind: ScriptKind
    scope: Scope
    catalog: ScriptCatalog
    root: ScriptNode
    version: int                              # sube en cada mutación (los modelos de la interfaz lo miran)

    def __init__(self, block: Block, kind: ScriptKind, scope: Scope, catalog: ScriptCatalog, *,
                 skip: Iterable[str] = (), touch: Callable[[], None] | None = None) -> None:
        self.block = block
        self.kind = ScriptKind(kind)
        self.scope = Scope(scope)
        self.catalog = catalog
        self.version = 0
        self.skip = frozenset(key.lower() for key in skip)
        self._touch_callback = touch
        self._nodes: dict[int, ScriptNode] = {}
        self.root = ScriptNode(self, None, None)
        self._sync(self.root)

    def _touch(self) -> None:
        if self._touch_callback is None:
            raise RuntimeError("árbol de solo lectura: no se construyó con «touch»")
        self._touch_callback()

    def _changed(self) -> None:
        self._sync(self.root)
        self.version += 1

    def _sync(self, node: ScriptNode) -> None:
        """Recalcula los hijos de ``node`` (y los de debajo), reutilizando el nodo de cada entrada."""
        children = []
        if node.entry is None or node.form in (NodeForm.GROUP, NodeForm.SCOPE):
            block = self.block if node.entry is None else node.entry.value
            for entry in block.entries:
                key = "" if entry.key is None else entry.key.text
                if node.entry is None and key.lower() in self.skip:
                    continue
                child = self._nodes.get(id(entry))
                if child is None or child.entry is not entry:
                    child = self._nodes[id(entry)] = ScriptNode(self, entry, node)
                child.parent, child.kind, child.scope = node, node.inner_kind, node.inner_scope
                child.definition = self.catalog.lookup(key, child.kind, child.scope,
                                                       block=_is_block(entry.value)) if key else None
                children.append(child)
        node.children = children
        for child in children:
            self._sync(child)
        if node.entry is None:
            alive = {id(n.entry) for n in self.walk()}
            self._nodes = {key: n for key, n in self._nodes.items() if key in alive}

    def walk(self) -> Iterator[ScriptNode]:
        """Todos los nodos en preorden, sin la raíz."""
        pending = list(reversed(self.root.children))
        while pending:
            node = pending.pop()
            yield node
            pending.extend(reversed(node.children))

    def node_at(self, path: Iterable[int]) -> ScriptNode | None:
        """El nodo en ``path`` (``ScriptNode.path``); None si ya no existe. Vacío: la raíz."""
        node = self.root
        for position in path:
            if not 0 <= position < len(node.children):
                return None
            node = node.children[position]
        return node

    def node_of(self, entry: Entry) -> ScriptNode | None:
        """El nodo de ``entry`` (por identidad); None si no es de este árbol."""
        node = self._nodes.get(id(entry))
        return node if node is not None and node.entry is entry else None

    def issues(self, ctx: CheckContext | None = None) -> list[Problem]:
        """Problemas de todo el árbol, por línea: clave desconocida (``script_unknown_key``, información),
        ámbito incorrecto (``scope_mismatch``), valor que no encaja (``script_bad_value``) y, con ``ctx``,
        referencia inexistente (``script_ref_missing``). Cada ``Problem`` lleva la línea y la columna de la
        entrada del nodo. No escribe nada (I4)."""
        found = [problem for node in self.walk() for problem in node.issues(ctx)]
        found.sort(key=lambda p: (p.line or 0, p.column or 0))
        return found

    def raw_count(self) -> int:
        """Cuántos nodos crudos hay (el censo del criterio 2 los cuenta sobre vanilla)."""
        return sum(1 for node in self.walk() if node.raw)


def check_source(text: str) -> list[Diagnostic]:
    """Errores de sintaxis de ``text`` como contenido de un bloque de guion (vacía si es válido), para
    marcar el editor de texto de un nodo mientras se teclea, sin tocar el árbol."""
    from ..clausewitz import Severity, parse

    return [d for d in parse(text).diagnostics if d.severity is Severity.ERROR]
