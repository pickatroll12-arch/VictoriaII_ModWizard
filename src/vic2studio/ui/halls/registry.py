"""Las 7 salas y sus secciones, registradas por descubrimiento (wizard §13.1, §20).

Cada sala es un paquete ``ui/halls/<sala>/`` cuyo ``__init__.py`` exporta
``HALL: HallSpec`` y ``SECTIONS: list[SectionSpec]``. ``discover_halls`` los
recorre con ``pkgutil.iter_modules`` y los ordena por ``order``: no hay listas
centrales, así que cada agente toca solo su sala. Una sección sin ``factory`` ni
``schema_kind`` se ve como la tarjeta «en desarrollo» con su ``iteration``.

Desde la iteración 4, las secciones de entidades salen del **registro de esquemas** (``schema_sections``): cada
esquema editable con ``hall`` y ``section`` da una ``SectionSpec`` (una por ``View`` si tiene vistas) con el
``EntityEditorPage`` como ``factory``. Si la sala ya declara una sección con esa clave (la tarjeta planificada de
reserva), la del esquema la sustituye. Añadir un esquema no toca ningún archivo de ``ui/`` (criterio 6).

Desde la iteración 5, una sección declarada puede **alojar** esquemas (``SectionSpec.hosts``): la sala Mapa edita
varios esquemas en una misma página hecha a mano (el lienzo con la ficha de la provincia, el árbol de regiones…),
así que sus esquemas no generan un ``EntityEditorPage`` aunque sean editables y nombren esa sección. La navegación
(``MainWindow.open_entity``) sigue llegando a ella por ``hall`` y ``section`` del esquema y llama a su
``focus_field(ref, field)``.
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
    hosts: tuple[str, ...] = ()  # ``kind`` de los esquemas que esta sección edita en su propia página (iteración 5)

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
        sections = merge_schema_sections(list(getattr(module, "SECTIONS", ())), schema_sections(hall.key))
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


def _entity_badge(schema, view):
    def badge(session) -> int | None:
        entities = getattr(session, "entities", None)
        if entities is None:
            return None
        try:
            return len(entities.list(schema.kind, view=view)) or None
        except Exception:  # noqa: BLE001 - un contador nunca rompe la ventana
            return None

    return badge


def schema_sections(hall: str, schemas=None) -> list[SectionSpec]:
    """Las secciones que generan los esquemas de ``hall`` (``schemas``: los del registro si es None)."""
    if schemas is None:
        from ...core.schema import registry

        schemas = registry.all_schemas()
    from ..entity.editor_page import entity_section_factory

    specs = []
    for schema in schemas:
        if not schema.editable or schema.hall != hall or not schema.section:
            continue
        if schema.views:
            for offset, view in enumerate(schema.views):
                specs.append(SectionSpec(view.section, hall, schema.order + offset,
                                         f"schema.{schema.kind}.view.{view.key}", schema.icon,
                                         factory=entity_section_factory(schema, view.key), schema_kind=schema.kind,
                                         view=view.key, badge=_entity_badge(schema, view.key)))
        else:
            specs.append(SectionSpec(schema.section, hall, schema.order, f"schema.{schema.kind}.title", schema.icon,
                                     factory=entity_section_factory(schema), schema_kind=schema.kind,
                                     badge=_entity_badge(schema, None)))
    return specs


def hosting_section(kind: str) -> str | None:
    """``"sala:sección"`` de la sección declarada que aloja el esquema ``kind`` (``SectionSpec.hosts``); None si
    ninguna lo aloja. Vale también para esquemas de solo lectura (``terrain``, ``adjacency``), que no tienen
    sección generada."""
    for hall, sections in discover_halls():
        for section in sections:
            if kind in section.hosts:
                return f"{hall.key}:{section.key}"
    return None


def merge_schema_sections(declared: list[SectionSpec], generated: list[SectionSpec]) -> list[SectionSpec]:
    """Las secciones de la sala con las de los esquemas encima: una generada sustituye a la declarada con la misma
    clave (la tarjeta planificada de reserva); el resto se añade. Ordenadas por ``order``.

    Una generada cuyo esquema está en los ``hosts`` de una declarada se descarta: ese esquema se edita en la página
    de esa sección (o se verá en ella cuando exista: mientras tanto sigue su tarjeta «en desarrollo»)."""
    hosted = {kind for spec in declared for kind in spec.hosts}
    by_key = {spec.key: spec for spec in generated if spec.schema_kind not in hosted}
    merged = [by_key.pop(spec.key, spec) for spec in declared]
    merged.extend(by_key.values())
    return sorted(merged, key=lambda s: s.order)
