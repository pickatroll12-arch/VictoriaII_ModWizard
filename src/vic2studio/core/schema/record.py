"""Registros y servicio de entidades (wizard §10.5, API pública fija de ENCARGO_MOTOR).

``RecordRef`` es la referencia ligera que la interfaz guarda y pasa al servicio
(nunca nodos); ``EntitySummary`` es la fila de una lista. ``Record`` es una
vista sobre el ``Block`` real de un documento abierto: lee y escribe con la API
del CST (§4.1) sin copiar datos, y toda mutación pasa por ``ws.touch``, que
exige una transacción abierta por quien llama (igual que editar a mano). Leer
(``get``, ``dynamic``, ``unknown``, ``issues``, ``loc_keys``) no escribe nada
(I4). ``Entities`` es el servicio: lista, abre, crea, duplica, renombra, mueve de
grupo, borra y restaura registros. ``create``/``duplicate``/``rename``/
``move_to_group``/``delete``/``restore_vanilla`` abren su propia transacción
(archivo + compañeros + claves de localización): un ``ws.undo()`` lo deshace todo
(I5). El renombrado seguro (§15) está en ``rename.py``.

La vista efectiva (I7): ``list`` sale del índice con **todos** los documentos
abiertos del layout encima (los sin guardar y los ya guardados que el índice
aún no ha releído), y ``open`` lee siempre a través del ``Workspace``. Si se
borró sin guardar la copia del mod de un archivo que también tiene el juego, lo
que se ve es el archivo del juego (la lápida no lo tapa): se lista y se abre, y
editarlo revive el documento en el mod.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..clausewitz.diagnostics import EditError
from ..clausewitz.nodes import Block, Entry, Scalar
from ..vfs.model import LayerKind
from ..vfs.paths import VPath
from .entity import EntitySchema, LocSpec
from .fields import MISSING, OPEN_CATALOG, Children, DynamicKeys, Field, Group, Opaque, Script, Section
from .layouts import GroupedIn, OnePerFile, entry_path, follow_path, parent_block
from .placement import SchemaOrder, dynamic_insert_index, first_dated_index, insertion_index
from .registry import registry
from .validate import CheckContext, issue as make_issue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..index.model import SymbolRef
    from ..locsync import LocSync
    from ..project.model import DocHandle
    from ..project.workspace import Workspace
    from ..validate.model import Problem


@dataclass(frozen=True)
class RecordRef:
    """Referencia a un registro. ``rel``: entidades repartidas (POPs de una provincia en un
    archivo) o archivo efectivo cuando hay que distinguirlo; None, el que dé el esquema."""

    kind: str
    ident: str
    rel: VPath | None = None


@dataclass(frozen=True)
class EntitySummary:
    """Fila de una lista de entidades: la referencia y el archivo efectivo donde está.

    ``parent``: el grupo del registro en un ``GroupedIn`` de nivel 1 (la cultura → su grupo); None si no
    tiene."""

    ref: RecordRef
    rel: VPath
    parent: str | None = None


def bookmark_dates(index) -> list:
    """Fechas de los bookmarks del índice (``attrs["date"]``), ordenadas y sin repetir; vacía sin índice."""
    from ..clausewitz.nodes import ClausewitzDate

    found = set()
    if index is None:
        return []
    try:
        symbols = index.symbols("bookmark")
    except Exception:  # noqa: BLE001 - un índice falso puede no tener el tipo
        return []
    for symbol in symbols:
        text = (getattr(symbol, "attrs", None) or {}).get("date")
        if isinstance(text, ClausewitzDate):
            found.add(text)
            continue
        try:
            found.add(ClausewitzDate.parse(str(text)))
        except (TypeError, ValueError):
            continue
    return sorted(found)


class InvalidIdentError(ValueError):
    """``create``/``duplicate``/``rename`` con un id inválido (``.code``: ``empty``, ``bad_chars``,
    ``reserved``, ``out_of_range``…), que ya existe (``taken``) o que es el que ya tiene
    (``unchanged``, al renombrar). No se cambia nada: ni documentos, ni deshacer, ni archivos.
    ``message(lang)`` da el motivo traducido (``schema.ident.<código>``)."""

    def __init__(self, code: str, ident: str = "", **params) -> None:
        self.code = code
        self.ident = ident
        self.params = params
        super().__init__(f"{code}: {ident}" if ident else code)

    def message(self, lang: str = "en") -> str:
        from ..texts import text

        return text(f"schema.ident.{self.code}", lang, ident=self.ident, **self.params)


class EntityInUseError(ValueError):
    """``delete`` de un registro con usos en el índice (``index.refs_to``) sin ``force``.

    ``.uses`` es la lista de ``SymbolRef`` que bloquean el borrado. No se cambia nada.
    """

    def __init__(self, uses: list[SymbolRef]) -> None:
        self.uses = uses
        super().__init__(f"en uso por {len(uses)} referencia(s)")


class ReadOnlySchemaError(PermissionError):
    """Crear, duplicar o borrar un registro de un esquema de solo lectura (``editable=False``)."""


# Patrón de un id «palabra» (IdRule.WORD): los ids reales son minúsculas con guiones bajos.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_SNAKE_RE = re.compile(r"[a-z][a-z0-9_]*")


def ident_problem(schema: EntitySchema, ident: str) -> str | None:
    """Código de ``InvalidIdentError`` si ``ident`` no es válido para ``schema.ident_rule``;
    None si vale. Solo comprueba la forma: si ya existe lo dice ``Entities``."""
    if not isinstance(ident, str) or not ident:
        return "empty"
    rule = schema.ident_rule
    if rule.mode == "snake":
        return None if _SNAKE_RE.fullmatch(ident) else "bad_chars"
    if rule.mode == "word":
        return None if _WORD_RE.fullmatch(ident) else "bad_chars"
    # tag e int_range llegan con los esquemas que los usan (countries, events…).
    return None


def _children_spec(items) -> Children | None:
    for item in items:
        if isinstance(item, Section):
            found = _children_spec(item.items)
            if found is not None:
                return found
        elif isinstance(item, Children):
            return item
    return None


class Record:
    """Vista sobre el ``Block`` real; nunca copia datos (§10.5).

    Los métodos de lectura (``get``, ``dynamic``, ``unknown``, ``issues``, ``loc_keys``) no
    dejan el documento sucio ni escriben nada (I4). ``set`` y ``set_dynamic`` pasan por
    ``ws.touch``: exigen una transacción abierta por quien llama. ``None`` o ``MISSING`` quitan
    la entrada. Si el valor de un campo no encaja con su tipo, ``get`` devuelve el texto crudo
    en vez de fallar (el problema lo reporta ``issues`` como ``bad_type``).

    Si el documento ya no es el que el ``Workspace`` tiene abierto (lo expulsó la LRU, o es la lápida
    de una copia del mod y se está viendo el archivo del juego), mutar vuelve a abrirlo (reviviéndolo
    si hace falta) y sigue al mismo bloque por su posición antes de tocarlo.
    """

    schema: EntitySchema
    ref: RecordRef
    handle: DocHandle
    block: Block
    origin: LayerKind | None = None           # capa de la que se leyó (juego, mod, nuevo)

    def __init__(self, schema: EntitySchema, ref: RecordRef, handle: DocHandle, block: Block,
                 origin: LayerKind | None = None, *, ws: Workspace = None, index=None,
                 entry: Entry | None = None, document: Block | None = None) -> None:
        self.schema = schema
        self.ref = ref
        self.handle = handle
        self.block = block
        self.origin = origin
        self._ws = ws                          # para touch (mutar exige transacción)
        self._index = index                    # catálogos de los DynamicKeys (B2)
        self._entry = entry                    # la entrada dueña en el documento (borrar)
        self._document = document              # el documento del bloque (None: el del handle)

    # --- esquema efectivo ---------------------------------------------------------------

    def _variant_value(self) -> str | None:
        variant = self.schema.variants
        if variant is None:
            return None
        entry = self.block.find(variant.field, ignore_case=True)
        if entry is None or not isinstance(entry.value, Scalar):
            return None
        return entry.value.text

    def _effective_fields(self) -> tuple:
        """Campos y secciones del esquema con los de la variante activa añadidos (``unit``)."""
        base = self.schema.fields
        variant = self.schema.variants
        if variant is None:
            return base
        value = self._variant_value()
        if value is None or value not in variant.cases:
            return base
        return tuple(base) + tuple(variant.cases[value])

    def _index_schema(self) -> tuple[dict, dict, dict]:
        """``(fields, groups, dynamics)`` del esquema efectivo: ``fields`` por clave (y alias),
        ``groups`` por clave y ``dynamics`` por nombre con su contenedor (None = raíz)."""
        fields: dict[str, Field] = {}
        groups: dict[str, Group] = {}
        dynamics: dict[str, tuple[DynamicKeys, str | None]] = {}

        def walk(items):
            for item in items:
                if isinstance(item, Section):
                    walk(item.items)
                elif isinstance(item, Field):
                    fields[item.key] = item
                    for alias in item.aliases:
                        fields.setdefault(alias, item)
                elif isinstance(item, Group):
                    groups[item.key] = item
                    if item.dynamic is not None:
                        dynamics[item.dynamic.name] = (item.dynamic, item.key)
                elif isinstance(item, DynamicKeys):
                    dynamics[item.name] = (item, None)

        walk(self._effective_fields())
        return fields, groups, dynamics

    def _opaque_keys(self) -> frozenset[str]:
        """Claves de ``Script`` y ``Opaque``: se conservan y se editan como código, no son desconocidas."""
        found: set[str] = set()

        def walk(items):
            for item in items:
                if isinstance(item, Section):
                    walk(item.items)
                elif isinstance(item, (Script, Opaque)):
                    found.add(item.key)

        walk(self._effective_fields())
        return frozenset(found)

    def _ordered_keys(self, fields: dict) -> tuple[str, ...]:
        return tuple(fields)

    def _field_of(self, key: str) -> Field | None:
        return self._index_schema()[0].get(key)

    def _find_entry(self, key: str) -> Entry | None:
        field = self._field_of(key)
        return self.block.find(key, ignore_case=field.ignore_case) if field is not None \
            else self.block.find(key)

    def _rebind(self, handle) -> None:
        """Pasa a ``handle`` siguiendo el mismo bloque por su posición (misma forma de árbol)."""
        old_document = self._document if self._document is not None else self.handle.model.document
        document = handle.model.document
        if self._entry is not None:
            path = entry_path(old_document, self._entry)
            entry = follow_path(document, path) if path is not None else None
            if entry is None or not isinstance(entry.value, Block):
                raise KeyError(f"{self.ref.kind}:{self.ref.ident} ya no está en {handle.rel}")
            self._entry = entry
            self.block = entry.value
        else:
            self.block = document
        self.handle = handle
        self._document = None

    def _touch(self) -> None:
        if self._ws is None:
            raise RuntimeError("el Record no tiene Workspace (construido a mano): mutar exige una transacción")
        ws = self._ws
        current = ws.peek(self.handle.rel)
        if current is None or current is not self.handle or current.deleted or self._document is not None:
            revive = current is not None and current.deleted
            self._rebind(ws.open(self.handle.rel, create=revive))
        ws.touch(self.handle)

    # --- lectura ------------------------------------------------------------------------

    def get(self, key: str, default: object = MISSING) -> object:
        """Valor tipado de ``key``, el ``default`` del campo si falta, o ``default`` (MISSING si
        no se pasa). Un valor que no encaja con su tipo se devuelve crudo (ver docstring)."""
        field = self._field_of(key)
        entry = self._find_entry(key)
        if entry is None:
            if field is not None and field.default is not MISSING:
                return field.default
            return default
        if field is None:
            value = entry.value
            return value.text if isinstance(value, Scalar) else value
        try:
            return field.type.read(entry.value)
        except (ValueError, EditError):
            value = entry.value
            return value.text if isinstance(value, Scalar) else value

    def get_all(self, key: str) -> list:
        """Todos los valores de una clave repetible, en orden."""
        field = self._field_of(key)
        entries = self.block.find_all(key, ignore_case=field.ignore_case) if field is not None \
            else self.block.find_all(key)
        if field is not None:
            values = []
            for entry in entries:
                try:
                    values.append(field.type.read(entry.value))
                except (ValueError, EditError):
                    value = entry.value
                    values.append(value.text if isinstance(value, Scalar) else value)
            return values
        return [entry.value for entry in entries]

    def node(self, key: str) -> Entry | None:
        """La entrada del CST de ``key`` («ir al código»); None si no está."""
        return self._find_entry(key)

    def set(self, key: str, value: object) -> None:
        """Escribe ``key`` según su tipo; ``None`` o ``MISSING`` quitan la entrada. Dentro de una
        transacción abierta por quien llama (I5). Un valor que no encaja lanza ``ValueError`` sin
        tocar nada (se comprueba antes de ``touch``)."""
        field = self._field_of(key)
        if field is None:
            raise KeyError(f"el esquema {self.schema.kind} no declara el campo {key!r}")
        if value is not None and value is not MISSING:
            field.type.write(value, None)   # valida antes de ensuciar el documento
        self._touch()
        if value is None or value is MISSING:
            entry = self._find_entry(key)
            if entry is not None:
                self.block.remove_entry(entry)
            return
        entry = self._find_entry(key)
        written = field.type.write(value, None if entry is None else entry.value)
        if entry is not None:
            entry.value = written
            return
        fields, _, _ = self._index_schema()
        index = insertion_index(self.block, key=key, order=SchemaOrder(self._ordered_keys(fields)),
                                first_dated=first_dated_index(self.block))
        self.block.insert(index, key, written)

    def add(self, key: str, value: object) -> Entry:
        """Añade un valor a una clave repetible, tras la última de la misma clave (§10.7.1)."""
        field = self._field_of(key)
        if field is None:
            raise KeyError(f"el esquema {self.schema.kind} no declara el campo {key!r}")
        written = field.type.write(value, None)
        self._touch()
        siblings = self.block.find_all(key)
        if siblings:
            return self.block.insert_after(siblings[-1], key, written)
        return self.block.append(key, written)

    def remove(self, key: str, value: object = MISSING) -> int:
        """Quita valores de una clave repetible; devuelve cuántos. Sin ``value``, todos."""
        self._touch()
        return self.block.remove(key) if value is MISSING else self.block.remove(key, value)

    def group(self, key: str, index: int = 0) -> Record:
        """Vista del bloque anidado ``key`` (la repetición ``index``)."""
        entries = self.block.find_all(key)
        if index >= len(entries) or not isinstance(entries[index].value, Block):
            raise KeyError(f"no hay grupo {key!r} #{index}")
        return Record(self.schema, self.ref, self.handle, entries[index].value, self.origin,
                      ws=self._ws, index=self._index, entry=entries[index], document=self._document)

    def groups(self, key: str) -> list[Record]:
        """Vistas de todas las repeticiones del grupo ``key``."""
        return [Record(self.schema, self.ref, self.handle, entry.value, self.origin, ws=self._ws,
                       index=self._index, entry=entry, document=self._document)
                for entry in self.block.find_all(key) if isinstance(entry.value, Block)]

    def add_group(self, key: str, values: dict) -> Record:
        """Añade una repetición del grupo ``key`` con ``values``; devuelve su vista."""
        self._touch()
        block = Block()
        for sub_key, value in values.items():
            block.append(sub_key, coerce_value(value))
        entry = self.block.append(key, block)
        return Record(self.schema, self.ref, self.handle, block, self.origin, ws=self._ws,
                      index=self._index, entry=entry)

    # --- claves dinámicas ---------------------------------------------------------------

    def _dynamic(self, name: str) -> tuple[DynamicKeys, Block | None, str | None]:
        """``(spec, bloque destino, clave del grupo)`` del ``DynamicKeys`` ``name``; el bloque
        es None si el grupo no existe. Las claves sueltas viven en la raíz; las de un grupo, en
        el bloque del grupo."""
        _, _, dynamics = self._index_schema()
        if name not in dynamics:
            raise KeyError(f"el esquema {self.schema.kind} no declara las claves dinámicas {name!r}")
        spec, container = dynamics[name]
        if container is None:
            return spec, self.block, None
        entry = self.block.find(container)
        if entry is None or not isinstance(entry.value, Block):
            return spec, None, container
        return spec, entry.value, container

    def _dynamic_reader(self, spec: DynamicKeys, key: str):
        value_type = spec.value(key) if callable(spec.value) else spec.value
        return value_type

    def _catalog(self, spec: DynamicKeys) -> frozenset[str] | None:
        """Claves del catálogo del ``DynamicKeys``: los símbolos de su ``key_kind`` en el índice.
        Sin índice, el catálogo es vacío y ninguna clave suelta cuenta como dinámica (B2).
        None: catálogo abierto (``OPEN_CATALOG``), cualquier clave que no sea un campo fijo."""
        if spec.key_kind == OPEN_CATALOG:
            return None
        index = getattr(self, "_index", None)
        if index is None:
            return frozenset()
        return frozenset(index.names(spec.key_kind))

    def _in_catalog(self, spec: DynamicKeys, catalog, key: str) -> bool:
        if catalog is not None and key not in catalog:
            return False
        return spec.key_filter is None or bool(spec.key_filter(key))

    def dynamic(self, name: str) -> dict[str, object]:
        """Los valores de un ``DynamicKeys`` (``{"flintlock_rifles": 1, …}``): las claves del
        bloque que no son campos fijos y están en el catálogo del índice; el resto va a
        ``unknown()`` (B2). Se leen con su tipo (crudas si no encajan)."""
        spec, block, container = self._dynamic(name)
        if block is None:
            return {}
        fixed = self._fixed_keys(container)
        catalog = self._catalog(spec)
        result: dict[str, object] = {}
        for entry in block.entries:
            if entry.key is None or entry.key.text in fixed \
                    or not self._in_catalog(spec, catalog, entry.key.text):
                continue
            if catalog is None and isinstance(entry.value, Block):
                continue   # catálogo abierto: solo valores sueltos (los bloques son hijos u otros campos)
            value_type = self._dynamic_reader(spec, entry.key.text)
            try:
                result[entry.key.text] = value_type.read(entry.value)
            except (ValueError, EditError):
                value = entry.value
                result[entry.key.text] = value.text if isinstance(value, Scalar) else value
        return result

    def _fixed_keys(self, container: str | None) -> frozenset[str]:
        """Claves fijas del bloque destino: las del record (raíz) o las del grupo."""
        fields, groups, _ = self._index_schema()
        if container is None:
            return frozenset(fields) | frozenset(groups) | self._opaque_keys()
        group = groups.get(container)
        return frozenset(field.key for field in group.fields if isinstance(field, Field)) \
            if group is not None else frozenset()

    def set_dynamic(self, name: str, key: str, value: object) -> None:
        """Escribe ``key`` de un ``DynamicKeys``. Con ``only_true`` y valor falso, borra la clave
        en vez de escribir ``= no`` (§10.10). Dentro de una transacción (I5)."""
        spec, _, _ = self._dynamic(name)
        removing = value is None or value is MISSING or (spec.only_true and not value)
        if not removing:
            self._dynamic_reader(spec, key).write(value, None)   # valida antes de ensuciar
        self._touch()
        spec, block, container = self._dynamic(name)
        if block is None:
            if removing:
                return
            block = Block()
            fields, _, _ = self._index_schema()
            index = insertion_index(self.block, key=container, order=SchemaOrder(self._ordered_keys(fields)),
                                    first_dated=first_dated_index(self.block))
            self.block.insert(index, container, block)
        if removing:
            entry = block.find(key)
            if entry is not None:
                block.remove_entry(entry)
            return
        value_type = self._dynamic_reader(spec, key)
        entry = block.find(key)
        written = value_type.write(value, None if entry is None else entry.value)
        if entry is not None:
            entry.value = written
            return
        fixed = self._fixed_keys(container)
        if container is None and _children_spec(self._effective_fields()) is not None:
            # Con hijos (bloques) en el mismo nivel, las claves sueltas van antes del primer hijo.
            fixed = fixed | {entry.key.text for entry in block.entries
                             if entry.key is not None and isinstance(entry.value, Block)}
        block.insert(dynamic_insert_index(block, fixed=fixed), key, written)

    # --- resto del esquema --------------------------------------------------------------

    def children(self) -> list[Record]:
        """Registros hijos (``Children``): culturas dentro del grupo, en orden de archivo. Son los
        bloques que el esquema no reclama como campos (``REMAINING_BLOCKS``) o los que dé ``match``."""
        spec = _children_spec(self._effective_fields()) if hasattr(self, "schema") else None
        if spec is None:
            return []
        fields, groups, _ = self._index_schema()
        claimed = set(fields) | set(groups) | self._opaque_keys()
        found: list[Record] = []
        for entry in self.block.entries:
            if entry.key is None or not isinstance(entry.value, Block) or entry.key.text in claimed:
                continue
            if spec.match is not None and callable(spec.match) and not spec.match(entry):
                continue
            ref = RecordRef(spec.schema.kind, entry.key.text, self.ref.rel)
            found.append(Record(spec.schema, ref, self.handle, entry.value, self.origin, ws=self._ws,
                                index=self._index, entry=entry, document=self._document))
        return found

    def script(self, key: str):
        """Árbol de guion de ``key`` (lo edita ``core.script``, iteración 7)."""
        raise NotImplementedError

    def at(self, date, bookmarks=None):  # ClausewitzDate | None, Sequence[ClausewitzDate] | None
        """``HistoryView`` de este registro en ``date`` (§10.6, iteración 5). ``bookmarks``: las fechas de
        inicio; None = las de los símbolos ``bookmark`` del índice del registro (``attrs["date"]``)."""
        from .history import HistoryView

        if bookmarks is None:
            bookmarks = bookmark_dates(getattr(self, "_index", None))
        return HistoryView(self, date, bookmarks)

    def unknown(self) -> list[Entry]:
        """Entradas que el esquema no declara: se conservan (I6) y salen en «Otros campos».

        Las claves de un ``DynamicKeys`` solo las reclama su catálogo (B2): una clave suelta que
        no está en el índice (``electoin``, ``foo_bar``) va a ``unknown`` y da ``unknown_field``.
        Los bloques hijos de un ``Children`` y las claves de ``Script``/``Opaque`` no son desconocidos.
        """
        fields, groups, dynamics = self._index_schema()
        found: list[Entry] = []
        covered_root = set(fields) | set(groups) | self._opaque_keys()
        children = _children_spec(self._effective_fields())
        root_specs = [spec for spec, container in dynamics.values() if container is None]
        for entry in self.block.entries:
            if entry.key is None or entry.key.text in covered_root:
                continue
            if children is not None and isinstance(entry.value, Block):
                continue
            key = entry.key.text
            if any(self._in_catalog(spec, self._catalog(spec), key)
                   and not (spec.key_kind == OPEN_CATALOG and isinstance(entry.value, Block))
                   for spec in root_specs):
                continue
            found.append(entry)
        for key, group in groups.items():
            entry = self.block.find(key)
            if entry is None or not isinstance(entry.value, Block):
                continue
            covered = frozenset(field.key for field in group.fields if isinstance(field, Field))
            dynamic_spec = next((spec for name, (spec, container) in dynamics.items()
                                 if container == key), None)
            for sub in entry.value.entries:
                if sub.key is None or sub.key.text in covered:
                    continue
                if dynamic_spec is not None and self._in_catalog(dynamic_spec, self._catalog(dynamic_spec),
                                                                 sub.key.text):
                    continue
                found.append(sub)
        return found

    def issues(self, ctx: CheckContext = None) -> list[Problem]:
        """Problemas de este registro: campos (tipo, repetición, obligatorios), validadores del
        esquema, compañeros y claves desconocidas (salvo ``unknown="keep"``); sin tocar nada (I4).
        Los compañeros que necesitan el ``Workspace`` no dan nada con ``ctx.ws`` None (validación
        en segundo plano)."""
        fields, _, _ = self._index_schema()
        problems: list[Problem] = []
        for key, field in fields.items():
            entries = self.block.find_all(key, ignore_case=field.ignore_case)
            if len(entries) > 1 and not field.repeat:
                problems.append(make_issue("duplicate_field", self, field=(key,), key=key))
            for entry in entries:
                try:
                    field.type.read(entry.value)
                except (ValueError, EditError):
                    value = entry.value
                    problems.append(make_issue("bad_type", self, field=(key,), key=key,
                                               kind=self.ref.kind,
                                               value=value.text if isinstance(value, Scalar) else "…"))
            if not entries and field.required and field.default is MISSING:
                problems.append(make_issue("required_missing", self, field=(key,), key=key,
                                           kind=self.ref.kind))
        for validator in self.schema.validators:
            problems.extend(validator(self, ctx))
        if ctx is not None:
            for companion in self.schema.companions:
                problems.extend(companion.check(ctx, self) or ())
        if self.schema.unknown != "keep":
            for entry in self.unknown():
                problems.append(make_issue("unknown_field", self, field=(entry.key.text,),
                                           key=entry.key.text, kind=self.ref.kind))
        problems.sort(key=lambda p: (p.line or 0, p.code))
        return problems

    def loc_keys(self) -> list[tuple[LocSpec, str]]:
        """Claves de localización de este registro: ``(LocSpec, clave ya formateada)``."""
        return [(spec, spec.template.replace("{id}", self.ref.ident)) for spec in self.schema.loc]


def coerce_value(value) -> Scalar | Block:
    """Valor de Python a nodo para ``add_group`` (delega en el CST)."""
    from ..clausewitz.nodes import coerce_value as cst_coerce

    return cst_coerce(value)


def build_block(schema: EntitySchema, ident: str, values: dict, index=None) -> Block:
    """Bloque nuevo con los valores en el orden canónico del esquema (regla 6 de §10.7). Con
    ``IdSpec.FIELD`` (bookmarks), el id se escribe en su campo."""
    merged: dict = {}
    if schema.template is not None:
        merged.update(dict(schema.template(ident, index)))
    merged.update(values)
    if schema.ident.mode == "field":
        merged[schema.ident.value] = ident
    block = Block()

    def emit(items) -> None:
        for item in items:
            if isinstance(item, Field):
                if item.key in merged and merged[item.key] is not None and merged[item.key] is not MISSING:
                    block.append(item.key, item.type.write(merged[item.key], None))
            elif isinstance(item, DynamicKeys):
                payload = merged.get(item.name)
                if isinstance(payload, dict):
                    for key, item_value in payload.items():
                        if item_value is None or item_value is MISSING:
                            continue
                        if item.only_true and not item_value:
                            continue
                        value_type = item.value(key) if callable(item.value) else item.value
                        block.append(key, value_type.write(item_value, None))
            elif isinstance(item, Group):
                payload = merged.get(item.key)
                if isinstance(payload, dict):
                    inner = Block()
                    for sub_key, item_value in payload.items():
                        if item_value is None or item_value is MISSING:
                            continue
                        if item.dynamic is not None:
                            value_type = item.dynamic.value
                            value_type = value_type(sub_key) if callable(value_type) else value_type
                            if item.dynamic.only_true and not item_value:
                                continue
                        else:
                            sub_field = next((f for f in item.fields if isinstance(f, Field)
                                              and f.key == sub_key), None)
                            if sub_field is None:
                                continue
                            value_type = sub_field.type
                        inner.append(sub_key, value_type.write(item_value, None))
                    if inner.entries or item.required:
                        block.append(item.key, inner)
            elif isinstance(item, Section):
                emit(item.items)

    emit(schema.fields)
    variant = schema.variants
    if variant is not None:
        case = merged.get(variant.field)
        if case in variant.cases:
            emit(variant.cases[case])
    return block


def _own_roles(schema: EntitySchema) -> frozenset[str]:
    roles: set[str] = set()
    for companion in schema.companions:
        roles |= set(getattr(companion, "own_roles", ()) or ())
    return frozenset(roles)


class Entities:
    """Servicio de entidades sobre un ``Workspace``, el ``SymbolIndex`` y el ``LocSync``.

    ``list`` y la comprobación de id ocupado siguen la **vista efectiva** (I7): todos los documentos
    del layout que el ``Workspace`` tiene abiertos (nuevos, sucios, borrados y también los limpios,
    que pueden ser lo recién guardado y aún no releído por el índice) se enumeran con el layout y ganan
    sobre el índice; el resto sale del índice. Así lo creado y no guardado sale, lo borrado no, un
    ``undo`` lo devuelve y tras guardar sigue saliendo aunque el índice vaya por detrás.
    ``create``, ``duplicate``, ``rename``, ``move_to_group``, ``delete`` y ``restore_vanilla`` abren su
    propia transacción (``undo.create_<kind>`` y compañía), I5.
    """

    def __init__(self, ws: Workspace, index, loc: LocSync) -> None:
        self.ws = ws
        self.index = index
        self.loc = loc

    def _schema(self, kind: str) -> EntitySchema:
        return registry.get(kind)

    def _provides(self, schema: EntitySchema) -> str:
        return schema.provides or schema.kind

    def _ctx(self) -> CheckContext:
        return CheckContext(self.ws, self.index, self.loc)

    def check_context(self) -> CheckContext:
        """Contexto de lectura para ``Record.issues`` y los compañeros (leer no escribe, I4)."""
        return self._ctx()

    # --- vista efectiva (I7) ------------------------------------------------------------

    def _layout_touches(self, schema: EntitySchema, rel: VPath) -> bool:
        """True si ``rel`` es un archivo que el layout de ``schema`` recorre."""
        touches = getattr(schema.layout, "touches", None)
        return bool(touches is not None and touches(rel))

    def _open_handles(self, schema: EntitySchema) -> list:
        """Documentos abiertos del layout (con o sin cambios, también lápidas): la parte de la vista
        efectiva que el índice puede no conocer todavía (decisión 4 del informe)."""
        return [handle for handle in self.ws.documents() if self._layout_touches(schema, handle.rel)]

    def _underlying(self, rel: VPath):
        """Documento del archivo que el juego cargaría sin la copia del mod (juego o dependencia), leído
        sin pasar por el ``Workspace``; None si no hay. Leer no escribe (I4)."""
        from ..project.codecs import parse_bytes

        vfs = self.ws.vfs
        for entry in vfs.stack(rel):
            if entry.layer.kind is LayerKind.MOD or vfs.hidden_by_replace_path(entry):
                continue
            try:
                return parse_bytes(entry.path.read_bytes()).document
            except OSError:
                return None
        return None

    def _effective_document(self, handle):
        """``(documento, es_el_de_debajo)`` de un documento abierto: el suyo o, si es una lápida, el del
        juego que vuelve a ganar; ``(None, False)`` si no se ve nada."""
        if not handle.deleted:
            return handle.model.document, False
        underlying = self._underlying(handle.rel)
        return underlying, underlying is not None

    def _indexed(self, schema: EntitySchema) -> bool:
        index = self.index
        if index is None:
            return False
        try:
            return self._provides(schema) in index.kinds()
        except Exception:  # noqa: BLE001 - un índice falso puede no saberlo
            return True

    def _parent(self, schema: EntitySchema, document, ident: str) -> str | None:
        parent_of = getattr(schema.layout, "parent_of", None)
        return parent_of(document, ident) if parent_of is not None else None

    def _ident_exists(self, schema: EntitySchema, ident: str) -> bool:
        """True si ``ident`` ya está ocupado en la vista efectiva (índice + documentos abiertos)."""
        return any(item.ref.ident == ident for item in self.list(schema.kind))

    # --- leer ---------------------------------------------------------------------------

    def list(self, kind: str, *, view: str | None = None) -> list[EntitySummary]:
        """Registros de ``kind`` en la vista efectiva (I7): el índice, con los documentos abiertos
        encima (lo creado sin guardar sale; lo borrado, no; lo guardado sigue saliendo). Con ``view``,
        solo los que su filtro admite. Sin el tipo en el índice, se recorren los archivos del layout."""
        schema = self._schema(kind)
        summaries: list[EntitySummary] = []
        if self._indexed(schema):
            for symbol in self.index.symbols(self._provides(schema)):
                if not self._layout_touches(schema, symbol.rel):
                    continue   # mismo tipo de símbolo en otro archivo (static_modifiers.txt…)
                parent = None
                if isinstance(schema.layout, GroupedIn) and schema.layout.level > 0:
                    parent = (getattr(symbol, "attrs", None) or {}).get("group")
                summaries.append(EntitySummary(RecordRef(kind, symbol.name), symbol.rel, parent))
        else:
            for entry in schema.layout.files(self.ws.vfs):
                handle = self.ws.peek(entry.rel)
                if handle is not None:
                    continue   # lo pone el bucle de abajo
                try:
                    handle = self.ws.open(entry.rel)
                except (FileNotFoundError, OSError):
                    continue
                summaries.extend(self._summaries_of(schema, kind, handle.model.document, handle.rel))
        open_keys: set[str] = set()
        for handle in self._open_handles(schema):
            open_keys.add(handle.rel.key)
            summaries = [item for item in summaries if item.rel.key != handle.rel.key]
            document, _ = self._effective_document(handle)
            if document is None:
                continue
            summaries.extend(self._summaries_of(schema, kind, document, handle.rel))
        summaries.sort(key=lambda item: item.ref.ident)
        if view is not None:
            spec = next((candidate for candidate in schema.views if candidate.key == view), None)
            if spec is None:
                raise KeyError(f"vista desconocida: {view}")
            summaries = [item for item in summaries if spec.filter(self.open(item.ref))]
        return summaries

    def _summaries_of(self, schema, kind, document, rel) -> list[EntitySummary]:
        found = []
        grouped = isinstance(schema.layout, GroupedIn) and schema.layout.level > 0
        if grouped:
            for group, block, _ in schema.layout.groups(document):
                for child in block.entries:
                    if child.key is not None and isinstance(child.value, Block) and not child.key.is_date():
                        found.append(EntitySummary(RecordRef(kind, child.key.text), rel, group))
            return found
        for ident, _, _ in schema.layout.entries(document, rel):
            found.append(EntitySummary(RecordRef(kind, ident), rel))
        return found

    def _rel_of(self, schema: EntitySchema, ident: str, ref_rel: VPath | None) -> VPath:
        if ref_rel is not None:
            return VPath.of(ref_rel)
        for handle in self._open_handles(schema):
            document, _ = self._effective_document(handle)
            if document is not None and any(found == ident for found, _, _ in
                                            schema.layout.entries(document, handle.rel)):
                return handle.rel
        if self._indexed(schema):
            for symbol in self.index.lookup(self._provides(schema), ident) or []:
                if self._layout_touches(schema, symbol.rel):
                    return symbol.rel
        for entry in schema.layout.files(self.ws.vfs):
            try:
                document = self.ws.open(entry.rel).model.document
            except (FileNotFoundError, OSError):
                continue
            if any(found == ident for found, _, _ in schema.layout.entries(document, entry.rel)):
                return entry.rel
        rel, _ = schema.layout.target_for_new(None, ident, {"group": "_"})
        return rel

    def open(self, ref: RecordRef) -> Record:
        """Registro vivo de ``ref``: abre el documento efectivo si hace falta. Leer no escribe (I4).

        Si el documento es la lápida de una copia del mod y el juego tiene el archivo, el registro se
        lee del archivo del juego; mutarlo revive el documento (ver ``Record``)."""
        schema = self._schema(ref.kind)
        rel = self._rel_of(schema, ref.ident, ref.rel)
        handle = self.ws.peek(rel)
        document = None
        if handle is not None and handle.deleted:
            document = self._underlying(rel)
            if document is None:
                raise FileNotFoundError(str(rel))
        else:
            handle = self.ws.open(rel)
        source = document if document is not None else handle.model.document
        for ident, block, entry in schema.layout.entries(source, rel):
            if ident == ref.ident:
                if document is not None:
                    origin = LayerKind.GAME
                else:
                    origin = None if handle.origin is None else handle.origin.layer.kind
                return Record(schema, RecordRef(ref.kind, ident, rel), handle, block, origin,
                              ws=self.ws, index=self.index, entry=entry, document=document)
        raise KeyError(f"{ref.kind}:{ref.ident} no está en {rel}")

    def parent(self, ref: RecordRef) -> str | None:
        """Grupo del registro en un ``GroupedIn`` de nivel 1 (la cultura → su grupo); None si no tiene."""
        record = self.open(ref)
        document = record._document if record._document is not None else record.handle.model.document
        return self._parent(record.schema, document, ref.ident)

    def where_used(self, ref: RecordRef) -> list[SymbolRef]:
        """Referencias del índice a este registro (``index.refs_to``) sin las de sus compañeros, que
        las mantiene el propio motor (``peace_order``, la matriz de rebeldes); leer no escribe (I4)."""
        schema = self._schema(ref.kind)
        if self.index is None:
            return []
        own = _own_roles(schema)
        uses = self.index.refs_to(self._provides(schema), ref.ident)
        # Una fila propia («junta = junta») también nombra al registro como destino en la misma línea: es suya.
        owned = {(use.rel.key, use.line) for use in uses if use.role in own}
        return [use for use in uses if use.role not in own and (use.rel.key, use.line) not in owned]

    def origin_of(self, ref: RecordRef) -> str:
        """Cinta de origen de §13.5: ``"game"`` (se copiará al guardar), ``"mod"``, ``"mod_over_game"``
        (el mod sustituye al juego) o ``"new"``."""
        return self._origin(self.open(ref))

    def _origin(self, record: Record) -> str:
        handle = record.handle
        if record._document is not None:
            return "game"
        if handle.origin is None:
            return "new"
        if handle.origin.layer.kind is not LayerKind.MOD:
            return "game"
        vfs = self.ws.vfs
        if any(entry.layer.kind is not LayerKind.MOD for entry in vfs.stack(handle.rel)):
            return "mod_over_game"
        return "mod"

    # --- escribir -----------------------------------------------------------------------

    def _require_editable(self, schema: EntitySchema) -> None:
        if not schema.editable:
            raise ReadOnlySchemaError(f"{schema.kind} es de solo lectura")

    def _container(self, schema: EntitySchema, document, path) -> Block:
        container = path.resolve(document)
        if container is None:
            raise InvalidIdentError("no_group", "")
        return container

    def create(self, kind: str, ident: str, values: dict | None = None, *,
               texts: Mapping[str, Mapping[str, str]] | None = None) -> RecordRef:
        """Crea un registro en una transacción (archivo + compañeros + claves de localización).

        Un id inválido o ya existente lanza ``InvalidIdentError`` sin cambiar nada. ``texts``:
        ``{clave: {lang: texto}}`` de las claves de ``loc`` (``LocSync.ensure``). En un ``GroupedIn``
        de nivel 1, ``values["group"]`` dice el grupo (``InvalidIdentError("no_group")`` si falta).
        """
        schema = self._schema(kind)
        self._require_editable(schema)
        problem = ident_problem(schema, ident)
        if problem is not None:
            raise InvalidIdentError(problem, ident)
        if self._ident_exists(schema, ident):
            raise InvalidIdentError("taken", ident)
        values = dict(values or {})
        try:
            rel, path = schema.layout.target_for_new(self._ctx(), ident, values)
        except ValueError:
            raise InvalidIdentError("no_group", ident) from None
        existing = self.ws.peek(rel)
        if path.parts:
            probe = existing if existing is not None and not existing.deleted else None
            document = probe.model.document if probe is not None else self._read_only_document(rel)
            if document is None or path.resolve(document) is None:
                raise InvalidIdentError("no_group", ident)
        with self.ws.transaction(f"undo.create_{kind}", kind=kind, ident=ident):
            block = self._build_block(schema, ident, values)
            handle = self.ws.open(rel, create=True)
            self.ws.touch(handle)   # la transacción captura el estado previo (I5)
            document = handle.model.document
            entry = schema.layout.insert(document, self._container(schema, document, path), ident, block)
            record = Record(schema, RecordRef(kind, ident, rel), handle, block,
                            None if handle.origin is None else handle.origin.layer.kind,
                            ws=self.ws, index=self.index, entry=entry)
            self._ensure_loc(schema, ident, texts)
            from .companions import EditContext

            for companion in schema.companions:
                companion.on_create(EditContext(self.ws, self.index, self.loc), record)
            self._reread(handle)
        return RecordRef(kind, ident, rel)

    def _read_only_document(self, rel: VPath):
        try:
            return self.ws.open(rel).model.document
        except (FileNotFoundError, OSError):
            return None

    def _build_block(self, schema: EntitySchema, ident: str, values: dict) -> Block:
        return build_block(schema, ident, values, self.index)

    def duplicate(self, ref: RecordRef, new_ident: str) -> RecordRef:
        """Copia un registro como ``new_ident`` («basar en…»), con sus claves de localización,
        en una transacción. En un ``GroupedIn`` la copia va al mismo grupo que el original."""
        schema = self._schema(ref.kind)
        self._require_editable(schema)
        problem = ident_problem(schema, new_ident)
        if problem is not None:
            raise InvalidIdentError(problem, new_ident)
        if self._ident_exists(schema, new_ident):
            raise InvalidIdentError("taken", new_ident)
        source = self.open(ref)
        source_document = source._document if source._document is not None else source.handle.model.document
        values = {}
        group = self._parent(schema, source_document, ref.ident)
        if group is not None:
            values["group"] = group
        rel, path = schema.layout.target_for_new(self._ctx(), new_ident, values)
        clone = self._clone_source_block(source)
        with self.ws.transaction(f"undo.duplicate_{ref.kind}", kind=ref.kind, ident=new_ident):
            handle = self.ws.open(rel, create=True)
            self.ws.touch(handle)   # la transacción captura el estado previo (I5)
            document = handle.model.document
            inserted = schema.layout.insert(document, self._container(schema, document, path), new_ident, clone)
            if schema.ident.mode == "field":
                inserted.value.set(schema.ident.value, new_ident)   # conserva las comillas del original
            record = Record(schema, RecordRef(ref.kind, new_ident, rel), handle, inserted.value,
                            None if handle.origin is None else handle.origin.layer.kind,
                            ws=self.ws, index=self.index, entry=inserted)
            self._copy_loc(schema, ref.ident, new_ident)
            from .companions import EditContext

            for companion in schema.companions:
                companion.on_create(EditContext(self.ws, self.index, self.loc), record)
            self._reread(handle)
        return RecordRef(ref.kind, new_ident, rel)

    def _reread(self, handle) -> None:
        """Vuelve a leer el documento tras insertar un registro, dentro de la misma transacción.

        Los nodos nuevos no tienen posición y los de ``_clone_source_block`` llevan las del archivo
        de origen (en ``governments.txt``, las de ``democracy`` para ``democracia2``): sin releer,
        los problemas y «ir al código» del registro nuevo señalarían líneas de otro registro.
        """
        from ..project.codecs import codec_for

        self.ws.replace_text(handle, codec_for(handle.kind).snapshot(handle.model))

    def delete(self, ref: RecordRef, *, force: bool = False) -> None:
        """Borra un registro en una transacción (compañeros y claves incluidas).

        Con usos en el índice y sin ``force`` lanza ``EntityInUseError`` (con ``.uses``) y no
        cambia nada. Las referencias que mantienen sus propios compañeros (``peace_order``, las filas
        de la matriz de rebeldes) no cuentan como usos: el borrado las quita.
        """
        schema = self._schema(ref.kind)
        self._require_editable(schema)
        uses = self.where_used(ref)
        if uses and not force:
            raise EntityInUseError(uses)
        record = self.open(ref)
        with self.ws.transaction(f"undo.delete_{ref.kind}", kind=ref.kind, ident=ref.ident):
            from .companions import EditContext

            for companion in schema.companions:
                companion.on_delete(EditContext(self.ws, self.index, self.loc), record)
            if isinstance(schema.layout, OnePerFile):
                self.ws.delete(record.ref.rel)
            else:
                record._touch()
                entry = record._entry
                container = parent_block(record.handle.model.document, entry) if entry is not None else None
                if container is None:
                    raise KeyError(f"{ref.kind}:{ref.ident} no tiene entrada dueña")
                container.remove_entry(entry)
            for spec in schema.loc:
                if spec.shared:
                    continue
                self.loc.delete(spec.template.replace("{id}", ref.ident))

    # --- renombrar (§15) ----------------------------------------------------------------

    def _ident_taken(self, schema: EntitySchema, ident: str) -> bool:
        """Como ``_ident_exists`` y, además, True si otro archivo define un símbolo del mismo tipo con ese
        nombre (un modificador de ``static_modifiers.txt``): los usos de los dos se confundirían."""
        if self._ident_exists(schema, ident):
            return True
        if self.index is None:
            return False
        try:
            lookup = getattr(self.index, "effective", None) or self.index.lookup
            symbols = lookup(self._provides(schema), ident)
        except Exception:  # noqa: BLE001 - un índice falso puede no saberlo
            return False
        return any(not self._layout_touches(schema, symbol.rel) for symbol in symbols or ())

    def _rename_error(self, record: Record, new_ident: str, found) -> Exception | None:
        """Por qué no se puede renombrar ``record`` a ``new_ident`` (la excepción, sin lanzarla), o None."""
        from .rename import BLOCKED_GAME_FILE, BLOCKED_READ_ONLY_FILE, BLOCKED_UNRESOLVED_USES, RenameBlockedError

        schema = record.schema
        if not schema.editable:
            return ReadOnlySchemaError(f"{schema.kind} es de solo lectura")
        problem = ident_problem(schema, new_ident)
        if problem is not None:
            return InvalidIdentError(problem, new_ident)
        if new_ident == record.ref.ident:
            return InvalidIdentError("unchanged", new_ident)
        layout = schema.layout
        if isinstance(layout, OnePerFile) and (found.moved is None or layout._ident(found.moved[1]) != new_ident):
            return InvalidIdentError("bad_chars", new_ident)   # el archivo nuevo no sería de esta entidad
        if self._ident_taken(schema, new_ident):
            return InvalidIdentError("taken", new_ident)
        if isinstance(layout, OnePerFile):
            # El archivo cambia de nombre con el id. Si el juego base tiene el viejo, el mod no puede ocultarlo
            # (sin vaciarlo, que es otra edición): la entidad vieja seguiría existiendo. Se bloquea, como el borrado.
            if self._origin(record) not in ("mod", "new"):
                return RenameBlockedError(BLOCKED_GAME_FILE, rel=str(record.handle.rel))
            target = found.moved[1]
            handle = self.ws.peek(target)
            below = next((entry for entry in self.ws.vfs.stack(target)
                          if entry.layer.kind is not LayerKind.MOD
                          and not self.ws.vfs.hidden_by_replace_path(entry)), None)
            if below is not None or (handle is not None and not handle.deleted) \
                    or (handle is None and self.ws.vfs.resolve(target) is not None):
                return InvalidIdentError("taken", new_ident)
        if found.read_only:
            return RenameBlockedError(BLOCKED_READ_ONLY_FILE, rel=str(next(iter(found.read_only.values()))))
        if found.unresolved:
            return RenameBlockedError(BLOCKED_UNRESOLVED_USES, uses=tuple(found.unresolved))
        return None

    def rename_plan(self, ref: RecordRef, new_ident: str):
        """Lo que haría ``rename(ref, new_ident)``, sin cambiar nada (I4): un ``RenamePlan`` con los usos por
        archivo, las claves de localización que cambian, los archivos que se copiarán del juego y, en
        ``error``, el motivo por el que se rechazaría (None si se puede). Sirve también con un id aún
        inválido (mientras se escribe): los usos no dependen del id nuevo."""
        from . import rename as engine

        record = self.open(ref)
        found = engine.scan(self, record, new_ident)
        return engine.plan_of(found, record.ref, self._rename_error(record, new_ident, found))

    def rename(self, ref: RecordRef, new_ident: str) -> RecordRef:
        """Renombrado seguro (§15): cambia el id en la definición, en todos sus usos (``index.refs_to`` y
        lo abierto sin guardar), en lo que mantienen los compañeros (``on_rename``) y en las claves de
        localización que siguen la plantilla del esquema (las ``shared`` no). Una transacción
        ``undo.rename_<kind>``: un deshacer lo devuelve todo (I5). Solo cambia el token del id en cada sitio
        (I3); los archivos del juego que toca se copian al mod al guardar.

        Un id inválido, igual al actual o ya ocupado lanza ``InvalidIdentError``; lo que dejaría el
        renombrado a medias, ``RenameBlockedError`` (ver ``rename.py``). En los dos casos no cambia nada.
        Una unidad (``OnePerFile``) cambia además de archivo: ``units/<id>.txt``. Devuelve la referencia
        nueva."""
        from . import rename as engine
        from .companions import EditContext

        record = self.open(ref)
        schema = record.schema
        found = engine.scan(self, record, new_ident)
        error = self._rename_error(record, new_ident, found)
        if error is not None:
            raise error
        old = record.ref.ident
        rel = record.handle.rel
        with self.ws.transaction(f"undo.rename_{ref.kind}", kind=ref.kind, ident=old, new=new_ident):
            engine.apply_sites(self.ws, found)
            if found.moved is not None:
                rel = self._move_document(*found.moved)
            renamed = self.open(RecordRef(ref.kind, new_ident, rel))
            ctx = EditContext(self.ws, self.index, self.loc)
            for companion in schema.companions:
                companion.on_rename(ctx, renamed, old, new_ident)
            self._rename_loc(found.loc)
        return RecordRef(ref.kind, new_ident, rel)

    def _move_document(self, old_rel: VPath, new_rel: VPath) -> VPath:
        """El documento de ``old_rel`` pasa a ``new_rel`` con su texto actual (en la transacción de quien
        llama): el viejo va a la papelera al guardar y el nuevo se crea con los mismos bytes."""
        from ..project.codecs import codec_for

        handle = self.ws.open(old_rel)
        kind = handle.kind
        model, _ = codec_for(kind).load(codec_for(kind).snapshot(handle.model), new_rel)
        self.ws.delete(old_rel)
        return self.ws.create(new_rel, kind, model).rel

    def _rename_loc(self, changes) -> None:
        """Aplica los ``LocRename`` de un renombrado: mueve las filas del mod o copia las del juego."""
        from ..csvloc.model import LANGUAGE_CODES
        from .rename import LOC_COPY, LOC_RENAME

        for change, area in changes:
            if change.action == LOC_RENAME:
                self.loc.rename(change.old, change.new)
            elif change.action == LOC_COPY:
                # Los 13 idiomas de la fila: copiar una clave del juego no pierde sus otras traducciones.
                texts = {lang: self.loc.text(change.old, lang) for lang in LANGUAGE_CODES}
                self.loc.ensure({change.new: {lang: text for lang, text in texts.items() if text}}, area=area)

    # --- grupos (§14.13) ----------------------------------------------------------------

    def group_kind(self, kind: str) -> str | None:
        """El ``kind`` de los grupos de un esquema ``GroupedIn`` de nivel 1 (``culture`` →
        ``culture_group``): el esquema de nivel 0 del mismo archivo. None si ``kind`` no va en grupos."""
        layout = self._schema(kind).layout
        if not isinstance(layout, GroupedIn) or layout.level == 0:
            return None
        for schema in registry.all_schemas():
            other = schema.layout
            if isinstance(other, GroupedIn) and other.level == 0 \
                    and VPath.of(other.path).key == VPath.of(layout.path).key:
                return schema.kind
        return None

    def groups(self, kind: str) -> list[str]:
        """Grupos donde puede ir un registro de ``kind`` (``GroupedIn`` de nivel 1), en orden de archivo y
        también los vacíos, en la vista efectiva (I7). Lista vacía si ``kind`` no va en grupos."""
        layout = self._schema(kind).layout
        if not isinstance(layout, GroupedIn) or layout.level == 0:
            return []
        rel = VPath.of(layout.path)
        handle = self.ws.peek(rel)
        if handle is not None and handle.deleted:
            document = self._underlying(rel)
        else:
            document = self._read_only_document(rel)
        return [] if document is None else [name for name, _, _ in layout.groups(document)]

    def move_to_group(self, ref: RecordRef, group: str) -> RecordRef:
        """Mueve un registro de un ``GroupedIn`` de nivel 1 (una cultura) al final de ``group``, en una
        transacción ``undo.move_<kind>``. El bloque se quita y se añade con su texto intacto: comentarios,
        sangría y formato (§14.13, I3); el resto del archivo no cambia.

        ``InvalidIdentError("no_group")`` si el grupo no existe; ``ValueError`` si el esquema no va en
        grupos. Si ya está en ``group`` no hace nada (ni transacción ni paso de deshacer)."""
        schema = self._schema(ref.kind)
        self._require_editable(schema)
        layout = schema.layout
        if not isinstance(layout, GroupedIn) or layout.level == 0:
            raise ValueError(f"{ref.kind} no va en grupos")
        record = self.open(ref)
        document = record._document if record._document is not None else record.handle.model.document
        if not any(name == group for name, _, _ in layout.groups(document)):
            raise InvalidIdentError("no_group", group)
        if self._parent(schema, document, ref.ident) == group:
            return record.ref
        with self.ws.transaction(f"undo.move_{ref.kind}", kind=ref.kind, ident=ref.ident, group=group):
            record._touch()   # si se veía el archivo del juego bajo una lápida, lo revive
            document = record.handle.model.document
            source = parent_block(document, record._entry)
            target = next(block for name, block, _ in layout.groups(document) if name == group)
            source.move(record._entry, to=target)
            self._reread(record.handle)
        return RecordRef(ref.kind, ref.ident, record.handle.rel)

    def _vanilla_entry(self, record: Record):
        """``(documento del juego, entrada del registro en él)`` si el registro se ve desde el mod o con
        cambios y el juego (o una dependencia) tiene su versión; None si no."""
        handle = record.handle
        if record._document is not None:
            return None   # ya se está viendo el del juego
        from_mod = handle.origin is not None and handle.origin.layer.kind is LayerKind.MOD
        if not from_mod and not handle.dirty:
            return None
        underlying = self._underlying(handle.rel)
        if underlying is None:
            return None
        for ident, _, entry in record.schema.layout.entries(underlying, handle.rel):
            if ident == record.ref.ident:
                return underlying, entry
        return None

    def can_restore_vanilla(self, ref: RecordRef) -> bool:
        """True si el registro está en el mod (o tiene cambios) y el juego tiene su versión."""
        try:
            return self._vanilla_entry(self.open(ref)) is not None
        except (KeyError, FileNotFoundError):
            return False

    def restore_vanilla(self, ref: RecordRef) -> None:
        """Vuelve a la versión del juego (§10.5), en una transacción ``undo.restore_vanilla``.

        - ``OnePerFile`` con copia en el mod: la copia va a la papelera al guardar; entretanto ``list`` y
          ``open`` leen el archivo del juego de debajo de la lápida (límite de CONTINUAR §6, resuelto).
        - Documento del juego con cambios sin guardar: se revierte a lo del disco (queda limpio).
        - Archivo único (gobiernos, CB…) copiado en el mod: el bloque del registro se sustituye por el
          del juego, con su formato exacto; el resto del archivo no cambia.

        ``KeyError`` si no hay versión del juego que restaurar; no cambia nada.
        """
        from ..project.codecs import parse_bytes

        schema = self._schema(ref.kind)
        self._require_editable(schema)
        record = self.open(ref)
        found = self._vanilla_entry(record)
        if found is None:
            raise KeyError(f"{ref.kind}:{ref.ident} no tiene versión en el juego base")
        underlying, vanilla_entry = found
        handle = record.handle
        from_mod = handle.origin is not None and handle.origin.layer.kind is LayerKind.MOD
        with self.ws.transaction("undo.restore_vanilla", kind=ref.kind, ident=ref.ident):
            if not from_mod:
                self.ws.revert(handle.rel)
                return
            if isinstance(schema.layout, OnePerFile):
                self.ws.delete(handle.rel)
                return
            record._touch()
            vanilla = next(entry for entry in self.ws.vfs.stack(handle.rel)
                           if entry.layer.kind is not LayerKind.MOD and not self.ws.vfs.hidden_by_replace_path(entry))
            reparsed = parse_bytes(vanilla.path.read_bytes()).document
            fresh = follow_path(reparsed, entry_path(underlying, vanilla_entry))
            record._entry.value = fresh.value
            self._reread(record.handle)

    # --- localización -------------------------------------------------------------------

    def _loc_pairs(self, schema: EntitySchema, ident: str) -> dict[str, str]:
        """Clave de localización → área, agrupada por ``LocSpec``."""
        pairs: dict[str, str] = {}
        for spec in schema.loc:
            pairs[spec.template.replace("{id}", ident)] = spec.area
        return pairs

    def _ensure_loc(self, schema: EntitySchema, ident: str,
                    texts: Mapping[str, Mapping[str, str]] | None) -> None:
        by_area: dict[str, dict] = {}
        for key, area in self._loc_pairs(schema, ident).items():
            by_area.setdefault(area, {})[key] = dict((texts or {}).get(key, {}) or {})
        for area, keys in by_area.items():
            self.loc.ensure(keys, area=area)

    def _copy_loc(self, schema: EntitySchema, old_ident: str, new_ident: str) -> None:
        """Copia los textos de las claves viejas a las nuevas (las que falten, sin texto)."""
        by_area: dict[str, dict] = {}
        for spec in schema.loc:
            if spec.shared:
                continue
            old_key = spec.template.replace("{id}", old_ident)
            new_key = spec.template.replace("{id}", new_ident)
            copied = {}
            for lang in getattr(self.loc, "languages", ("en", "es")):
                existing = self.loc.text(old_key, lang)
                if existing:
                    copied[lang] = existing
            by_area.setdefault(spec.area, {})[new_key] = copied
        for area, keys in by_area.items():
            self.loc.ensure(keys, area=area)

    def _clone_source_block(self, record: Record) -> Block:
        """El bloque de origen con su formato exacto (líneas en blanco y sangría incluidas).

        ``Block.clone`` es «sin formato de origen» por diseño (los tokens son privados y la copia
        se formatea según el destino, M2): para conservarlo se reparsea el texto del documento y
        se toma la entrada homóloga del documento reparseado (por su posición en el árbol, también
        dentro de un grupo), que lleva los tokens tal como se leyeron. Si no hay homóloga (archivo
        roto o sin entrada dueña), ``clone()``.
        """
        from ..project.codecs import codec_for, parse_bytes

        owner = record._entry
        if owner is None:
            return record.block.clone()
        if record._document is not None:
            # Visto desde debajo de una lápida: el texto es el del archivo del juego.
            document = record._document
            vfs = self.ws.vfs
            vanilla = next((entry for entry in vfs.stack(record.handle.rel)
                            if entry.layer.kind is not LayerKind.MOD and not vfs.hidden_by_replace_path(entry)),
                           None)
            if vanilla is None:
                return record.block.clone()
            data = vanilla.path.read_bytes()
        else:
            document = record.handle.model.document
            data = codec_for(record.handle.kind).snapshot(record.handle.model)
        path = entry_path(document, owner)
        reparsed = parse_bytes(data).document
        copied = follow_path(reparsed, path) if path is not None else None
        if copied is None or owner.key is None or copied.key is None \
                or copied.key.text != owner.key.text or not isinstance(copied.value, Block):
            return record.block.clone()
        return copied.value


__all__ = ["build_block", "Entities", "EntityInUseError", "EntitySummary", "InvalidIdentError", "ReadOnlySchemaError", "Record",
           "RecordRef", "ident_problem"]
