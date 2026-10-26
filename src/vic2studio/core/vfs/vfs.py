"""``VirtualFS``: el juego base, las dependencias y el mod vistos como el juego los carga (wizard §5.1–5.3).

Orden de prioridad: mod > dependencias (la última declarada primero) > juego.
``replace_paths`` oculta los archivos **del juego** bajo esas carpetas (siguen en
``stack`` para comparar, nunca en ``resolve``); los del propio mod se siguen
cargando (§5.3). ``replace_recursive`` decide si alcanza a las subcarpetas
[verificar en juego]: la opción es explícita y las pruebas cubren los dos valores.

``scan`` solo hace ``os.scandir``: no lee contenidos (I4). ``snapshot`` da una
copia inmutable para los hilos de fondo (I12).

``paths.DESCRIPTOR_REL`` nombra el descriptor (``.mod``, fuera de la carpeta del
mod): ``resolve``, ``stack``, ``read_bytes`` y ``mod_target`` lo tratan como un
archivo de la capa MOD cuya ruta real es ``descriptor_path``; no sale en ``list``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from ..cancel import CancelCheck
from ..modfile import ModDescriptor
from .guard import WriteGuard
from .model import FileEntry, Layer, VfsSnapshot
from .paths import VPath

# Carpetas de primer nivel que no son del juego y nunca se recorren (I4: abrir no escribe; tampoco las lista).
IGNORED_TOP_FOLDERS = frozenset({".vic2studio", ".git"})
IGNORED_SUFFIXES = frozenset({".bak", ".tmp"})


class VirtualFS:
    def __init__(self, game_root: Path | None, mod_root: Path, *, descriptor: Path | None = None,
                 replace_paths: Sequence[str] = (), replace_recursive: bool = True,
                 dependencies: Sequence[Path] = ()) -> None:
        """``descriptor`` es el ``.mod`` (lo admite ``guard``); ``game_root=None``: solo el mod (pruebas, mods sueltos)."""
        raise NotImplementedError

    @classmethod
    def from_descriptor(cls, game_root: Path, descriptor: ModDescriptor, *,
                        replace_recursive: bool = True) -> VirtualFS:
        """Mod en ``<juego>/<descriptor.path>``, con sus ``replace_path`` y ``dependencies`` resueltas por nombre."""
        raise NotImplementedError

    @property
    def guard(self) -> WriteGuard:
        raise NotImplementedError

    @property
    def layers(self) -> tuple[Layer, ...]:
        """De más prioritaria a menos: mod, dependencias, juego."""
        raise NotImplementedError

    @property
    def game_root(self) -> Path | None:
        raise NotImplementedError

    @property
    def mod_root(self) -> Path:
        raise NotImplementedError

    @property
    def descriptor_path(self) -> Path | None:
        raise NotImplementedError

    def scan(self, *, progress=None, cancelled: CancelCheck = None) -> None:
        """Recorre las capas con ``os.scandir`` (sin leer contenidos); lanza ``core.cancel.Cancelled``.

        ``progress(done, total)`` es opcional. Omite ``IGNORED_TOP_FOLDERS`` y los
        ``IGNORED_SUFFIXES``.
        """
        raise NotImplementedError

    def resolve(self, rel: str | VPath) -> FileEntry | None:
        """Archivo que cargaría el juego (el ganador efectivo), o None."""
        raise NotImplementedError

    def stack(self, rel: str | VPath) -> list[FileEntry]:
        """Todas las capas que tienen ``rel``, ganador primero (incluidos los ocultos por replace_path)."""
        raise NotImplementedError

    def list(self, folder: str, pattern: str = "*.txt", *, recursive: bool | None = None) -> list[FileEntry]:
        """Ganadores bajo ``folder`` ordenados por ``rel.key``; ``recursive=None`` usa la regla de carga."""
        raise NotImplementedError

    def hidden_by_replace_path(self, entry: FileEntry) -> bool:
        raise NotImplementedError

    def mod_target(self, rel: str | VPath) -> Path:
        """Destino en el mod: la misma ruta, reutilizando la mayúscula de las carpetas que el mod ya tenga."""
        raise NotImplementedError

    def read_bytes(self, rel_or_entry: str | VPath | FileEntry) -> bytes:
        """Bytes del ganador (o de la entrada dada); ``FileNotFoundError`` si no hay."""
        raise NotImplementedError

    def same_as_game(self, rel: str | VPath) -> bool:
        """True si el archivo del mod es idéntico byte a byte al del juego (mods copia completa, H15)."""
        raise NotImplementedError

    def snapshot(self) -> VfsSnapshot:
        raise NotImplementedError

    def refresh(self, rels: Iterable[VPath] | None = None) -> set[VPath]:
        """Vuelve a mirar ``rels`` (o todo) y devuelve las rutas cuya huella o ganador cambió."""
        raise NotImplementedError

    def case_collisions(self) -> list[tuple[FileEntry, FileEntry]]:
        """Pares de archivos de una misma capa que solo difieren en mayúsculas (Windows los confundiría)."""
        raise NotImplementedError
