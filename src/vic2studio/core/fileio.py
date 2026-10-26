"""Lectura y escritura segura de archivos del mod.

Toda escritura es atómica (archivo temporal en la misma carpeta + ``os.replace``)
para que un fallo a mitad de guardado nunca deje un archivo del mod a medias.
Los archivos nuevos reciben los permisos por defecto (``0o666`` menos la umask),
como los que crea cualquier programa; los existentes conservan los suyos.

Para no pisar cambios hechos fuera de la aplicación (en Excel, Notepad++...)
``read_text`` devuelve la huella (``FileStamp``) de lo leído y
``atomic_write_bytes(..., expected=huella)`` lanza ``FileChangedError`` antes de
tocar nada si el archivo ya no es el que se leyó.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from .encoding import DecodedText, decode_bytes, encode_text

BACKUP_SUFFIX = ".bak"
FILE_CHANGED = "file_changed"
MESSAGES = {
    "es": {
        FILE_CHANGED: (
            "{path} ha cambiado fuera de la aplicación desde que se abrió. Guardar ahora "
            "sustituiría esos cambios: vuelve a abrirlo o confirma que quieres sobrescribirlo."
        ),
    },
    "en": {
        FILE_CHANGED: (
            "{path} has changed outside the application since it was opened. Saving now would "
            "replace those changes: reopen it, or confirm that you want to overwrite it."
        ),
    },
}
_TEMP_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)


@dataclass(frozen=True)
class FileStamp:
    """Huella del contenido de un archivo: tamaño y resumen BLAKE2 de sus bytes."""

    size: int
    digest: bytes

    @classmethod
    def of(cls, data: bytes) -> FileStamp:
        return cls(len(data), hashlib.blake2b(data, digest_size=16).digest())


class FileChangedError(OSError):
    """El archivo de destino ya no es el que se leyó: se ha cambiado (o borrado) fuera de la aplicación."""

    code = FILE_CHANGED

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        super().__init__(self.message("es"))

    def message(self, lang: str = "en") -> str:
        return MESSAGES.get(lang, MESSAGES["en"])[FILE_CHANGED].format(path=self.path)


def file_stamp(path: str | os.PathLike) -> FileStamp | None:
    """Huella del archivo tal como está ahora en disco; ``None`` si no existe."""
    try:
        return FileStamp.of(Path(path).read_bytes())
    except FileNotFoundError:
        return None


def read_text(path: str | os.PathLike, encoding: str | None = None) -> DecodedText:
    """Lee un archivo y detecta su codificación (ver ``encoding.decode_bytes``); incluye su huella."""
    data = Path(path).read_bytes()
    return replace(decode_bytes(data, encoding), stamp=FileStamp.of(data))


def _create_temp(target: Path) -> tuple[int, str]:
    # Como tempfile.mkstemp pero con el modo por defecto (mkstemp crea siempre 0o600).
    while True:
        name = os.path.join(target.parent, f".{target.name}.{secrets.token_hex(4)}.tmp")
        try:
            return os.open(name, _TEMP_FLAGS, 0o666), name
        except FileExistsError:
            continue


def atomic_write_bytes(path: str | os.PathLike, data: bytes, *, backup: bool = False,
                       expected: FileStamp | None = None) -> Path | None:
    """Escribe ``data`` de forma atómica. Con ``backup`` copia antes el original a ``*.bak``.

    Crea las carpetas intermedias si no existen. Con ``expected`` comprueba antes
    de nada que el archivo sigue siendo el que tenía esa huella y, si no (o si ya
    no existe), lanza ``FileChangedError``. Devuelve la ruta de la copia de
    seguridad, o ``None`` si no se hizo.
    """
    target = Path(path)
    if expected is not None and file_stamp(target) != expected:
        raise FileChangedError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if backup and target.exists():
        backup_path = target.with_name(target.name + BACKUP_SUFFIX)
        shutil.copy2(target, backup_path)
    fd, tmp_name = _create_temp(target)
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


def write_text(path: str | os.PathLike, text: str, encoding: str, *, backup: bool = False,
               expected: FileStamp | None = None) -> Path | None:
    """Codifica (lanza ``UnencodableTextError`` si no se puede) y escribe de forma atómica."""
    return atomic_write_bytes(path, encode_text(text, encoding), backup=backup, expected=expected)
