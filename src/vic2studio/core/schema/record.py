"""Registros y servicio de entidades (wizard §10.5, API pública fija de ENCARGO_MOTOR).

``RecordRef`` es la referencia ligera que la interfaz guarda y pasa al servicio
(nunca nodos); ``EntitySummary`` es la fila de una lista. ``Record`` es una
vista sobre el ``Block`` real de un documento abierto: lee y escribe con la API
del CST (§4.1) sin copiar datos, y toda mutación pasa por ``ws.touch``, que
exige una transacción abierta por quien llama (igual que editar a mano). Leer
(``get``, ``dynamic``, ``unknown``, ``issues``, ``loc_keys``) no escribe nada
(I4). ``Entities`` es el servicio: lista, abre, crea, duplica y borra
registros. ``create``/``duplicate``/``delete`` abren su propia transacción
(archivo + compañeros + claves de localización): un ``ws.undo()`` lo deshace
todo (I5).

La vista efectiva (I7): ``list`` sale del índice (que incluye los documentos
sin guardar) y ``open`` lee siempre a través del ``Workspace``.
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
from .fields import MISSING, DynamicKeys, Field, Group, Section
from .layouts import OnePerFile, SingleFile
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
    """Fila de una lista de entidades: la referencia y el archivo efectivo donde está."""

    ref: RecordRef
    rel: VPath


class InvalidIdentError(ValueError):
    """``create``/``duplicate`` con un id inválido (``.code``: ``empty``, ``bad_chars``,
    ``reserved``, ``out_of_range``…) o que ya existe (``.code``: ``taken``). No se cambia nada:
    ni documentos, ni deshacer, ni archivos."""

    def __init__(self, code: str, ident: str = "", **params) -> None:
        self.code = code
        self.ident = ident
        self.params = params
        super().__init__(f"{code}: {ident}" if ident else code)


class EntityInUseError(ValueError):
    """``delete`` de un registro con usos en el índice (``index.refs_to``) sin ``force``.

    ``.uses`` es la lista de ``SymbolRef`` que bloquean el borrado. No se cambia nada.
    """

    def __init__(self, uses: list[SymbolRef]) -> None:
        self.uses = uses
        super().__init__(f"en uso por {len(uses)} referencia(s)")


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


class Record:
    """Vista sobre el ``Block`` real; nunca copia datos (§10.5).

    Los métodos de lectura (``get``, ``dynamic``, ``unknown``, ``issues``, ``loc_keys``) no
    dejan el documento sucio ni escriben nada (I4). ``set`` y ``set_dynamic`` pasan por
    ``ws.touch``: exigen una transacción abierta por quien llama. ``None`` o ``MISSING`` quitan
    la entrada. Si el valor de un campo no encaja con su tipo, ``get`` devuelve el texto crudo
    en vez de fallar (el problema lo reporta ``issues`` como ``bad_type``).
    """

    schema: EntitySchema
    ref: RecordRef
    handle: DocHandle
    block: Block
    origin: LayerKind | None = None           # capa de la que se leyó (juego, mod, nuevo)

    def __init__(self, schema: EntitySchema, ref: RecordRef, handle: DocHandle, block: Block,
                 origin: LayerKind | None = None, *, ws: Workspace = None, index=None,
                 entry: Entry | None = None) -> None:
        self.schema = schema
        self.ref = ref
        self.handle = handle
        self.block = block
        self.origin = origin
        self._ws = ws                          # para touch (mutar exige transacción)
        self._index = index                    # catálogos de los DynamicKeys (B2)
        self._entry = entry                    # la entrada dueña en el documento (borrar)

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

    def _ordered_keys(self, fields: dict) -> tuple[str, ...]:
        return tuple(fields)

    def _field_of(self, key: str) -> Field | None:
        return self._index_schema()[0].get(key)

    def _find_entry(self, key: str) -> Entry | None:
        field = self._field_of(key)
        return self.block.find(key, ignore_case=field.ignore_case) if field is not None \
            else self.block.find(key)

    def _touch(self) -> None:
        if self._ws is None:
            raise RuntimeError("el Record no tiene Workspace (construido a mano): mutar exige una transacción")
        self._ws.touch(self.handle)

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
        transacción abierta por quien llama (I5)."""
        field = self._field_of(key)
        if field is None:
            raise KeyError(f"el esquema {self.schema.kind} no declara el campo {key!r}")
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
        self._touch()
        written = field.type.write(value, None)
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
                      ws=self._ws, index=self._index, entry=entries[index])

    def groups(self, key: str) -> list[Record]:
        """Vistas de todas las repeticiones del grupo ``key``."""
        return [Record(self.schema, self.ref, self.handle, entry.value, self.origin, ws=self._ws,
                       index=self._index, entry=entry)
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

    def _catalog(self, spec: DynamicKeys) -> frozenset[str]:
        """Claves del catálogo del ``DynamicKeys``: los símbolos de su ``key_kind`` en el índice.
        Sin índice, el catálogo es vacío y ninguna clave suelta cuenta como dinámica (B2)."""
        index = getattr(self, "_index", None)
        if index is None:
            return frozenset()
        return frozenset(index.names(spec.key_kind))

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
            if entry.key is None or entry.key.text in fixed or entry.key.text not in catalog:
                continue
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
            return frozenset(fields) | frozenset(groups)
        group = groups.get(container)
        return frozenset(field.key for field in group.fields if isinstance(field, Field)) \
            if group is not None else frozenset()

    def set_dynamic(self, name: str, key: str, value: object) -> None:
        """Escribe ``key`` de un ``DynamicKeys``. Con ``only_true`` y valor falso, borra la clave
        en vez de escribir ``= no`` (§10.10). Dentro de una transacción (I5)."""
        self._touch()
        spec, block, container = self._dynamic(name)
        if block is None:
            block = Block()
            fields, _, _ = self._index_schema()
            index = insertion_index(self.block, key=container, order=SchemaOrder(self._ordered_keys(fields)),
                                    first_dated=first_dated_index(self.block))
            self.block.insert(index, container, block)
        if value is None or value is MISSING or (spec.only_true and not value):
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
        block.insert(dynamic_insert_index(block, fixed=fixed), key, written)

    # --- resto del esquema --------------------------------------------------------------

    def children(self) -> list[Record]:
        """Registros hijos (``Children``): culturas dentro del grupo."""
        raise NotImplementedError

    def script(self, key: str):
        """Árbol de guion de ``key`` (lo edita ``core.script``, iteración 7)."""
        raise NotImplementedError

    def at(self, date):  # ClausewitzDate | None
        """Vista de historia en la fecha ``date`` (§10.6)."""
        raise NotImplementedError

    def unknown(self) -> list[Entry]:
        """Entradas que el esquema no declara: se conservan (I6) y salen en «Otros campos».

        Las claves de un ``DynamicKeys`` solo las reclama su catálogo (B2): una clave suelta que
        no está en el índice (``electoin``, ``foo_bar``) va a ``unknown`` y da ``unknown_field``.
        """
        fields, groups, dynamics = self._index_schema()
        found: list[Entry] = []
        covered_root = set(fields) | set(groups)
        free_dynamic = any(container is None for _, container in dynamics.values())
        root_catalog: frozenset[str] | None = None
        if free_dynamic:
            for spec, container in dynamics.values():
                if container is None:
                    root_catalog = self._catalog(spec)
        for entry in self.block.entries:
            if entry.key is None or entry.key.text in covered_root:
                continue
            if free_dynamic and root_catalog is not None and entry.key.text in root_catalog:
                continue
            found.append(entry)
        for key, group in groups.items():
            entry = self.block.find(key)
            if entry is None or not isinstance(entry.value, Block):
                continue
            covered = frozenset(field.key for field in group.fields if isinstance(field, Field))
            dynamic_spec = next((spec for name, (spec, container) in dynamics.items()
                                 if container == key), None)
            if dynamic_spec is not None:
                catalog = self._catalog(dynamic_spec)
            else:
                catalog = None
            for sub in entry.value.entries:
                if sub.key is None or sub.key.text in covered:
                    continue
                if catalog is not None and sub.key.text in catalog:
                    continue
                found.append(sub)
        return found

    def issues(self, ctx: CheckContext = None) -> list[Problem]:
        """Problemas de este registro: campos (tipo, repetición, obligatorios), validadores del
        esquema y claves desconocidas; sin tocar nada (I4)."""
        fields, _, _ = self._index_schema()
        problems: list[Problem] = []
        for key, field in fields.items():
            entries = self.block.find_all(key, ignore_case=field.ignore_case)
            if len(entries) > 1:
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


class Entities:
    """Servicio de entidades sobre un ``Workspace``, el ``SymbolIndex`` y el ``LocSync``.

    ``list`` y la comprobación de id ocupado siguen la **vista efectiva** (I7): los documentos
    que el ``Workspace`` tiene abiertos con cambios (nuevos, sucios o borrados) se enumeran con
    el layout sobre el documento efectivo y ganan sobre el índice; el resto sale del índice.
    Así lo creado y no guardado sale, lo borrado y no guardado no, y un ``undo`` lo devuelve.
    ``create``, ``duplicate`` y ``delete`` abren su propia transacción
    (``undo.create_<kind>`` y compañía), I5.
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

    # --- vista efectiva (I7) ------------------------------------------------------------

    def _layout_touches(self, schema: EntitySchema, rel: VPath) -> bool:
        """True si ``rel`` es un archivo que el layout de ``schema`` recorre."""
        layout = schema.layout
        if isinstance(layout, SingleFile):
            return rel.key == VPath.of(layout.path).key
        if isinstance(layout, OnePerFile):
            folder = tuple(layout.folder.split("/"))
            return tuple(rel.parts[:len(folder)]) == folder and layout._ident(rel) is not None
        return False

    def _changed_handles(self, schema: EntitySchema) -> list:
        """Documentos abiertos del layout con cambios (nuevos, sucios o borrados): la parte de
        la vista efectiva que el índice no puede conocer."""
        return [handle for handle in self.ws.documents()
                if (handle.dirty or handle.is_new or handle.deleted)
                and self._layout_touches(schema, handle.rel)]

    def _ident_exists(self, schema: EntitySchema, ident: str) -> bool:
        """True si ``ident`` ya está ocupado en la vista efectiva (índice + documentos abiertos)."""
        if self.index.exists(self._provides(schema), ident):
            return True
        for handle in self._changed_handles(schema):
            if handle.deleted:
                continue
            document = handle.model.document
            if any(found == ident for found, _, _ in schema.layout.entries(document, handle.rel)):
                return True
        return False

    # --- leer ---------------------------------------------------------------------------

    def list(self, kind: str, *, view: str | None = None) -> list[EntitySummary]:
        """Registros de ``kind`` en la vista efectiva (I7): el índice, con los documentos
        abiertos con cambios encima (lo creado sin guardar sale; lo borrado, no). Con ``view``,
        solo los que su filtro admite."""
        schema = self._schema(kind)
        summaries = [EntitySummary(RecordRef(kind, symbol.name), symbol.rel)
                     for symbol in self.index.symbols(self._provides(schema))]
        for handle in self._changed_handles(schema):
            summaries = [item for item in summaries if item.rel.key != handle.rel.key]
            if handle.deleted:
                continue
            document = handle.model.document
            for ident, _, _ in schema.layout.entries(document, handle.rel):
                summaries.append(EntitySummary(RecordRef(kind, ident), handle.rel))
        summaries.sort(key=lambda item: item.ref.ident)
        if view is not None:
            spec = next((candidate for candidate in schema.views if candidate.key == view), None)
            if spec is None:
                raise KeyError(f"vista desconocida: {view}")
            summaries = [item for item in summaries if spec.filter(self.open(item.ref))]
        return summaries

    def _rel_of(self, schema: EntitySchema, ident: str, ref_rel: VPath | None) -> VPath:
        if ref_rel is not None:
            return VPath.of(ref_rel)
        symbol = self.index.get(self._provides(schema), ident)
        if symbol is not None:
            return symbol.rel
        rel, _ = schema.layout.target_for_new(None, ident, {})
        return rel

    def open(self, ref: RecordRef) -> Record:
        """Registro vivo de ``ref``: abre el documento efectivo si hace falta. Leer no escribe (I4)."""
        schema = self._schema(ref.kind)
        rel = self._rel_of(schema, ref.ident, ref.rel)
        handle = self.ws.open(rel)
        document = handle.model.document
        for ident, block, entry in schema.layout.entries(document, rel):
            if ident == ref.ident:
                origin = None if handle.origin is None else handle.origin.layer.kind
                return Record(schema, RecordRef(ref.kind, ident, rel), handle, block, origin,
                              ws=self.ws, index=self.index, entry=entry)
        raise KeyError(f"{ref.kind}:{ref.ident} no está en {rel}")

    def where_used(self, ref: RecordRef) -> list[SymbolRef]:
        """Referencias del índice a este registro (``index.refs_to``); leer no escribe (I4)."""
        schema = self._schema(ref.kind)
        return self.index.refs_to(self._provides(schema), ref.ident)

    # --- escribir -----------------------------------------------------------------------

    def create(self, kind: str, ident: str, values: dict | None = None, *,
               texts: Mapping[str, Mapping[str, str]] | None = None) -> RecordRef:
        """Crea un registro en una transacción (archivo + compañeros + claves de localización).

        Un id inválido o ya existente lanza ``InvalidIdentError`` sin cambiar nada. ``texts``:
        ``{clave: {lang: texto}}`` de las claves de ``loc`` (``LocSync.ensure``).
        """
        schema = self._schema(kind)
        problem = ident_problem(schema, ident)
        if problem is not None:
            raise InvalidIdentError(problem, ident)
        if self._ident_exists(schema, ident):
            raise InvalidIdentError("taken", ident)
        values = dict(values or {})
        with self.ws.transaction(f"undo.create_{kind}", kind=kind, ident=ident):
            rel, _ = schema.layout.target_for_new(self._ctx(), ident, values)
            block = self._build_block(schema, ident, values)
            handle = self.ws.open(rel, create=True)
            self.ws.touch(handle)   # la transacción captura el estado previo (I5)
            document = handle.model.document
            schema.layout.insert(document, document, ident, block)
            record = Record(schema, RecordRef(kind, ident, rel), handle, block,
                            None if handle.origin is None else handle.origin.layer.kind,
                            ws=self.ws, index=self.index, entry=document.find(ident))
            self._ensure_loc(schema, ident, texts)
            from .companions import EditContext

            for companion in schema.companions:
                companion.on_create(EditContext(self.ws, self.index, self.loc), record)
            self._reread(handle)
        return RecordRef(kind, ident, rel)

    def _build_block(self, schema: EntitySchema, ident: str, values: dict) -> Block:
        """Bloque nuevo con los valores en el orden canónico del esquema (regla 6 de §10.7)."""
        merged: dict = {}
        if schema.template is not None:
            merged.update(dict(schema.template(ident, self.index)))
        merged.update(values)
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
        return block

    def duplicate(self, ref: RecordRef, new_ident: str) -> RecordRef:
        """Copia un registro como ``new_ident`` («basar en…»), con sus claves de localización,
        en una transacción."""
        schema = self._schema(ref.kind)
        problem = ident_problem(schema, new_ident)
        if problem is not None:
            raise InvalidIdentError(problem, new_ident)
        if self._ident_exists(schema, new_ident):
            raise InvalidIdentError("taken", new_ident)
        source = self.open(ref)
        with self.ws.transaction(f"undo.duplicate_{ref.kind}", kind=ref.kind, ident=new_ident):
            rel, _ = schema.layout.target_for_new(self._ctx(), new_ident, {})
            handle = self.ws.open(rel, create=True)
            self.ws.touch(handle)   # la transacción captura el estado previo (I5)
            document = handle.model.document
            schema.layout.insert(document, document, new_ident, self._clone_source_block(source))
            inserted = document.find(new_ident)
            record = Record(schema, RecordRef(ref.kind, new_ident, rel), handle,
                            inserted.value if inserted is not None else source.block,
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
        cambia nada.
        """
        schema = self._schema(ref.kind)
        uses = self.index.refs_to(self._provides(schema), ref.ident)
        if uses and not force:
            raise EntityInUseError(uses)
        record = self.open(ref)
        with self.ws.transaction(f"undo.delete_{ref.kind}", kind=ref.kind, ident=ref.ident):
            from .companions import EditContext

            for companion in schema.companions:
                companion.on_delete(EditContext(self.ws, self.index, self.loc), record)
            if isinstance(schema.layout, SingleFile):
                entry = record._entry
                if entry is None:
                    raise KeyError(f"{ref.kind}:{ref.ident} no tiene entrada dueña")
                self.ws.touch(record.handle)
                record.handle.model.document.remove_entry(entry)
            else:
                self.ws.delete(record.ref.rel)
            for spec in schema.loc:
                if spec.shared:
                    continue
                self.loc.delete(spec.template.replace("{id}", ref.ident))

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
        se toma la entrada homóloga del documento reparseado, que lleva los tokens tal como se
        leyeron. Si no hay homóloga (archivo roto o sin entrada dueña), ``clone()``.
        """
        from ..project.codecs import codec_for, parse_bytes

        owner = record._entry
        if owner is None:
            return record.block.clone()
        document = record.handle.model.document
        index = document.entries.index(owner)
        data = codec_for(record.handle.kind).snapshot(record.handle.model)
        reparsed = parse_bytes(data).document
        copied = reparsed.entries[index] if index < len(reparsed.entries) else None
        if copied is None or owner.key is None or copied.key is None \
                or copied.key.text != owner.key.text:
            copied = next((entry for entry in reparsed.entries
                           if entry.key is not None and owner.key is not None
                           and entry.key.text == owner.key.text and isinstance(entry.value, Block)),
                          None)
        if copied is None or not isinstance(copied.value, Block):
            return record.block.clone()
        return copied.value
