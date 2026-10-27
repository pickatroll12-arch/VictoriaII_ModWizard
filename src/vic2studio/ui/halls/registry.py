"""Las 7 salas y sus secciones, registradas por descubrimiento (wizard §13.1, §20).

Cada sala es un paquete ``ui/halls/<sala>/`` cuyo ``__init__.py`` exporta
``HALL: HallSpec`` y ``SECTIONS: list[SectionSpec]``. ``discover_halls`` los
recorre con ``pkgutil.iter_modules`` y los ordena por ``order``: no hay listas
centrales, así que cada agente toca solo su sala. Una sección sin ``factory`` ni
``schema_kind`` se ve como la tarjeta «en desarrollo» con su ``iteration``.
"""

from __future__ import annotations

import importlib
import pkgutil
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

    @property
    def planned(self) -> bool:
        """True si la sección aún no existe: se ve como la tarjeta «en desarrollo» (``iteration``)."""
        return self.factory is None and self.schema_kind is None


def discover_halls() -> list[tuple[HallSpec, list[SectionSpec]]]:
    """Salas de ``ui/halls/*`` ordenadas por ``order``, cada una con sus secciones ordenadas.

    Lanza ``ValueError`` si una sala no es de ``HALL_KEYS``, se repite una clave o un orden, una sección dice
    ser de otra sala o una sección planificada no indica su iteración.
    """
    package = importlib.import_module(__package__)
    halls: list[tuple[HallSpec, list[SectionSpec]]] = []
    for info in pkgutil.iter_modules(package.__path__):
        if not info.ispkg:
            continue
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        hall = getattr(module, "HALL", None)
        if hall is None:
            continue
        sections = sorted(getattr(module, "SECTIONS", ()), key=lambda s: s.order)
        _check_hall(hall, sections)
        halls.append((hall, sections))
    halls.sort(key=lambda item: item[0].order)
    for kind, values in (("clave", [h.key for h, _ in halls]), ("orden", [h.order for h, _ in halls])):
        if len(set(values)) != len(values):
            raise ValueError(f"salas con la misma {kind}: {values}")
    return halls


def _check_hall(hall: HallSpec, sections: list[SectionSpec]) -> None:
    if hall.key not in HALL_KEYS:
        raise ValueError(f"sala desconocida: {hall.key!r} (se esperaba una de {HALL_KEYS})")
    keys = [s.key for s in sections]
    orders = [s.order for s in sections]
    if len(set(keys)) != len(keys) or len(set(orders)) != len(orders):
        raise ValueError(f"sala {hall.key!r}: secciones con la misma clave u orden ({keys}, {orders})")
    for section in sections:
        if section.hall != hall.key:
            raise ValueError(f"la sección {section.key!r} dice ser de {section.hall!r}, pero está en {hall.key!r}")
        if section.planned and section.iteration is None:
            raise ValueError(f"la sección planificada {hall.key}.{section.key} no dice en qué iteración llega")
