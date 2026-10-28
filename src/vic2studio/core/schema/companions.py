"""Compañeros y recetas (wizard §10.8).

Un compañero es un archivo o conjunto de claves que acompaña a la entidad: se
mantiene al crearla, renombrarla o borrarla (dentro de la misma transacción,
I5) y puede añadir problemas al validarla. ``EditContext`` da lo que un
compañero necesita sin tocar disco por su cuenta. Las dataclasses son el
contrato de §10.8; la lógica llega en la fase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..locsync import LocSync
    from ..project.workspace import Workspace
    from ..validate.model import Problem
    from .record import Record
    from .validate import CheckContext


class EditContext:
    """Contexto de una edición de entidad (crear, duplicar, renombrar, borrar): el ``Workspace``
    (transacción ya abierta), el índice y la sincronización de localización."""

    def __init__(self, ws: Workspace, index, loc: LocSync) -> None:
        self.ws = ws
        self.index = index
        self.loc = loc


class Companion(Protocol):
    """Mantenimiento de un archivo o clave que acompaña a la entidad (todo dentro de la
    transacción de quien crea/renombra/borra)."""

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        """Recién creado ``rec`` (ya está en su documento): mantiene el compañero."""
        ...

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        """Antes de que ``rec`` desaparezca: quita lo suyo."""
        ...

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        """``rec`` pasó de ``old`` a ``new``: mueve lo suyo."""
        ...

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        """Problemas propios del compañero sobre ``rec`` (leer no escribe, I4)."""
        ...


@dataclass(frozen=True)
class RegisterTag:
    """Registra el TAG nuevo en ``registry``, justo antes de ``before`` (H11)."""

    registry: str = "common/countries.txt"
    before: str = "dynamic_tags"
    value: str = "countries/{file}.txt"


@dataclass(frozen=True)
class AppendToList:
    """Mantiene la entidad en una lista de un archivo (``cb_types.txt`` → ``peace_order``):
    al crear se añade al final; al borrar se quita."""

    rel: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class Ask:
    """Valor que el usuario debe confirmar al crear (``MappingTable.default``)."""

    pass


@dataclass(frozen=True)
class MappingTable:
    """Matriz de destino (``common/rebel_types.txt``): 14 tablas ``government = { <gob> = <gob
    destino> }`` (H16). Al crear un gobierno, la clave se añade a todas las tablas (con el
    ``default`` propuesto, o ``Ask()`` para preguntar); al borrarlo se quita."""

    rel: str
    table: str
    default: str | Ask = Ask()


@dataclass(frozen=True)
class ActivateUnit:
    """Muestra (y puede cambiar) la tecnología o invención que activa la unidad
    (``activate_unit = <id>``); opcional, así que no exige que exista."""

    optional: bool = True


@dataclass(frozen=True)
class UnitNamesSlot:
    """Al crear una unidad naval, ofrece añadir su lista de nombres (``unit_names``) en los
    países."""
