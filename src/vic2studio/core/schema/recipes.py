"""Recetas (wizard §10.8): flujos multiarchivo con asistente. Contrato.

Una receta con nombre (``new_country``, ``new_war``, ``new_map``) encadena
pasos (``CreateRecord``, ``CopyRecord``, ``RegistryLine``, ``AppendToList``,
``EnsureLoc``, ``WriteImages``, ``AssignProvinces``, ``Conditional``) y termina
en un ``ChangePlan`` legible (P1). ``Entities.create`` ejecuta una receta
implícita (``CreateRecord`` + ``EnsureLoc`` + compañeros). Ninguno de los dos
esquemas de este corte necesita recetas con nombre: queda solo el contrato.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .fields import FieldLike
    from .record import RecordRef
    from .validate import CheckContext


class RecipeContext:
    """Contexto de una receta: lo que sus pasos necesitan (Workspace, índice, localización)."""

    def __init__(self, ctx: CheckContext) -> None:
        self.ctx = ctx


@dataclass(frozen=True)
class Recipe:
    """Receta con nombre: parámetros (que también son campos de esquema), pasos y páginas del
    asistente. ``plan`` da la vista previa (archivos, acciones y diff) sin cambiar nada;
    ``apply`` lo ejecuta en una transacción (I5)."""

    key: str
    label: str
    params: tuple[FieldLike, ...]
    steps: tuple[Step, ...]
    pages: tuple[tuple[str, tuple[str, ...]], ...] = ()   # pasos del asistente

    def plan(self, ctx: RecipeContext, values: dict) -> ChangePlan:  # noqa: F821 - ChangePlan de validate.model
        raise NotImplementedError

    def apply(self, ctx: RecipeContext, values: dict) -> list[RecordRef]:
        raise NotImplementedError


class Step:
    """Un paso de una receta (firmas en la fase 2)."""


@dataclass(frozen=True)
class CreateRecord(Step):
    """Crea el registro principal (``Entities.create``, sin transacción propia)."""

    kind: str


@dataclass(frozen=True)
class CopyRecord(Step):
    """Copia otro registro como base (``duplicate``)."""

    kind: str
    ref: object


@dataclass(frozen=True)
class RegistryLine(Step):
    """Añade una línea a un registro (``countries.txt``)."""

    rel: str


@dataclass(frozen=True)
class AppendToList(Step):
    """Añade la entidad al final de una lista (``peace_order``)."""

    rel: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class EnsureLoc(Step):
    """Crea las claves de localización (``LocSync.ensure``)."""

    pass


@dataclass(frozen=True)
class WriteImages(Step):
    """Genera las imágenes (banderas, retratos…)."""

    pass


@dataclass(frozen=True)
class AssignProvinces(Step):
    """Asigna provincias (guerras, países)."""

    pass


@dataclass(frozen=True)
class Conditional(Step):
    """Ejecuta pasos según una condición sobre los valores."""

    when: object
    steps: tuple[Step, ...]
