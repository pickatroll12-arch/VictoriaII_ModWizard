"""``map/positions.txt``: lectura y edición de los puntos de cada provincia (wizard §14.3, §16). Contrato.

Un bloque ``<id> = { … }`` por provincia (3 248 en vanilla, 1,4 MB, CRLF; uno vacío). Dentro hay puntos ``{ x y }``
(``unit``, ``text_position``, ``factory``, ``building_construction``, ``military_construction``, ``city``,
``town``), ``building_position = { fort|naval_base|railroad = { x y } }``, giros (``building_rotation = {
naval_base = r }``, ``text_rotation``) y escalas (``text_scale``). Las coordenadas son las del juego, las mismas
del ráster (criterio 2: el punto ``unit`` cae en su provincia o junto a ella en ≥ 95 % de los casos).

``Positions`` es una vista sobre el CST del documento: no copia nada y editar un punto cambia solo sus dos
números, con los decimales que ya tenía (3 en vanilla), I3. Las ediciones van dentro de la transacción de quien
llama, tras ``ws.touch``. Generar los puntos de un mapa nuevo (``generate``) llega con el taller, iteración 9a.

Ojo con el tamaño: reanalizar este archivo cuesta 0,6–1 s (CONTINUAR §6), así que la interfaz no lo abre para
pintar; para leer en segundo plano está ``unit_points``, que recibe bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..clausewitz.nodes import Block, Entry, Scalar
from ..project.codecs import parse_bytes
from ..vfs.paths import VPath

POSITIONS_REL = VPath.of("map/positions.txt")
POINT_KEYS = ("unit", "text_position", "factory", "building_construction", "military_construction", "city",
              "town")
BUILDING_KEYS = ("fort", "naval_base", "railroad")
SCALAR_KEYS = ("text_scale", "text_rotation")
DECIMALS = 3                         # los de un número nuevo (los existentes conservan los suyos)


@dataclass(frozen=True)
class Point:
    x: float
    y: float


def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def _number(value: float, like: str | None = None) -> Scalar:
    """Número con los decimales de ``like`` (el texto que sustituye) o con ``DECIMALS`` si es nuevo."""
    places = DECIMALS if like is None else _decimals(like)
    return Scalar(f"{float(value):.{places}f}" if places else str(int(round(float(value)))))


def _float(value) -> float | None:
    if isinstance(value, Scalar):
        try:
            return value.as_float()
        except ValueError:
            return None
    return None


def _point_of(value) -> Point | None:
    if not isinstance(value, Block):
        return None
    x, y = _float(value.get("x")), _float(value.get("y"))
    if x is None or y is None:
        return None
    return Point(x, y)


def _set_number(block: Block, key: str, value: float) -> None:
    entry = block.find(key)
    if entry is None:
        block.append(key, _number(value))
    elif not (isinstance(entry.value, Scalar) and _float(entry.value) == float(value)):
        old = entry.value.text if isinstance(entry.value, Scalar) else None
        entry.value = _number(value, old)


def _set_xy(parent: Block, key: str, point: Point | None) -> None:
    entry = parent.find(key)
    if point is None:
        if entry is not None:
            parent.remove_entry(entry)
        return
    if entry is None or not isinstance(entry.value, Block):
        block = Block()
        block.append("x", _number(point.x))
        block.append("y", _number(point.y))
        if entry is None:
            parent.append(key, block)
        else:
            entry.value = block
        return
    _set_number(entry.value, "x", point.x)
    _set_number(entry.value, "y", point.y)


def _pid(entry: Entry) -> int | None:
    if entry.key is None or not isinstance(entry.value, Block):
        return None
    try:
        return entry.key.as_int()
    except ValueError:
        return None


class Positions:
    """Puntos de ``positions.txt`` sobre su documento (``DocHandle.model.document``)."""

    def __init__(self, document: Block) -> None:
        self.document = document

    def _blocks(self) -> dict[int, Block]:
        out: dict[int, Block] = {}
        for entry in self.document:
            pid = _pid(entry)
            if pid is not None and pid not in out:
                out[pid] = entry.value
        return out

    def _block(self, pid: int, *, create: bool = False) -> Block | None:
        block = self._blocks().get(pid)
        if block is None and create:
            self.document.append(str(int(pid)), Block())
            block = self._blocks().get(pid)
        return block

    def ids(self) -> list[int]:
        """Ids con bloque, en orden de archivo (un id repetido sale una vez; cuenta su primer bloque)."""
        return list(self._blocks())

    def has(self, pid: int) -> bool:
        return pid in self._blocks()

    def point(self, pid: int, key: str) -> Point | None:
        """Punto ``key`` (uno de ``POINT_KEYS``) de ``pid``; None si falta o no son dos números."""
        block = self._block(pid)
        return None if block is None else _point_of(block.get(key))

    def building_point(self, pid: int, building: str) -> Point | None:
        """``building_position = { <building> = { x y } }``."""
        block = self._block(pid)
        inner = None if block is None else block.get("building_position")
        return _point_of(inner.get(building)) if isinstance(inner, Block) else None

    def rotation(self, pid: int, building: str) -> float | None:
        """``building_rotation = { <building> = r }``."""
        block = self._block(pid)
        inner = None if block is None else block.get("building_rotation")
        return _float(inner.get(building)) if isinstance(inner, Block) else None

    def scalar(self, pid: int, key: str) -> float | None:
        """``text_scale`` o ``text_rotation``."""
        block = self._block(pid)
        return None if block is None else _float(block.get(key))

    def set_point(self, pid: int, key: str, point: Point | None) -> None:
        """Pone o quita (None) el punto. Si el bloque de ``pid`` no existe, lo crea al final del archivo; si el
        punto existe, cambia solo ``x`` e ``y``. ``ValueError`` si ``key`` no es de ``POINT_KEYS``."""
        if key not in POINT_KEYS:
            raise ValueError(f"no es un punto de positions.txt: {key}")
        block = self._block(pid, create=point is not None)
        if block is not None:
            _set_xy(block, key, point)

    def _inner(self, pid: int, key: str, create: bool) -> Block | None:
        block = self._block(pid, create=create)
        if block is None:
            return None
        inner = block.get(key)
        if not isinstance(inner, Block) and create:
            block.append(key, Block())
            inner = block.get(key)
        return inner if isinstance(inner, Block) else None

    def set_building_point(self, pid: int, building: str, point: Point | None) -> None:
        if building not in BUILDING_KEYS:
            raise ValueError(f"no es un edificio de positions.txt: {building}")
        inner = self._inner(pid, "building_position", point is not None)
        if inner is not None:
            _set_xy(inner, building, point)

    def set_rotation(self, pid: int, building: str, value: float | None) -> None:
        if building not in BUILDING_KEYS:
            raise ValueError(f"no es un edificio de positions.txt: {building}")
        inner = self._inner(pid, "building_rotation", value is not None)
        if inner is None:
            return
        if value is None:
            inner.remove(building)
        else:
            _set_number(inner, building, value)

    def set_scalar(self, pid: int, key: str, value: float | None) -> None:
        if key not in SCALAR_KEYS:
            raise ValueError(f"no es un valor de positions.txt: {key}")
        block = self._block(pid, create=value is not None)
        if block is None:
            return
        if value is None:
            block.remove(key)
        else:
            _set_number(block, key, value)


def unit_points(data: bytes) -> dict[int, Point]:
    """El punto ``unit`` de cada provincia que lo tiene, leído de los bytes del archivo (hilo de tarea, I12)."""
    positions = Positions(parse_bytes(data).document)
    out: dict[int, Point] = {}
    for pid, block in positions._blocks().items():
        point = _point_of(block.get("unit"))
        if point is not None:
            out[pid] = point
    return out
