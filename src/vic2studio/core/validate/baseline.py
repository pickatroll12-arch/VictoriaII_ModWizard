"""Línea base: los problemas del juego base solo, para no culpar al mod (wizard §11, I11).

``compute_baseline`` valida el contexto con solo la capa del juego y devuelve las
huellas (``Problem.fingerprint``) de sus problemas. Se guarda en caché por
instalación (``<cache_dir>/baseline/game-<sha1(realpath)>.v<N>.json``, a través de
``core.fileio``, nunca en el mod) con la firma de los archivos del juego y la
versión de las reglas: si cambia cualquiera de las dos, se recalcula.
"""

from __future__ import annotations

from pathlib import Path

from ..cancel import CancelCheck
from ..vfs.model import VfsSnapshot
from .context import ValidationContext

BASELINE_FORMAT = 1


def compute_baseline(game_only: ValidationContext, *, cancelled: CancelCheck = None) -> frozenset[tuple]:
    raise NotImplementedError


class BaselineCache:
    def __init__(self, root: Path | None = None) -> None:
        """``root`` = carpeta de la caché (por defecto ``appdirs.cache_dir() / "baseline"``)."""
        raise NotImplementedError

    def load(self, snapshot: VfsSnapshot) -> frozenset[tuple] | None:
        """Línea base guardada para el juego de ``snapshot`` si sigue valiendo; None si hay que calcularla."""
        raise NotImplementedError

    def store(self, snapshot: VfsSnapshot, baseline: frozenset[tuple]) -> None:
        raise NotImplementedError
