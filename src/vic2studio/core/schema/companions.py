"""Compañeros y recetas (wizard §10.8).

Un compañero es un archivo o conjunto de claves que acompaña a la entidad: se
mantiene al crearla o borrarla (dentro de la misma transacción, I5) y puede
añadir problemas al validarla. ``EditContext`` da lo que un compañero necesita
sin tocar disco por su cuenta.

En este corte solo ``MappingTable`` lleva lógica real (la matriz de rebeldes de
los gobiernos, H16 — punto extra del encargo): el resto queda como contrato y
lanza ``NotImplementedError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..clausewitz.nodes import Block

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..locsync import LocSync
    from ..project.workspace import Workspace
    from ..validate.model import Problem
    from ..vfs.paths import VPath
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
    """Registra el TAG nuevo en ``registry``, justo antes de ``before`` (H11). Contrato."""

    registry: str = "common/countries.txt"
    before: str = "dynamic_tags"
    value: str = "countries/{file}.txt"

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        raise NotImplementedError

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        raise NotImplementedError

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        raise NotImplementedError

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        return ()


@dataclass(frozen=True)
class AppendToList:
    """Mantiene la entidad en una lista de un archivo (``cb_types.txt`` → ``peace_order``):
    al crear se añade al final; al borrar se quita. Contrato."""

    rel: str
    path: tuple[str, ...]

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        raise NotImplementedError

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        raise NotImplementedError

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        raise NotImplementedError

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        return ()


@dataclass(frozen=True)
class Ask:
    """Valor que el usuario debe confirmar al crear (``MappingTable.default``)."""

    pass


@dataclass(frozen=True)
class MappingTable:
    """Matriz de destino (``common/rebel_types.txt``): 14 tablas ``government = { <gob> = <gob
    destino> }`` (H16). Al crear un gobierno, la clave se añade a todas las tablas (con el
    ``default`` propuesto, o ``Ask()`` → el propio id, como propone §14.11); al borrarlo se
    quita. Todo dentro de la transacción de quien crea o borra (I5)."""

    rel: str
    table: str
    default: str | Ask = Ask()

    def _value(self, rec: Record) -> str:
        return rec.ref.ident if isinstance(self.default, Ask) else self.default

    def _tables(self, ctx: EditContext) -> list[Block]:
        """Los bloques ``table = { … }`` del archivo, en cualquier nivel (en vanilla están en la
        raíz; la muestra sintética los anida bajo cada tipo de rebelde)."""
        handle = ctx.ws.open(self.rel, create=True)
        document = handle.model.document
        found: list[Block] = []

        def walk(block: Block) -> None:
            for entry in block.entries:
                if entry.key is not None and entry.key.text == self.table \
                        and isinstance(entry.value, Block):
                    found.append(entry.value)
                if isinstance(entry.value, Block):
                    walk(entry.value)

        walk(document)
        return found

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        handle = ctx.ws.open(self.rel, create=True)
        ctx.ws.touch(handle)
        value = self._value(rec)
        for table in self._tables(ctx):
            if table.find(rec.ref.ident) is None:
                table.append(rec.ref.ident, value)

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        handle = ctx.ws.open(self.rel, create=True)
        ctx.ws.touch(handle)
        for table in self._tables(ctx):
            entry = table.find(rec.ref.ident)
            if entry is not None:
                table.remove_entry(entry)

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        raise NotImplementedError

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        """``government_missing_in_rebel_map`` (código de core/validate) si falta en alguna
        tabla de la matriz."""
        from ..clausewitz.diagnostics import Severity
        from ..validate.model import Problem
        from ..vfs.paths import VPath

        tables = self._tables(ctx)
        for table in tables:
            if table.find(rec.ref.ident) is None:
                yield Problem("government_missing_in_rebel_map", Severity.ERROR, VPath.of(self.rel),
                              None, None, (rec.ref.kind, rec.ref.ident), (), {"government": rec.ref.ident})
                return


@dataclass(frozen=True)
class ActivateUnit:
    """Muestra (y puede cambiar) la tecnología o invención que activa la unidad
    (``activate_unit = <id>``); opcional, así que no exige que exista. Contrato."""

    optional: bool = True

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        raise NotImplementedError

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        raise NotImplementedError

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        raise NotImplementedError

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        return ()


@dataclass(frozen=True)
class UnitNamesSlot:
    """Al crear una unidad naval, ofrece añadir su lista de nombres (``unit_names``) en los
    países. Contrato."""

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        raise NotImplementedError

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        raise NotImplementedError

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        raise NotImplementedError

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        return ()
