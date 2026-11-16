"""``ProvinceFacts``: lo que los modos de mapa necesitan de cada provincia, en arrays (wizard §16.1). Contrato.

Un array por dato, indexado por id (``(N+1,)``; el índice 0 es «sin provincia»). Los datos que son nombres (dueño,
bien, terreno, región…) van como **códigos** de una tabla de nombres propia (``tags``, ``goods``…): el código 0 es
siempre «ninguno» (la tabla empieza por ``""``) y los demás siguen el orden alfabético, así que una LUT de color se
calcula por código y se aplica con ``np.take``, sin diccionarios por provincia. No guarda ningún CST.

Dos maneras de rellenarlo, que deben dar lo mismo (una prueba de la cadena A las compara en todas las provincias):

- ``ProvinceFacts.build``: entero, desde el **índice de símbolos** (historias de provincia, bloques de POP,
  regiones, continentes, climas) y ``GameRules``, con las reglas de lectura de ``HistoryView`` en la fecha
  (§10.6). No abre archivos ni necesita el ``Workspace``: vale en un hilo de tarea con una copia del índice (I12).
  Para eso, el extractor de historias guarda en ``attrs`` todo lo que aquí se lee (``railroad``, ``fort``,
  ``naval_base``, los núcleos…) y el de POPs, el tamaño y el POP mayoritario de cada bloque.
- ``update``: una provincia, desde su ``Record`` vivo, justo después de editarla (hilo de la interfaz): el
  repintado tras cambiar un dueño no espera al índice (criterio: ≤ 50 ms).

En el mar, los datos de tierra valen 0. El terreno es la anulación ``terrain =`` de la historia o, si no hay, la
categoría del índice mayoritario de ``terrain.bmp`` (§16.2); sin ráster de terreno, 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from ..cancel import CancelCheck
from ..clausewitz.nodes import ClausewitzDate

if TYPE_CHECKING:
    from ..rules.game import GameRules
    from ..schema.record import Record

NONE = 0                             # código de «ninguno» en todas las tablas de nombres
# Campos de ``ProvinceFacts`` que son códigos y la tabla de nombres de cada uno.
CODED = {"owner": "tags", "controller": "tags", "trade_goods": "goods", "terrain": "terrains",
         "region": "regions", "continent": "continents", "climate": "climates", "culture": "cultures",
         "religion": "religions"}
# Campos numéricos (niveles y cantidades).
NUMERIC = ("life_rating", "railroad", "fort", "naval_base", "colonial", "population")


@dataclass(eq=False)
class ProvinceFacts:
    """Hechos de todas las provincias en ``date``. Todos los arrays miden ``size`` (= ``N+1``)."""

    date: ClausewitzDate
    owner: np.ndarray                # int32, código de ``tags``
    controller: np.ndarray           # int32, código de ``tags``
    trade_goods: np.ndarray          # int32, código de ``goods``
    life_rating: np.ndarray          # int16
    railroad: np.ndarray             # int8 (nivel)
    fort: np.ndarray                 # int8
    naval_base: np.ndarray           # int8
    colonial: np.ndarray             # int8: el valor de ``colonial``/``colony`` (0 no, 1 protectorado, 2 colonia; [verificar en juego])
    terrain: np.ndarray              # int32, código de ``terrains``
    region: np.ndarray               # int32, código de ``regions`` (tierra: region.txt; mar: region_sea.txt)
    continent: np.ndarray            # int32, código de ``continents``
    climate: np.ndarray              # int32, código de ``climates``
    is_sea: np.ndarray               # bool (``default.map``: sea_starts)
    population: np.ndarray           # int64: suma de ``size`` de sus bloques de POP en la carpeta de la fecha
    culture: np.ndarray              # int32, código de ``cultures``: la del POP mayoritario
    religion: np.ndarray             # int32, código de ``religions``: la del POP mayoritario
    cores: tuple[frozenset[int], ...] = ()      # por id: códigos de ``tags`` con núcleo en la fecha
    tags: tuple[str, ...] = ("",)
    goods: tuple[str, ...] = ("",)
    terrains: tuple[str, ...] = ("",)
    regions: tuple[str, ...] = ("",)
    continents: tuple[str, ...] = ("",)
    climates: tuple[str, ...] = ("",)
    cultures: tuple[str, ...] = ("",)
    religions: tuple[str, ...] = ("",)
    generation: int = 0              # sube con cada ``update``: las LUT recordadas se comparan con él
    _codes: dict = field(default_factory=dict, repr=False)   # tabla → {nombre: código}, perezoso

    @property
    def size(self) -> int:
        return int(self.owner.shape[0])

    @classmethod
    def build(cls, index, rules: GameRules, date: ClausewitzDate, *, size: int | None = None,
              terrain_majority: np.ndarray | None = None, terrain_types: Mapping[int, str] | None = None,
              cancelled: CancelCheck = None) -> ProvinceFacts:
        """Hechos de la vista efectiva del índice en ``date``.

        ``size``: ``N+1`` (por defecto, el mayor id del índice más 1; con ráster, ``raster.max_id + 1``).
        ``terrain_majority`` es ``ProvinceRaster.majority(terrain.bmp)`` y ``terrain_types`` el resultado de
        ``terrain_types()``; sin ellos solo cuentan las anulaciones. La historia duplicada de un id cuenta la
        copia efectiva (la primera, decisión 1 del contrato); los POPs, la carpeta ``PopsIndex.folder_for(date)``
        con los bloques repetidos sumados. Una provincia sin historia queda con todo a 0.
        """
        raise NotImplementedError

    def code(self, table: str, name: str | None) -> int:
        """Código de ``name`` en la tabla ``table`` (``"tags"``, ``"goods"``…); ``NONE`` si es None, vacío o no
        está. No distingue mayúsculas en los TAG."""
        raise NotImplementedError

    def name(self, table: str, code: int) -> str:
        """El nombre de un código (``""`` para ``NONE``)."""
        raise NotImplementedError

    def update(self, pid: int, record: Record | None, date: ClausewitzDate) -> None:
        """Recalcula la provincia ``pid`` desde ``record`` (su historia, ya editada) con ``HistoryView`` en
        ``date`` y sube ``generation``. ``record=None``: la provincia se queda sin historia (todo a 0).

        Un nombre que aún no está en su tabla (un TAG recién creado) se añade al final con el código siguiente
        (las tablas dejan de estar ordenadas hasta el próximo ``build``; los códigos ya dados no cambian). No
        toca región, continente, clima, mar ni POPs: para esos, ``set_group`` y ``set_population``.
        """
        raise NotImplementedError

    def set_group(self, field_name: str, pid: int, name: str | None) -> None:
        """Pone ``region``, ``continent`` o ``climate`` de ``pid`` (tras mover la provincia con ``ProvinceGroups``)
        y sube ``generation``."""
        raise NotImplementedError

    def set_population(self, pid: int, total: int, culture: str | None, religion: str | None) -> None:
        """Pone la población y el POP mayoritario de ``pid`` (tras editar sus POPs) y sube ``generation``."""
        raise NotImplementedError


def terrain_types(terrain_txt: bytes) -> dict[int, str]:
    """Índice de ``terrain.bmp`` → categoría de ``terrain.txt``, leído de las entradas ``<nombre> = { type = X
    color = { i j … } }`` que hay fuera de ``categories`` (66 en vanilla; una con 191 índices). Si un índice sale
    en dos entradas gana la primera. Recibe bytes: vale en un hilo de tarea."""
    raise NotImplementedError
