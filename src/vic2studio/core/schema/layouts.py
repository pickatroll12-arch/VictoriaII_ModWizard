"""Disposición de una entidad en los archivos (wizard §10.4).

``FileLayout`` describe dónde viven los registros de un ``kind``: cómo se leen
(``files`` sobre la VFS, ``entries`` sobre un documento), dónde se escribe lo
nuevo (``target_for_new``: archivo del mod y contenedor) y cómo se inserta
(``insert``). ``merge`` es el ``LoadMode`` de la VFS (§3.3) del archivo.

Solo ``SingleFile`` (gobiernos) y ``OnePerFile`` (unidades) llevan lógica real
en este corte; las demás disposiciones quedan como contrato.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..vfs.model import FileEntry
from ..vfs.paths import VPath
from ..vfs.rules import LoadMode

if TYPE_CHECKING:
    from ..clausewitz.nodes import Block, Document, Entry
    from ..vfs.vfs import VirtualFS
    from .validate import CheckContext


@dataclass(frozen=True)
class BlockPath:
    """Camino a un bloque dentro de un documento (para ``target_for_new``/``insert``).

    ``parts`` es la ruta de claves desde la raíz (``("political_decisions",)`` → el bloque de
    las decisiones); vacío, la raíz del documento.
    """

    parts: tuple[str | int, ...] = ()


class FileLayout(Protocol):
    """Protocolo de disposición (§10.4). Los métodos solo se llaman dentro de una transacción."""

    merge: LoadMode

    def files(self, vfs: VirtualFS) -> list[FileEntry]:
        """Archivos efectivos que contienen registros (el ganador de la VFS por ruta)."""
        ...

    def entries(self, doc: Document, rel: VPath) -> Iterator[tuple[str, Block, Entry | None]]:
        """Registros de ``doc``: ``(id, bloque, entrada dueña)``. La entrada es None cuando el
        bloque es la raíz del documento (``OnePerFile``: ``<id> = { … }`` como raíz)."""
        ...

    def target_for_new(self, ctx: CheckContext, ident: str, values: dict) -> tuple[VPath, BlockPath]:
        """Archivo del mod (vista efectiva) y contenedor donde irá una entidad nueva."""
        ...

    def insert(self, doc: Document, container: Block, ident: str, block: Block) -> Entry:
        """Inserta ``block`` como ``ident`` en ``container`` según la política de colocación (§10.7)."""
        ...


@dataclass(frozen=True)
class SingleFile:
    """Todas las entidades en un archivo (``common/governments.txt``), una entrada ``<id> = { … }``
    por registro. ``skip``: claves del archivo que no son de la entidad (``cb_types.txt`` sin
    ``peace_order``). ``merge`` es ``WHOLE_FILE``: la copia del mod sustituye a la del juego."""

    path: str
    skip: tuple[str, ...] = ()
    merge: LoadMode = LoadMode.WHOLE_FILE


@dataclass(frozen=True)
class OnePerFile:
    """Un documento por entidad (``units/<id>.txt``): el registro es el bloque raíz del archivo.

    ``regex`` captura el id del nombre de archivo (``^(?P<id>...)\\.txt$``); ``new_name`` es la
    plantilla del archivo nuevo (``"{id}.txt"``). ``merge`` es ``UNION_BY_PATH``: cada archivo
    del mod sustituye solo al suyo. Lo nuevo va a ``<folder>/<new_name>`` en el mod.
    """

    folder: str
    regex: str
    new_name: str
    recursive: bool = False
    merge: LoadMode = LoadMode.UNION_BY_PATH


@dataclass(frozen=True)
class PairedKeys:
    """Una entidad, dos entradas con la misma clave (``map/climate.txt``, H7): la primera con los
    modificadores y la segunda con la lista de provincias. En ese archivo está prohibido
    ``Block.set(nombre)``."""

    path: str
    merge: LoadMode = LoadMode.WHOLE_FILE


@dataclass(frozen=True)
class RepeatedKey:
    """Varias entradas de la misma clave en un archivo (``bookmarks.txt``: ``bookmark = { … }``);
    el id sale de ``id_field`` (bookmark → ``name``)."""

    path: str
    key: str
    id_field: str
    merge: LoadMode = LoadMode.WHOLE_FILE


@dataclass(frozen=True)
class GroupedIn:
    """Padre e hijos (``common/cultures.txt``): los grupos contienen las culturas como bloques
    hijos sin clave fija (``Children``, H18)."""

    path: str
    merge: LoadMode = LoadMode.WHOLE_FILE


@dataclass(frozen=True)
class Registry:
    """Registro de ids en un archivo (``common/countries.txt``): la entrada nueva se inserta justo
    antes de ``before`` (``dynamic_tags``), delante de la trivia que lo precede (H11)."""

    path: str
    before: str = "dynamic_tags"
    merge: LoadMode = LoadMode.WHOLE_FILE


@dataclass(frozen=True)
class NestedIn:
    """Entidades anidadas en un contenedor (``decisions/*.txt`` →
    ``political_decisions = { X = { … } }``). Lo nuevo va a ``new_file``."""

    glob: str
    container: str
    new_file: str
    merge: LoadMode = LoadMode.UNION_BY_PATH


@dataclass(frozen=True)
class TypedEntries:
    """Entidades de varios tipos en los mismos archivos (``events/*.txt``:
    ``country_event``/``province_event``, id = ``id``). Lo nuevo va a ``new_file``."""

    glob: str
    keys: tuple[str, ...]
    id_field: str
    new_file: str
    merge: LoadMode = LoadMode.UNION_BY_PATH


@dataclass(frozen=True)
class KeyedAcross:
    """Entidad repartida entre archivos (``history/pops/<fecha>/*.txt``): el ``RecordRef`` lleva
    ``rel`` porque una misma entidad (provincia) aparece en varios documentos."""

    glob: str
    key_regex: str
    merge: LoadMode = LoadMode.KEYED_UNION


@dataclass(frozen=True)
class Table:
    """Filas de un CSV (``map/definition.csv``), una por registro."""

    path: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Descriptor:
    """El descriptor ``<juego>/mod/<carpeta>.mod``: lo resuelve la VFS, fuera de las rutas
    relativas (``core/modfile``)."""
