"""Lectura y escritura segura de archivos del mod.

Toda escritura es atómica (archivo temporal en la misma carpeta + ``os.replace``)
para que un fallo a mitad de guardado nunca deje un archivo del mod a medias.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .encoding import DecodedText, decode_bytes, encode_text

BACKUP_SUFFIX = ".bak"


def read_text(path: str | os.PathLike, encoding: str | None = None) -> DecodedText:
    """Lee un archivo y detecta su codificación (ver ``encoding.decode_bytes``)."""
    return decode_bytes(Path(path).read_bytes(), encoding)


def atomic_write_bytes(path: str | os.PathLike, data: bytes, *, backup: bool = False) -> Path | None:
    """Escribe ``data`` de forma atómica. Con ``backup`` copia antes el original a ``*.bak``.

    Crea las carpetas intermedias si no existen. Devuelve la ruta de la copia de
    seguridad, o ``None`` si no se hizo.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if backup and target.exists():
        backup_path = target.with_name(target.name + BACKUP_SUFFIX)
        shutil.copy2(target, backup_path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            shutil.copymode(target, tmp_name)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return backup_path


def write_text(path: str | os.PathLike, text: str, encoding: str, *, backup: bool = False) -> Path | None:
    """Codifica (lanza ``UnencodableTextError`` si no se puede) y escribe de forma atómica."""
    return atomic_write_bytes(path, encode_text(text, encoding), backup=backup)
