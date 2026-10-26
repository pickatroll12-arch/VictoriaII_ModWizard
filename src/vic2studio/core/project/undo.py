"""Pila de deshacer por instantáneas (wizard §6.3, D3, I5).

Deshacer sustituye el modelo por ``codec.load(before)``: exacto gracias a la ida
y vuelta byte a byte, sin programar la inversa de cada mutación. Hay una sola
pila global: «Crear país» toca unos 10 archivos y se deshace de una vez. El
historial no se guarda en disco (se documenta así).
"""

from __future__ import annotations

from .model import Snapshot, UndoStep

MERGE_SECONDS = 1.0           # teclear en el mismo campo en menos de esto se funde en un paso
SNAPSHOT_TO_DISK = 8 * 2**20  # instantáneas mayores van a disco (Snapshot.before_path)


def compress(data: bytes | None) -> bytes | None:
    """zlib nivel 1 (rápido); None se conserva."""
    raise NotImplementedError


def decompress(data: bytes | None) -> bytes | None:
    raise NotImplementedError


class UndoStack:
    def __init__(self, *, limit: int = 500, max_bytes: int = 256 * 2**20) -> None:
        raise NotImplementedError

    def push(self, step: UndoStep, *, now: float | None = None) -> None:
        """Apila (o funde con el anterior si comparte ``merge_key`` dentro de MERGE_SECONDS) y vacía rehacer.

        Si se pasa de ``limit`` pasos o de ``max_bytes`` comprimidos, descarta los más viejos.
        """
        raise NotImplementedError

    def undo(self) -> UndoStep | None:
        raise NotImplementedError

    def redo(self) -> UndoStep | None:
        raise NotImplementedError

    def can_undo(self) -> bool:
        raise NotImplementedError

    def can_redo(self) -> bool:
        raise NotImplementedError

    def labels(self) -> list[tuple[str, dict]]:
        """(clave, formato) de los pasos que se pueden deshacer, el más reciente primero (panel «Historial»)."""
        raise NotImplementedError

    def referenced(self) -> set[str]:
        """``rel.key`` de los documentos que alguna instantánea nombra (no se expulsan de la LRU)."""
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


__all__ = ["MERGE_SECONDS", "SNAPSHOT_TO_DISK", "Snapshot", "UndoStack", "UndoStep", "compress", "decompress"]
