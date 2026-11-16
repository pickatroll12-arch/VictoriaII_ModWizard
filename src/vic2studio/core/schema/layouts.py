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

Contrato de la iteración 5 (el mapa): ``KeyedFiles`` (historias de provincia: el archivo entero es el
registro y su id es la clave del nombre), ``KeyedAcross`` (POPs: varios bloques por archivo en carpetas de
fecha), ``PairedKeys`` (climas), ``WholeFile`` (``default.map``) y ``Table`` (``adjacencies.csv``). De ellas
solo está hecho ``touches`` (un predicado sobre la ruta, que ya usan la navegación y ``Entities``); el resto
lanza ``NotImplementedError`` hasta que lo implemente la cadena A.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Protocol

from ..clausewitz.nodes import Block, Document, Entry, Scalar
from ..vfs.model import FileEntry
from ..vfs.paths import VPath
from ..vfs.rules import LoadMode, leading_int_key

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

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry | None:
        """Inserta ``block`` como ``ident`` en ``container`` según la política de colocación (§10.7). Devuelve la
        entrada dueña; None cuando el registro es la raíz del documento (``KeyedFiles``, ``WholeFile``)."""
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
    """Una entidad, dos entradas con la misma clave (``map/climate.txt``, H7): una con los modificadores y otra
    con la lista de provincias. Contrato de la iteración 5.

    Vanilla trae primero las 4 entradas de modificadores y después las 4 listas; el minijuego las alterna. Regla
    de lectura, la misma que ``core.map.groups`` y el extractor del índice: de las entradas de un nombre, la
    **lista** es la última cuyos valores son todos sueltos (y tiene alguno) y los **modificadores**, la primera
    que no es la lista. El registro (``entries``) es el bloque de modificadores; la lista se edita con
    ``ProvinceGroups(layout="paired")``. Un nombre con una sola entrada o con más de una lista da
    ``climate_layout``. En este archivo está prohibido ``Block.set(nombre)``: cambiaría la primera entrada sin
    mirar cuál es.
    """

    path: str
    merge: LoadMode = LoadMode.MAP_BUNDLE

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        raise NotImplementedError

    def touches(self, rel: VPath) -> bool:
        return VPath.of(rel).key == VPath.of(self.path).key

    def context_rels(self, ctx) -> list[VPath]:
        raise NotImplementedError

    def pair(self, doc: Document, ident: str) -> tuple[Entry | None, Entry | None]:
        """``(modificadores, lista)`` de ``ident``; None lo que falte."""
        raise NotImplementedError

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        """Un registro por nombre, en el orden de su primera aparición: ``(nombre, bloque de modificadores,
        su entrada)``. Un nombre que solo tiene la lista da un bloque vacío sin entrada (None)."""
        raise NotImplementedError

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        raise NotImplementedError

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        """Añade las dos entradas: ``ident = <block>`` tras la última de modificadores e ``ident = { }`` (la
        lista, vacía) al final. Devuelve la de modificadores."""
        raise NotImplementedError


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


# Qué copia cuenta cuando una clave está en dos archivos de un ``KeyedFiles``: la primera por ``rel.key`` (la
# misma que ``SymbolIndex`` da como efectiva). Cuál carga el juego es [verificar en juego] (wizard §23).
KEYED_WINNER = "first"


def ascii_name(text: str) -> str:
    """``text`` como parte de un nombre de archivo en ASCII: los acentos se transliteran (``Córdoba`` →
    ``Cordoba``), lo que no tiene equivalente se quita y el resultado pasa por ``rules.names.clean_file_name``
    (sin caracteres vetados en Windows ni punto o espacio final). Vacío si no queda nada. El id es lo que
    cuenta para el juego (H9); los acentos van en la localización (§23)."""
    raise NotImplementedError


