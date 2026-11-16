"""Compañeros y recetas (wizard §10.8).

Un compañero es un archivo o conjunto de claves que acompaña a la entidad: se
mantiene al crearla, renombrarla o borrarla (dentro de la misma transacción, I5)
y puede añadir problemas al validarla. ``EditContext`` da lo que un compañero
necesita sin tocar disco por su cuenta.

Tienen lógica ``AppendToList`` (``peace_order`` de los CB), ``MappingTable``
(la matriz de rebeldes, H16), ``ActivateUnit`` y ``UnitNamesSlot``. ``own_roles``
de un compañero son los papeles de sus propias referencias en el índice: no
bloquean el borrado porque el compañero las quita. ``RegisterTag`` llega con los
países.

``on_rename`` (§15) cambia solo el token del id en lo que el compañero mantiene y
se basta solo: no depende de que ``Entities.rename`` haya reescrito antes los usos
del índice (que también cubren ``peace_order``, la matriz y ``activate_unit``). Lo
que el índice no conoce (las listas de ``unit_names``) lo declara el compañero con
``rename_uses``, opcional y de solo lectura, para que salga en el plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ..clausewitz.nodes import Block, Scalar

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..locsync import LocSync
    from ..project.workspace import Workspace
    from ..validate.model import Problem
    from .record import Record
    from .validate import CheckContext


def _entries_under(block: Block):
    """Todas las entradas bajo ``block``, a cualquier profundidad y sin recursión."""
    stack = [block]
    while stack:
        current = stack.pop()
        for entry in current.entries:
            yield entry
            if isinstance(entry.value, Block):
                stack.append(entry.value)


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
        """``rec`` pasó de ``old`` a ``new`` (ya lleva el id nuevo): cambia el id en lo suyo."""
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
    """Mantiene la entidad en una lista de un archivo (``cb_types.txt`` → ``peace_order``): al crear
    se añade al **final** de la lista; al borrar se quitan todas sus apariciones. ``role`` es el papel
    con el que el índice registra esas apariciones (``peace_order``): no cuentan como usos que
    bloqueen el borrado, porque el propio compañero las quita (``own_roles``).

    ``check`` no da nada: ``cb_not_in_peace_order`` ya lo da la validación global (core/validate)."""

    rel: str
    path: tuple[str, ...]
    role: str = "peace_order"

    @property
    def own_roles(self) -> frozenset[str]:
        return frozenset({self.role})

    def _list(self, ctx: EditContext) -> Block | None:
        handle = ctx.ws.open(self.rel)
        block: Block = handle.model.document
        for key in self.path:
            entry = block.find(key, ignore_case=True)
            if entry is None or not isinstance(entry.value, Block):
                return None
            block = entry.value
        return block

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        from ..clausewitz.nodes import Scalar

        handle = ctx.ws.open(self.rel)
        ctx.ws.touch(handle)
        block = self._list(ctx)
        if block is None:
            return
        if any(entry.key is None and isinstance(entry.value, Scalar) and entry.value.text == rec.ref.ident
               for entry in block.entries):
            return
        if not self._append_line(ctx, handle, rec.ref.ident):
            block.append_value(Scalar(rec.ref.ident, False))

    def _append_line(self, ctx: EditContext, handle, ident: str) -> bool:
        """Si la lista lleva un valor por línea (``peace_order`` de vanilla y del minijuego), añade ``ident`` en
        una línea propia antes de la ``}``, con la sangría y el salto de la última. El serializador pondría un valor
        suelto nuevo en la misma línea que el anterior (``annex my_cb``), que es correcto para ``{ 1 2 3 }`` pero no
        respeta este formato. Es un empalme de texto de una línea (I3): todo lo demás queda byte a byte."""
        import re

        from ..clausewitz.nodes import Scalar
        from ..project.codecs import codec_for, parse_bytes

        data = codec_for(handle.kind).snapshot(handle.model)
        block: Block = parse_bytes(data).document
        for key in self.path:
            entry = block.find(key, ignore_case=True)
            if entry is None or not isinstance(entry.value, Block):
                return False
            block = entry.value
        values = [entry for entry in block.entries if entry.key is None and isinstance(entry.value, Scalar)]
        close = block.close_position
        if len(values) < 2 or close is None or len(values) != len(block.entries) \
                or len({entry.line for entry in values}) != len(values):
            return False
        text = data.decode("latin-1")   # biyectivo: los bytes vuelven tal cual
        lines = re.split(r"(?<=\r\n)|(?<=\n)(?<!\r\n)|(?<=\r)(?!\n)", text)
        last_line = values[-1].line - 1
        close_line = close[0] - 1
        if not 0 <= last_line < close_line < len(lines) or lines[close_line].lstrip(" \t")[:1] != "}":
            return False
        previous = lines[last_line]
        indent = previous[:len(previous) - len(previous.lstrip(" \t"))]
        newline = "\r\n" if previous.endswith("\r\n") else ("\r" if previous.endswith("\r") else "\n")
        lines.insert(close_line, f"{indent}{ident}{newline}")
        ctx.ws.replace_text(handle, "".join(lines).encode("latin-1"))
        return True

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        from ..clausewitz.nodes import Scalar

        handle = ctx.ws.open(self.rel)
        ctx.ws.touch(handle)
        block = self._list(ctx)
        if block is None:
            return
        for entry in [entry for entry in block.entries
                      if entry.key is None and isinstance(entry.value, Scalar) and entry.value.text == rec.ref.ident]:
            block.remove_entry(entry)

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        """Cada aparición de ``old`` en la lista pasa a ser ``new``, en su sitio (misma línea y sangría)."""
        try:
            handle = ctx.ws.open(self.rel)
        except (FileNotFoundError, OSError):
            return
        block = self._list(ctx)
        found = [] if block is None else [
            entry for entry in block.entries
            if entry.key is None and isinstance(entry.value, Scalar) and entry.value.text == old]
        if not found:
            return
        ctx.ws.touch(handle)
        for entry in found:
            entry.value = Scalar(new, entry.value.quoted)

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

    # Papeles con que el índice registra las filas de la matriz (core/index/extractors/politics.py): la fila
    # «<gob> = …» es del propio compañero, que la quita al borrar.
    own_roles = frozenset({"rebel_government"})

    def rows(self, ctx: EditContext, ident: str) -> list[tuple[str, str | None]]:
        """``(tipo de rebelde, destino)`` de ``ident`` en cada tabla (None si falta): la matriz de §14.11."""
        from ..clausewitz.nodes import Scalar

        handle = ctx.ws.open(self.rel)
        found: list[tuple[str, str | None]] = []

        def walk(block: Block, owner: str) -> None:
            for entry in block.entries:
                if entry.key is None or not isinstance(entry.value, Block):
                    continue
                if entry.key.text == self.table:
                    row = entry.value.find(ident)
                    value = row.value.text if row is not None and isinstance(row.value, Scalar) else None
                    found.append((owner, value))
                else:
                    walk(entry.value, entry.key.text)

        walk(handle.model.document, "")
        return found

    def set_target(self, ctx: EditContext, ident: str, owner: str, target: str) -> None:
        """Pone ``ident = target`` en la tabla del tipo de rebelde ``owner`` (transacción de quien llama)."""
        handle = ctx.ws.open(self.rel)
        ctx.ws.touch(handle)
        document = handle.model.document
        rebel = document.find(owner) if owner else None
        container = rebel.value if rebel is not None and isinstance(rebel.value, Block) else document
        table = container.find(self.table)
        if table is None or not isinstance(table.value, Block):
            raise KeyError(f"{owner}: no tiene tabla {self.table}")
        row = table.value.find(ident)
        if row is None:
            table.value.append(ident, target)
        else:
            row.value = target

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
        """En cada tabla, la fila ``old = …`` pasa a ``new = …`` y los destinos ``… = old`` a ``… = new``
        (también los de las filas de otros gobiernos). Sin el archivo no hay nada que cambiar (no se crea)."""
        try:
            handle = ctx.ws.open(self.rel)
        except (FileNotFoundError, OSError):
            return
        rows = [entry for table in self._tables(ctx) for entry in table.entries if entry.key is not None]
        keys = [entry for entry in rows if entry.key.text == old]
        targets = [entry for entry in rows if isinstance(entry.value, Scalar) and entry.value.text == old]
        if not keys and not targets:
            return
        ctx.ws.touch(handle)
        for entry in keys:
            entry.key = Scalar(new, entry.key.quoted)
        for entry in targets:
            entry.value = Scalar(new, entry.value.quoted)

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        """``government_missing_in_rebel_map`` (código de core/validate) por cada tipo de rebelde cuya tabla no
        tiene el gobierno, con sus argumentos (``government`` y ``rebel``) y su línea."""
        from ..clausewitz.diagnostics import Severity
        from ..validate.model import Problem
        from ..vfs.paths import VPath

        if ctx is None or ctx.ws is None:
            return   # validación en segundo plano: el código ya lo da core/validate (I12)
        handle = ctx.ws.open(self.rel, create=True)
        found: list[tuple[str, int | None]] = []

        def walk(block: Block, owner: str, line) -> None:
            for entry in block.entries:
                if entry.key is None or not isinstance(entry.value, Block):
                    continue
                if entry.key.text == self.table:
                    if entry.value.find(rec.ref.ident) is None:
                        found.append((owner, line))
                else:
                    walk(entry.value, entry.key.text, entry.line)

        walk(handle.model.document, "", None)
        for owner, line in found:
            yield Problem("government_missing_in_rebel_map", Severity.ERROR, VPath.of(self.rel), line, None,
                          (rec.ref.kind, rec.ref.ident), (), {"government": rec.ref.ident, "rebel": owner})


ROLE_ACTIVATE_UNIT = "activate_unit"


@dataclass(frozen=True)
class ActivateUnit:
    """La tecnología o invención que activa la unidad (``activate_unit = <id>``, §14.4).

    ``sources`` las enumera desde el índice y ``activate_in`` añade la línea a otra (en la transacción de
    quien llama: el archivo de tecnología se copia al mod al guardar). Es opcional: crear o borrar no
    toca nada. ``check`` da ``unit_never_active`` (información) si la unidad tiene ``active = no`` y nada
    la activa: el jugador nunca podrá construirla.
    """

    optional: bool = True

    def sources(self, ctx, rec: Record) -> list:
        """Los ``SymbolRef`` con papel ``activate_unit`` que nombran la unidad (tecnologías e invenciones)."""
        if ctx is None or ctx.index is None:
            return []
        return [use for use in ctx.index.refs_to(rec.schema.provides or rec.schema.kind, rec.ref.ident)
                if use.role == ROLE_ACTIVATE_UNIT]

    def activate_in(self, ctx: EditContext, rec: Record, kind: str, name: str) -> None:
        """Añade ``activate_unit = <id>`` a la tecnología (en su bloque) o a la invención (en su ``effect``)."""
        symbol = ctx.index.get(kind, name)
        if symbol is None:
            raise KeyError(f"{kind}:{name} no existe")
        handle = ctx.ws.open(symbol.rel)
        ctx.ws.touch(handle)
        entry = handle.model.document.find(name)
        if entry is None or not isinstance(entry.value, Block):
            raise KeyError(f"{kind}:{name} no está en {symbol.rel}")
        target = entry.value
        if kind == "invention":
            effect = target.find("effect")
            if effect is None or not isinstance(effect.value, Block):
                effect = target.append("effect", Block())
            target = effect.value
        if target.find(ROLE_ACTIVATE_UNIT, rec.ref.ident) is None:
            target.append(ROLE_ACTIVATE_UNIT, rec.ref.ident)

    def deactivate_in(self, ctx: EditContext, rec: Record, rel) -> int:
        """Quita cada ``activate_unit = <id>`` del archivo ``rel`` (a cualquier profundidad), en la transacción
        de quien llama. El resto del archivo no cambia. Devuelve cuántas líneas quitó (0: no toca nada)."""
        handle = ctx.ws.open(rel)
        found = []
        stack = [handle.model.document]
        while stack:
            block = stack.pop()
            for entry in block.entries:
                if isinstance(entry.value, Block):
                    stack.append(entry.value)
                elif entry.key is not None and entry.key.text.lower() == ROLE_ACTIVATE_UNIT \
                        and entry.value.text == rec.ref.ident:
                    found.append((block, entry))
        if not found:
            return 0
        ctx.ws.touch(handle)
        for block, entry in found:
            block.remove_entry(entry)
        return len(found)

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        return None

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        return None

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        """Las tecnologías e invenciones que activaban ``old`` (según el índice) pasan a activar ``new``: cambia
        el valor de cada ``activate_unit = old`` de esos archivos, a cualquier profundidad."""
        if ctx.index is None:
            return
        kind = rec.schema.provides or rec.schema.kind
        rels = {use.rel.key: use.rel for use in ctx.index.refs_to(kind, old) if use.role == ROLE_ACTIVATE_UNIT}
        for key in sorted(rels):
            try:
                handle = ctx.ws.open(rels[key])
            except (FileNotFoundError, OSError):
                continue
            found = [entry for entry in _entries_under(handle.model.document)
                     if entry.key is not None and entry.key.text.lower() == ROLE_ACTIVATE_UNIT
                     and isinstance(entry.value, Scalar) and entry.value.text == old]
            if not found:
                continue
            ctx.ws.touch(handle)
            for entry in found:
                entry.value = Scalar(new, entry.value.quoted)

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        from .validate import issue

        if ctx is None or ctx.index is None:
            return ()
        if rec.get("active", True) is False and not self.sources(ctx, rec):
            return (issue("unit_never_active", rec, field=("active",), ident=rec.ref.ident),)
        return ()


@dataclass(frozen=True)
class UnitNamesSlot:
    """Al crear una unidad naval, ofrece añadir su lista de nombres (``unit_names``) en los países (§14.12).

    Ofrecer es cosa de la interfaz: ``on_create`` no cambia nada. ``candidates`` da los archivos de país con
    bloque ``unit_names`` que aún no tienen la unidad y ``add_to`` les añade ``<id> = { }`` (en la
    transacción de quien llama). Solo para unidades navales (``type = naval``).
    """

    folder: str = "common/countries"

    def applies(self, rec: Record) -> bool:
        return rec.get("type", None) == "naval"

    def candidates(self, ctx, rec: Record) -> list:
        """``VPath`` de los archivos de país con ``unit_names`` sin la unidad (leer no escribe, I4)."""
        from ..vfs.paths import VPath

        if not self.applies(rec):
            return []
        found = []
        for entry in ctx.ws.vfs.list(self.folder, "*.txt", recursive=False):
            handle = ctx.ws.peek(entry.rel)
            if handle is None or handle.deleted:
                try:
                    handle = ctx.ws.open(entry.rel)
                except (FileNotFoundError, OSError):
                    continue
            names = handle.model.document.find("unit_names")
            if names is not None and isinstance(names.value, Block) and names.value.find(rec.ref.ident) is None:
                found.append(VPath.of(entry.rel))
        return found

    def add_to(self, ctx: EditContext, rec: Record, rels) -> int:
        """Añade ``<id> = { }`` al ``unit_names`` de cada archivo; devuelve cuántos cambió."""
        changed = 0
        for rel in rels:
            handle = ctx.ws.open(rel)
            names = handle.model.document.find("unit_names")
            if names is None or not isinstance(names.value, Block) or names.value.find(rec.ref.ident) is not None:
                continue
            ctx.ws.touch(handle)
            names.value.append(rec.ref.ident, Block())
            changed += 1
        return changed

    def on_create(self, ctx: EditContext, rec: Record) -> None:
        return None

    def on_delete(self, ctx: EditContext, rec: Record) -> None:
        return None

    def _named_in(self, ctx, ident: str) -> list[tuple]:
        """``(archivo, línea, columna)`` de la clave ``ident`` en el ``unit_names`` de cada archivo de país que
        la tiene. Leer no escribe (I4): lo abierto se mira en su documento (con lo sin guardar) y lo demás, en
        sus bytes, que solo se analizan si citan el id (vanilla trae cientos de archivos de país)."""
        from ..project.codecs import parse_bytes
        from ..vfs.model import DocKind
        from ..vfs.paths import VPath

        found: list[tuple] = []

        def look(rel, document) -> None:
            names = document.find("unit_names")
            row = names.value.find(ident) if names is not None and isinstance(names.value, Block) else None
            if row is not None:
                found.append((VPath.of(rel), row.line, row.column))

        seen: set[str] = set()
        needle = ident.encode("cp1252", "ignore")
        for entry in ctx.ws.vfs.list(self.folder, "*.txt", recursive=False):
            seen.add(entry.rel.key)
            handle = ctx.ws.peek(entry.rel)
            if handle is not None:
                if not handle.deleted and handle.kind is DocKind.CLAUSEWITZ:
                    look(handle.rel, handle.model.document)
                continue
            try:
                data = entry.path.read_bytes()
            except OSError:
                continue
            if needle in data:
                look(entry.rel, parse_bytes(data).document)
        folder = self.folder.lower()
        for handle in ctx.ws.documents():   # archivos de país nuevos, aún sin guardar
            if handle.rel.key in seen or handle.deleted or handle.kind is not DocKind.CLAUSEWITZ:
                continue
            if "/".join(handle.rel.parts[:-1]).lower() == folder and handle.rel.suffix == ".txt":
                look(handle.rel, handle.model.document)
        return found

    def rename_uses(self, ctx, rec: Record, old: str) -> list:
        """Lo que ``on_rename`` cambiará y el índice no conoce (para el plan del renombrado): un ``SymbolRef``
        con papel ``unit_names`` por archivo de país que nombra la unidad. Leer no escribe (I4)."""
        from ..index.model import SymbolRef

        kind = rec.schema.provides or rec.schema.kind
        return [SymbolRef(kind, old, rel, line, column, "unit_names")
                for rel, line, column in self._named_in(ctx, old)]

    def on_rename(self, ctx: EditContext, rec: Record, old: str, new: str) -> None:
        """La lista de nombres ``old = { … }`` de cada país pasa a llamarse ``new``; los nombres no se tocan.
        Si un país ya tiene una lista ``new``, la vieja se deja como está (no se mezclan)."""
        for rel, _, _ in self._named_in(ctx, old):
            handle = ctx.ws.open(rel)
            names = handle.model.document.find("unit_names")
            if names.value.find(new) is not None:
                continue
            ctx.ws.touch(handle)
            row = names.value.find(old)
            row.key = Scalar(new, row.key.quoted)

    def check(self, ctx: CheckContext, rec: Record) -> Iterable[Problem]:
        return ()
