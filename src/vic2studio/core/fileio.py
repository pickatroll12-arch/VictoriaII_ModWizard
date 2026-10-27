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

import errno
import hashlib
import os
import secrets
import shutil
import time
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

    def __reduce__(self):
        return (type(self), (self.path,))

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


def _create_temp(target: Path, token: str | None = None) -> tuple[int, str]:
    # Como tempfile.mkstemp pero con el modo por defecto (mkstemp crea siempre 0o600). Con ``token`` el nombre es
    # predecible (``.<nombre>.<token>.tmp``: el diario lo anota para limpiarlo tras un corte).
    while True:
        name = os.path.join(target.parent, f".{target.name}.{token or secrets.token_hex(4)}.tmp")
        try:
            return os.open(name, _TEMP_FLAGS, 0o666), name
        except FileExistsError:
            if token is not None:
                raise
            continue


def atomic_write_bytes(path: str | os.PathLike, data: bytes, *, backup: bool = False,
                       expected: FileStamp | None = None) -> Path | None:
    """Escribe ``data`` de forma atómica. Con ``backup`` copia antes el original a ``*.bak``.

    Crea las carpetas intermedias si no existen. Con ``expected`` comprueba antes
    de nada que el archivo sigue siendo el que tenía esa huella y, si no (o si ya
    no existe), lanza ``FileChangedError``. Devuelve la ruta de la copia de
    seguridad, o ``None`` si no se hizo. Va sobre ``stage_bytes`` + ``commit_staged``.
    """
    target = Path(path)
    if expected is not None and file_stamp(target) != expected:
        raise FileChangedError(target)
    make_dirs(target.parent)
    backup_path = None
    if backup and target.exists():
        backup_path = target.with_name(target.name + BACKUP_SUFFIX)
        copy_file(target, backup_path)
    temp = stage_bytes(target, data)
    try:
        commit_staged(temp, target)
    except BaseException:
        discard_staged(temp)
        raise
    return backup_path


def write_text(path: str | os.PathLike, text: str, encoding: str, *, backup: bool = False,
               expected: FileStamp | None = None) -> Path | None:
    """Codifica (lanza ``UnencodableTextError`` si no se puede) y escribe de forma atómica."""
    return atomic_write_bytes(path, encode_text(text, encoding), backup=backup, expected=expected)


# --- primitivas del guardado con diario (wizard §6.5) ------------------------------------
# Son las únicas escrituras crudas del proyecto (tests/test_arch_writes.py). Dentro del mod solo
# las llama core/project/journal.py, después de WriteGuard.check; fuera, el bloqueo y las cachés.
# atomic_write_bytes se reimplementa encima de stage_bytes + commit_staged con la misma firma.

REPLACE_RETRIES = 3          # os.replace ante PermissionError (antivirus o editor con el archivo abierto en Windows)
REPLACE_RETRY_DELAY = 0.1    # segundos entre intentos


def stage_bytes(target: str | os.PathLike, data: bytes, *, token: str | None = None) -> Path:
    """Escribe ``data`` en un temporal ``.<nombre>.<token>.tmp`` junto a ``target``, con fsync; devuelve su ruta.

    Crea las carpetas intermedias. No toca ``target``. Sin ``token`` se usa uno
    aleatorio; con él (el txid del diario) el nombre es predecible y, si ya existe,
    lanza ``FileExistsError``.
    """
    target = Path(target)
    make_dirs(target.parent)
    fd, name = _create_temp(target, token)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        remove_file(name)
        raise
    return Path(name)


