"""``GameRules``: los datos del juego que condicionan la validación y los asistentes (wizard §9).

Se leen de la vista efectiva (mod sobre juego, con los cambios sin guardar como
``overrides``) y son inmutables: aptos para hilos de fondo (I12). Leer no escribe
nada (I4) y un archivo que falta o está roto da los valores por defecto del juego
base, nunca una excepción.

Fuentes: ``common/defines.lua`` (``start_date``/``end_date`` con ``LuaDefines``),
``common/bookmarks.txt``, ``map/default.map`` (``max_provinces``, ``sea_starts`` y
los nombres de los archivos del mapa), la cabecera del BMP de provincias que
nombra ``default.map`` (sin decodificarlo), ``common/issues.txt`` y
``common/governments.txt``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ..clausewitz.nodes import ClausewitzDate, Scalar
from ..vfs.model import VfsSnapshot
from ..vfs.paths import VPath

_log = logging.getLogger(__name__)

DEFAULT_START = ClausewitzDate(1836, 1, 1)
DEFAULT_END = ClausewitzDate(1935, 12, 31)

DEFINES_REL = VPath.of("common/defines.lua")
BOOKMARKS_REL = VPath.of("common/bookmarks.txt")
DEFAULT_MAP_REL = VPath.of("map/default.map")
ISSUES_REL = VPath.of("common/issues.txt")
GOVERNMENTS_REL = VPath.of("common/governments.txt")
PARTY_ISSUES = "party_issues"
# Nombres por defecto de los archivos del mapa (los de vanilla, H5), por clave de default.map.
DEFAULT_MAP_FILES = MappingProxyType({
    "definitions": "definition.csv", "provinces": "provinces.bmp", "positions": "positions.txt",
    "terrain": "terrain.bmp", "rivers": "rivers.bmp", "terrain_definition": "terrain.txt",
    "tree_definition": "trees.txt", "continent": "continent.txt", "adjacencies": "adjacencies.csv",
    "region": "region.txt", "region_sea": "region_sea.txt", "province_flag_sprite": "province_flag_sprites",
})
# Claves de un gobierno que no son ideologías (``<ideología> = yes``, H16).
GOVERNMENT_FIELDS = frozenset({"election", "duration", "appoint_ruling_party", "flagtype"})
BMP_HEADER_BYTES = 30                               # core.map.bmp.HEADER_BYTES (sin importar numpy aquí)


@dataclass(frozen=True)
class GameRules:
    start_date: ClausewitzDate = DEFAULT_START          # common/defines.lua (START_DATE / start_date)
    end_date: ClausewitzDate = DEFAULT_END
    bookmarks: tuple[ClausewitzDate, ...] = ()          # common/bookmarks.txt
    max_provinces: int = 0                              # map/default.map
    sea: frozenset[int] = frozenset()                   # default.map: sea_starts (H5: 3246 es de tierra)
    map_size: tuple[int, int] = (0, 0)                  # cabecera de map/provinces.bmp, sin decodificarlo
    party_policies: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({}))   # common/issues.txt → party_issues: grupo → opciones
    government_ideologies: Mapping[str, frozenset[str]] = field(
        default_factory=lambda: MappingProxyType({}))   # common/governments.txt: gobierno → ideologías
    # Ampliaciones compatibles de la iteración 3:
    reforms: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({}))   # issues.txt sin party_issues: grupo → opciones
    map_files: Mapping[str, str] = DEFAULT_MAP_FILES    # default.map: clave → archivo de map/

    @classmethod
    def from_snapshot(cls, snapshot: VfsSnapshot, overrides: Mapping[VPath, bytes] | None = None) -> GameRules:
        """Reglas de la vista efectiva de ``snapshot`` (``overrides``: documentos sin guardar)."""
        reader = _Reader(snapshot, overrides or {})
        values: dict = {}
        for loader in (_defines, _bookmarks, _default_map, _issues, _governments):
            try:
                values.update(loader(reader))
            except Exception:  # noqa: BLE001 - un archivo roto da los valores por defecto (docstring)
                _log.exception("no se pudieron leer las reglas del juego con %s", loader.__name__)
        files = values.get("map_files", DEFAULT_MAP_FILES)
        try:
            values["map_size"] = _bmp_size(reader.head(VPath.of(f"map/{files.get('provinces', 'provinces.bmp')}"),
                                                       BMP_HEADER_BYTES))
        except Exception:  # noqa: BLE001
            _log.exception("no se pudo leer la cabecera del BMP de provincias")
        return cls(**values)

    @classmethod
    def from_vfs(cls, vfs) -> GameRules:
        """Atajo para ``from_snapshot(vfs.snapshot())``."""
        return cls.from_snapshot(vfs.snapshot())

    def is_sea(self, province: int) -> bool:
        return province in self.sea


class _Reader:
    """Bytes efectivos: el documento sin guardar si lo hay; si no, el ganador de la instantánea."""

    def __init__(self, snapshot: VfsSnapshot, overrides: Mapping[VPath, bytes]) -> None:
        self.snapshot = snapshot
        self.overrides = {VPath.of(rel).key: data for rel, data in overrides.items()}

    def read(self, rel: VPath) -> bytes | None:
        if rel.key in self.overrides:
            return self.overrides[rel.key]
        entry = self.snapshot.resolve(rel)
        if entry is None:
            return None
        try:
            return entry.path.read_bytes()
        except OSError:
            return None

    def head(self, rel: VPath, size: int) -> bytes | None:
        if rel.key in self.overrides:
            data = self.overrides[rel.key]
            return None if data is None else data[:size]
        entry = self.snapshot.resolve(rel)
        if entry is None:
            return None
        try:
            with open(entry.path, "rb") as handle:
                return handle.read(size)
        except OSError:
            return None

    def document(self, rel: VPath):
        data = self.read(rel)
        if data is None:
            return None
        from ..project.codecs import parse_bytes

        return parse_bytes(data).document


def _date(text: str | None) -> ClausewitzDate | None:
    if not text:
        return None
    try:
        return ClausewitzDate.parse(text.strip().strip("'\""))
    except ValueError:
        return None


def _defines(reader: _Reader) -> dict:
    data = reader.read(DEFINES_REL)
    if data is None:
        return {}
    from ..lua_defines import LuaDefines

    defines = LuaDefines.from_bytes(data)
    found = {}
    for key, name in (("start_date", "start_date"), ("end_date", "end_date")):
        value = defines.get(key)
        date = _date(value.text) if value is not None else None
        if date is not None:
            found[name] = date
    return found


def _bookmarks(reader: _Reader) -> dict:
    doc = reader.document(BOOKMARKS_REL)
    if doc is None:
        return {}
    dates = []
    for entry in doc.entries:
        if entry.key is not None and entry.key.text.lower() == "bookmark" and entry.value.__class__ is not Scalar:
            date = _date(entry.value.get_text("date"))
            if date is not None:
                dates.append(date)
    return {"bookmarks": tuple(dates)}


def _default_map(reader: _Reader) -> dict:
    doc = reader.document(DEFAULT_MAP_REL)
    if doc is None:
        return {}
    found: dict = {}
    files = dict(DEFAULT_MAP_FILES)
    for entry in doc.entries:
        if entry.key is None:
            continue
        key = entry.key.text.lower()
        value = entry.value
        if key == "max_provinces" and value.__class__ is Scalar and value.text.lstrip("-").isdigit():
            found["max_provinces"] = int(value.text)
        elif key == "sea_starts" and value.__class__ is not Scalar:
            found["sea"] = frozenset(int(e.value.text) for e in value.entries
                                     if e.key is None and e.value.__class__ is Scalar and e.value.text.isdigit())
        elif key in DEFAULT_MAP_FILES and value.__class__ is Scalar:
            name = value.text.replace("\\", "/")
            if map_file_ok(name):
                files[key] = name
            else:
                _log.info("default.map nombra un archivo no válido en %s (%r): se usa %s", key, name, files[key])
    found["map_files"] = MappingProxyType(files)
    return found


def map_file_ok(name: str) -> bool:
    """True si ``name`` (un valor de ``default.map``) es un archivo válido dentro de ``map/``: sin ``..``, sin ruta
    absoluta ni unidad (``VPath.of`` lo rechazaría y las reglas que lo leen fallarían)."""
    from ..vfs.paths import InvalidPathError

    if not name.strip():
        return False
    try:
        rel = VPath.of(f"map/{name}")
    except (InvalidPathError, ValueError, TypeError):
        return False
    return rel.key.startswith("MAP/") and len(rel.parts) >= 2


def _issues(reader: _Reader) -> dict:
    doc = reader.document(ISSUES_REL)
    if doc is None:
        return {}
    party: dict[str, tuple[str, ...]] = {}
    reforms: dict[str, tuple[str, ...]] = {}
    for category in doc.entries:
        if category.key is None or category.value.__class__ is Scalar:
            continue
        target = party if category.key.text == PARTY_ISSUES else reforms
        for group in category.value.entries:
            if group.key is None or group.value.__class__ is Scalar:
                continue
            target[group.key.text] = tuple(o.key.text for o in group.value.entries
                                           if o.key is not None and o.value.__class__ is not Scalar)
    return {"party_policies": MappingProxyType(party), "reforms": MappingProxyType(reforms)}


def _governments(reader: _Reader) -> dict:
    doc = reader.document(GOVERNMENTS_REL)
    if doc is None:
        return {}
    found: dict[str, frozenset[str]] = {}
    for entry in doc.entries:
        if entry.key is None or entry.value.__class__ is Scalar:
            continue
        found[entry.key.text] = frozenset(
            child.key.text for child in entry.value.entries
            if child.key is not None and child.value.__class__ is Scalar and child.key.text.lower() not in
            GOVERNMENT_FIELDS and child.value.text.lower() == "yes")
    return {"government_ideologies": MappingProxyType(found)}


def _bmp_size(header: bytes | None) -> tuple[int, int]:
    """Ancho y alto de un BMP leyendo solo su cabecera; (0, 0) si no es un BMP. La cabecera la interpreta
    ``core.map.bmp``, el único lector de BMP (contrato de la iteración 5)."""
    if header is None:
        return (0, 0)
    from ..map.bmp import BmpError, bmp_size

    try:
        width, height = bmp_size(header)
    except BmpError:
        return (0, 0)
    return (abs(width), height)
