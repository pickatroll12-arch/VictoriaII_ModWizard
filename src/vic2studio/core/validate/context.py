"""``ValidationContext``: lo que ven las reglas, inmutable y apto para un hilo de fondo (wizard §11, I12).

Une la instantánea de la VFS, los documentos sin guardar (``overrides``: bytes del
``snapshot`` de su códec), el índice, la localización efectiva y las reglas del
juego. Las reglas leen archivos solo a través de ``read``/``parse``, que dan
primero el documento sin guardar y guardan en caché lo ya analizado.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..cancel import CancelCheck
from ..clausewitz.nodes import ClausewitzDate
from ..vfs.model import FileEntry, LayerKind, VfsSnapshot
from ..vfs.paths import VPath


@dataclass
class ValidationContext:
    snapshot: VfsSnapshot
    index: object                         # SymbolIndex
    loc: object                           # csvloc.LocalisationDB efectiva (mod + juego + sin guardar)
    rules: object                         # rules.GameRules
    overrides: Mapping[VPath, bytes] = field(default_factory=dict)
    date: ClausewitzDate | None = None    # fecha de trabajo (historia fechada)
    mapdata: object | None = None         # iteración 5
    game_only: bool = False               # contexto de la línea base: solo la capa del juego
    cancelled: CancelCheck = None

    def entry(self, rel: VPath) -> FileEntry | None:
        """Ganador de ``rel`` en la instantánea (None si solo existe como documento sin guardar o no existe)."""
        raise NotImplementedError

    def layer_of(self, rel: VPath) -> LayerKind | None:
        """Capa del ganador; ``LayerKind.MOD`` para un documento sin guardar."""
        raise NotImplementedError

    def read(self, rel: VPath) -> bytes | None:
        """Bytes efectivos de ``rel`` (el documento sin guardar si lo hay); None si no existe o no se puede leer."""
        raise NotImplementedError

    def parse(self, rel: VPath):
        """``clausewitz.ParseResult`` de ``read(rel)`` (en caché por contexto); None si no existe."""
        raise NotImplementedError

    def rels(self, folder: str, pattern: str = "*.txt") -> list[VPath]:
        """Rutas efectivas bajo ``folder`` (con los documentos nuevos sin guardar), ordenadas."""
        raise NotImplementedError


def build_context(snapshot: VfsSnapshot, index, overrides: Mapping[VPath, bytes] | None = None, *,
                  date: ClausewitzDate | None = None, loc=None, game_only: bool = False,
                  cancelled: CancelCheck = None) -> ValidationContext:
    """Contexto completo: si no se da ``loc``, construye la ``LocalisationDB`` efectiva de ``localisation/*.csv``
    (``LocalisationDB.from_entries``); calcula ``GameRules.from_snapshot``."""
    raise NotImplementedError


def game_only_snapshot(snapshot: VfsSnapshot) -> VfsSnapshot:
    """La misma instantánea con solo la capa del juego (contexto de la línea base, I11)."""
    raise NotImplementedError