def commit_staged(temp: str | os.PathLike, target: str | os.PathLike, *, retries: int = REPLACE_RETRIES,
                  delay: float = REPLACE_RETRY_DELAY) -> None:
    """``os.replace(temp, target)`` conservando los permisos de ``target`` si existía; reintenta ante PermissionError.

    Hace hasta ``retries`` reintentos, cada ``delay`` segundos; si todos fallan,
    relanza el último ``PermissionError`` y deja ``temp`` donde estaba.
    """
    temp, target = os.fspath(temp), os.fspath(target)
    if os.path.exists(target):
        try:
            shutil.copymode(target, temp)
        except OSError:
            pass  # los permisos son cosméticos: no impiden guardar
    for attempt in range(retries + 1):
        try:
            os.replace(temp, target)
            return
        except PermissionError:
            if attempt >= retries:
                raise
            time.sleep(delay)


def discard_staged(temp: str | os.PathLike) -> None:
    """Borra un temporal de ``stage_bytes`` (no falla si ya no existe)."""
    remove_file(temp)


def fsync_dir(folder: str | os.PathLike) -> None:
    """fsync de la carpeta para que los renombrados sobrevivan a un corte (no-op donde no se puede, p. ej. Windows)."""
    if os.name == "nt":
        return  # Windows no abre carpetas con os.open; NTFS registra los renombrados en su propio diario
    try:
        fd = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # algunos sistemas de archivos no admiten fsync de carpetas
    finally:
        os.close(fd)


def _fsync_file(path: str | os.PathLike) -> None:
    # Con escritura: en Windows os.fsync (FlushFileBuffers) la exige.
    fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_file(source: str | os.PathLike, target: str | os.PathLike) -> None:
    """Copia con metadatos (``copy2``) y fsync, creando las carpetas intermedias (``.bak``, ``originals/``).

    Es atómica: copia a un temporal junto a ``target`` y lo renombra, así que un
    corte deja la copia anterior o la nueva, nunca una a medias.
    """
    target = Path(target)
    make_dirs(target.parent)
    fd, name = _create_temp(target)
    os.close(fd)
    try:
        shutil.copy2(source, name)
        _fsync_file(name)
        commit_staged(name, target)
    except BaseException:
        remove_file(name)
        raise


def move_file(source: str | os.PathLike, target: str | os.PathLike) -> None:
    """Mueve (``os.replace``, o copia y borra entre unidades) creando las carpetas intermedias (papelera)."""
    target = Path(target)
    make_dirs(target.parent)
    try:
        os.replace(source, target)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        copy_file(source, target)
        os.remove(source)


def remove_file(path: str | os.PathLike) -> None:
    """Borra un archivo (no falla si ya no existe)."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def make_dirs(folder: str | os.PathLike) -> None:
    """``mkdir(parents=True, exist_ok=True)``."""
    Path(folder).mkdir(parents=True, exist_ok=True)


def _norm(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(path))


def remove_empty_dirs(folder: str | os.PathLike, *, stop_at: str | os.PathLike) -> None:
    """Borra ``folder`` y sus padres vacíos hasta ``stop_at`` (excluido); para limpiar ``journal/`` y temporales.

    No hace nada si ``folder`` no está dentro de ``stop_at``, y se detiene en la
    primera carpeta que no está vacía (o que no existe).
    """
    current = Path(os.path.abspath(folder))
    stop = _norm(stop_at)
    while _norm(current) != stop and _norm(current).startswith(stop.rstrip(os.sep) + os.sep):
        try:
            os.rmdir(current)
        except FileNotFoundError:
            pass  # ya no estaba: se sigue con el padre
        except OSError:
            return  # no está vacía (o no se puede): se para aquí
        current = current.parent


def create_exclusive(path: str | os.PathLike, data: bytes) -> bool:
    """Crea ``path`` con ``data`` solo si no existe (``O_EXCL``), con fsync; False si ya existía.

    Es la primitiva del bloqueo entre instancias: dos procesos que la llaman a la
    vez no pueden ganar los dos. Crea las carpetas intermedias.
    """
    path = Path(path)
    make_dirs(path.parent)
    try:
        fd = os.open(path, _TEMP_FLAGS, 0o666)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        remove_file(path)
        raise
    return True
