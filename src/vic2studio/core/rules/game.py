"""``GameRules``: los datos del juego que condicionan la validación y los asistentes (wizard §9).

Se leen de la vista efectiva (mod sobre juego, con los cambios sin guardar como
``overrides``) y son inmutables: aptos para hilos de fondo (I12). Leer no escribe
nada (I4) y un archivo que falta o está roto da los valores por defecto del juego
base, nunca una excepción.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ..clausewitz.nodes import ClausewitzDate
from ..vfs.model import VfsSnapshot
from ..vfs.paths import VPath

DEFAULT_START = ClausewitzDate(1836, 1, 1)
DEFAULT_END = ClausewitzDate(1935, 12, 31)


@dataclass(frozen=True)
class GameRules:
    start_date: ClausewitzDate = DEFAULT_START          # common/defines.lua (START_DATE / start_date)
    end_date: ClausewitzDate = DEFAULT_END
    bookmarks: tuple[ClausewitzDate, ...] = ()          # common/bookmarks.txt
    max_provinces: int = 0                              # map/default.map
    sea: frozenset[int] = frozenset()                   # default.map: sea_starts (H5: 3246 es de tierra)
    map_size: tuple[int, int] = (0, 0)                  # cabecera de map/provinces.bmp, sin decodificarlo
    party_policies: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({}))   # common/issues.txt → party_issues: grupo → opciones
    government_ideologies: Mapping[str, frozenset[str]] = field(
        default_factory=lambda: MappingProxyType({}))   # common/governments.txt: gobierno → ideologías

    @classmethod
    def from_snapshot(cls, snapshot: VfsSnapshot, overrides: Mapping[VPath, bytes] | None = None) -> GameRules:
        """Reglas de la vista efectiva de ``snapshot`` (``overrides``: documentos sin guardar)."""
        raise NotImplementedError

    @classmethod
    def from_vfs(cls, vfs) -> GameRules:
        """Atajo para ``from_snapshot(vfs.snapshot())``."""
        return cls.from_snapshot(vfs.snapshot())
