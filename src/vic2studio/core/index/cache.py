"""Caché de hechos del índice: JSON-lines comprimido por capa, nunca pickle (wizard §7).

``<cache_dir>/index/game-<sha1(realpath)>/facts.v<INDEX_FORMAT>.jsonl.gz`` para el
juego base (compartida entre mods) y ``…/mod-<sha1>/`` para cada mod o
dependencia. Cada línea son los ``FileFacts`` de un archivo con su huella y la
versión de su extractor; al leer se descartan los de un extractor de otra versión.
Escribe solo fuera del mod, a través de ``core.fileio`` y con rutas de
``core.appdirs`` (I1, I4; lo vigila ``test_arch_writes``). Una caché ilegible o de
otro formato se ignora (se reconstruye), nunca hace fallar la apertura.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..vfs.model import Layer
from ..vfs.paths import VPath
from .model import FileFacts


class FactsCache:
    def __init__(self, root: Path | None = None) -> None:
        """``root`` = carpeta de la caché (por defecto ``appdirs.cache_dir() / "index"``)."""
        raise NotImplementedError

    def folder(self, layer: Layer) -> Path:
        """Carpeta de la caché de una capa (``game-``/``mod-`` + sha1 de su ruta real)."""
        raise NotImplementedError

    def load(self, layer: Layer) -> dict[tuple[str, str], FileFacts]:
        """Hechos guardados de la capa por ``(rel.key, extractor)``; vacío si no hay o no se puede leer."""
        raise NotImplementedError

    def store(self, layer: Layer, facts: Iterable[FileFacts]) -> None:
        """Sustituye la caché de la capa por ``facts`` (escritura atómica)."""
        raise NotImplementedError

    def drop(self, layer: Layer, rels: Iterable[VPath] = ()) -> None:
        """Olvida la capa entera o solo esas rutas."""
        raise NotImplementedError
