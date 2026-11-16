"""De dónde lee la suite de interfaces los archivos efectivos (I7).

Tres orígenes con la misma forma (``GuiSource``):

- ``WorkspaceSource``: el ``Workspace`` vivo, en el hilo de la interfaz. Un documento abierto (sin guardar,
  nuevo o borrado) manda sobre el disco.
- ``ContextSource``: un ``ValidationContext``, para las reglas de F7 en segundo plano.
- ``SnapshotSource``: una instantánea de la VFS más bytes sin guardar; apto para tareas (I12).

Ninguno escribe (I4).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ..clausewitz.nodes import Document
from ..vfs.model import VfsSnapshot, matching_keys
from ..vfs.paths import VPath


class GuiSource(Protocol):
    def rels(self, folder: str, pattern: str) -> list[VPath]:
        """Rutas efectivas de ``folder`` que casan con ``pattern``, ordenadas."""
        ...

    def document(self, rel: VPath) -> Document | None:
        """El documento Clausewitz efectivo de ``rel``; None si no existe o no se puede leer."""
        ...

    def find(self, rel: VPath) -> VPath | None:
        """La ruta real (con sus mayúsculas) del archivo efectivo ``rel``; None si no existe."""
        ...

    def read(self, rel: VPath) -> bytes | None:
        """Bytes efectivos de ``rel``; None si no existe."""
        ...


class SnapshotSource:
    """Instantánea de la VFS más ``overrides`` (bytes sin guardar; None = borrado)."""

    def __init__(self, snapshot: VfsSnapshot, overrides: Mapping[VPath, bytes | None] | None = None) -> None:
        self.snapshot = snapshot
        self._overrides = {VPath.of(rel).key: (VPath.of(rel), data) for rel, data in dict(overrides or {}).items()}

    def rels(self, folder: str, pattern: str) -> list[VPath]:
        found = {entry.rel.key: entry.rel for entry in self.snapshot.list(folder, pattern)}
        for key in matching_keys(self._overrides.keys(), folder, pattern, None):
            rel, data = self._overrides[key]
            if data is None:
                found.pop(key, None)
            else:
                found[key] = rel
        return [found[key] for key in sorted(found)]

    def read(self, rel: VPath) -> bytes | None:
        key = VPath.of(rel).key
        if key in self._overrides:
            return self._overrides[key][1]
        entry = self.snapshot.resolve(rel)
        if entry is None:
            return None
        try:
            return entry.path.read_bytes()
        except OSError:
            return None

    def find(self, rel: VPath) -> VPath | None:
        key = VPath.of(rel).key
        if key in self._overrides:
            found, data = self._overrides[key]
            return None if data is None else found
        entry = self.snapshot.resolve(rel)
        return None if entry is None else entry.rel

    def document(self, rel: VPath) -> Document | None:
        data = self.read(rel)
        if data is None:
            return None
        from ..project.codecs import parse_bytes

        return parse_bytes(data).document


class ContextSource:
    """Un ``ValidationContext``: sus lecturas y su caché de documentos analizados."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx

    def rels(self, folder: str, pattern: str) -> list[VPath]:
        return self.ctx.rels(folder, pattern)

    def read(self, rel: VPath) -> bytes | None:
        return self.ctx.read(VPath.of(rel))

    def find(self, rel: VPath) -> VPath | None:
        rel = VPath.of(rel)
        if self.ctx.unsaved(rel):
            return rel if self.ctx.read(rel) is not None else None
        entry = self.ctx.entry(rel)
        return None if entry is None else entry.rel

    def document(self, rel: VPath) -> Document | None:
        result = self.ctx.parse(VPath.of(rel))
        return None if result is None else result.document


class WorkspaceSource:
    """El ``Workspace`` vivo: lo abierto manda sobre el disco. Solo en el hilo del ``Workspace`` (I12).

    ``document`` abre el archivo en el ``Workspace`` (sin ``create``: abrir no escribe), así que el árbol que
    devuelve es el que se edita dentro de una transacción.
    """

    def __init__(self, ws) -> None:
        self.ws = ws

    def _open_docs(self, folder: str, pattern: str) -> dict[str, object]:
        handles = {handle.rel.key: handle for handle in self.ws.documents()}
        return {key: handles[key] for key in matching_keys(handles.keys(), folder, pattern, None)}

    def rels(self, folder: str, pattern: str) -> list[VPath]:
        found = {entry.rel.key: entry.rel for entry in self.ws.vfs.list(folder, pattern)}
        for key, handle in self._open_docs(folder, pattern).items():
            if handle.deleted:
                # Una lápida de la copia del mod deja ver el archivo de debajo, si lo hay.
                below = [e for e in self.ws.vfs.stack(handle.rel) if e.layer.kind.name != "MOD"]
                if below:
                    found[key] = below[0].rel
                else:
                    found.pop(key, None)
            else:
                found[key] = handle.rel
        return [found[key] for key in sorted(found)]

    def find(self, rel: VPath) -> VPath | None:
        rel = VPath.of(rel)
        handle = self.ws.peek(rel)
        if handle is not None:
            if not handle.deleted:
                return handle.rel
            below = [e for e in self.ws.vfs.stack(rel) if e.layer.kind.name != "MOD"]
            return below[0].rel if below else None
        entry = self.ws.vfs.resolve(rel)
        return None if entry is None else entry.rel

    def read(self, rel: VPath) -> bytes | None:
        rel = VPath.of(rel)
        handle = self.ws.peek(rel)
        if handle is not None and not handle.deleted and isinstance(handle.model, (bytes, bytearray)):
            # Una imagen o un binario abierto (``DocKind.IMAGE``/``BINARY``): sus bytes sin guardar mandan.
            return bytes(handle.model)
        if self.find(rel) is None:
            return None
        try:
            return self.ws.vfs.read_bytes(rel)
        except OSError:
            return None

    def document(self, rel: VPath) -> Document | None:
        rel = VPath.of(rel)
        if self.find(rel) is None:
            return None
        peeked = self.ws.peek(rel)
        if peeked is not None and peeked.deleted:
            # Lápida con el archivo del juego debajo: se lee este, de solo lectura (editarlo es cosa de quien
            # reviva el documento dentro de una transacción).
            below = [e for e in self.ws.vfs.stack(rel) if e.layer.kind.name != "MOD"]
            try:
                data = self.ws.vfs.read_bytes(below[0])
            except (OSError, IndexError):
                return None
            from ..project.codecs import parse_bytes

            return parse_bytes(data).document
        try:
            handle = self.ws.open(rel)
        except (OSError, ValueError):
            return None
        return getattr(handle.model, "document", None)
