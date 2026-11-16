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

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

from ..clausewitz.nodes import Block, Entry, Scalar
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


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*\Z")


def _ints(block: Block) -> list[int]:
    out = []
    for entry in block:
        if entry.key is None and isinstance(entry.value, Scalar):
            try:
                out.append(entry.value.as_int())
            except ValueError:
                continue
    return out


def _all_bare(block: Block) -> bool:
    return all(entry.key is None for entry in block)


def _lists(document: Block, layout: str) -> dict[str, Block]:
    """``{grupo: bloque de su lista}`` en orden de archivo (la primera aparición fija el orden)."""
    found: dict[str, Block | None] = {}
    for entry in document:
        if entry.key is None or not isinstance(entry.value, Block):
            continue
        name = entry.key.text
        if layout == LAYOUT_FLAT:
            found.setdefault(name, entry.value)
        elif layout == LAYOUT_PROVINCES_KEY:
            inner = entry.value.get(PROVINCES_KEY)
            if name not in found or found[name] is None:
                found[name] = inner if isinstance(inner, Block) else None
        else:
            found.setdefault(name, None)
            if _all_bare(entry.value):
                found[name] = entry.value
    return found


def read_groups(data: bytes, layout: str = LAYOUT_FLAT) -> dict[str, list[int]]:
    """``{grupo: ids}`` en orden de archivo, leído de bytes (hilo de tarea, I12; coherencia y hechos). Con la
    misma lectura que ``ProvinceGroups``."""
    from ..project.codecs import parse_bytes

    document = parse_bytes(data).document
    return {name: ([] if block is None else _ints(block)) for name, block in _lists(document, layout).items()}


class ProvinceGroups:
    def __init__(self, ws: Workspace, rel: VPath, *, layout: str = LAYOUT_FLAT) -> None:
        """Vista de ``rel`` en ``ws``. No abre el documento hasta la primera consulta. ``ValueError`` si
        ``layout`` no es de ``LAYOUTS``."""
        if layout not in LAYOUTS:
            raise ValueError(f"layout desconocido: {layout}")
        self.ws = ws
        self.rel = VPath.of(rel)
        self.layout = layout

    def _handle(self):
        return self.ws.open(self.rel)

    def _document(self) -> Block:
        return self._handle().model.document

    def _lists(self) -> dict[str, Block | None]:
        return _lists(self._document(), self.layout)

    def _touch(self) -> Block:
        handle = self._handle()
        self.ws.touch(handle)
        return handle.model.document

    def groups(self) -> list[str]:
        """Nombres en orden de archivo (en ``paired``, el de la primera aparición), sin repetir."""
        return list(self._lists())

    def members(self, gid: str) -> list[int]:
        """Ids del grupo en su orden, con los repetidos tal cual. ``GroupError("unknown_group")`` si no existe."""
        lists = self._lists()
        if gid not in lists:
            raise GroupError("unknown_group", gid)
        block = lists[gid]
        return [] if block is None else _ints(block)

    def group_of(self, pid: int) -> str | None:
        """El primer grupo (en orden de archivo) que contiene ``pid``; None si ninguno."""
        found = self.groups_of(pid)
        return found[0] if found else None

    def groups_of(self, pid: int) -> list[str]:
        """Todos los grupos que contienen ``pid`` (más de uno = ``land_province_multiple_regions``)."""
        return [name for name, block in self._lists().items() if block is not None and pid in _ints(block)]

    def _list_for_write(self, gid: str, lists: dict[str, Block | None]) -> Block:
        block = lists.get(gid)
        if gid not in lists:
            raise GroupError("unknown_group", gid)
        if block is not None:
            return block
        document = self._document()
        if self.layout == LAYOUT_PAIRED:
            raise GroupError("paired_layout", gid)
        entry = next(e for e in document if e.key is not None and e.key.text == gid and isinstance(e.value, Block))
        entry.value.append(PROVINCES_KEY, Block())
        return entry.value.get(PROVINCES_KEY)

    @staticmethod
    def _drop(block: Block, pid: int) -> int:
        removed = 0
        for entry in list(block):
            if entry.key is None and isinstance(entry.value, Scalar):
                try:
                    if entry.value.as_int() == pid:
                        block.remove_entry(entry)
                        removed += 1
                except ValueError:
                    continue
        return removed

    def move(self, pid: int, gid: str) -> None:
        """Deja ``pid`` solo en ``gid``: lo quita de los demás grupos y lo añade al final de ``gid`` si no
        estaba. Si ya estaba solo en ``gid`` no cambia nada (ni ensucia el documento)."""
        lists = self._lists()
        if gid not in lists:
            raise GroupError("unknown_group", gid)
        if self.layout == LAYOUT_PAIRED and lists[gid] is None:
            raise GroupError("paired_layout", gid)
        if self.groups_of(pid) == [gid] and self.members(gid).count(pid) == 1:
            return
        self._touch()
        lists = self._lists()
        for name, block in lists.items():
            if name != gid and block is not None:
                self._drop(block, pid)
        target = self._list_for_write(gid, lists)
        present = _ints(target).count(pid)
        if present > 1:
            self._drop(target, pid)
            present = 0
        if not present:
            target.append_value(int(pid))

    def remove(self, pid: int) -> None:
        """Quita ``pid`` de todos los grupos (una provincia que pasa a ser de mar)."""
        if not self.groups_of(pid):
            return
        self._touch()
        for block in self._lists().values():
            if block is not None:
                self._drop(block, pid)

    def create(self, gid: str, members: Iterable[int] = ()) -> None:
        """Grupo nuevo al final del archivo con ``members`` (que se quitan de los grupos donde estuvieran).
        ``GroupError`` si el nombre ya existe o no es una palabra válida. En ``paired`` crea las dos entradas
        (la de modificadores, vacía, y la lista); en ``provinces_key``, ``provinces = { … }``."""
        if not _NAME.match(gid or ""):
            raise GroupError("bad_name", gid)
        lists = self._lists()
        if gid in lists:
            raise GroupError("group_exists", gid)
        members = list(dict.fromkeys(int(m) for m in members))
        document = self._touch()
        for block in lists.values():
            if block is not None:
                for pid in members:
                    self._drop(block, pid)
        listing = Block()
        for pid in members:
            listing.append_value(pid)
        if self.layout == LAYOUT_FLAT:
            document.append(gid, listing)
        elif self.layout == LAYOUT_PROVINCES_KEY:
            outer = Block()
            outer.append(PROVINCES_KEY, listing)
            document.append(gid, outer)
        else:
            document.append(gid, Block())
            document.append(gid, listing)

    def rename(self, old: str, new: str) -> None:
        """Cambia la clave del grupo (las dos, en ``paired``). No toca los usos en otros archivos ni la
        localización: eso es del renombrado seguro (§15). ``GroupError`` si ``new`` ya existe."""
        if not _NAME.match(new or ""):
            raise GroupError("bad_name", new)
        lists = self._lists()
        if old not in lists:
            raise GroupError("unknown_group", old)
        if new in lists:
            raise GroupError("group_exists", new)
        document = self._touch()
        for entry in list(document):
            if entry.key is not None and entry.key.text == old and isinstance(entry.value, Block):
                entry.key = new

    def delete(self, gid: str) -> None:
        """Borra el grupo; ``GroupError("group_not_empty")`` si aún tiene provincias (§14.14)."""
        if self.members(gid):
            raise GroupError("group_not_empty", gid)
        document = self._touch()
        for entry in list(document):
            if entry.key is not None and entry.key.text == gid and isinstance(entry.value, Block):
                document.remove_entry(entry)
