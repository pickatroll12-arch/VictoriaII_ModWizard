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
from ..clausewitz.nodes import Block, ClausewitzDate, Scalar
from ..schema.history import read_order

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
    _map_terrain: dict = field(default_factory=dict, repr=False)  # id → código del terreno mayoritario del ráster

    @property
    def size(self) -> int:
        return int(self.owner.shape[0])

    @classmethod
    def empty(cls, size: int, date: ClausewitzDate) -> ProvinceFacts:
        """Hechos a 0 de ``size`` provincias (las tablas, solo con ``""``)."""
        def zeros(dtype):
            return np.zeros(size, dtype=dtype)

        return cls(date, zeros(np.int32), zeros(np.int32), zeros(np.int32), zeros(np.int16), zeros(np.int8),
                   zeros(np.int8), zeros(np.int8), zeros(np.int8), zeros(np.int32), zeros(np.int32),
                   zeros(np.int32), zeros(np.int32), zeros(bool), zeros(np.int64), zeros(np.int32),
                   zeros(np.int32), tuple(frozenset() for _ in range(size)))

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
        from ..cancel import raise_if_cancelled
        from ..domain.pops import PopsIndex
        from ..index.model import (
            KIND_CLIMATE, KIND_CONTINENT, KIND_POP_BLOCK, KIND_PROVINCE, KIND_PROVINCE_HISTORY, KIND_REGION,
            KIND_SEA_PROVINCE, KIND_SEA_REGION,
        )

        if size is None:
            ids = [int(n) for kind in (KIND_PROVINCE, KIND_SEA_PROVINCE) for n in index.names(kind) if n.isdigit()]
            size = max(ids, default=0) + 1
        # 1) Lo que dice cada historia en la fecha (como texto) y los núcleos.
        raw: dict[int, dict[str, str]] = {}
        raw_cores: dict[int, list[str]] = {}
        for symbol in index.symbols(KIND_PROVINCE_HISTORY):
            if not symbol.name.isdigit() or int(symbol.name) >= size:
                continue
            attrs = symbol.attrs or {}
            values, cores = _history_at(attrs.get("fields") or {}, attrs.get("dated") or (), date)
            raw[int(symbol.name)] = values
            raw_cores[int(symbol.name)] = cores
        raise_if_cancelled(cancelled)
        # 2) Grupos.
        groups: dict[str, dict[int, str]] = {"region": {}, "continent": {}, "climate": {}}
        for kind, field_name in ((KIND_REGION, "region"), (KIND_SEA_REGION, "region"),
                                 (KIND_CONTINENT, "continent"), (KIND_CLIMATE, "climate")):
            target = groups[field_name]
            for symbol in index.symbols(kind):
                for pid in (symbol.attrs or {}).get("provinces") or ():
                    if 0 < int(pid) < size:
                        target.setdefault(int(pid), symbol.name)
        # 3) POPs de la carpeta de la fecha.
        population: dict[int, int] = {}
        majority: dict[int, tuple[int, str | None, str | None]] = {}
        pops = PopsIndex(index)
        folder = pops.folder_for(date)
        if folder is not None:
            prefix = f"{folder}:"
            for name in index.names(KIND_POP_BLOCK):
                if not name.startswith(prefix):
                    continue
                province = name[len(prefix):]
                if not province.isdigit() or int(province) >= size:
                    continue
                pid = int(province)
                for symbol in index.effective(KIND_POP_BLOCK, name):
                    attrs = symbol.attrs or {}
                    population[pid] = population.get(pid, 0) + int(attrs.get("size") or 0)
                    top = int(attrs.get("top") or 0)
                    if pid not in majority or top > majority[pid][0]:
                        majority[pid] = (top, attrs.get("culture"), attrs.get("religion"))
        raise_if_cancelled(cancelled)
        # 4) Tablas de nombres (ordenadas) y arrays.
        facts = cls.empty(size, date)
        names: dict[str, set[str]] = {table: set() for table in set(CODED.values())}
        for values in raw.values():
            for key in ("owner", "controller"):
                if values.get(key):
                    names["tags"].add(values[key].upper())
            if values.get("trade_goods"):
                names["goods"].add(values["trade_goods"])
            if values.get("terrain"):
                names["terrains"].add(values["terrain"])
        for cores in raw_cores.values():
            names["tags"].update(tag.upper() for tag in cores)
        names["terrains"].update((terrain_types or {}).values())
        names["regions"].update(groups["region"].values())
        names["continents"].update(groups["continent"].values())
        names["climates"].update(groups["climate"].values())
        for _, culture, religion in majority.values():
            if culture:
                names["cultures"].add(culture)
            if religion:
                names["religions"].add(religion)
        for table, found in names.items():
            setattr(facts, table, ("", *sorted(found)))
        facts._codes = {}
        sea = [pid for pid in rules.sea if 0 < pid < size]
        facts.is_sea[sea] = True
        for pid, values in raw.items():
            facts._apply(pid, values, raw_cores.get(pid, ()))
        if terrain_majority is not None and terrain_types:
            majority_terrain = np.asarray(terrain_majority)
            limit = min(size, majority_terrain.shape[0])
            for pid in range(1, limit):
                category = terrain_types.get(int(majority_terrain[pid]))
                if category:
                    facts._map_terrain[pid] = facts.code("terrains", category)
                    if facts.terrain[pid] == NONE:
                        facts.terrain[pid] = facts._map_terrain[pid]
        for field_name, members in groups.items():
            array = getattr(facts, field_name)
            for pid, name in members.items():
                array[pid] = facts.code(CODED[field_name], name)
        for pid, total in population.items():
            facts.population[pid] = total
        for pid, (_, culture, religion) in majority.items():
            facts.culture[pid] = facts.code("cultures", culture)
            facts.religion[pid] = facts.code("religions", religion)
        return facts

    # --- tablas de nombres ----------------------------------------------------------------------------

    def _table_codes(self, table: str) -> dict[str, int]:
        codes = self._codes.get(table)
        if codes is None:
            names = getattr(self, table)
            fold = table == "tags"
            codes = {}
            for code, name in enumerate(names):
                if code:
                    codes.setdefault(name.upper() if fold else name, code)
            self._codes[table] = codes
        return codes

    def code(self, table: str, name: str | None) -> int:
        """Código de ``name`` en la tabla ``table`` (``"tags"``, ``"goods"``…); ``NONE`` si es None, vacío o no
        está. No distingue mayúsculas en los TAG."""
        if not name:
            return NONE
        return self._table_codes(table).get(name.upper() if table == "tags" else name, NONE)

    def _code_or_add(self, table: str, name: str | None) -> int:
        if not name:
            return NONE
        found = self.code(table, name)
        if found:
            return found
        names = getattr(self, table)
        value = name.upper() if table == "tags" else name
        setattr(self, table, (*names, value))
        self._table_codes(table)[value.upper() if table == "tags" else value] = len(names)
        return len(names)

    def name(self, table: str, code: int) -> str:
        """El nombre de un código (``""`` para ``NONE``)."""
        names = getattr(self, table)
        return names[code] if 0 <= code < len(names) else ""

    # --- actualización ------------------------------------------------------------------------------

    def _apply(self, pid: int, values: Mapping[str, str], cores) -> None:
        self.owner[pid] = self._code_or_add("tags", values.get("owner"))
        self.controller[pid] = self._code_or_add("tags", values.get("controller"))
        self.trade_goods[pid] = self._code_or_add("goods", values.get("trade_goods"))
        self.life_rating[pid] = _int(values.get("life_rating"))
        self.railroad[pid] = _int(values.get("railroad"))
        self.fort[pid] = _int(values.get("fort"))
        self.naval_base[pid] = _int(values.get("naval_base"))
        self.colonial[pid] = _int(values.get("colonial") or values.get("colony"))
        self.terrain[pid] = self._code_or_add("terrains", values.get("terrain"))
        cores_codes = frozenset(self._code_or_add("tags", tag) for tag in cores if tag)
        self.cores = (*self.cores[:pid], cores_codes, *self.cores[pid + 1:])

    def update(self, pid: int, record: Record | None, date: ClausewitzDate) -> None:
        """Recalcula la provincia ``pid`` desde ``record`` (su historia, ya editada) con ``HistoryView`` en
        ``date`` y sube ``generation``. ``record=None``: la provincia se queda sin historia (todo a 0).

        Un nombre que aún no está en su tabla (un TAG recién creado) se añade al final con el código siguiente
        (las tablas dejan de estar ordenadas hasta el próximo ``build``; los códigos ya dados no cambian). No
        toca región, continente, clima, mar ni POPs: para esos, ``set_group`` y ``set_population``.
        """
        if not 0 < pid < self.size:
            return
        if record is None:
            self._apply(pid, {}, ())
        else:
            fields, dated = _record_history(record.block)
            values, cores = _history_at(fields, dated, date)
            self._apply(pid, values, cores)
            if not values.get("terrain"):
                self.terrain[pid] = self._map_terrain.get(pid, NONE)
        self.generation += 1

    def set_group(self, field_name: str, pid: int, name: str | None) -> None:
        """Pone ``region``, ``continent`` o ``climate`` de ``pid`` (tras mover la provincia con ``ProvinceGroups``)
        y sube ``generation``."""
        if field_name not in ("region", "continent", "climate"):
            raise ValueError(field_name)
        if 0 < pid < self.size:
            getattr(self, field_name)[pid] = self._code_or_add(CODED[field_name], name)
            self.generation += 1

    def set_population(self, pid: int, total: int, culture: str | None, religion: str | None) -> None:
        """Pone la población y el POP mayoritario de ``pid`` (tras editar sus POPs) y sube ``generation``."""
        if 0 < pid < self.size:
            self.population[pid] = int(total)
            self.culture[pid] = self._code_or_add("cultures", culture)
            self.religion[pid] = self._code_or_add("religions", religion)
            self.generation += 1


