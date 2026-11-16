"""Renombrado seguro de entidades (wizard §15): el plan de solo lectura y su aplicación.

Renombrar es cambiar **el token del id** en cada sitio donde aparece, y nada más (I3): la definición (la
clave del bloque o, en un bookmark, el valor de ``name``), los usos que da el índice (``refs_to``) y lo que
mantienen los compañeros. ``scan`` recorre la vista efectiva sin cambiar nada (I4) y deja los sitios como
``(archivo, camino en el árbol, clave o valor)``; ``Entities.rename_plan`` los enseña y ``Entities.rename``
los aplica dentro de una transacción (I5).

**De dónde salen los usos.** El índice dice en qué archivos hay usos; las posiciones se vuelven a sacar del
texto **actual** de cada archivo (los mismos extractores sobre los bytes del documento, con lo sin guardar),
porque el índice va con retraso respecto del ``Workspace`` (decisión 4 de INFORME_IT4). Por eso se miran
también todos los documentos abiertos, aunque el índice aún no sepa que citan el id. Cada referencia señala
una entrada: se cambia su valor si es el id y su clave si lo es (las dos en ``junta = junta`` de la matriz de
rebeldes, que da dos referencias). El índice de ``history/pops`` solo guarda la primera aparición de cada
cultura por archivo: una entrada con la misma clave y el mismo valor en el mismo archivo es el mismo uso y
se cambia con ella.

**Lo que bloquea.** Una referencia que no es un token del archivo (un id que sale del nombre de un archivo)
o que está en un archivo que no se puede editar (errores de sintaxis, D17) dejaría el renombrado a medias:
se rechaza entero con ``RenameBlockedError`` y su motivo traducido. Igual que una unidad (``OnePerFile``)
que vive en el juego base: el archivo cambia de nombre con el id y un mod no puede ocultar el viejo, así que
la unidad vieja seguiría existiendo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..clausewitz.nodes import Block, Scalar
from ..index.model import SymbolRef
from ..vfs.model import DocKind, LayerKind
from ..vfs.paths import VPath
from .entity import EntitySchema
from .layouts import OnePerFile, entry_path, follow_path
from .types import LocKey

if TYPE_CHECKING:
    from .record import Entities, Record, RecordRef

ROLE_DEFINITION = "definition"           # papel del sitio que define la entidad (no es un uso del índice)
TOKEN_KEY = "key"
TOKEN_VALUE = "value"

# Qué pasa con una clave de localización (``LocRename.action``).
LOC_RENAME = "rename"                    # las filas del mod cambian de clave
LOC_COPY = "copy"                        # la clave es del juego (o la usa alguien más): fila nueva con sus textos
LOC_KEPT = "kept"                        # la clave nueva ya existe: se usa esa y la vieja se queda donde está

BLOCKED_GAME_FILE = "game_file"
BLOCKED_READ_ONLY_FILE = "read_only_file"
BLOCKED_UNRESOLVED_USES = "unresolved_uses"
BLOCKED_GUI_ELEMENT = "gui_element"     # el ejecutable busca los elementos de un .gui por su nombre (§17.4)


class RenameBlockedError(PermissionError):
    """El renombrado dejaría algo a medias y no se hace (``.code``): ``game_file`` (la entidad es un archivo
    del juego base, que el mod no puede ocultar), ``read_only_file`` (un archivo con usos no se puede editar)
    o ``unresolved_uses`` (usos que no son un token del archivo; van en ``.uses``). No se cambia nada.

    ``message(lang)`` da el motivo traducido (``schema.rename.blocked.<código>``)."""

    def __init__(self, code: str, *, uses: tuple[SymbolRef, ...] = (), **params) -> None:
        self.code = code
        self.uses = tuple(uses)
        self.params = params
        super().__init__(f"{code}: {params}" if params else code)

    def message(self, lang: str = "en") -> str:
        from ..texts import text

        return text(f"schema.rename.blocked.{self.code}", lang, count=len(self.uses), **self.params)


@dataclass(frozen=True)
class RenameUse:
    """Un token que cambia. ``line`` y ``column`` son las del texto actual del documento (None si la entrada
    aún no tiene posición). ``role``: el papel del índice (``casus_belli``, ``government``…) o
    ``definition``. ``own``: lo mantiene un compañero de la entidad (``peace_order``, la fila de la matriz):
    no sale en «dónde se usa»."""

    rel: VPath
    line: int | None
    column: int | None
    role: str
    own: bool = False


@dataclass(frozen=True)
class RenameFile:
    """Los cambios de un archivo. ``from_game``: hoy es del juego base (o de una dependencia) y se copiará al
    mod al guardar."""

    rel: VPath
    uses: tuple[RenameUse, ...]
    from_game: bool = False


@dataclass(frozen=True)
class LocRename:
    """Una clave de localización que sigue la plantilla del esquema: ``old`` → ``new`` según ``action``
    (``LOC_*``). ``rel``: el archivo donde gana hoy la vieja."""

    old: str
    new: str
    action: str
    rel: VPath


@dataclass(frozen=True)
class RenamePlan:
    """Lo que hará ``Entities.rename(ref, new_ident)``, sin hacerlo (P1).

    ``files``: la definición y los usos, por archivo. ``loc``: las claves de localización que cambian.
    ``moved``: ``(archivo viejo, archivo nuevo)`` si el archivo cambia de nombre con el id (unidades).
    ``error``: la excepción con la que ``rename`` lo rechazaría (``InvalidIdentError``,
    ``RenameBlockedError`` o ``ReadOnlySchemaError``), o None si se puede renombrar."""

    ref: RecordRef
    new_ident: str
    files: tuple[RenameFile, ...] = ()
    loc: tuple[LocRename, ...] = ()
    moved: tuple[VPath, VPath] | None = None
    error: Exception | None = None

    @property
    def copies(self) -> tuple[VPath, ...]:
        """Archivos del juego base que se copiarán al mod al guardar."""
        return tuple(item.rel for item in self.files if item.from_game)

    @property
    def uses(self) -> tuple[RenameUse, ...]:
        """Los usos (sin la definición), en orden de archivo y línea."""
        return tuple(use for item in self.files for use in item.uses if use.role != ROLE_DEFINITION)

    @property
    def allowed(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class Site:
    """Un token que cambia de ``old`` a ``new``: la clave o el valor de la entrada que está en ``path``
    (índices desde la raíz, ``layouts.entry_path``) del documento ``rel``."""

    rel: VPath
    path: tuple[int, ...]
    token: str
    old: str
    new: str
    role: str
    line: int | None = None
    column: int | None = None
    own: bool = False


@dataclass
class Scan:
    """Resultado de ``scan``: todo lo que ``rename`` necesita, ya decidido. Solo lectura."""

    schema: EntitySchema
    record: Record
    new_ident: str
    sites: dict[str, list[Site]] = field(default_factory=dict)          # por rel.key, en orden de hallazgo
    rels: dict[str, VPath] = field(default_factory=dict)
    from_game: set[str] = field(default_factory=set)                     # rel.key de lo que se copiará al mod
    read_only: dict[str, VPath] = field(default_factory=dict)            # archivos con sitios que no se editan
    unresolved: list[SymbolRef] = field(default_factory=list)            # usos que no son un token
    extra: list[SymbolRef] = field(default_factory=list)                 # usos que solo conocen los compañeros
    loc: list[tuple[LocRename, str]] = field(default_factory=list)       # (cambio, área de la LocSpec)
    moved: tuple[VPath, VPath] | None = None

    def add(self, site: Site) -> None:
        found = self.sites.setdefault(site.rel.key, [])
        self.rels.setdefault(site.rel.key, site.rel)
        if not any(other.path == site.path and other.token == site.token for other in found):
            found.append(site)


def _below_mod(vfs, rel: VPath):
    """La entrada de ``rel`` que el juego cargaría sin la copia del mod (juego o dependencia), o None."""
    return next((entry for entry in vfs.stack(rel)
                 if entry.layer.kind is not LayerKind.MOD and not vfs.hidden_by_replace_path(entry)), None)


def _from_game(ws, rel: VPath) -> bool:
    """True si el documento efectivo de ``rel`` es hoy del juego base o de una dependencia: editarlo lo copia
    al mod al guardar."""
    handle = ws.peek(rel)
    if handle is not None and not handle.deleted:
        origin = handle.origin
    else:
        origin = ws.vfs.resolve(rel) if handle is None else _below_mod(ws.vfs, rel)
    return origin is not None and origin.layer.kind is not LayerKind.MOD


def _source(ws, rel: VPath) -> bytes | None:
    """Bytes actuales del documento efectivo de ``rel`` si es Clausewitz; None si no lo es o no existe. Un
    documento abierto da su texto con lo sin guardar; uno sin abrir se lee de la VFS sin abrirlo (I4); bajo
    una lápida se ve el archivo del juego (I7)."""
    from ..project.codecs import codec_for, kind_for

    handle = ws.peek(rel)
    if handle is not None and not handle.deleted:
        if handle.kind is not DocKind.CLAUSEWITZ:
            return None
        return codec_for(handle.kind).snapshot(handle.model)
    entry = ws.vfs.resolve(rel) if handle is None else _below_mod(ws.vfs, rel)
    if entry is None or kind_for(entry.rel) is not DocKind.CLAUSEWITZ:
        return None
    try:
        return entry.path.read_bytes()
    except OSError:
        return None


def _fresh_refs(rel: VPath, data: bytes, kind: str, name: str) -> list[SymbolRef] | None:
    """Referencias a ``kind``/``name`` que los extractores del índice sacan de ``data`` (el texto actual de
    ``rel``); None si alguno falla."""
    from ..index.model import discover_extractors, extractors_for

    discover_extractors()
    found: list[SymbolRef] = []
    for spec in extractors_for(rel):
        if not spec.needs_data:
            continue
        try:
            _, refs = spec.fn(rel, data, LayerKind.MOD)
        except Exception:  # noqa: BLE001 - un extractor que no puede con el archivo no decide el renombrado
            return None
        found.extend(ref for ref in refs if ref.kind == kind and ref.name == name)
    return found


def _walk(document: Block):
    """``(entrada, camino)`` de todas las entradas de ``document``, sin recursión."""
    stack: list[tuple[Block, tuple[int, ...]]] = [(document, ())]
    while stack:
        block, prefix = stack.pop()
        for index, entry in enumerate(block.entries):
            path = prefix + (index,)
            yield entry, path
            if isinstance(entry.value, Block):
                stack.append((entry.value, path))


def _scan_uses(scan: Scan, entities: Entities, rel: VPath, index_refs: list[SymbolRef], kind: str, old: str,
               own: frozenset[str]) -> None:
    """Sitios de ``rel`` donde se usa ``old``, sobre su texto actual."""
    from ..index import parsing

    data = _source(entities.ws, rel)
    if data is None:
        scan.unresolved.extend(index_refs)   # no es un documento Clausewitz que se pueda reescribir
        return
    if old.encode("cp1252", "ignore") not in data:
        return
    refs = _fresh_refs(rel, data, kind, old)
    if refs is None:
        scan.unresolved.extend(index_refs)
        return
    if not refs:
        return
    try:
        entries = list(_walk(parsing.document(data)))
    finally:
        parsing.forget()
    at = {(entry.line, entry.column): (entry, path) for entry, path in entries}
    by_position: dict[tuple, list[SymbolRef]] = {}
    for ref in refs:
        by_position.setdefault((ref.line, ref.column), []).append(ref)
    before = len(scan.sites.get(rel.key, ()))
    twins: dict[str, str] = {}               # clave en minúsculas → papel: mismas clave y valor en el archivo
    for (line, column), group in by_position.items():
        entry, path = at.get((line, column), (None, None))
        value_hit = entry is not None and isinstance(entry.value, Scalar) and entry.value.text == old
        key_hit = entry is not None and entry.key is not None and entry.key.text == old
        if not value_hit and not key_hit:
            scan.unresolved.extend(group)
            continue
        is_own = any(ref.role in own for ref in group)   # la fila propia entera es del compañero (where_used)
        if value_hit:
            # Con dos referencias en la entrada («junta = junta»), la de la clave va antes que la del valor.
            role = group[-1].role
            scan.add(Site(rel, path, TOKEN_VALUE, old, scan.new_ident, role, line, column, is_own))
            if entry.key is not None:
                twins.setdefault(entry.key.text.lower(), role)
        # La clave solo es un uso si el valor no lo era o si la entrada da dos referencias.
        if key_hit and (not value_hit or len(group) > 1):
            scan.add(Site(rel, path, TOKEN_KEY, old, scan.new_ident, group[0].role, line, column, is_own))
    if twins:
        for entry, path in entries:
            if entry.key is None or not isinstance(entry.value, Scalar) or entry.value.text != old:
                continue
            role = twins.get(entry.key.text.lower())
            if role is not None:
                scan.add(Site(rel, path, TOKEN_VALUE, old, scan.new_ident, role, entry.line, entry.column,
                              role in own))
    if len(scan.sites.get(rel.key, ())) > before:
        _note_file(scan, entities.ws, rel)


def _note_file(scan: Scan, ws, rel: VPath) -> None:
    """Apunta si ``rel`` se copiará del juego y si no se puede editar (D17). Abre el documento (leer no
    escribe): ``rename`` lo necesita abierto de todos modos. Bajo una lápida no se abre nada: revivirla es
    editar."""
    scan.rels.setdefault(rel.key, rel)
    if _from_game(ws, rel):
        scan.from_game.add(rel.key)
    handle = ws.peek(rel)
    if handle is None:
        try:
            handle = ws.open(rel)
        except (FileNotFoundError, OSError):
            return
    if not handle.deleted and handle.read_only_reason is not None:
        scan.read_only.setdefault(rel.key, rel)


def _definition_sites(scan: Scan, record: Record, old: str, new: str) -> None:
    """El token que define la entidad y los campos ``LocKey`` del registro que siguen una plantilla de
    ``loc`` (``desc = "<id>_DESC"`` de un bookmark): cambian con el id para seguir a su clave."""
    schema = record.schema
    document = record._document if record._document is not None else record.handle.model.document
    rel = record.handle.rel
    id_field = schema.ident.value if schema.ident.mode == "field" else None
    target = record.block.find(id_field) if id_field is not None else record._entry
    path = entry_path(document, target) if target is not None else None
    if path is None:
        raise KeyError(f"{record.ref.kind}:{old} no tiene entrada dueña")
    token = TOKEN_VALUE if id_field is not None else TOKEN_KEY
    scan.add(Site(rel, path, token, old, new, ROLE_DEFINITION, target.line, target.column))
    templates = {spec.template.replace("{id}", old): spec.template.replace("{id}", new)
                 for spec in schema.loc if not spec.shared and "{id}" in spec.template}
    seen: set[str] = set()
    for item in record._index_schema()[0].values():
        if item.key in seen or item.key == id_field or not isinstance(item.type, LocKey):
            continue
        seen.add(item.key)
        entry = record.block.find(item.key)
        if entry is None or not isinstance(entry.value, Scalar) or entry.value.text not in templates:
            continue
        field_path = entry_path(document, entry)
        if field_path is not None:
            scan.add(Site(rel, field_path, TOKEN_VALUE, entry.value.text, templates[entry.value.text],
                          item.key, entry.line, entry.column, True))
    _note_file(scan, record._ws, rel)


def _loc_changes(entities: Entities, schema: EntitySchema, old: str, new: str) -> list[tuple[LocRename, str]]:
    """Las claves de las ``LocSpec`` no compartidas que existen, con lo que les pasará (ver ``LOC_*``)."""
    loc = entities.loc
    found: list[tuple[LocRename, str]] = []
    if loc is None or not new:
        return found
    for spec in schema.loc:
        if spec.shared:
            continue
        old_key = spec.template.replace("{id}", old)
        new_key = spec.template.replace("{id}", new)
        current = loc.entry(old_key) if old_key != new_key else None
        if current is None:
            continue
        if loc.entry(new_key) is not None:
            action = LOC_KEPT
        elif current.layer is LayerKind.MOD and not _key_has_other_uses(entities.index, old_key):
            action = LOC_RENAME
        else:
            action = LOC_COPY
        found.append((LocRename(old_key, new_key, action, current.rel), spec.area))
    return found


def _key_has_other_uses(index, key: str) -> bool:
    """True si algo más nombra la clave (el título de un evento, por ejemplo): se copia en vez de moverla."""
    if index is None:
        return False
    try:
        return bool(index.refs_to("loc_key", key))
    except Exception:  # noqa: BLE001 - un índice falso puede no saberlo
        return False


def scan(entities: Entities, record: Record, new_ident: str) -> Scan:
    """Recorre la vista efectiva y devuelve todo lo que cambiaría al renombrar ``record`` a ``new_ident``.
    No cambia nada (I4): abre documentos, pero no los toca."""
    from ..project.codecs import kind_for
    from .companions import EditContext
    from .record import _own_roles

    schema = record.schema
    old = record.ref.ident
    kind = schema.provides or schema.kind
    found = Scan(schema, record, new_ident)
    _definition_sites(found, record, old, new_ident)

    rels: dict[str, VPath] = {}
    index_refs: dict[str, list[SymbolRef]] = {}
    if entities.index is not None:
        for use in entities.index.refs_to(kind, old):
            rels.setdefault(use.rel.key, use.rel)
            index_refs.setdefault(use.rel.key, []).append(use)
    # Lo abierto puede citar el id sin que el índice lo sepa todavía (sin guardar, o recién guardado).
    for handle in entities.ws.documents():
        if not handle.deleted and handle.kind is DocKind.CLAUSEWITZ:
            rels.setdefault(handle.rel.key, handle.rel)
    rels.setdefault(record.handle.rel.key, record.handle.rel)
    own = _own_roles(schema)
    for key in sorted(rels):
        _scan_uses(found, entities, rels[key], index_refs.get(key, []), kind, old, own)

    ctx = EditContext(entities.ws, entities.index, entities.loc)
    for companion in schema.companions:
        extra = getattr(companion, "rename_uses", None)
        if extra is None:
            continue
        for use in extra(ctx, record, old):
            found.extra.append(use)
            _note_file(found, entities.ws, use.rel)

    found.loc = _loc_changes(entities, schema, old, new_ident)
    layout = schema.layout
    if isinstance(layout, OnePerFile) and new_ident:
        old_rel = record.handle.rel
        new_rel = VPath.of("/".join((*old_rel.parts[:-1], layout.new_name.format(id=new_ident))))
        if kind_for(new_rel) is DocKind.CLAUSEWITZ:
            found.moved = (old_rel, new_rel)
    return found


def plan_of(found: Scan, ref: RecordRef, error: Exception | None) -> RenamePlan:
    """El ``RenamePlan`` público de un ``Scan``."""
    by_rel: dict[str, list[RenameUse]] = {}
    for key, sites in found.sites.items():
        by_rel.setdefault(key, []).extend(
            RenameUse(site.rel, site.line, site.column, site.role, site.own) for site in sites)
    for use in found.extra:
        by_rel.setdefault(use.rel.key, []).append(RenameUse(use.rel, use.line, use.column, use.role, True))
    files = []
    for key in sorted(by_rel):
        uses = sorted(by_rel[key], key=lambda use: (use.role != ROLE_DEFINITION, use.line or 0, use.column or 0))
        files.append(RenameFile(found.rels[key], tuple(uses), key in found.from_game))
    return RenamePlan(ref, found.new_ident, tuple(files), tuple(change for change, _ in found.loc),
                      found.moved, error)


def apply_sites(ws, found: Scan) -> None:
    """Cambia cada token de ``found.sites`` (dentro de la transacción de quien llama). Solo cambia el token:
    la trivia, las comillas y el resto del archivo quedan byte a byte (I3). Si un sitio ya no está donde se
    vio, ``KeyError``: la transacción se deshace entera."""
    for key, sites in found.sites.items():
        rel = found.rels[key]
        handle = ws.peek(rel)
        if handle is None:
            handle = ws.open(rel)
        elif handle.deleted:
            handle = ws.open(rel, create=True)   # revive con el archivo del juego que se estaba viendo
        ws.touch(handle)
        document = handle.model.document
        for site in sites:
            entry = follow_path(document, site.path)
            node = None if entry is None else (entry.key if site.token == TOKEN_KEY else entry.value)
            if not isinstance(node, Scalar) or node.text != site.old:
                raise KeyError(f"{rel}: «{site.old}» ya no está donde se vio ({site.role})")
            if site.token == TOKEN_KEY:
                entry.key = Scalar(site.new, node.quoted)
            else:
                entry.value = Scalar(site.new, node.quoted)


__all__ = ["BLOCKED_GAME_FILE", "BLOCKED_GUI_ELEMENT", "BLOCKED_READ_ONLY_FILE", "BLOCKED_UNRESOLVED_USES", "LOC_COPY", "LOC_KEPT",
           "LOC_RENAME", "ROLE_DEFINITION", "LocRename", "RenameBlockedError", "RenameFile", "RenamePlan",
           "RenameUse"]
