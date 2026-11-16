"""``ProvinceGroups``: regiones, regiones de mar, continentes y climas como grupos de provincias (wizard §14.14).

Contrato. Los cuatro archivos son «nombre → lista de ids» con tres formas (``layout``):

- ``"flat"`` — ``map/region.txt`` y ``map/region_sea.txt``: ``NOMBRE = { 1 2 3 }``. Vanilla: 549 estados, ninguno
  vacío ni repetido; ``region_sea.txt`` es solo CR y sus 3 regiones están vacías.
- ``"provinces_key"`` — ``map/continent.txt``: ``nombre = { provinces = { … } <modificadores> }`` (6 en vanilla).
- ``"paired"`` — ``map/climate.txt``: dos entradas con la misma clave (H7), la primera con los modificadores y la
  segunda con la lista. Vanilla trae las 4 de modificadores y después las 4 listas; el minijuego las alterna. La
  lista es la última entrada con ese nombre cuyos valores son todos sueltos; aquí nunca se usa ``Block.set(nombre)``.

Es una vista sobre el documento efectivo del ``Workspace`` (I7): lee sin escribir (I4) y cada mutación llama a
``ws.touch`` (exige una transacción de quien llama, I5) y edita solo las listas afectadas, conservando el resto
byte a byte: añadir pone el id al final de la lista con la separación de sus vecinos y quitar se lleva solo ese
valor (I3). ``move`` es una edición compuesta: quita de todos los grupos donde esté y añade al destino, de modo
que «cada provincia de tierra está en exactamente un estado» se cumple tras cada llamada (criterio 7).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..vfs.paths import VPath

if TYPE_CHECKING:
    from ..project.workspace import Workspace

LAYOUT_FLAT = "flat"
LAYOUT_PROVINCES_KEY = "provinces_key"
LAYOUT_PAIRED = "paired"
LAYOUTS = (LAYOUT_FLAT, LAYOUT_PROVINCES_KEY, LAYOUT_PAIRED)
PROVINCES_KEY = "provinces"

REGION_REL = VPath.of("map/region.txt")
REGION_SEA_REL = VPath.of("map/region_sea.txt")
CONTINENT_REL = VPath.of("map/continent.txt")
CLIMATE_REL = VPath.of("map/climate.txt")
# Los cuatro archivos por su clave en ``default.map`` (``GameRules.map_files``) y su forma. ``climate`` no está en
# ``default.map``: su ruta es fija.
GROUP_FILES = {"region": (REGION_REL, LAYOUT_FLAT), "region_sea": (REGION_SEA_REL, LAYOUT_FLAT),
               "continent": (CONTINENT_REL, LAYOUT_PROVINCES_KEY), "climate": (CLIMATE_REL, LAYOUT_PAIRED)}


class GroupError(ValueError):
    """Una operación que rompería el archivo; no se cambió nada. ``code``: ``unknown_group``, ``group_exists``,
    ``group_not_empty``, ``bad_name`` o ``paired_layout`` (un clima sin su entrada de lista)."""

    def __init__(self, code: str, group: str = "") -> None:
        self.code = code
        self.group = group
        super().__init__(f"{code}: {group}" if group else code)


class ProvinceGroups:
    def __init__(self, ws: Workspace, rel: VPath, *, layout: str = LAYOUT_FLAT) -> None:
        """Vista de ``rel`` en ``ws``. No abre el documento hasta la primera consulta. ``ValueError`` si
        ``layout`` no es de ``LAYOUTS``."""
        if layout not in LAYOUTS:
            raise ValueError(f"layout desconocido: {layout}")
        self.ws = ws
        self.rel = VPath.of(rel)
        self.layout = layout

    def groups(self) -> list[str]:
        """Nombres en orden de archivo (en ``paired``, el de la primera aparición), sin repetir."""
        raise NotImplementedError

    def members(self, gid: str) -> list[int]:
        """Ids del grupo en su orden, con los repetidos tal cual. ``GroupError("unknown_group")`` si no existe."""
        raise NotImplementedError

    def group_of(self, pid: int) -> str | None:
        """El primer grupo (en orden de archivo) que contiene ``pid``; None si ninguno."""
        raise NotImplementedError

    def groups_of(self, pid: int) -> list[str]:
        """Todos los grupos que contienen ``pid`` (más de uno = ``land_province_multiple_regions``)."""
        raise NotImplementedError

    def move(self, pid: int, gid: str) -> None:
        """Deja ``pid`` solo en ``gid``: lo quita de los demás grupos y lo añade al final de ``gid`` si no
        estaba. Si ya estaba solo en ``gid`` no cambia nada (ni ensucia el documento)."""
        raise NotImplementedError

    def remove(self, pid: int) -> None:
        """Quita ``pid`` de todos los grupos (una provincia que pasa a ser de mar)."""
        raise NotImplementedError

    def create(self, gid: str, members: Iterable[int] = ()) -> None:
        """Grupo nuevo al final del archivo con ``members`` (que se quitan de los grupos donde estuvieran).
        ``GroupError`` si el nombre ya existe o no es una palabra válida. En ``paired`` crea las dos entradas
        (la de modificadores, vacía, y la lista); en ``provinces_key``, ``provinces = { … }``."""
        raise NotImplementedError

    def rename(self, old: str, new: str) -> None:
        """Cambia la clave del grupo (las dos, en ``paired``). No toca los usos en otros archivos ni la
        localización: eso es del renombrado seguro (§15). ``GroupError`` si ``new`` ya existe."""
        raise NotImplementedError

    def delete(self, gid: str) -> None:
        """Borra el grupo; ``GroupError("group_not_empty")`` si aún tiene provincias (§14.14)."""
        raise NotImplementedError


def read_groups(data: bytes, layout: str = LAYOUT_FLAT) -> dict[str, list[int]]:
    """``{grupo: ids}`` en orden de archivo, leído de bytes (hilo de tarea, I12; coherencia y hechos). Con la
    misma lectura que ``ProvinceGroups``."""
    raise NotImplementedError
