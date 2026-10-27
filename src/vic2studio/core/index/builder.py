"""Construcción del índice: extraer hechos de cada archivo, con caché por huella (wizard §7).

``build_index`` recorre la instantánea de la VFS (sin el CST vivo, I12): para cada
archivo de cada capa con algún extractor, reutiliza los hechos de la caché si la
huella (tamaño y mtime) y la versión del extractor coinciden, y si no lo lee y lo
extrae. ``overrides`` son los documentos sin guardar (``rel → bytes`` del
``snapshot`` de su códec): sustituyen al archivo del mod (o lo crean) sin tocar la
caché. Lanza ``core.cancel.Cancelled``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..cancel import CancelCheck
from ..vfs.model import FileEntry, LayerKind, VfsSnapshot
from ..vfs.paths import VPath
from .cache import FactsCache
from .index import SymbolIndex
from .model import FileFacts

# Contador de extracciones de la última construcción (criterio 2: «cambiar un archivo reprocesa solo ese»).
ParseCounter = Callable[[VPath, str], None]


def extract_bytes(rel: VPath, data: bytes, layer: LayerKind, *, fingerprint=None) -> list[FileFacts]:
    """Hechos de unos bytes con todos los extractores que procesan ``rel`` (uno por extractor; vacío si ninguno).

    Nunca lanza por el contenido: un archivo roto da los hechos que se puedan sacar.
    """
    raise NotImplementedError


def extract_entry(entry: FileEntry) -> list[FileFacts]:
    """``extract_bytes`` del archivo en disco de ``entry`` (``OSError`` si no se puede leer)."""
    raise NotImplementedError


def build_index(snapshot: VfsSnapshot, cache: FactsCache | None, overrides: Mapping[VPath, bytes] | None = None, *,
                progress: Callable[[int, int], None] | None = None, cancelled: CancelCheck = None,
                on_extract: ParseCounter | None = None) -> SymbolIndex:
    """Índice de la vista efectiva. ``cache=None`` no usa caché. ``progress(hechos, total)`` por archivo;
    ``on_extract(rel, extractor)`` cada vez que se extrae de verdad (no desde la caché). Guarda en la caché lo
    nuevo antes de volver."""
    raise NotImplementedError
