"""Fachada de provincia: ver y editar una provincia en la fecha de trabajo (wizard §14.3). Contrato.

Junta lo que el panel de provincia y la brocha necesitan sin que la interfaz conozca los archivos: la fila de
``definition.csv`` y los grupos (del índice), la historia fechada (``HistoryView`` sobre el registro
``province_history``) y los POPs (``ProvincePops``). Trabaja sobre ``Entities``: siempre la vista efectiva (I7) y
en el hilo del ``Workspace`` (I12).

Reglas:

- **Leer no escribe** (I4): ``state``, ``get``, ``timeline``… no abren transacciones ni ensucian documentos.
- **Editar va dentro de la transacción de quien llama** (I5): la interfaz abre una sola con ``session.edit`` y la
  etiqueta ``UNDO_*`` que toque, y dentro llama a ``set``/``paint``…; un trazo de brocha sobre 30 provincias es
  un solo paso de deshacer. Sin transacción abierta, el ``Workspace`` lanza.
- **Dónde se escribe**: lo decide ``HistoryView`` (§10.6). En la fecha de inicio, la entrada sin fecha; después,
  el último bloque fechado del intervalo (bookmark anterior, fecha]; si no hay, uno nuevo ``fecha = { }``.
  Cambiar el dueño de 549 con vanilla crea solo ``history/provinces/germany/549 - Berlin.txt`` en el mod con un
  diff de 1 línea (criterio 4); editar en 1861.7.1 escribe en el ``1861.1.1`` que ya tiene (criterio 5).
- **Provincia sin historia**: ``ensure_history`` crea ``history/provinces/<carpeta>/<id> - <Nombre>.txt`` (la
  carpeta de su región o ``studio``, decisión 1 del contrato); ``set`` la llama sola si hace falta.
- **Mar**: una provincia de mar no tiene dueño, núcleos ni POPs: editarla lanza ``ProvinceError("sea")``.
- Un id con dos historias (1396 y 1397 en vanilla): se lee y se edita la copia efectiva; las demás están en
  ``ProvinceInfo.duplicates``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..clausewitz.nodes import ClausewitzDate
from ..map.definition import RGB
from ..vfs.paths import VPath
from .pops import ProvincePops

if TYPE_CHECKING:
    from ..rules.game import GameRules
    from ..schema.history import Effective, HistoryView
    from ..schema.record import Entities, Record, RecordRef

KIND = "province_history"            # el esquema de la historia de provincia
# Claves con un valor vigente por fecha (``set``/``get``) y las de edificios (niveles).
VALUE_KEYS = ("owner", "controller", "trade_goods", "life_rating", "terrain", "colonial", "colony", "is_slave")
BUILDING_KEYS = ("railroad", "fort", "naval_base")
CORE_KEY = "add_core"                # acumulativa: ``add_core``/``remove_core`` (``cores``, ``add_core``…)
# Lo que la brocha puede pintar (``paint``): un valor o un nivel; los núcleos van con add_core/remove_core.
PAINT_KEYS = (*VALUE_KEYS[:5], *BUILDING_KEYS)

# Etiquetas de deshacer (textos en core/domain/texts): la interfaz las pasa a ``session.edit``.
UNDO_SET = "undo.province_set"                    # {province}, {field}
UNDO_PAINT = "undo.province_paint"                # {field}, {count}
UNDO_CORE = "undo.province_core"                  # {province}, {tag}
UNDO_CREATE_HISTORY = "undo.province_history_create"   # {province}
UNDO_POPS = "undo.province_pops"                  # {province}
UNDO_GROUP_MOVE = "undo.map_group_move"           # {province}, {group}
UNDO_GROUP_CREATE = "undo.map_group_create"       # {group}
UNDO_GROUP_RENAME = "undo.map_group_rename"       # {group}, {new}
UNDO_GROUP_DELETE = "undo.map_group_delete"       # {group}
UNDO_ADJACENCY_ADD = "undo.map_adjacency_add"     # {start}, {end}
UNDO_ADJACENCY_REMOVE = "undo.map_adjacency_remove"   # {start}, {end}
UNDO_LABELS = (UNDO_SET, UNDO_PAINT, UNDO_CORE, UNDO_CREATE_HISTORY, UNDO_POPS, UNDO_GROUP_MOVE,
               UNDO_GROUP_CREATE, UNDO_GROUP_RENAME, UNDO_GROUP_DELETE, UNDO_ADJACENCY_ADD, UNDO_ADJACENCY_REMOVE)


class ProvinceError(ValueError):
    """Una operación que no se puede hacer; no se cambió nada. ``code``: ``unknown`` (el id no está en
    ``definition.csv``), ``sea`` (editar una provincia de mar) o ``bad_key`` (la clave no es editable así)."""

    def __init__(self, code: str, province: int, detail: str = "") -> None:
        self.code = code
        self.province = province
        self.detail = detail
        super().__init__(f"{code}: {province}" + (f" ({detail})" if detail else ""))


@dataclass(frozen=True)
class ProvinceInfo:
    """Lo que no depende de la fecha. ``name`` es el de su fila de ``definition.csv`` (el texto visible es la
    clave ``PROV<id>``). ``history`` es la copia efectiva de su historia (None si no tiene)."""

    id: int
    name: str
    rgb: RGB | None
    is_sea: bool
    region: str | None
    continent: str | None
    climate: str | None
    history: VPath | None
    duplicates: tuple[VPath, ...] = ()


@dataclass(frozen=True)
class ProvinceState:
    """La provincia en una fecha: lo que enseña la pestaña Resumen. Lo que falta vale None (o 0 en niveles)."""

    id: int
    date: ClausewitzDate
    owner: str | None
    controller: str | None
    cores: tuple[str, ...]
    trade_goods: str | None
    life_rating: int | None
    terrain: str | None              # solo la anulación ``terrain =``; el del BMP lo da ``ProvinceFacts``
    railroad: int
    fort: int
    naval_base: int
    colonial: int
    is_slave: bool


@dataclass(frozen=True)
class TimelineEvent:
    """Un bloque fechado de la historia: ``index`` es su posición entre los bloques del archivo (dos bloques
    con la misma fecha, como los dos ``1861.1.1`` de 549, son dos sucesos) y ``changes`` sus entradas
    ``(clave, texto del valor)`` en orden."""

    date: ClausewitzDate
    index: int
    changes: tuple[tuple[str, str], ...]


class Provinces:
    def __init__(self, entities: Entities, rules: GameRules) -> None:
        """``rules``: las del proyecto (mar, ``max_provinces``, fechas de los bookmarks para ``HistoryView``)."""
        self.entities = entities
        self.rules = rules

    # --- leer ---------------------------------------------------------------------------------------

    def ids(self, *, land: bool = True, sea: bool = True) -> list[int]:
        """Ids de ``definition.csv`` ordenados, de tierra, de mar o ambos."""
        raise NotImplementedError

    def info(self, pid: int) -> ProvinceInfo:
        """``ProvinceError("unknown")`` si el id no está en ``definition.csv``."""
        raise NotImplementedError

    def record(self, pid: int) -> Record | None:
        """El registro ``province_history`` de la copia efectiva; None si la provincia no tiene historia."""
        raise NotImplementedError

    def view(self, pid: int, date: ClausewitzDate) -> HistoryView | None:
        """``HistoryView`` de su historia en ``date`` con los bookmarks de ``rules``; None sin historia."""
        raise NotImplementedError

    def state(self, pid: int, date: ClausewitzDate) -> ProvinceState:
        """La provincia en ``date``. Sin historia (o de mar), todo vacío."""
        raise NotImplementedError

    def get(self, pid: int, key: str, date: ClausewitzDate) -> Effective:
        """Valor vigente de una clave de ``VALUE_KEYS`` o ``BUILDING_KEYS`` con la entrada que lo define
        («ir al código»); ``Effective(None, None, None)`` si no está."""
        raise NotImplementedError

    def cores(self, pid: int, date: ClausewitzDate) -> list[str]:
        """TAG con núcleo en ``date`` (``add_core`` menos ``remove_core``), en el orden en que entran."""
        raise NotImplementedError

    def timeline(self, pid: int) -> list[TimelineEvent]:
        """Los bloques fechados en orden de lectura (por fecha; a igualdad, por archivo)."""
        raise NotImplementedError

    # --- editar (dentro de la transacción de quien llama) --------------------------------------------

    def ensure_history(self, pid: int) -> RecordRef:
        """La referencia de su historia; si no tiene, la crea vacía donde diga la disposición."""
        raise NotImplementedError

    def set(self, pid: int, key: str, value: object, date: ClausewitzDate) -> bool:
        """Pone ``key`` (de ``VALUE_KEYS`` o ``BUILDING_KEYS``) a ``value`` en ``date``; None quita la clave en
        la fecha de inicio. False si ya valía eso (no cambia ni ensucia nada)."""
        raise NotImplementedError

    def add_core(self, pid: int, tag: str, date: ClausewitzDate) -> bool:
        raise NotImplementedError

    def remove_core(self, pid: int, tag: str, date: ClausewitzDate) -> bool:
        raise NotImplementedError

    def paint(self, pids: Iterable[int], key: str, value: object, date: ClausewitzDate) -> list[int]:
        """La brocha: ``set`` sobre cada provincia de tierra de ``pids`` (las de mar se saltan sin error).
        Devuelve las que cambiaron, para ``ProvinceFacts.update`` y ``MapCanvas.refresh``."""
        raise NotImplementedError

    def edit_event(self, pid: int, event: TimelineEvent, key: str, value: object) -> None:
        """Edita un suceso concreto de la línea temporal (el bloque ``event``, no el que elegiría la fecha de
        trabajo); None quita la clave de ese bloque."""
        raise NotImplementedError

    # --- POPs ---------------------------------------------------------------------------------------

    def pops(self) -> ProvincePops:
        """El editor de POPs sobre las mismas ``Entities``."""
        raise NotImplementedError
