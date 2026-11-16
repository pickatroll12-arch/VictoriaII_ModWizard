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
from ..schema.fields import MISSING
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


def _definition_row(index, pid: int):
    from ..index.model import KIND_PROVINCE, KIND_SEA_PROVINCE

    for kind in (KIND_PROVINCE, KIND_SEA_PROVINCE):
        symbol = index.get(kind, str(pid))
        if symbol is not None:
            return kind, symbol
    return None, None


def _group_of(index, kind: str, pid: int) -> str | None:
    for symbol in index.symbols(kind):
        if pid in ((symbol.attrs or {}).get("provinces") or ()):
            return symbol.name
    return None


def _to_int(value) -> int:
    if value is None or value is MISSING:
        return 0
    try:
        return int(float(str(value)))
    except ValueError:
        return 0


class Provinces:
    def __init__(self, entities: Entities, rules: GameRules) -> None:
        """``rules``: las del proyecto (mar, ``max_provinces``, fechas de los bookmarks para ``HistoryView``)."""
        self.entities = entities
        self.rules = rules

    @property
    def index(self):
        return self.entities.index

    def _bookmarks(self) -> tuple[ClausewitzDate, ...]:
        found = tuple(getattr(self.rules, "bookmarks", ()) or ())
        if found:
            return found
        from ..schema.record import bookmark_dates

        return tuple(bookmark_dates(self.index))

    def is_sea(self, pid: int) -> bool:
        sea = getattr(self.rules, "sea", None)
        if sea:
            return pid in sea
        from ..index.model import KIND_SEA_PROVINCE

        return self.index.get(KIND_SEA_PROVINCE, str(pid)) is not None

    # --- leer ---------------------------------------------------------------------------------------

    def ids(self, *, land: bool = True, sea: bool = True) -> list[int]:
        """Ids de ``definition.csv`` ordenados, de tierra, de mar o ambos."""
        from ..index.model import KIND_PROVINCE, KIND_SEA_PROVINCE

        found = set()
        if land:
            found.update(int(n) for n in self.index.names(KIND_PROVINCE) if n.isdigit())
        if sea:
            found.update(int(n) for n in self.index.names(KIND_SEA_PROVINCE) if n.isdigit())
        return sorted(found)

    def info(self, pid: int) -> ProvinceInfo:
        """``ProvinceError("unknown")`` si el id no está en ``definition.csv``."""
        from ..index.model import KIND_CLIMATE, KIND_CONTINENT, KIND_PROVINCE_HISTORY, KIND_REGION, KIND_SEA_REGION

        kind, symbol = _definition_row(self.index, pid)
        if symbol is None:
            raise ProvinceError("unknown", pid)
        attrs = symbol.attrs or {}
        color = attrs.get("color")
        sea = self.is_sea(pid)
        histories = self.index.effective(KIND_PROVINCE_HISTORY, str(pid))
        return ProvinceInfo(
            pid, str(attrs.get("name") or ""), tuple(color) if isinstance(color, (list, tuple)) else None, sea,
            _group_of(self.index, KIND_SEA_REGION if sea else KIND_REGION, pid),
            _group_of(self.index, KIND_CONTINENT, pid), _group_of(self.index, KIND_CLIMATE, pid),
            histories[0].rel if histories else None, tuple(h.rel for h in histories[1:]))

    def record(self, pid: int) -> Record | None:
        """El registro ``province_history`` de la copia efectiva; None si la provincia no tiene historia."""
        from ..schema.record import RecordRef

        try:
            return self.entities.open(RecordRef(KIND, str(int(pid))))
        except (KeyError, FileNotFoundError, LookupError):
            return None

    def view(self, pid: int, date: ClausewitzDate) -> HistoryView | None:
        """``HistoryView`` de su historia en ``date`` con los bookmarks de ``rules``; None sin historia."""
        record = self.record(pid)
        return None if record is None else record.at(date, self._bookmarks())

    def state(self, pid: int, date: ClausewitzDate) -> ProvinceState:
        """La provincia en ``date``. Sin historia (o de mar), todo vacío."""
        view = None if self.is_sea(pid) else self.view(pid, date)
        if view is None:
            return ProvinceState(pid, date, None, None, (), None, None, None, 0, 0, 0, 0, False)

        def value(key):
            found = view.get(key).value
            return None if found is MISSING else found

        cores = tuple(str(item.value) for item in view.get_set(CORE_KEY))
        life = value("life_rating")
        slave = value("is_slave")
        return ProvinceState(
            pid, date, _str(value("owner")), _str(value("controller")), cores, _str(value("trade_goods")),
            None if life is None else _to_int(life), _str(value("terrain")), _to_int(value("railroad")),
            _to_int(value("fort")), _to_int(value("naval_base")),
            _to_int(value("colonial") if value("colonial") is not None else value("colony")),
            bool(slave) if isinstance(slave, bool) else str(slave).lower() == "yes" if slave is not None else False)

    def get(self, pid: int, key: str, date: ClausewitzDate) -> Effective:
        """Valor vigente de una clave de ``VALUE_KEYS`` o ``BUILDING_KEYS`` con la entrada que lo define
        («ir al código»); ``Effective(None, None, None)`` si no está."""
        from ..schema.history import Effective

        if key not in VALUE_KEYS and key not in BUILDING_KEYS:
            raise ProvinceError("bad_key", pid, key)
        view = self.view(pid, date)
        if view is None:
            return Effective(None, None, None)
        found = view.get(key)
        return Effective(None, None, None) if found.value is MISSING else found

    def cores(self, pid: int, date: ClausewitzDate) -> list[str]:
        """TAG con núcleo en ``date`` (``add_core`` menos ``remove_core``), en el orden en que entran."""
        view = self.view(pid, date)
        return [] if view is None else [str(item.value) for item in view.get_set(CORE_KEY)]

    def timeline(self, pid: int) -> list[TimelineEvent]:
        """Los bloques fechados en orden de lectura (por fecha; a igualdad, por archivo)."""
        from ..clausewitz.nodes import Block, Scalar

        record = self.record(pid)
        if record is None:
            return []
        dated = []
        for entry in record.block.entries:
            if entry.key is None or not isinstance(entry.value, Block) or not entry.key.is_date():
                continue
            try:
                when = ClausewitzDate.parse(entry.key.text)
            except ValueError:
                continue
            changes = tuple((child.key.text, child.value.text if isinstance(child.value, Scalar) else "{…}")
                            for child in entry.value.entries if child.key is not None)
            dated.append(TimelineEvent(when, len(dated), changes))
        return sorted(dated, key=lambda event: (event.date, event.index))

    # --- editar (dentro de la transacción de quien llama) --------------------------------------------

    def _land(self, pid: int) -> None:
        kind, symbol = _definition_row(self.index, pid)
        if symbol is None:
            raise ProvinceError("unknown", pid)
        if self.is_sea(pid):
            raise ProvinceError("sea", pid)

    def ensure_history(self, pid: int) -> RecordRef:
        """La referencia de su historia; si no tiene, la crea vacía donde diga la disposición."""
        from ..schema.record import RecordRef

        self._land(pid)
        record = self.record(pid)
        if record is not None:
            return record.ref
        return self.entities.create(KIND, str(int(pid)), {})

    def _writable(self, pid: int, date: ClausewitzDate) -> HistoryView:
        self._land(pid)
        self.ensure_history(pid)
        view = self.view(pid, date)
        assert view is not None
        return view

    def set(self, pid: int, key: str, value: object, date: ClausewitzDate) -> bool:
        """Pone ``key`` (de ``VALUE_KEYS`` o ``BUILDING_KEYS``) a ``value`` en ``date``; None quita la clave en
        la fecha de inicio. False si ya valía eso (no cambia ni ensucia nada)."""
        if key not in VALUE_KEYS and key not in BUILDING_KEYS:
            raise ProvinceError("bad_key", pid, key)
        self._land(pid)
        current = self.get(pid, key, date).value
        if _same(current, value):
            return False
        self._writable(pid, date).set(key, value)
        return True

    def add_core(self, pid: int, tag: str, date: ClausewitzDate) -> bool:
        self._land(pid)
        if tag.upper() in (core.upper() for core in self.cores(pid, date)):
            return False
        self._writable(pid, date).add(CORE_KEY, tag)
        return True

    def remove_core(self, pid: int, tag: str, date: ClausewitzDate) -> bool:
        self._land(pid)
        if tag.upper() not in (core.upper() for core in self.cores(pid, date)):
            return False
        self._writable(pid, date).remove(CORE_KEY, tag)
        return True

    def paint(self, pids: Iterable[int], key: str, value: object, date: ClausewitzDate) -> list[int]:
        """La brocha: ``set`` sobre cada provincia de tierra de ``pids`` (las de mar se saltan sin error).
        Devuelve las que cambiaron, para ``ProvinceFacts.update`` y ``MapCanvas.refresh``."""
        if key not in PAINT_KEYS:
            raise ProvinceError("bad_key", 0, key)
        changed = []
        for pid in dict.fromkeys(int(p) for p in pids):
            if self.is_sea(pid) or _definition_row(self.index, pid)[1] is None:
                continue
            if self.set(pid, key, value, date):
                changed.append(pid)
        return changed

    def edit_event(self, pid: int, event: TimelineEvent, key: str, value: object) -> None:
        """Edita un suceso concreto de la línea temporal (el bloque ``event``, no el que elegiría la fecha de
        trabajo); None quita la clave de ese bloque."""
        from ..clausewitz.nodes import Block

        self._land(pid)
        record = self.record(pid)
        if record is None:
            raise ProvinceError("unknown", pid)
        dated = [entry for entry in record.block.entries
                 if entry.key is not None and isinstance(entry.value, Block) and entry.key.is_date()]
        if not 0 <= event.index < len(dated):
            raise ProvinceError("unknown", pid, str(event.date))
        block = dated[event.index].value
        field = record._field_of(key)
        record._touch()
        if value is None:
            block.remove(key)
            return
        written = field.type.write(value, None) if field is not None else value
        found = block.find(key)
        if found is None:
            block.append(key, written)
        else:
            found.value = written

    # --- POPs ---------------------------------------------------------------------------------------

    def pops(self) -> ProvincePops:
        """El editor de POPs sobre las mismas ``Entities``."""
        return ProvincePops(self.entities)


def _str(value) -> str | None:
    if value is None or value is MISSING:
        return None
    return str(value)


def _same(current, value) -> bool:
    if current is None or current is MISSING:
        return value is None
    if value is None:
        return False
    return str(current).lower() == str(value).lower()
