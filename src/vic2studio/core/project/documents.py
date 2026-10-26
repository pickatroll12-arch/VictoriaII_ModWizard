"""Almacén de documentos abiertos con expulsión LRU (wizard §6.2).

Una instancia por ``rel.key``. Los documentos limpios que no nombra la pila de
deshacer se pueden expulsar cuando se pasa de ``lru_bytes`` (tamaño de su
``snapshot``); los sucios y los referenciados quedan fijados.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..vfs.paths import VPath
from .model import DocHandle


class DocumentStore:
    def __init__(self, *, lru_bytes: int = 300 * 2**20) -> None:
        raise NotImplementedError

    def get(self, rel: str | VPath) -> DocHandle | None:
        """Sin cargar nada; marca el documento como usado."""
        raise NotImplementedError

    def add(self, handle: DocHandle, size: int) -> None:
        raise NotImplementedError

    def discard(self, rel: str | VPath) -> None:
        raise NotImplementedError

    def evict(self, pinned: set[str]) -> list[VPath]:
        """Expulsa limpios no fijados (``pinned``: ``rel.key``) hasta quedar bajo el límite; devuelve los expulsados."""
        raise NotImplementedError

    def __iter__(self) -> Iterator[DocHandle]:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError
