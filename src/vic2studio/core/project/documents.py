"""Almacén de documentos abiertos con expulsión LRU (wizard §6.2).

Una instancia por ``rel.key``. Los documentos limpios que no nombra la pila de
deshacer se pueden expulsar cuando se pasa de ``lru_bytes`` (tamaño de su
``snapshot``); los sucios y los referenciados quedan fijados.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator

from ..vfs.paths import VPath
from .model import DocHandle


class DocumentStore:
    def __init__(self, *, lru_bytes: int = 300 * 2**20) -> None:
        self.lru_bytes = lru_bytes
        self._docs: OrderedDict[str, tuple[DocHandle, int]] = OrderedDict()
        self._bytes = 0

    def get(self, rel: str | VPath) -> DocHandle | None:
        """Sin cargar nada; marca el documento como usado."""
        key = VPath.of(rel).key
        item = self._docs.get(key)
        if item is None:
            return None
        self._docs.move_to_end(key)
        return item[0]

    def add(self, handle: DocHandle, size: int) -> None:
        key = handle.rel.key
        previous = self._docs.pop(key, None)
        if previous is not None:
            self._bytes -= previous[1]
        self._docs[key] = (handle, size)
        self._bytes += size

    def resize(self, rel: str | VPath, size: int) -> None:
        key = VPath.of(rel).key
        item = self._docs.get(key)
        if item is not None:
            self._bytes += size - item[1]
            self._docs[key] = (item[0], size)

    def discard(self, rel: str | VPath) -> None:
        item = self._docs.pop(VPath.of(rel).key, None)
        if item is not None:
            self._bytes -= item[1]

    @property
    def total_bytes(self) -> int:
        return self._bytes

    def evict(self, pinned: set[str]) -> list[VPath]:
        """Expulsa limpios no fijados (``pinned``: ``rel.key``) hasta quedar bajo el límite; devuelve los expulsados."""
        evicted: list[VPath] = []
        if self._bytes <= self.lru_bytes:
            return evicted
        for key in list(self._docs):
            if self._bytes <= self.lru_bytes:
                break
            handle, size = self._docs[key]
            if key in pinned or handle.dirty or handle.deleted:
                continue
            del self._docs[key]
            self._bytes -= size
            evicted.append(handle.rel)
        return evicted

    def clear(self) -> None:
        self._docs.clear()
        self._bytes = 0

    def __iter__(self) -> Iterator[DocHandle]:
        return iter([handle for handle, _ in self._docs.values()])

    def __len__(self) -> int:
        return len(self._docs)