@dataclass(frozen=True)
class KeyedFiles:
    """Un archivo por registro y el id es la **clave del nombre del archivo**: las historias de provincia,
    ``history/provinces/<carpeta>/<id> - <Nombre>.txt``. Contrato de la iteración 5 (decisión 1).

    El registro es **el documento entero** (su bloque es la raíz y no tiene entrada dueña), a diferencia de
    ``OnePerFile``, cuyo registro es la única entrada ``<id> = { … }`` del archivo. La clave la da ``key``, por
    defecto ``vfs.rules.leading_int_key`` (el entero inicial del nombre, sin ceros a la izquierda), la misma
    función que usan la regla de carga ``history/provinces/**/*.txt`` y el extractor del índice: así las tres
    capas ven el mismo id. Cubre las formas reales del nombre: «549 - Berlin.txt» (2 703 de 2 705 en vanilla) y
    sin guion y con dos espacios (2: 1337 y 3246).

    **Enumeración.** Todos los ``*.txt`` bajo ``folder`` a cualquier profundidad (vanilla: 2 705 archivos, todos
    a un nivel, en 25 carpetas; si el juego baja más niveles o lee los sueltos de ``folder`` es [verificar en
    juego]). Un archivo sin clave en el nombre no es un registro. Los nombres de las carpetas no significan nada
    para el juego.

    **Duplicados.** Si una clave está en dos rutas (1396 y 1397 en vanilla, en ``asia`` e ``indonesia``; las dos
    copias de 1396 son distintas), cuenta la primera por ``rel.key`` (``KEYED_WINNER``, igual que el índice) y
    las demás dan ``province_history_duplicate``. ``RecordRef.rel`` distingue las copias: sin ``rel`` es la
    efectiva. El Studio nunca crea un duplicado: editar una historia del juego la copia al mod **en la misma
    ruta y con las mismas mayúsculas** (``VirtualFS.mod_target``), donde sustituye a la del juego por ruta.

    **Registro nuevo.** ``<folder>/<subcarpeta>/<new_name>``: la subcarpeta es ``values["folder"]``, o lo que
    diga ``subfolder_of(ctx, id)`` (provincias: la carpeta donde están las historias de su región), o
    ``default_subfolder``; el nombre usa ``values["name"]`` o ``name_of(ctx, id)`` pasado por ``ascii_name``
    (``"<id>.txt"`` si queda vacío). ``merge`` es ``KEYED_UNION``.
    """

    folder: str
    new_name: str = "{id} - {name}.txt"
    default_subfolder: str = "studio"
    subfolder_of: Callable[[CheckContext, str], str | None] | None = None
    name_of: Callable[[CheckContext, str], str | None] | None = None
    key: Callable[[VPath], str | None] = leading_int_key
    merge: LoadMode = LoadMode.KEYED_UNION

    def key_of(self, rel: VPath) -> str | None:
        """La clave (id) del archivo ``rel``; None si su nombre no la tiene."""
        return self.key(VPath.of(rel))

    def touches(self, rel: VPath) -> bool:
        rel = VPath.of(rel)
        folder = tuple(part.lower() for part in self.folder.split("/"))
        parts = tuple(part.lower() for part in rel.parts)
        return (len(parts) > len(folder) and parts[:len(folder)] == folder and rel.name.lower().endswith(".txt")
                and self.key_of(rel) is not None)

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        """Las historias efectivas (el ganador de la VFS por ruta), ordenadas por ``rel.key``; con las
        duplicadas."""
        raise NotImplementedError

    def context_rels(self, ctx) -> list[VPath]:
        raise NotImplementedError

    def effective(self, rels: Iterable[VPath]) -> dict[str, VPath]:
        """Clave → la copia que cuenta (``KEYED_WINNER``) entre ``rels``."""
        raise NotImplementedError

    def duplicates(self, rels: Iterable[VPath]) -> dict[str, list[VPath]]:
        """Clave → todas sus rutas, ordenadas por ``rel.key``, solo de las claves con más de una."""
        raise NotImplementedError

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        """``(key_of(rel), doc, None)``, una sola vez; nada si el nombre no tiene clave."""
        raise NotImplementedError

    def file_name(self, ident: str, name: str | None) -> str:
        """Nombre del archivo nuevo de ``ident`` (ASCII; ``"<id>.txt"`` sin nombre)."""
        raise NotImplementedError

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        """Ruta del archivo nuevo (ver la clase) y ``BlockPath()`` (la raíz). No comprueba que el id esté libre:
        lo hace ``Entities``."""
        raise NotImplementedError

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> None:
        """Pasa las entradas de ``block`` a la raíz de ``doc`` (el documento nuevo), en su orden. Devuelve None:
        el registro no tiene entrada dueña."""
        raise NotImplementedError


@dataclass(frozen=True)
class KeyedAcross:
    """Entidad repartida en bloques ``<clave> = { … }`` de varios archivos agrupados en carpetas:
    ``history/pops/<fecha>/<Zona>.txt`` (clave = id de provincia). Contrato de la iteración 5 (decisión 1).

    ``glob`` tiene la forma ``<base>/*/<patrón>``: el comodín del medio es la **carpeta** (la fecha) y forma parte
    del id. Cada bloque de la raíz cuya clave encaja entera con ``key_regex`` es un registro con id
    ``"<carpeta>:<clave>"`` (el nombre del símbolo ``pop_block`` del índice); si la clave se repite en el mismo
    archivo (2482 en ``1861.4.14/Australia.txt``), la aparición n-ésima (n ≥ 2) es ``"<carpeta>:<clave>#n"``
    (``core.domain.pops.pop_ident``). ``RecordRef.rel`` dice el archivo; sin ``rel``, el primero por ``rel.key``
    que tenga ese id. ``merge`` es ``UNION_BY_PATH``, como su regla de carga: editar un bloque copia su archivo
    entero al mod, a la misma ruta. Lo nuevo va a ``<base>/<carpeta>/<new_file>`` con el prefijo del proyecto.
    """

    glob: str
    key_regex: str = r"\d+"
    new_file: str = "00_{prefix}_pops.txt"
    merge: LoadMode = LoadMode.UNION_BY_PATH

    def _base(self) -> tuple[str, ...]:
        return tuple(part.lower() for part in self.glob.split("/")[:-2])

    def folder_of(self, rel: VPath) -> str | None:
        """La carpeta (fecha) de ``rel`` tal como está escrita; None si ``rel`` no es de esta disposición."""
        rel = VPath.of(rel)
        return rel.parts[-2] if self.touches(rel) else None

    def touches(self, rel: VPath) -> bool:
        rel = VPath.of(rel)
        base = self._base()
        parts = tuple(part.lower() for part in rel.parts)
        return (len(parts) == len(base) + 2 and parts[:len(base)] == base
                and fnmatch.fnmatch(parts[-1], self.glob.rsplit("/", 1)[-1].lower()))

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        raise NotImplementedError

    def context_rels(self, ctx) -> list[VPath]:
        raise NotImplementedError

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        """``(id, bloque, entrada)`` de cada bloque con clave válida, en orden de archivo."""
        raise NotImplementedError

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        """``<base>/<carpeta del id>/<new_file>`` y la raíz. ``ValueError`` si el id no es ``carpeta:clave``."""
        raise NotImplementedError

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        """Añade ``<clave> = <block>`` al final del documento (la clave es la parte del id tras la carpeta)."""
        raise NotImplementedError


@dataclass(frozen=True)
class WholeFile:
    """Un archivo que es un único registro: ``map/default.map``. Su bloque es la raíz del documento, no tiene
    entrada dueña y su id es fijo (``ident``). No se crea ni se borra. Contrato de la iteración 5."""

    path: str
    ident: str
    merge: LoadMode = LoadMode.MAP_BUNDLE

    def touches(self, rel: VPath) -> bool:
        return VPath.of(rel).key == VPath.of(self.path).key

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        raise NotImplementedError

    def context_rels(self, ctx) -> list[VPath]:
        raise NotImplementedError

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        """``(ident, doc, None)``."""
        raise NotImplementedError

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        raise NotImplementedError

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class Table:
    """Filas de un CSV del mapa (``map/adjacencies.csv``), una por registro. Contrato de la iteración 5.

    Declara dónde viven (para la referencia, la navegación y la validación), pero ``Entities`` no sirve
    registros de tabla: un ``Record`` es una vista sobre un bloque Clausewitz. Las filas se leen y se editan
    con su modelo sin pérdidas (``core.map.adjacency.AdjacencyTable``, ``core.map.definition.DefinitionTable``)."""

    path: str
    columns: tuple[str, ...]
    merge: LoadMode = LoadMode.MAP_BUNDLE

    def touches(self, rel: VPath) -> bool:
        return VPath.of(rel).key == VPath.of(self.path).key

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        raise NotImplementedError

    def context_rels(self, ctx) -> list[VPath]:
        raise NotImplementedError


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
