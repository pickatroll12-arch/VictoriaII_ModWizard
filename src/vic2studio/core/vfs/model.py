"""Tipos de la VFS: capas, huellas, entradas y la instantánea inmutable para hilos (wizard §5.1, I12)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from .paths import VPath


class DocKind(Enum):
    """Qué códec abre un archivo (wizard §6.1). Vive aquí porque las reglas de carga lo declaran."""

    CLAUSEWITZ = "clausewitz"
    LOCALISATION = "localisation"
    TABLE = "table"        # definition.csv, adjacencies.csv (iteración 5)
    LUA = "lua"            # defines.lua (iteración 3)
    BMP = "bmp"            # provinces.bmp, terrain.bmp, rivers.bmp (iteración 5)
    IMAGE = "image"        # tga, dds, png (iteraciones 6 y 8)
    BINARY = "binary"      # cualquier otro: solo lectura


class LayerKind(Enum):
    GAME = "game"
    DEPENDENCY = "dependency"
    MOD = "mod"


@dataclass(frozen=True)
class Layer:
    kind: LayerKind
    root: Path
    label: str


@dataclass(frozen=True)
class Fingerprint:
    """Huella barata de ``os.stat`` (tamaño y mtime en ns); ``sha256`` se calcula solo si hace falta."""

    size: int
    mtime_ns: int
    sha256: str | None = None

    @classmethod
    def of_path(cls, path: Path, *, with_hash: bool = False) -> Fingerprint:
        raise NotImplementedError

    def same_stat(self, other: Fingerprint | None) -> bool:
        """Mismo tamaño y mtime (sin mirar el sha)."""
        raise NotImplementedError


@dataclass(frozen=True)
class FileEntry:
    """Un archivo concreto de una capa: ``rel`` en el juego, ``path`` real en disco."""

    rel: VPath
    layer: Layer
    path: Path
    fingerprint: Fingerprint


@dataclass(frozen=True)
class VfsSnapshot:
    """Vista inmutable de la VFS en un momento dado: apta para hilos de fondo (I12).

    ``entries`` va de ``rel.key`` a la pila de esa ruta (ganador primero, igual que
    ``VirtualFS.stack``). Las entradas ocultas por ``replace_path`` siguen en la pila
    y ``hidden`` las nombra. No lee ni escribe disco.
    """

    layers: tuple[Layer, ...]
    entries: Mapping[str, tuple[FileEntry, ...]] = MappingProxyType({})
    hidden: frozenset[str] = frozenset()   # (rel.key) de archivos del juego ocultos por replace_path

    def resolve(self, rel: str | VPath) -> FileEntry | None:
        raise NotImplementedError

    def stack(self, rel: str | VPath) -> list[FileEntry]:
        raise NotImplementedError

    def list(self, folder: str, pattern: str = "*.txt", *, recursive: bool | None = None) -> list[FileEntry]:
        raise NotImplementedError

    def rels(self) -> Iterable[VPath]:
        raise NotImplementedError
