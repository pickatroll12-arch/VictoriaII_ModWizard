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

from ..clausewitz.nodes import Block
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


class Positions:
    """Puntos de ``positions.txt`` sobre su documento (``DocHandle.model.document``)."""

    def __init__(self, document: Block) -> None:
        self.document = document

    def ids(self) -> list[int]:
        """Ids con bloque, en orden de archivo (un id repetido sale una vez; cuenta su primer bloque)."""
        raise NotImplementedError

    def has(self, pid: int) -> bool:
        raise NotImplementedError

    def point(self, pid: int, key: str) -> Point | None:
        """Punto ``key`` (uno de ``POINT_KEYS``) de ``pid``; None si falta o no son dos números."""
        raise NotImplementedError

    def building_point(self, pid: int, building: str) -> Point | None:
        """``building_position = { <building> = { x y } }``."""
        raise NotImplementedError

    def rotation(self, pid: int, building: str) -> float | None:
        """``building_rotation = { <building> = r }``."""
        raise NotImplementedError

    def scalar(self, pid: int, key: str) -> float | None:
        """``text_scale`` o ``text_rotation``."""
        raise NotImplementedError

    def set_point(self, pid: int, key: str, point: Point | None) -> None:
        """Pone o quita (None) el punto. Si el bloque de ``pid`` no existe, lo crea al final del archivo; si el
        punto existe, cambia solo ``x`` e ``y``. ``ValueError`` si ``key`` no es de ``POINT_KEYS``."""
        raise NotImplementedError

    def set_building_point(self, pid: int, building: str, point: Point | None) -> None:
        raise NotImplementedError

    def set_rotation(self, pid: int, building: str, value: float | None) -> None:
        raise NotImplementedError

    def set_scalar(self, pid: int, key: str, value: float | None) -> None:
        raise NotImplementedError


def unit_points(data: bytes) -> dict[int, Point]:
    """El punto ``unit`` de cada provincia que lo tiene, leído de los bytes del archivo (hilo de tarea, I12)."""
    raise NotImplementedError
