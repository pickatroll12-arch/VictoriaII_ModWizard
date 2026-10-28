"""Registros y servicio de entidades (wizard §10.5, API pública fija de ENCARGO_MOTOR).

``RecordRef`` es la referencia ligera que la interfaz guarda y pasa al servicio
(nunca nodos); ``EntitySummary`` es la fila de una lista. ``Record`` es una
vista sobre el ``Block`` real de un documento abierto: lee y escribe con la API
del CST (§4.1) sin copiar datos, y toda mutación exige una transacción abierta
por quien llama (igual que ``ws.touch``). ``Entities`` es el servicio: lista,
abre, crea, duplica y borra registros sobre el ``Workspace``, el índice y la
sincronización de localización. ``create``/``duplicate``/``delete`` abren su
propia transacción (archivo + compañeros + claves: un ``ws.undo()`` lo deshace
todo), I5.

En esta fase son las firmas del contrato; la lógica llega en la fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .fields import MISSING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ..clausewitz.nodes import Block, Entry
    from ..clausewitz.nodes import ClausewitzDate
    from ..index.model import SymbolRef
    from ..locsync import LocSync
    from ..project.model import DocHandle
    from ..project.workspace import Workspace
    from ..validate.model import Problem
    from ..vfs.model import LayerKind
    from ..vfs.paths import VPath
    from .entity import EntitySchema, LocSpec
    from .validate import CheckContext


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


class Record:
    """Vista sobre el ``Block`` real; nunca copia datos (§10.5).

    Los métodos de lectura (``get``, ``dynamic``, ``unknown``, ``issues``, ``loc_keys``) no
    dejan el documento sucio ni escriben nada (I4). ``set`` y ``set_dynamic`` llaman a
    ``ws.touch(handle)``: exigen una transacción abierta por quien llama. ``None`` o ``MISSING``
    quitan la entrada.
    """

    schema: EntitySchema
    ref: RecordRef
    handle: DocHandle
    block: Block
    origin: LayerKind | None = None           # capa de la que se leyó (juego, mod, nuevo)

    def get(self, key: str, default: object = MISSING) -> object:
        """Valor tipado de ``key``, el ``default`` del campo si falta, o ``default`` (MISSING si
        no se pasa). Lee a través del esquema (variantes y secciones incluidas)."""
        raise NotImplementedError

    def get_all(self, key: str) -> list:
        """Todos los valores de una clave repetible, en orden."""
        raise NotImplementedError

    def node(self, key: str) -> Entry | None:
        """La entrada del CST de ``key`` («ir al código»); None si no está."""
        raise NotImplementedError

    def set(self, key: str, value: object) -> None:
        """Escribe ``key`` según su tipo; ``None`` o ``MISSING`` quitan la entrada. Dentro de una
        transacción abierta por quien llama (I5)."""
        raise NotImplementedError

    def add(self, key: str, value: object) -> Entry:
        """Añade un valor a una clave repetible, tras la última de la misma clave (§10.7.1)."""
        raise NotImplementedError

    def remove(self, key: str, value: object = MISSING) -> int:
        """Quita valores de una clave repetible; devuelve cuántos. Sin ``value``, todos."""
        raise NotImplementedError

    def group(self, key: str, index: int = 0) -> Record:
        """Vista del bloque anidado ``key`` (la repetición ``index``)."""
        raise NotImplementedError

    def groups(self, key: str) -> list[Record]:
        """Vistas de todas las repeticiones del grupo ``key``."""
        raise NotImplementedError

    def add_group(self, key: str, values: dict) -> Record:
        """Añade una repetición del grupo ``key`` con ``values``; devuelve su vista."""
        raise NotImplementedError

    def dynamic(self, name: str) -> dict[str, object]:
        """Los valores de un ``DynamicKeys`` del esquema (``{"flintlock_rifles": 1, …}``)."""
        raise NotImplementedError

    def set_dynamic(self, name: str, key: str, value: object) -> None:
        """Escribe ``key`` de un ``DynamicKeys``. Con ``only_true`` y valor falso, borra la clave
        en vez de escribir ``= no`` (§10.10). Dentro de una transacción (I5)."""
        raise NotImplementedError

    def children(self) -> list[Record]:
        """Registros hijos (``Children``): culturas dentro del grupo."""
        raise NotImplementedError

    def script(self, key: str):
        """Árbol de guion de ``key`` (lo edita ``core.script``, iteración 7)."""
        raise NotImplementedError

    def at(self, date: ClausewitzDate | None):
        """Vista de historia en la fecha ``date`` (§10.6)."""
        raise NotImplementedError

    def unknown(self) -> list[Entry]:
        """Entradas que el esquema no declara: se conservan (I6) y salen en «Otros campos»."""
        raise NotImplementedError

    def issues(self, ctx: CheckContext = None) -> list[Problem]:  # noqa: F821 - CheckContext de .validate
        """Problemas de este registro: campos y validadores del esquema, sin tocar nada (I4)."""
        raise NotImplementedError

    def loc_keys(self) -> list[tuple[LocSpec, str]]:
        """Claves de localización de este registro: ``(LocSpec, clave ya formateada)``."""
        raise NotImplementedError


class Entities:
    """Servicio de entidades sobre un ``Workspace``, el ``SymbolIndex`` y el ``LocSync``.

    ``list`` refleja la vista efectiva (I7): lo creado y no guardado sale; lo borrado y no
    guardado, no. ``create``, ``duplicate`` y ``delete`` abren su propia transacción
    (``undo.create_<kind>`` y compañía), I5.
    """

    def __init__(self, ws: Workspace, index, loc: LocSync) -> None:
        self.ws = ws
        self.index = index
        self.loc = loc

    def list(self, kind: str, *, view: str | None = None) -> list[EntitySummary]:
        """Registros de ``kind`` (los del índice), filtrados por la vista ``view`` si se da."""
        raise NotImplementedError

    def open(self, ref: RecordRef) -> Record:
        """Registro vivo de ``ref``: abre el documento efectivo si hace falta. Leer no escribe (I4)."""
        raise NotImplementedError

    def create(self, kind: str, ident: str, values: dict | None = None, *,
               texts: Mapping[str, Mapping[str, str]] | None = None) -> RecordRef:
        """Crea un registro en una transacción (archivo + compañeros + claves de localización).

        Un id inválido o ya existente lanza ``InvalidIdentError`` sin cambiar nada. ``texts``:
        ``{clave: {lang: texto}}`` de las claves de ``loc`` (``LocSync.ensure``).
        """
        raise NotImplementedError

    def duplicate(self, ref: RecordRef, new_ident: str) -> RecordRef:
        """Copia un registro como ``new_ident`` («basar en…»), con sus claves de localización,
        en una transacción."""
        raise NotImplementedError

    def delete(self, ref: RecordRef, *, force: bool = False) -> None:
        """Borra un registro en una transacción (compañeros y claves incluidas).

        Con usos en el índice y sin ``force`` lanza ``EntityInUseError`` (con ``.uses``) y no
        cambia nada.
        """
        raise NotImplementedError

    def where_used(self, ref: RecordRef) -> list[SymbolRef]:
        """Referencias del índice a este registro (``index.refs_to``); leer no escribe (I4)."""
        raise NotImplementedError
