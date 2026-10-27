"""Pila de deshacer por instantáneas (wizard §6.3, D3, I5).

Deshacer sustituye el modelo por ``codec.load(before)``: exacto gracias a la ida
y vuelta byte a byte, sin programar la inversa de cada mutación. Hay una sola
pila global: «Crear país» toca unos 10 archivos y se deshace de una vez. El
historial no se guarda en disco (se documenta así).

Las instantáneas van comprimidas en memoria. Las de más de ``SNAPSHOT_TO_DISK``
también (en esta iteración no se pasan a disco: escribir en el mod al editar
rompería I4 y el texto comprime unas 10 veces).
"""

from __future__ import annotations

import time
import zlib

from .model import Snapshot, UndoStep

MERGE_SECONDS = 1.0           # teclear en el mismo campo en menos de esto se funde en un paso
SNAPSHOT_TO_DISK = 8 * 2**20  # instantáneas mayores van a disco (Snapshot.before_path)


def compress(data: bytes | None) -> bytes | None:
    """zlib nivel 1 (rápido); None se conserva."""
    return None if data is None else zlib.compress(data, 1)


def decompress(data: bytes | None) -> bytes | None:
    return None if data is None else zlib.decompress(data)


def step_size(step: UndoStep) -> int:
    """Bytes comprimidos que ocupa un paso. ``before`` y ``after`` que son el mismo objeto (una lápida guarda sus
    bytes una vez) cuentan una vez: contados dos, el paso de la papelera en el mod del usuario (161 MB) pasaba de
    ``max_bytes`` y la edición siguiente lo echaba de la pila."""
    return sum(len(s.before or b"") + (0 if s.after is s.before else len(s.after or b"")) for s in step.snapshots)


class UndoStack:
    def __init__(self, *, limit: int = 500, max_bytes: int = 256 * 2**20) -> None:
        self.limit = limit
        self.max_bytes = max_bytes
        self._undo: list[UndoStep] = []
        self._redo: list[UndoStep] = []
        self._sizes: dict[int, int] = {}
        self._bytes = 0
        self._last_push: float | None = None
        self._mergeable: UndoStep | None = None   # el último apilado, si nada lo ha deshecho desde entonces

    def push(self, step: UndoStep, *, now: float | None = None) -> None:
        """Apila (o funde con el anterior si comparte ``merge_key`` dentro de MERGE_SECONDS) y vacía rehacer.

        Si se pasa de ``limit`` pasos o de ``max_bytes`` comprimidos, descarta los más viejos.
        """
        now = time.monotonic() if now is None else now
        self._clear_redo()
        top = self._undo[-1] if self._undo else None
        if (step.merge_key is not None and top is not None and top is self._mergeable
                and top.merge_key == step.merge_key and self._last_push is not None
                and now - self._last_push < MERGE_SECONDS):
            self._forget(top)
            _merge(top, step)
            self._remember(top)
        else:
            self._undo.append(step)
            self._remember(step)
            top = step
        self._mergeable = top
        self._last_push = now
        while len(self._undo) > 1 and (len(self._undo) > self.limit or self._bytes > self.max_bytes):
            self._forget(self._undo.pop(0))

    def undo(self) -> UndoStep | None:
        if not self._undo:
            return None
        step = self._undo.pop()
        self._redo.append(step)
        self._mergeable = None
        return step

    def redo(self) -> UndoStep | None:
        if not self._redo:
            return None
        step = self._redo.pop()
        self._undo.append(step)
        self._mergeable = None
        return step

    def seal(self) -> None:
        """El próximo paso no se funde con el anterior (tras guardar o recargar: el punto guardado sigue alcanzable)."""
        self._mergeable = None

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def labels(self) -> list[tuple[str, dict]]:
        """(clave, formato) de los pasos que se pueden deshacer, el más reciente primero (panel «Historial»)."""
        return [(step.label, dict(step.fmt)) for step in reversed(self._undo)]

    def redo_labels(self) -> list[tuple[str, dict]]:
        """(clave, formato) de los pasos que se pueden rehacer, el próximo primero."""
        return [(step.label, dict(step.fmt)) for step in reversed(self._redo)]

    def referenced(self) -> set[str]:
        """``rel.key`` de los documentos que alguna instantánea nombra (no se expulsan de la LRU)."""
        return {s.rel.key for step in (*self._undo, *self._redo) for s in step.snapshots}

    @property
    def total_bytes(self) -> int:
        return self._bytes

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._sizes.clear()
        self._bytes = 0
        self._mergeable = None
        self._last_push = None

    def _clear_redo(self) -> None:
        for step in self._redo:
            self._forget(step)
        self._redo.clear()

    def _remember(self, step: UndoStep) -> None:
        size = step_size(step)
        self._sizes[id(step)] = size
        self._bytes += size

    def _forget(self, step: UndoStep) -> None:
        self._bytes -= self._sizes.pop(id(step), 0)


def _merge(into: UndoStep, step: UndoStep) -> None:
    """Funde ``step`` (posterior) en ``into``: conserva los ``before`` de ``into`` y toma los ``after`` de ``step``."""
    by_key = {s.rel.key: s for s in into.snapshots}
    for snapshot in step.snapshots:
        existing = by_key.get(snapshot.rel.key)
        if existing is None:
            into.snapshots.append(snapshot)
            by_key[snapshot.rel.key] = snapshot
        else:
            existing.after = snapshot.after
            existing.after_deleted = snapshot.after_deleted
            existing.after_version = snapshot.after_version
            existing.rel = snapshot.rel
    into.patches.extend(step.patches)
    into.label = step.label
    into.fmt = step.fmt


__all__ = ["MERGE_SECONDS", "SNAPSHOT_TO_DISK", "Snapshot", "UndoStack", "UndoStep", "compress", "decompress"]
