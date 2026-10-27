"""Tipos de la VFS: capas, huellas, entradas y la instantánea inmutable para hilos (wizard §5.1, I12)."""

from __future__ import annotations

import fnmatch
import hashlib
import os
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
    JSON = "json"          # archivos propios del Studio (.vic2studio/project.json)
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
        """Huella de ``path`` ahora; ``FileNotFoundError`` si no existe. ``with_hash`` lee el archivo entero."""
        stat = os.stat(path)
        return cls(stat.st_size, stat.st_mtime_ns, sha256_file(path) if with_hash else None)

    @classmethod
    def of_bytes(cls, data: bytes, stat: os.stat_result) -> Fingerprint:
        """Huella con sha de unos bytes ya leídos y el ``stat`` que se tomó al leerlos."""
        return cls(stat.st_size, stat.st_mtime_ns, sha256_bytes(data))

    def same_stat(self, other: Fingerprint | None) -> bool:
        """Mismo tamaño y mtime (sin mirar el sha)."""
        return other is not None and self.size == other.size and self.mtime_ns == other.mtime_ns

    def matches(self, other: Fingerprint | None, path: Path | None = None) -> bool:
        """True si ``other`` (la huella actual de ``path``) describe el mismo contenido.

        Mismo ``stat`` basta; si cambió el mtime pero el tamaño no, y esta huella
        tiene sha, se compara el sha del archivo (otro programa lo tocó sin cambiarlo).
        """
        if other is None:
            return False
        if self.same_stat(other):
            return True
        if self.sha256 is None or self.size != other.size:
            return False
        if other.sha256 is not None:
            return other.sha256 == self.sha256
        if path is None:
            return False
        try:
            return sha256_file(path) == self.sha256
        except OSError:
            return False


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        key = VPath.of(rel).key
        return winner(self.entries.get(key, ()), key in self.hidden)

    def stack(self, rel: str | VPath) -> list[FileEntry]:
        return list(self.entries.get(VPath.of(rel).key, ()))

    def list(self, folder: str, pattern: str = "*.txt", *, recursive: bool | None = None) -> list[FileEntry]:
        found = []
        for key in matching_keys(self.entries.keys(), folder, pattern, recursive):
            entry = winner(self.entries[key], key in self.hidden)
            if entry is not None:
                found.append(entry)
        return found

    def rels(self) -> Iterable[VPath]:
        for key, stack in self.entries.items():
            entry = winner(stack, key in self.hidden)
            if entry is not None:
                yield entry.rel


def winner(stack: Iterable[FileEntry], hidden: bool) -> FileEntry | None:
    """Primera entrada de la pila que carga el juego: con ``hidden`` se saltan las de la capa del juego."""
    for entry in stack:
        if not (hidden and entry.layer.kind is LayerKind.GAME):
            return entry
    return None


def matching_keys(keys: Iterable[str], folder: str, pattern: str, recursive: bool | None) -> list[str]:
    """Claves bajo ``folder`` cuyo nombre encaja con ``pattern`` (glob sin mayúsculas), ordenadas.

    ``recursive=None`` usa la regla de carga de un archivo de ejemplo de esa carpeta.
    Nunca incluye ``DESCRIPTOR_REL``.
    """
    from .paths import DESCRIPTOR_REL, folder_key
    from .rules import rule_for

    prefix = folder_key(folder)
    if recursive is None:
        sample = (prefix.lower() + "/" if prefix else "") + (pattern.replace("*", "x").replace("?", "x") or "x")
        try:
            recursive = rule_for(VPath.of(sample)).recursive
        except ValueError:
            recursive = False
    name_pattern = pattern.upper()
    descriptor = DESCRIPTOR_REL.key
    found = []
    for key in keys:
        if key == descriptor:
            continue
        head, _, name = key.rpartition("/")
        if recursive:
            if prefix and not key.startswith(prefix + "/"):
                continue
        elif head != prefix:
            continue
        if fnmatch.fnmatchcase(name, name_pattern):
            found.append(key)
    found.sort()
    return found
