"""Las 7 salas y sus secciones, registradas por descubrimiento (wizard §13.1, §20).

Cada sala es un paquete ``ui/halls/<sala>/`` cuyo ``__init__.py`` exporta
``HALL: HallSpec`` y ``SECTIONS: list[SectionSpec]``. ``discover_halls`` los
recorre con ``pkgutil.iter_modules`` y los ordena por ``order``: no hay listas
centrales, así que cada agente toca solo su sala. Una sección sin ``factory`` ni
``schema_kind`` se ve como la tarjeta «en desarrollo» con su ``iteration``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from ..session import Session

# Orden fijo de las salas (Ctrl+1..7).
HALL_KEYS = ("project", "map", "nations", "war", "events", "interface", "localisation")


@dataclass(frozen=True)
class HallSpec:
    key: str                     # uno de HALL_KEYS
    order: int                   # 1..7: también el atajo Ctrl+<order>
    plate_key: str               # nombre corto de la placa («Naciones»), clave i18n
    title_key: str               # título largo de la cabecera («Naciones»)
    subtitle_key: str
    icon: str


@dataclass(frozen=True)
class SectionSpec:
    key: str                     # único dentro de la sala («descriptor», «files»…)
    hall: str
    order: int
    title_key: str
    icon: str
    factory: Callable[[Session], QWidget] | None = None    # None + schema_kind → EntityEditorPage (iteración 4)
    schema_kind: str | None = None
    view: str | None = None
    badge: Callable[[Session], int | None] | None = None   # contador del índice lateral
    iteration: int | None = None # si aún no existe: la iteración en que llega (tarjeta «en desarrollo»)
    planned_keys: tuple[str, ...] = ()   # textos de la tarjeta «en desarrollo» (lo que hará)


def discover_halls() -> list[tuple[HallSpec, list[SectionSpec]]]:
    """Salas de ``ui/halls/*`` ordenadas por ``order``, cada una con sus secciones ordenadas."""
    raise NotImplementedError
