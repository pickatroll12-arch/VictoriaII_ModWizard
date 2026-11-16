"""Archivos binarios nuevos o sustituidos dentro de una transacción (imágenes del taller y de la suite de
interfaces, banderas).

Los binarios no tienen códec de escritura (no se editan por partes), pero sí se pueden poner enteros: el
``Workspace`` los guarda tal cual con el diario y la operación se deshace como cualquier otra. Es el mismo
camino que usa la restauración de un autoguardado (``Workspace.restore_bytes``).
"""

from __future__ import annotations

from ..vfs.paths import VPath
from .model import DocHandle


def put_bytes(ws, rel: str | VPath, data: bytes) -> DocHandle:
    """Deja ``data`` como contenido de ``rel`` (lo crea si no existe). Dentro de una transacción.

    Si ``rel`` existe en el juego, al guardar se escribe la copia del mod en la misma ruta. Poner los mismos
    bytes que ya tiene no ensucia el documento.
    """
    handle = ws.open(VPath.of(rel), create=True)
    if not handle.deleted and isinstance(handle.model, (bytes, bytearray)) and bytes(handle.model) == bytes(data) \
            and not handle.is_new:
        return handle
    ws.restore_bytes(handle, bytes(data))
    return handle
