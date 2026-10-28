"""Disposición de una entidad en los archivos (wizard §10.4).

``FileLayout`` describe dónde viven los registros de un ``kind``: cómo se leen
(``files`` sobre la VFS, ``entries`` sobre un documento), dónde se escribe lo
nuevo (``target_for_new``: archivo del mod y contenedor) y cómo se inserta
(``insert``). ``merge`` es el ``LoadMode`` de la VFS (§3.3) del archivo.

Además del protocolo de §10.4, cada disposición con lógica da ``touches(rel)``
(si un archivo es suyo: la vista efectiva de ``Entities`` y el filtro de los
símbolos del índice) y ``context_rels(ctx)`` (sus archivos en un
``ValidationContext``, para validar en segundo plano sin el ``Workspace``, I12).

Tienen lógica ``SingleFile`` (gobiernos, CB), ``OnePerFile`` (unidades),
``RepeatedKey`` (bookmarks), ``GroupedIn`` (culturas, ideologías, bienes) y
``NestedIn`` (tecnologías e invenciones, de solo lectura). Las demás quedan
como contrato para sus iteraciones.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol

from ..clausewitz.nodes import Block, Document, Entry, Scalar
from ..vfs.model import FileEntry
from ..vfs.paths import VPath
from ..vfs.rules import LoadMode

if TYPE_CHECKING:
    from ..vfs.vfs import VirtualFS
    from .validate import CheckContext


@dataclass(frozen=True)
class BlockPath:
    """Camino a un bloque dentro de un documento (para ``target_for_new``/``insert``).

    ``parts`` es la ruta de claves desde la raíz (``("political_decisions",)`` → el bloque de
    las decisiones); vacío, la raíz del documento.
    """

    parts: tuple[str | int, ...] = ()

    def resolve(self, document: Block) -> Block | None:
        """El bloque al que apunta en ``document`` (la primera entrada con cada clave); None si falta."""
        block = document
        for part in self.parts:
            entry = block.find(part) if isinstance(part, str) else (
                block.entries[part] if 0 <= part < len(block.entries) else None)
            if entry is None or not isinstance(entry.value, Block):
                return None
            block = entry.value
        return block


class FileLayout(Protocol):
    """Protocolo de disposición (§10.4). Los métodos solo se llaman dentro de una transacción."""

    merge: LoadMode

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        """Archivos efectivos que contienen registros (el ganador de la VFS por ruta)."""
        ...

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        """Registros de ``doc``: ``(id, bloque, entrada dueña)``; la entrada es None cuando el
        bloque es la raíz del documento (``OnePerFile`` da la entrada ``<id>`` como dueña)."""
        ...

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        """Archivo del mod (vista efectiva) y contenedor donde irá una entidad nueva."""
        ...

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        """Inserta ``block`` como ``ident`` en ``container`` según la política de colocación (§10.7)."""
        ...


def _glob_touches(glob: str, rel: VPath) -> bool:
    folder, _, pattern = glob.rpartition("/")
    parent = "/".join(rel.parts[:-1]).lower()
    return parent == folder.lower() and fnmatch.fnmatch(rel.name.lower(), pattern.lower())


@dataclass(frozen=True)
class SingleFile:
    """Todas las entidades en un archivo (``common/governments.txt``), una entrada ``<id> = { … }``
    por registro. ``skip``: claves del archivo que no son de la entidad (``cb_types.txt`` sin
    ``peace_order``). ``merge`` es ``WHOLE_FILE``: la copia del mod sustituye a la del juego."""

    path: str
    skip: tuple[str, ...] = ()
    merge: LoadMode = LoadMode.WHOLE_FILE

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        entry = vfs.resolve(self.path)
        return [] if entry is None else [entry]

    def touches(self, rel: VPath) -> bool:
        return VPath.of(rel).key == VPath.of(self.path).key

    def context_rels(self, ctx) -> list[VPath]:
        return [VPath.of(self.path)] if ctx.entry(VPath.of(self.path)) is not None else []

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        skip = {key.lower() for key in self.skip}
        for entry in doc.entries:
            if entry.key is None:
                continue
            key = entry.key.text
            if key.lower() in skip or not isinstance(entry.value, Block):
                continue
            yield key, entry.value, entry

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        # El documento efectivo (juego o mod): abrirlo y editarlo lo copia al mod al guardar (I1, I4).
        return VPath.of(self.path), BlockPath()

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        # La clave es el id y no tiene orden de esquema: lo nuevo va al final, como hace el usuario (H16).
        return container.append(ident, block)


@dataclass(frozen=True)
class OnePerFile:
    """Un documento por entidad (``units/<id>.txt``): el registro es el bloque ``<id> = { … }``,
    única entrada de la raíz. ``regex`` captura el id del nombre de archivo; ``new_name`` es la
    plantilla del archivo nuevo (``"{id}.txt"``). ``merge`` es ``UNION_BY_PATH``: cada archivo del
    mod sustituye solo al suyo. Lo nuevo va a ``<folder>/<new_name>`` en el mod.
    """

    folder: str
    regex: str
    new_name: str
    recursive: bool = False
    merge: LoadMode = LoadMode.UNION_BY_PATH

    def _ident(self, rel: VPath) -> str | None:
        match = re.search(self.regex, rel.name)
        if match is None:
            return None
        if "id" in match.groupdict():
            return match.group("id")
        return match.group(1)

    def _pattern(self) -> str:
        return f"*{PurePosixPath(self.new_name).suffix or '.txt'}"

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        return [entry for entry in vfs.list(self.folder, self._pattern(), recursive=self.recursive)
                if self._ident(entry.rel) is not None]

    def touches(self, rel: VPath) -> bool:
        rel = VPath.of(rel)
        folder = tuple(part.lower() for part in self.folder.split("/"))
        parts = tuple(part.lower() for part in rel.parts)
        if parts[:len(folder)] != folder or (not self.recursive and len(parts) != len(folder) + 1):
            return False
        return self._ident(rel) is not None

    def context_rels(self, ctx) -> list[VPath]:
        return [rel for rel in ctx.rels(self.folder, self._pattern()) if self.touches(rel)]

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        ident = self._ident(rel)
        if ident is None:
            return
        for entry in doc.entries:
            if entry.key is not None and entry.key.text == ident and isinstance(entry.value, Block):
                yield ident, entry.value, entry

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        return VPath.of(f"{self.folder}/{self.new_name.format(id=ident)}"), BlockPath()

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        # Documento nuevo: el registro es la única entrada de la raíz.
        return doc.append(ident, block)


@dataclass(frozen=True)
class PairedKeys:
    """Una entidad, dos entradas con la misma clave (``map/climate.txt``, H7): la primera con los
    modificadores y la segunda con la lista de provincias. En ese archivo está prohibido
    ``Block.set(nombre)``. Contrato (iteración 5)."""

    path: str
    merge: LoadMode = LoadMode.WHOLE_FILE


@dataclass(frozen=True)
class RepeatedKey:
    """Varias entradas de la misma clave en un archivo (``bookmarks.txt``: ``bookmark = { … }``);
    el id sale de ``id_field`` (bookmark → ``name``, sin comillas). Lo nuevo va al final del archivo
    efectivo, con el id ya escrito en su campo (lo pone ``Entities``)."""

    path: str
    key: str
    id_field: str
    merge: LoadMode = LoadMode.WHOLE_FILE

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        entry = vfs.resolve(self.path)
        return [] if entry is None else [entry]

    def touches(self, rel: VPath) -> bool:
        return VPath.of(rel).key == VPath.of(self.path).key

    def context_rels(self, ctx) -> list[VPath]:
        return [VPath.of(self.path)] if ctx.entry(VPath.of(self.path)) is not None else []

    def ident_of(self, block: Block) -> str | None:
        entry = block.find(self.id_field)
        if entry is None or not isinstance(entry.value, Scalar):
            return None
        return entry.value.text

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        for entry in doc.entries:
            if entry.key is None or entry.key.text.lower() != self.key.lower() \
                    or not isinstance(entry.value, Block):
                continue
            ident = self.ident_of(entry.value)
            if ident:
                yield ident, entry.value, entry

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        return VPath.of(self.path), BlockPath()

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        return container.append(self.key, block)


@dataclass(frozen=True)
class GroupedIn:
    """Padre e hijos (``common/cultures.txt``): los grupos contienen las culturas como bloques
    hijos sin clave fija (``Children``, H18).

    ``level=0``: los registros son los grupos (bloques de la raíz); ``level=1``: los hijos, es decir,
    los bloques dentro de cada grupo (las culturas, las ideologías, los bienes). Las claves escalares de
    un grupo (``leader``, ``unit``) son campos del grupo, nunca hijos. Lo nuevo de nivel 1 va al final
    del grupo que diga ``values["group"]`` (``target_for_new`` da su ``BlockPath``).
    """

    path: str
    level: int = 1
    merge: LoadMode = LoadMode.WHOLE_FILE

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        entry = vfs.resolve(self.path)
        return [] if entry is None else [entry]

    def touches(self, rel: VPath) -> bool:
        return VPath.of(rel).key == VPath.of(self.path).key

    def context_rels(self, ctx) -> list[VPath]:
        return [VPath.of(self.path)] if ctx.entry(VPath.of(self.path)) is not None else []

    def groups(self, doc: Document) -> Iterator[tuple[str, Block, Entry]]:
        for entry in doc.entries:
            if entry.key is not None and isinstance(entry.value, Block) and not entry.key.is_date():
                yield entry.key.text, entry.value, entry

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        for name, block, entry in self.groups(doc):
            if self.level == 0:
                yield name, block, entry
                continue
            for child in block.entries:
                if child.key is not None and isinstance(child.value, Block) and not child.key.is_date():
                    yield child.key.text, child.value, child

    def parent_of(self, doc: Document, ident: str) -> str | None:
        """El grupo que contiene al hijo ``ident`` (nivel 1); None si no está o en nivel 0."""
        if self.level == 0:
            return None
        for name, block, _ in self.groups(doc):
            for child in block.entries:
                if child.key is not None and child.key.text == ident and isinstance(child.value, Block):
                    return name
        return None

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        if self.level == 0:
            return VPath.of(self.path), BlockPath()
        group = values.get("group")
        if not group:
            raise ValueError("una entidad de un grupo necesita values['group']")
        return VPath.of(self.path), BlockPath((str(group),))

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        return container.append(ident, block)


@dataclass(frozen=True)
class Registry:
    """Registro de ids en un archivo (``common/countries.txt``): la entrada nueva se inserta justo
    antes de ``before`` (``dynamic_tags``), delante de la trivia que lo precede (H11). Contrato
    (iteración 6)."""

    path: str
    before: str = "dynamic_tags"
    merge: LoadMode = LoadMode.WHOLE_FILE


@dataclass(frozen=True)
class NestedIn:
    """Entidades anidadas en un contenedor (``decisions/*.txt`` →
    ``political_decisions = { X = { … } }``). Lo nuevo va a ``new_file``.

    ``container=""``: las entidades son los bloques de la raíz de cada archivo (``technologies/*.txt``,
    ``inventions/*.txt``). Aquí solo se leen (los esquemas de solo lectura); crear llega con las
    decisiones (iteración 7).
    """

    glob: str
    container: str
    new_file: str
    merge: LoadMode = LoadMode.UNION_BY_PATH

    def _folder_pattern(self) -> tuple[str, str]:
        folder, _, pattern = self.glob.rpartition("/")
        return folder, pattern

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        folder, pattern = self._folder_pattern()
        return [entry for entry in vfs.list(folder, pattern, recursive=False) if self.touches(entry.rel)]

    def touches(self, rel: VPath) -> bool:
        return _glob_touches(self.glob, VPath.of(rel))

    def context_rels(self, ctx) -> list[VPath]:
        folder, pattern = self._folder_pattern()
        return [rel for rel in ctx.rels(folder, pattern) if self.touches(rel)]

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        root: Block = doc
        if self.container:
            found = doc.find(self.container)
            if found is None or not isinstance(found.value, Block):
                return
            root = found.value
        for entry in root.entries:
            if entry.key is not None and isinstance(entry.value, Block) and not entry.key.is_date():
                yield entry.key.text, entry.value, entry

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        return VPath.of(self.new_file), BlockPath((self.container,) if self.container else ())

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        return container.append(ident, block)


@dataclass(frozen=True)
class TypedEntries:
    """Entidades de varios tipos en los mismos archivos (``events/*.txt``:
    ``country_event``/``province_event``, id = ``id``). Lo nuevo va a ``new_file``. Contrato
    (iteración 7)."""

    glob: str
    keys: tuple[str, ...]
    id_field: str
    new_file: str
    merge: LoadMode = LoadMode.UNION_BY_PATH


@dataclass(frozen=True)
class KeyedAcross:
    """Entidad repartida entre archivos (``history/pops/<fecha>/*.txt``): el ``RecordRef`` lleva
    ``rel`` porque una misma entidad (provincia) aparece en varios documentos. Contrato (iteración 5)."""

    glob: str
    key_regex: str
    merge: LoadMode = LoadMode.KEYED_UNION


@dataclass(frozen=True)
class Table:
    """Filas de un CSV (``map/definition.csv``), una por registro. Contrato (iteración 5)."""

    path: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Descriptor:
    """El descriptor ``<juego>/mod/<carpeta>.mod``: lo resuelve la VFS, fuera de las rutas
    relativas (``core/modfile``)."""


def entry_path(document: Block, target: Entry) -> tuple[int, ...] | None:
    """Índices desde la raíz hasta ``target`` (por identidad); None si no está en ``document``."""
    stack: list[tuple[Block, tuple[int, ...]]] = [(document, ())]
    while stack:
        block, prefix = stack.pop()
        for index, entry in enumerate(block.entries):
            if entry is target:
                return prefix + (index,)
            if isinstance(entry.value, Block):
                stack.append((entry.value, prefix + (index,)))
    return None


def parent_block(document: Block, target: Entry) -> Block | None:
    """El bloque que contiene ``target`` (por identidad); None si no está."""
    path = entry_path(document, target)
    if path is None:
        return None
    block = document
    for index in path[:-1]:
        block = block.entries[index].value
    return block


def follow_path(document: Block, path: tuple[int, ...]) -> Entry | None:
    """La entrada en ``path`` (de ``entry_path``) dentro de otro árbol con la misma forma."""
    block = document
    entry = None
    for index in path:
        if not isinstance(block, Block) or not 0 <= index < len(block.entries):
            return None
        entry = block.entries[index]
        block = entry.value
    return entry