def _int(text) -> int:
    if text is None:
        return 0
    try:
        return int(float(str(text)))
    except ValueError:
        return 0


def _record_history(block: Block) -> tuple[dict, list]:
    """Lo mismo que guarda el extractor de historias (``fields`` y ``dated``), leído de un bloque vivo."""
    from ..index.extractors.map import PROVINCE_KEPT, PROVINCE_LISTED

    def read(source: Block) -> dict:
        fields: dict = {}
        for entry in source.entries:
            if entry.key is None or not isinstance(entry.value, Scalar):
                continue
            lowered = entry.key.text.lower()
            if lowered in PROVINCE_KEPT:
                fields[lowered] = entry.value.text
            elif lowered in PROVINCE_LISTED:
                fields.setdefault(lowered, []).append(entry.value.text)
        return fields

    dated = []
    for entry in block.entries:
        if entry.key is not None and isinstance(entry.value, Block) and entry.key.is_date():
            dated.append([entry.key.text, entry.line, read(entry.value)])
    return read(block), dated


def _history_at(fields: Mapping, dated, date: ClausewitzDate) -> tuple[dict[str, str], list[str]]:
    """Valores vigentes en ``date`` y núcleos (en orden de entrada) con las reglas de ``HistoryView``."""
    layers = [fields]
    dates = []
    blocks = []
    for item in dated:
        try:
            dates.append(ClausewitzDate.parse(item[0]))
        except ValueError:
            continue
        blocks.append(item[2])
    layers.extend(blocks[index] for index in read_order(dates, date))
    values: dict[str, str] = {}
    cores: dict[str, str] = {}
    for layer in layers:
        for key, value in layer.items():
            if key == "add_core":
                for tag in value:
                    cores.pop(tag.upper(), None)
                    cores[tag.upper()] = tag
            elif key == "remove_core":
                for tag in value:
                    cores.pop(tag.upper(), None)
            else:
                values[key] = value
    return values, list(cores.values())


def terrain_types(terrain_txt: bytes) -> dict[int, str]:
    """Índice de ``terrain.bmp`` → categoría de ``terrain.txt``, leído de las entradas ``<nombre> = { type = X
    color = { i j … } }`` que hay fuera de ``categories`` (66 en vanilla; una con 191 índices). Si un índice sale
    en dos entradas gana la primera. Recibe bytes: vale en un hilo de tarea."""
    from ..project.codecs import parse_bytes

    found: dict[int, str] = {}
    for entry in parse_bytes(terrain_txt).document:
        if entry.key is None or not isinstance(entry.value, Block) or entry.key.text == "categories":
            continue
        kind = entry.value.get_text("type")
        colors = entry.value.get("color")
        if not kind or not isinstance(colors, Block):
            continue
        for item in colors:
            if item.key is None and isinstance(item.value, Scalar):
                try:
                    found.setdefault(item.value.as_int(), kind)
                except ValueError:
                    continue
    return found
